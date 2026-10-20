"""
Server-authoritative Aviator (crash) game engine.

Rounds are driven by wall-clock time, so no background worker is needed: every API
call "advances" the game lazily. Each round:

    BETTING  (AVIATOR["BETTING_SECONDS"])  -> players place / cancel bets
    FLYING   (until the crash point)       -> multiplier = e^(rate * t), players cash out
    CRASHED  (AVIATOR["CRASHED_SECONDS"])  -> results shown, then a new round starts

Provably fair: the crash point is derived from a random server seed whose SHA-256 hash
is published before the round starts. The seed is revealed after the crash so anyone
can recompute the result (see crash_point_from_seed).
"""
import hashlib
import hmac
import math
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from wallet import services as wallet
from wallet.models import Transaction

from .models import AviatorBet, GameRound

CFG = settings.AVIATOR
HMAC_KEY = b"lumabet-aviator"


class GameError(Exception):
    pass


# --------------------------------------------------------------------------- math
def crash_point_from_seed(server_seed: str) -> Decimal:
    """
    r is uniform in [0, 1) from the HMAC; crash = (1 - edge) / (1 - r).
    That gives P(crash > x) = (1 - edge) / x, so a cash out at ANY target x returns
    x * (1 - edge) / x = 1 - edge on average: the house edge is exact for every strategy.
    """
    digest = hmac.new(server_seed.encode(), HMAC_KEY, hashlib.sha256).hexdigest()
    r = int(digest[:13], 16) / 2 ** 52
    edge = CFG["HOUSE_EDGE_PERCENT"] / 100
    point = max(1.0, math.floor((1 - edge) / (1 - r) * 100) / 100)
    return min(Decimal(f"{point:.2f}"), Decimal(CFG["MAX_MULTIPLIER"]))


def multiplier_at(seconds: float) -> Decimal:
    if seconds <= 0:
        return Decimal("1.00")
    value = math.floor(math.exp(CFG["GROWTH_RATE"] * seconds) * 100) / 100
    return Decimal(f"{value:.2f}")


def seconds_to_reach(multiplier) -> float:
    return math.log(float(multiplier)) / CFG["GROWTH_RATE"]


def elapsed(game_round, now) -> float:
    return (now - game_round.flight_starts_at).total_seconds()


# --------------------------------------------------------------------------- rounds
def _new_round(sequence, now) -> GameRound:
    seed = secrets.token_hex(32)
    crash = crash_point_from_seed(seed)
    flight = now + timedelta(seconds=CFG["BETTING_SECONDS"])
    crashes = flight + timedelta(seconds=seconds_to_reach(crash))
    return GameRound.objects.create(
        sequence=sequence,
        server_seed=seed,
        seed_hash=hashlib.sha256(seed.encode()).hexdigest(),
        crash_point=crash,
        flight_starts_at=flight,
        crashes_at=crashes,
        next_round_at=crashes + timedelta(seconds=CFG["CRASHED_SECONDS"]),
    )


def current_round() -> GameRound:
    """Return the live round, settling/creating rounds as wall-clock time dictates."""
    now = timezone.now()
    latest = GameRound.objects.order_by("-sequence").first()

    if latest and now < latest.next_round_at:
        phase = latest.phase(now)
        if phase == GameRound.Phase.FLYING:
            settle_auto_cashouts(latest, now)
        elif phase == GameRound.Phase.CRASHED and not latest.settled:
            settle_round(latest)
        return latest

    if latest and not latest.settled:
        settle_round(latest)
    try:
        with transaction.atomic():
            return _new_round((latest.sequence + 1) if latest else 1, now)
    except IntegrityError:
        # Another request created the round at the same moment.
        return GameRound.objects.order_by("-sequence").first()


def _win(bet, multiplier) -> bool:
    """Atomically mark an active bet as won and pay it. Returns False if already settled."""
    payout = min(wallet.money(bet.amount * multiplier), Decimal(CFG["MAX_WIN"]))
    with transaction.atomic():
        updated = AviatorBet.objects.filter(pk=bet.pk, status=AviatorBet.Status.ACTIVE).update(
            status=AviatorBet.Status.WON, cashed_out_at=multiplier, payout=payout,
        )
        if updated:
            wallet.credit(bet.user, payout, Transaction.Kind.AVIATOR_WIN,
                          reference=f"AV{bet.round.sequence}", note=f"Cashed out @ {multiplier}x")
            bet.status, bet.cashed_out_at, bet.payout = AviatorBet.Status.WON, multiplier, payout
    return bool(updated)


def settle_auto_cashouts(game_round, now):
    m = multiplier_at(elapsed(game_round, now))
    bets = game_round.bets.filter(status=AviatorBet.Status.ACTIVE, auto_cashout__isnull=False,
                                  auto_cashout__lte=m).select_related("user", "round")
    for bet in bets:
        _win(bet, bet.auto_cashout)


def settle_round(game_round):
    with transaction.atomic():
        claimed = GameRound.objects.filter(pk=game_round.pk, settled=False).update(settled=True)
        if not claimed:
            return
        game_round.settled = True
        active = game_round.bets.filter(status=AviatorBet.Status.ACTIVE).select_related("user", "round")
        for bet in active:
            if bet.auto_cashout and bet.auto_cashout < game_round.crash_point:
                _win(bet, bet.auto_cashout)
        game_round.bets.filter(status=AviatorBet.Status.ACTIVE).update(status=AviatorBet.Status.LOST)


