import json

from django.conf import settings

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from sports.models import Match

from . import engine
from .models import AviatorBet, GameRound


def play(request):
    from sports import live
    live.tick()
    live_now = list(Match.objects.live().select_related("league").order_by("source", "kickoff")[:4])
    upcoming = list(Match.objects.upcoming().exclude(source=Match.Source.VIRTUAL).select_related("league")
                    .order_by("-is_featured", "kickoff")[:6 - len(live_now)])
    featured = live_now + upcoming
    return render(request, "aviator/play.html", {
        "featured_matches": featured, "min_bet": settings.AVIATOR["MIN_BET"],
    })


def fairness(request):
    rounds = GameRound.objects.filter(settled=True).order_by("-sequence")[:25]
    return render(request, "aviator/fairness.html", {
        "rounds": rounds, "hmac_key": engine.HMAC_KEY.decode(),
        "house_edge": settings.AVIATOR["HOUSE_EDGE_PERCENT"],
        "rtp": 100 - settings.AVIATOR["HOUSE_EDGE_PERCENT"], "max_multiplier": settings.AVIATOR["MAX_MULTIPLIER"],
    })


# ------------------------------------------------------------------ JSON API
def _json_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _api_login_required(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Please log in to play", "login": True}, status=401)
        return view(request, *args, **kwargs)
    return wrapped


def _respond(request, bet):
    return JsonResponse({"bet": engine.serialize_bet(bet, request.user),
                         "state": engine.game_state(request.user)})


@require_GET
def api_state(request):
    return JsonResponse(engine.game_state(request.user))


@require_POST
@_api_login_required
def api_bet(request):
    data = _json_body(request)
    try:
        bet = engine.place_bet(request.user, data.get("amount"), int(data.get("panel", 1)),
                               data.get("auto_cashout"))
    except (engine.GameError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return _respond(request, bet)


@require_POST
@_api_login_required
def api_cancel(request):
    try:
        bet = engine.cancel_bet(request.user, _json_body(request).get("bet_id"))
    except engine.GameError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return _respond(request, bet)


@require_POST
@_api_login_required
def api_cashout(request):
    try:
        bet = engine.cash_out(request.user, _json_body(request).get("bet_id"))
    except engine.GameError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return _respond(request, bet)


@require_GET
def api_history(request):
    tab = request.GET.get("tab", "previous")
    if tab == "mine":
        if not request.user.is_authenticated:
            return JsonResponse({"bets": []})
        bets = (AviatorBet.objects.filter(user=request.user).exclude(status=AviatorBet.Status.ACTIVE)
                .exclude(status=AviatorBet.Status.CANCELLED).select_related("user", "round")[:30])
        return JsonResponse({"bets": [
            {**engine.serialize_bet(b, request.user), "round": b.round.sequence,
             "crash_point": str(b.round.crash_point), "created_at": b.created_at.isoformat()}
            for b in bets]})
    prev = GameRound.objects.filter(settled=True).order_by("-sequence").first()
    if not prev:
        return JsonResponse({"bets": [], "round": None})
    bets = prev.bets.exclude(status=AviatorBet.Status.CANCELLED).select_related("user").order_by("-payout", "-amount")[:60]
    return JsonResponse({"round": {"sequence": prev.sequence, "crash_point": str(prev.crash_point)},
                         "bets": [engine.serialize_bet(b, request.user) for b in bets]})
