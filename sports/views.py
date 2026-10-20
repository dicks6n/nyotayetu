import json
from datetime import date, datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from wallet.services import get_wallet

from . import live, markets, services
from .models import League, Match

STATUSES = [("all", "All"), ("live", "Live"), ("finished", "Finished"), ("scheduled", "Scheduled")]
LEGACY_TABS = {"live": "live", "upcoming": "scheduled", "results": "finished"}


def _counts():
    real = Match.objects.exclude(source=Match.Source.VIRTUAL)
    return {
        "live": real.live().count(),
        "upcoming": real.upcoming().count(),
        "virtual": Match.objects.filter(source=Match.Source.VIRTUAL,
                                        status__in=[Match.Status.UPCOMING, Match.Status.LIVE]).count(),
    }


def _day_bounds(day):
    tz = timezone.get_current_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def match_list(request):
    """Flashscore-style board: pick a day, filter by status, leagues grouped by country."""
    live.tick()
    today = timezone.localdate()
    tab = request.GET.get("tab", "")
    status = request.GET.get("status") or LEGACY_TABS.get(tab, "all")
    if status not in dict(STATUSES):
        status = "all"
    try:
        day = date.fromisoformat(request.GET.get("date", "")) if request.GET.get("date") else today
    except ValueError:
        day = today
    league_id, q = request.GET.get("league"), request.GET.get("q", "").strip()
    virtual = tab == "virtual"

    real = Match.objects.exclude(source=Match.Source.VIRTUAL).select_related("league")
    start, end = _day_bounds(day)
    on_day = real.filter(kickoff__gte=start, kickoff__lt=end)
    if virtual:
        matches = (Match.objects.filter(source=Match.Source.VIRTUAL, status__in=[Match.Status.LIVE, Match.Status.UPCOMING])
                   .select_related("league").order_by("-status", "kickoff"))
    elif status == "live":
        matches = real.live()
    elif status == "finished":
        matches = on_day.filter(status__in=[Match.Status.FINISHED, Match.Status.CANCELLED])
    elif status == "scheduled":
        matches = on_day.filter(status=Match.Status.UPCOMING)
    else:
        matches = on_day
    if league_id:
        matches = matches.filter(league_id=league_id)
    if q:
        matches = matches.filter(Q(home_team__icontains=q) | Q(away_team__icontains=q) | Q(league__name__icontains=q)
                                 | Q(league__country__icontains=q))
    if not virtual:
        matches = matches.order_by("league__priority", "league__country", "league__name", "kickoff")

    labels = {today - timedelta(days=1): "Yesterday", today: "Today", today + timedelta(days=1): "Tomorrow"}
    days = [{"date": d, "label": labels.get(d, d.strftime("%a")), "sub": d.strftime("%d.%m"),
             "count": real.filter(kickoff__gte=_day_bounds(d)[0], kickoff__lt=_day_bounds(d)[1]).count()}
            for d in (today + timedelta(days=i) for i in range(-2, 6))]
    status_counts = {
        "all": on_day.count(), "live": real.live().count(),
        "finished": on_day.filter(status__in=[Match.Status.FINISHED, Match.Status.CANCELLED]).count(),
        "scheduled": on_day.filter(status=Match.Status.UPCOMING).count(),
    }
    leagues = (League.objects.annotate(n=Count("matches", filter=Q(matches__kickoff__gte=start, matches__kickoff__lt=end)
                                                & ~Q(matches__source=Match.Source.VIRTUAL)))
               .filter(n__gt=0).order_by("priority", "country", "name"))
    return render(request, "sports/match_list.html", {
        "matches": list(matches[:400]), "status": status, "statuses": STATUSES, "status_counts": status_counts,
        "day": day, "days": days, "today": today, "virtual": virtual, "leagues": leagues,
        "top_leagues": [lg for lg in leagues if lg.priority <= 12], "league_id": league_id, "q": q,
        "counts": _counts(),
    })


def match_detail(request, pk):
    live.tick()
    match = get_object_or_404(Match.objects.select_related("league"), pk=pk)
    return render(request, "sports/match_detail.html", {
        "m": match, "groups": markets.grouped(match.odds or {}, match.home_team, match.away_team),
    })


@require_GET
def api_live(request):
    """Live state + prices for the matches on screen. ?ids=1,2,3[&full=ID]"""
    live.tick()
    try:
        ids = [int(i) for i in request.GET.get("ids", "").split(",") if i][:80]
        full = int(request.GET.get("full") or 0)
    except ValueError:
        return JsonResponse({"error": "bad ids"}, status=400)
    data = {str(m.id): live.state(m, full=(m.id == full)) for m in Match.objects.filter(id__in=ids)}
    return JsonResponse({"matches": data, "counts": _counts()})


@require_GET
def api_ticker(request):
    live.tick()
    items = [{"id": m.id, "home": m.home_team, "away": m.away_team, "score": [m.home_score, m.away_score],
              "minute": m.minute, "period": m.period, "virtual": m.source == Match.Source.VIRTUAL}
             for m in Match.objects.live().order_by("source", "kickoff")[:20]]
    return JsonResponse({"live": items})


@require_POST
def place_bet(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Please log in to place a bet", "login": True}, status=401)
    try:
        data = json.loads(request.body or "{}")
        bet = services.place_bet(request.user, data.get("stake"), data.get("selections") or [],
                                 accept_odds_changes=bool(data.get("accept_changes")))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Bad request"}, status=400)
    except services.OddsChanged as exc:
        return JsonResponse({"error": str(exc), "odds_changed": exc.changed}, status=409)
    except services.SlipError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({
        "ok": True, "code": bet.code, "potential_win": str(bet.potential_win),
        "total_odds": str(bet.total_odds), "balance": str(get_wallet(request.user).balance),
    })


@login_required
def my_bets(request):
    bets = request.user.sports_bets.prefetch_related("selections__match")
    status = request.GET.get("status")
    if status:
        bets = bets.filter(status=status)
    page = Paginator(bets, 15).get_page(request.GET.get("page"))
    return render(request, "sports/my_bets.html", {"page": page, "status": status})