# --------------------------------------------------------------------------- player actions
def place_bet(user, amount, panel=1, auto_cashout=None) -> AviatorBet:
    try:
        amount = wallet.money(amount)
        auto = wallet.money(auto_cashout) if auto_cashout not in (None, "", 0) else None
    except Exception:
        raise GameError("Invalid amount")
    if panel not in (1, 2):
        raise GameError("Invalid bet panel")
    if amount < CFG["MIN_BET"] or amount > CFG["MAX_BET"]:
        raise GameError(f"Bet must be between {CFG['MIN_BET']} and {CFG['MAX_BET']:,}")
    if auto is not None and auto < Decimal("1.01"):
        raise GameError("Auto cash out must be at least 1.01x")

    game_round = current_round()
    if game_round.phase(timezone.now()) != GameRound.Phase.BETTING:
        raise GameError("Bets are closed — wait for the next round")
    try:
        with transaction.atomic():
            wallet.debit(user, amount, Transaction.Kind.AVIATOR_BET,
                         reference=f"AV{game_round.sequence}", note=f"Panel {panel}")
            return AviatorBet.objects.create(user=user, round=game_round, panel=panel,
                                             amount=amount, auto_cashout=auto)
    except wallet.InsufficientFunds:
        raise GameError("Insufficient balance — please deposit")
    except IntegrityError:
        raise GameError("You already have a bet on this panel")


def cancel_bet(user, bet_id) -> AviatorBet:
    bet = AviatorBet.objects.select_related("round").filter(pk=bet_id, user=user).first()
    if not bet:
        raise GameError("Bet not found")
    if bet.round.phase(timezone.now()) != GameRound.Phase.BETTING:
        raise GameError("Too late to cancel — the plane has taken off")
    with transaction.atomic():
        if AviatorBet.objects.filter(pk=bet.pk, status=AviatorBet.Status.ACTIVE).update(
                status=AviatorBet.Status.CANCELLED):
            wallet.credit(user, bet.amount, Transaction.Kind.AVIATOR_REFUND,
                          reference=f"AV{bet.round.sequence}", note="Bet cancelled")
            bet.status = AviatorBet.Status.CANCELLED
    return bet


def cash_out(user, bet_id) -> AviatorBet:
    bet = AviatorBet.objects.select_related("round", "user").filter(pk=bet_id, user=user).first()
    if not bet:
        raise GameError("Bet not found")
    if bet.status != AviatorBet.Status.ACTIVE:
        if bet.status == AviatorBet.Status.WON:
            return bet  # e.g. auto cash out beat the click
        raise GameError("This bet is no longer active")
    game_round, now = bet.round, timezone.now()
    if game_round.phase(now) != GameRound.Phase.FLYING:
        if game_round.phase(now) == GameRound.Phase.CRASHED:
            current_round()  # settle it
            raise GameError("Flew away! Too late to cash out")
        raise GameError("The plane hasn't taken off yet")
    m = multiplier_at(elapsed(game_round, now))
    if bet.auto_cashout and bet.auto_cashout <= m:
        m = bet.auto_cashout
    if m >= game_round.crash_point:
        raise GameError("Flew away! Too late to cash out")
    if not _win(bet, m):
        bet.refresh_from_db()
    return bet


# --------------------------------------------------------------------------- serialisation
def mask(username: str) -> str:
    if len(username) <= 3:
        return username[0] + "**"
    return f"{username[:2]}***{username[-2:]}"


def serialize_bet(bet, viewer=None):
    return {
        "id": bet.id,
        "player": bet.user.username if viewer and bet.user_id == viewer.id else mask(bet.user.username),
        "mine": bool(viewer and bet.user_id == viewer.id),
        "panel": bet.panel,
        "amount": str(bet.amount),
        "auto_cashout": str(bet.auto_cashout) if bet.auto_cashout else None,
        "cashed_out_at": str(bet.cashed_out_at) if bet.cashed_out_at else None,
        "payout": str(bet.payout),
        "status": bet.status,
    }


def game_state(user=None) -> dict:
    game_round = current_round()
    now = timezone.now()
    phase = game_round.phase(now)
    crashed = phase == GameRound.Phase.CRASHED
    ms = lambda dt: int(dt.timestamp() * 1000)  # noqa: E731

    bets = list(game_round.bets.exclude(status=AviatorBet.Status.CANCELLED)
                .select_related("user").order_by("-amount")[:60])
    history = GameRound.objects.filter(crashes_at__lte=now).order_by("-sequence").values_list(
        "sequence", "crash_point")[:30]

    state = {
        "now": ms(now),
        "round": {
            "id": game_round.id,
            "sequence": game_round.sequence,
            "phase": phase,
            "seed_hash": game_round.seed_hash,
            "flight_starts_at": ms(game_round.flight_starts_at),
            "next_round_at": ms(game_round.next_round_at),
            "betting_seconds": CFG["BETTING_SECONDS"],
            "crash_point": str(game_round.crash_point) if crashed else None,
            "server_seed": game_round.server_seed if crashed else None,
        },
        "growth_rate": CFG["GROWTH_RATE"],
        "multiplier": str(game_round.crash_point if crashed else multiplier_at(elapsed(game_round, now))),
        "history": [{"sequence": s, "crash_point": str(c)} for s, c in history],
        "bets": [serialize_bet(b, user) for b in bets],
        "stats": {
            "players": game_round.bets.exclude(status=AviatorBet.Status.CANCELLED).values("user").distinct().count(),
            "total": str(sum((b.amount for b in bets), Decimal(0))),
        },
        "my_bets": [],
        "balance": None,
    }
    if user and user.is_authenticated:
        mine = game_round.bets.filter(user=user).exclude(status=AviatorBet.Status.CANCELLED).select_related("user")
        state["my_bets"] = [serialize_bet(b, user) for b in mine]
        state["balance"] = str(wallet.get_wallet(user).balance)
    return state
