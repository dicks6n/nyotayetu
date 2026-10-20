import json
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from aviator.engine import mask
from wallet.services import get_wallet

from . import games, services
from .models import CasinoBet, SeedPair

CFG = settings.CASINO

GAMES = [
    {"slug": "dice", "name": "Dice", "icon": "🎲", "url": "casino:dice", "tag": "Pick your odds",
     "blurb": "Roll over or under your target. Lower chance, bigger multiplier.", "hue": 0},
    {"slug": "mines", "name": "Mines", "icon": "💎", "url": "casino:mines", "tag": "Up to 24 mines",
     "blurb": "Uncover gems, dodge the mines, cash out whenever you like.", "hue": 140},
    {"slug": "plinko", "name": "Plinko", "icon": "🔮", "url": "casino:plinko", "tag": f"Up to {games.plinko_table(16, 'high')[0]:,}x",
     "blurb": "Drop enchanted orbs through the pegs into a multiplier.", "hue": 0},
    {"slug": "wheel", "name": "Wheel", "icon": "🎡", "url": "casino:wheel", "tag": f"Up to {games.wheel_table('high')[-1]}x",
     "blurb": "Spin the wheel of fortune. Choose low, medium or high risk.", "hue": 140},
    {"slug": "roulette", "name": "Roulette", "icon": "🎯", "url": "casino:roulette", "tag": "Single zero · 35:1",
     "blurb": "European roulette. Spread chips across numbers, colours, dozens and columns.", "hue": 0},
    {"slug": "blackjack", "name": "Blackjack", "icon": "🃏", "url": "casino:blackjack", "tag": "Blackjack pays 3:2",
     "blurb": "Beat the dealer to 21. Hit, stand, double or split.", "hue": 140},
    {"slug": "baccarat", "name": "Baccarat", "icon": "👑", "url": "casino:baccarat", "tag": "Tie pays 8:1",
     "blurb": "Player, Banker or Tie — the elegant classic, dealt in an instant.", "hue": 0},
]


def _ctx(request, game, **extra):
    return {"game": next(g for g in GAMES if g["slug"] == game), "cfg": CFG,
            "rtp": 100 - CFG["HOUSE_EDGE_PERCENT"], **extra}


# ----------------------------------------------------------------------------- pages
def lobby(request):
    return render(request, "casino/lobby.html", {"games": GAMES, "rtp": 100 - CFG["HOUSE_EDGE_PERCENT"]})


def dice(request):
    return render(request, "casino/dice.html", _ctx(request, "dice", min_chance=games.DICE_MIN_CHANCE,
                                                    max_chance=games.DICE_MAX_CHANCE))


def mines(request):
    return render(request, "casino/mines.html", _ctx(request, "mines"))


def plinko(request):
    tables = {f"{r}-{k}": [str(m) for m in games.plinko_table(r, k)]
              for r in games.PLINKO_ROWS for k in games.PLINKO_RISKS}
    return render(request, "casino/plinko.html", _ctx(request, "plinko", tables=tables))


def wheel(request):
    tables = {k: [str(m) for m in games.wheel_table(k)] for k in games.WHEEL_RISKS}
    return render(request, "casino/wheel.html", _ctx(request, "wheel", tables=tables))


def roulette(request):
    return render(request, "casino/roulette.html", _ctx(request, "roulette", red=sorted(games.ROULETTE_RED)))


def baccarat(request):
    return render(request, "casino/baccarat.html", _ctx(request, "baccarat"))


def blackjack(request):
    return render(request, "casino/blackjack.html", _ctx(request, "blackjack"))


@login_required
def fairness(request):
    if request.method == "POST":
        try:
            old, new = services.rotate_seed(request.user, request.POST.get("client_seed", ""))
            messages.success(request, "New seed pair is active — your previous server seed is now revealed.")
        except services.CasinoError as exc:
            messages.error(request, str(exc))
        return redirect("casino:fairness")
    return render(request, "casino/fairness.html", {
        "active": services.active_seed(request.user),
        "revealed": SeedPair.objects.filter(user=request.user, active=False)[:10],
        "edge": CFG["HOUSE_EDGE_PERCENT"],
    })


