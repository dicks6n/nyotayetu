from datetime import timedelta

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from aviator import engine
from aviator.models import AviatorBet
from sports.models import SportsBet
from wallet.models import Transaction

from . import analytics


@staff_member_required
def dashboard(request):
    period = request.GET.get("period", "7d")
    if period not in analytics.PERIODS:
        period = "7d"
    since = analytics.period_start(period)
    series = analytics.daily_series(14)

    live_round = engine.current_round()
    live_bets = (live_round.bets.exclude(status=AviatorBet.Status.CANCELLED)
                 .select_related("user").order_by("-amount")[:25])
    players = analytics.players_queryset()

    return render(request, "backoffice/dashboard.html", {
        "period": period, "periods": analytics.PERIODS.items(),
        "s": analytics.summary(since),
        "series": series,
        "ggr_chart": analytics.bar_chart(series, "ggr"),
        "players_chart": analytics.bar_chart(series, "players", height=150),
        "live_round": live_round, "live_phase": live_round.phase(timezone.now()), "live_bets": live_bets,
        "top_value": players.filter(house_net__gt=0).order_by("-house_net")[:8],
        "top_winners": players.filter(house_net__lt=0).order_by("house_net")[:8],
        "big_wins": (AviatorBet.objects.filter(status=AviatorBet.Status.WON,
                                               created_at__gte=timezone.now() - timedelta(days=7))
                     .select_related("user", "round").order_by("-payout")[:8]),
        "pending_withdrawals": (Transaction.objects.filter(kind=Transaction.Kind.WITHDRAWAL,
                                                           status=Transaction.Status.PENDING)
                                .select_related("user").order_by("created_at")[:10]),
        "recent_signups": User.objects.select_related("profile").order_by("-date_joined")[:8],
        "house_edge": settings.AVIATOR["HOUSE_EDGE_PERCENT"],
    })


@staff_member_required
def players(request):
    qs = analytics.players_queryset()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(profile__phone__icontains=q) | Q(email__icontains=q))
    if request.GET.get("active") == "1":
        qs = qs.filter(last_seen__gte=timezone.now() - timedelta(days=7))
    sort = request.GET.get("sort", "house_net")
    qs = qs.order_by(analytics.PLAYER_SORTS.get(sort, "-house_net"), "-date_joined")
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "backoffice/players.html", {
        "page": page, "q": q, "sort": sort, "active": request.GET.get("active") == "1",
        "sorts": [("house_net", "Most valuable"), ("winners", "Biggest winners"), ("staked", "Most staked"),
                  ("deposits", "Top depositors"), ("balance", "Balance"), ("last_seen", "Recently active"),
                  ("joined", "Newest")],
    })


@staff_member_required
def player_detail(request, user_id):
    player = get_object_or_404(analytics.players_queryset(), pk=user_id)
    return render(request, "backoffice/player_detail.html", {
        "p": player,
        "stats": analytics.player_stats(player),
        "transactions": player.transactions.all()[:40],
        "aviator_bets": player.aviator_bets.select_related("round").exclude(status=AviatorBet.Status.CANCELLED)[:40],
        "sports_bets": SportsBet.objects.filter(user=player).prefetch_related("selections__match")[:10],
        "casino_bets": player.casino_bets.select_related("seed_pair")[:30],
        "referrals": player.referrals.select_related("user"),
    })