# ----------------------------------------------------------------------------- JSON API
def serialize(bet, viewer=None):
    data = {
        "id": bet.id, "game": bet.game, "amount": str(bet.amount), "multiplier": str(bet.multiplier),
        "payout": str(bet.payout), "status": bet.status, "params": bet.params,
        "player": bet.user.username if viewer and bet.user_id == viewer.id else mask(bet.user.username),
        "mine": bool(viewer and bet.user_id == viewer.id), "nonce": bet.nonce,
        "created_at": bet.created_at.isoformat(),
    }
    result = dict(bet.result)
    if bet.game == CasinoBet.Game.BLACKJACK:
        result.pop("shoe", None)
        result.pop("idx", None)
        result["hands"] = [{**h, "total": services.bj_total(h["cards"])} for h in result["hands"]]
        if bet.status == CasinoBet.Status.ACTIVE:
            result["dealer"] = result["dealer"][:1]   # hole card stays face down
        result["dealer_total"] = services.bj_total(result["dealer"])
        if bet.status == CasinoBet.Status.ACTIVE and result["current"] < len(result["hands"]):
            h = result["hands"][result["current"]]
            two = len(h["cards"]) == 2 and not h["split_aces"]
            data["can"] = {"double": two, "split": two and len(result["hands"]) == 1 and
                           games.bj_card_value(h["cards"][0]) == games.bj_card_value(h["cards"][1])}
    if bet.game == CasinoBet.Game.MINES:
        if bet.status == CasinoBet.Status.ACTIVE:
            result.pop("positions", None)   # never leak mine locations mid-game
            n = len(result["revealed"])
            data["next_multiplier"] = str(games.mines_multiplier(bet.params["mines"], n + 1)) \
                if n < games.MINES_TILES - bet.params["mines"] else None
    data["result"] = result
    return data


def api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Please log in to play", "login": True}, status=401)
        try:
            data = json.loads(request.body or "{}") if request.method == "POST" else request.GET
            bet = view(request, data)
        except (services.CasinoError, ValueError, TypeError, KeyError) as exc:
            return JsonResponse({"error": str(exc) or "Invalid request"}, status=400)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Bad request"}, status=400)
        return JsonResponse({"bet": serialize(bet, request.user) if bet else None,
                             "balance": str(get_wallet(request.user).balance)})
    return wrapped


@require_POST
@api
def api_dice(request, d):
    return services.play_dice(request.user, d.get("amount"), d.get("target"), bool(d.get("over", True)))


@require_POST
@api
def api_plinko(request, d):
    return services.play_plinko(request.user, d.get("amount"), d.get("rows", 12), d.get("risk", "medium"))


@require_POST
@api
def api_wheel(request, d):
    return services.play_wheel(request.user, d.get("amount"), d.get("risk", "medium"))


@require_POST
@api
def api_mines_start(request, d):
    return services.mines_start(request.user, d.get("amount"), d.get("mines", 3))


@require_POST
@api
def api_mines_reveal(request, d):
    return services.mines_reveal(request.user, d.get("tile"))


@require_POST
@api
def api_mines_cashout(request, d):
    return services.mines_cashout(request.user)


@require_POST
@api
def api_roulette(request, d):
    return services.play_roulette(request.user, d.get("chips"))


@require_POST
@api
def api_baccarat(request, d):
    return services.play_baccarat(request.user, d.get("bets"))


@require_POST
@api
def api_blackjack_deal(request, d):
    return services.bj_start(request.user, d.get("amount"))


@require_POST
@api
def api_blackjack_action(request, d):
    return services.bj_action(request.user, d.get("action"))


@require_GET
@api
def api_blackjack_state(request, d):
    return services.active_blackjack(request.user)


@require_GET
@api
def api_mines_state(request, d):
    return services.active_mines(request.user)


@require_GET
def api_feed(request):
    """Recent settled bets for a game (all players, masked) plus the viewer's own."""
    game = request.GET.get("game")
    qs = CasinoBet.objects.exclude(status=CasinoBet.Status.ACTIVE).select_related("user")
    if game in CasinoBet.Game.values:
        qs = qs.filter(game=game)
    viewer = request.user if request.user.is_authenticated else None
    mine = qs.filter(user=viewer)[:15] if viewer else []
    return JsonResponse({"all": [serialize(b, viewer) for b in qs[:20]],
                         "mine": [serialize(b, viewer) for b in mine]})
