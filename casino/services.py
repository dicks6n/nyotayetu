from __future__ import annotations

import math
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from wallet import services as wallet
from wallet.models import Transaction

from . import fair, games
from .models import CasinoBet, SeedPair

CFG = settings.CASINO
G = CasinoBet.Game


class CasinoError(Exception):
    pass


# ----------------------------------------------------------------------------- seeds
def active_seed(user, lock=False) -> SeedPair:
    qs = SeedPair.objects.select_for_update() if lock else SeedPair.objects
    pair = qs.filter(user=user, active=True).first()
    return pair or SeedPair.objects.create(user=user)


@transaction.atomic
def rotate_seed(user, client_seed=""):
    if CasinoBet.objects.filter(user=user, status=CasinoBet.Status.ACTIVE).exists():
        raise CasinoError("Finish your Mines game before changing seeds")
    old = active_seed(user, lock=True)
    old.active, old.revealed_at = False, timezone.now()
    old.save(update_fields=["active", "revealed_at"])
    client_seed = (client_seed or "").strip()[:64]
    return old, SeedPair.objects.create(user=user, **({"client_seed": client_seed} if client_seed else {}))


def _next_roll(user, count):
    """Lock the player's seed pair, consume one nonce, return (pair, nonce, floats)."""
    pair = active_seed(user, lock=True)
    nonce = pair.nonce
    pair.nonce = nonce + 1
    pair.save(update_fields=["nonce"])
    return pair, nonce, fair.floats(pair.server_seed, pair.client_seed, nonce, count)


# ----------------------------------------------------------------------------- money helpers
def _stake(user, amount, game):
    try:
        amount = wallet.money(amount)
    except Exception:
        raise CasinoError("Invalid amount")
    if amount < CFG["MIN_BET"] or amount > CFG["MAX_BET"]:
        raise CasinoError(f"Bet must be between {CFG['MIN_BET']} and {CFG['MAX_BET']:,}")
    try:
        wallet.debit(user, amount, Transaction.Kind.CASINO_BET, note=G(game).label)
    except wallet.InsufficientFunds:
        raise CasinoError("Insufficient balance — please deposit")
    return amount


def _settle(bet: CasinoBet, multiplier: Decimal, payout: Decimal | None = None):
    """Pay a finished bet. Table games pass the exact payout; the multiplier is then derived."""
    if payout is None:
        payout = wallet.money(bet.amount * multiplier)
    else:
        multiplier = (payout / bet.amount).quantize(Decimal("0.0001"))
    payout = min(payout, Decimal(CFG["MAX_WIN"]))
    bet.multiplier, bet.payout = multiplier, payout
    bet.status = CasinoBet.Status.WON if multiplier >= 1 else CasinoBet.Status.LOST
    if payout > 0:
        wallet.credit(bet.user, payout, Transaction.Kind.CASINO_WIN, reference=f"C{bet.pk}",
                      note=f"{bet.get_game_display()} {multiplier.normalize():f}x")


def _instant(user, game, amount, params, count, resolve, exact_payout=False):
    with transaction.atomic():
        amount = _stake(user, amount, game)
        pair, nonce, fs = _next_roll(user, count)
        value, result = resolve(fs)
        bet = CasinoBet.objects.create(user=user, game=game, seed_pair=pair, nonce=nonce,
                                       amount=amount, params=params, result=result)
        if exact_payout:
            _settle(bet, None, value)
        else:
            _settle(bet, value)
        bet.save(update_fields=["multiplier", "payout", "status"])
    return bet


# ----------------------------------------------------------------------------- Dice
def play_dice(user, amount, target, over=True):
    try:
        target = float(Decimal(str(target)).quantize(Decimal("0.01")))
    except Exception:
        raise CasinoError("Invalid target")
    chance = games.dice_chance(target, bool(over))
    if not games.DICE_MIN_CHANCE <= chance <= games.DICE_MAX_CHANCE:
        raise CasinoError(f"Win chance must be between {games.DICE_MIN_CHANCE:g}% and {games.DICE_MAX_CHANCE:g}%")
    payout_mult = games.dice_multiplier(chance)

    def resolve(fs):
        roll = games.dice_roll(fs[0])
        won = roll > Decimal(str(target)) if over else roll < Decimal(str(target))
        return (payout_mult if won else Decimal(0)), {"roll": str(roll), "won": won}

    return _instant(user, G.DICE, amount, {"target": target, "over": bool(over), "chance": chance,
                                            "multiplier": str(payout_mult)}, 1, resolve)


# ----------------------------------------------------------------------------- Plinko
def play_plinko(user, amount, rows=12, risk="medium"):
    rows = int(rows)
    if rows not in games.PLINKO_ROWS or risk not in games.PLINKO_RISKS:
        raise CasinoError("Invalid Plinko settings")
    table = games.plinko_table(rows, risk)

    def resolve(fs):
        path, slot = games.plinko_drop(fs)
        return table[slot], {"path": path, "slot": slot}

    return _instant(user, G.PLINKO, amount, {"rows": rows, "risk": risk}, rows, resolve)


# ----------------------------------------------------------------------------- Wheel
def play_wheel(user, amount, risk="medium"):
    if risk not in games.WHEEL_RISKS:
        raise CasinoError("Invalid wheel risk")
    table = games.wheel_table(risk)

    def resolve(fs):
        seg = games.wheel_segment(fs[0], risk)
        return table[seg], {"segment": seg}

    return _instant(user, G.WHEEL, amount, {"risk": risk}, 1, resolve)


# ----------------------------------------------------------------------------- Mines
def active_mines(user):
    return CasinoBet.objects.filter(user=user, game=G.MINES, status=CasinoBet.Status.ACTIVE).first()


def mines_start(user, amount, mines=3):
    mines = int(mines)
    if not 1 <= mines <= 24:
        raise CasinoError("Choose between 1 and 24 mines")
    with transaction.atomic():
        if CasinoBet.objects.select_for_update().filter(user=user, game=G.MINES,
                                                        status=CasinoBet.Status.ACTIVE).exists():
            raise CasinoError("You already have a Mines game in play")
        amount = _stake(user, amount, G.MINES)
        pair, nonce, fs = _next_roll(user, 24)
        return CasinoBet.objects.create(
            user=user, game=G.MINES, seed_pair=pair, nonce=nonce, amount=amount, multiplier=Decimal(1),
            params={"mines": mines}, result={"positions": games.mines_positions(fs, mines), "revealed": []},
        )


@transaction.atomic
def mines_reveal(user, tile):
    bet = CasinoBet.objects.select_for_update().filter(user=user, game=G.MINES,
                                                       status=CasinoBet.Status.ACTIVE).first()
    if not bet:
        raise CasinoError("No Mines game in play")
    tile = int(tile)
    revealed = bet.result["revealed"]
    if not 0 <= tile < games.MINES_TILES or tile in revealed:
        raise CasinoError("Pick a hidden tile")
    revealed.append(tile)
    if tile in bet.result["positions"]:
        bet.result["hit"] = tile
        bet.status, bet.multiplier = CasinoBet.Status.LOST, Decimal(0)
    else:
        mines = bet.params["mines"]
        bet.multiplier = games.mines_multiplier(mines, len(revealed))
        if len(revealed) == games.MINES_TILES - mines:   # cleared the board
            _settle(bet, bet.multiplier)
    bet.save(update_fields=["result", "status", "multiplier", "payout"])
    return bet


@transaction.atomic
def mines_cashout(user):
    bet = CasinoBet.objects.select_for_update().filter(user=user, game=G.MINES,
                                                       status=CasinoBet.Status.ACTIVE).first()
    if not bet:
        raise CasinoError("No Mines game in play")
    if not bet.result["revealed"]:
        raise CasinoError("Reveal at least one gem first")
    _settle(bet, bet.multiplier)
    bet.save(update_fields=["status", "multiplier", "payout"])
    return bet


# ----------------------------------------------------------------------------- Roulette
def _money_or_zero(v):
    try:
        v = wallet.money(v or 0)
    except Exception:
        raise CasinoError("Invalid chip amount")
    if v < 0:
        raise CasinoError("Invalid chip amount")
    return v


def play_roulette(user, chips):
    if not isinstance(chips, list) or not chips or len(chips) > 60:
        raise CasinoError("Place at least one chip on the table")
    clean = []
    for c in chips:
        kind, value = str(c.get("type")), c.get("value")
        if kind not in games.ROULETTE_PAYS:
            raise CasinoError("Unknown bet type")
        if kind == "number" and not (str(value).isdigit() and 0 <= int(value) <= 36):
            raise CasinoError("Numbers are 0–36")
        if kind in ("dozen", "column") and str(value) not in ("1", "2", "3"):
            raise CasinoError("Dozens and columns are 1–3")
        amt = _money_or_zero(c.get("amount"))
        if amt > 0:
            clean.append({"type": kind, "value": value if kind in ("number", "dozen", "column") else None,
                          "amount": str(amt)})
    total = sum((Decimal(c["amount"]) for c in clean), Decimal(0))

    def resolve(fs):
        n = math.floor(fs[0] * 37)
        payout, winners = Decimal(0), []
        for i, c in enumerate(clean):
            if games.roulette_wins(c["type"], c["value"], n):
                payout += Decimal(c["amount"]) * (games.ROULETTE_PAYS[c["type"]] + 1)
                winners.append(i)
        return payout, {"number": n, "color": "green" if n == 0 else "red" if n in games.ROULETTE_RED else "black",
                        "winners": winners}

    return _instant(user, G.ROULETTE, total, {"chips": clean}, 1, resolve, exact_payout=True)


# ----------------------------------------------------------------------------- Baccarat
def play_baccarat(user, bets):
    bets = {k: _money_or_zero((bets or {}).get(k)) for k in ("player", "banker", "tie")}
    total = sum(bets.values(), Decimal(0))

    def resolve(fs):
        deal = games.baccarat_deal(games.cards_from(fs))
        w = deal["winner"]
        payout = bets[w] * games.BACCARAT_PAYS[w]
        if w == "tie":                       # player/banker bets push on a tie
            payout += bets["player"] + bets["banker"]
        return wallet.money(payout), deal

    return _instant(user, G.BACCARAT, total, {k: str(v) for k, v in bets.items()}, 6, resolve, exact_payout=True)


# ----------------------------------------------------------------------------- Blackjack
def _bj_draw(res):
    card = res["shoe"][res["idx"]]
    res["idx"] += 1
    return card


def _bj_finish(bet):
    """Dealer plays out (if any hand is still live), every hand is graded, the bet is paid."""
    res = bet.result
    dealer = res["dealer"]
    live = [h for h in res["hands"] if bj_total(h["cards"]) <= 21]
    natural = len(res["hands"]) == 1 and games.bj_is_blackjack(res["hands"][0]["cards"])
    if live and not natural:
        while True:
            total, _soft = games.bj_value(dealer)
            if total >= 17:                  # stands on all 17s, soft included
                break
            dealer.append(_bj_draw(res))
    d_total, d_bj = games.bj_value(dealer)[0], games.bj_is_blackjack(dealer)
    payout = Decimal(0)
    for h in res["hands"]:
        stake, p_total = Decimal(h["stake"]), bj_total(h["cards"])
        p_bj = natural
        if p_total > 21:
            h["outcome"] = "bust"
        elif p_bj and d_bj:
            h["outcome"], win = "push", stake
            payout += win
        elif p_bj:
            h["outcome"] = "blackjack"
            payout += stake * Decimal("2.5")
        elif d_bj:
            h["outcome"] = "lose"
        elif d_total > 21 or p_total > d_total:
            h["outcome"] = "win"
            payout += stake * 2
        elif p_total == d_total:
            h["outcome"] = "push"
            payout += stake
        else:
            h["outcome"] = "lose"
        h["done"] = True
    res["dealer_total"] = d_total
    res["finished"] = True
    _settle(bet, None, wallet.money(payout))


def bj_total(cards):
    return games.bj_value(cards)[0]


def _bj_advance(bet):
    res = bet.result
    hands = res["hands"]
    for i, h in enumerate(hands):
        if not h["done"] and bj_total(h["cards"]) >= 21:
            h["done"] = True
    while res["current"] < len(hands) and hands[res["current"]]["done"]:
        res["current"] += 1
    if res["current"] >= len(hands):
        _bj_finish(bet)


def active_blackjack(user):
    return CasinoBet.objects.filter(user=user, game=G.BLACKJACK, status=CasinoBet.Status.ACTIVE).first()


def bj_start(user, amount):
    with transaction.atomic():
        if CasinoBet.objects.select_for_update().filter(user=user, game=G.BLACKJACK,
                                                        status=CasinoBet.Status.ACTIVE).exists():
            raise CasinoError("Finish your current hand first")
        amount = _stake(user, amount, G.BLACKJACK)
        pair, nonce, fs = _next_roll(user, 60)
        shoe = games.cards_from(fs)
        res = {"shoe": shoe, "idx": 4, "dealer": [shoe[1], shoe[3]], "current": 0, "finished": False,
               "hands": [{"cards": [shoe[0], shoe[2]], "stake": str(amount), "doubled": False,
                          "split_aces": False, "done": False, "outcome": None}]}
        bet = CasinoBet.objects.create(user=user, game=G.BLACKJACK, seed_pair=pair, nonce=nonce,
                                       amount=amount, multiplier=Decimal(0), params={"amount": str(amount)},
                                       result=res)
        # Naturals: dealer peeks, player blackjack settles immediately.
        if games.bj_is_blackjack(res["hands"][0]["cards"]) or games.bj_is_blackjack(res["dealer"]):
            _bj_finish(bet)
        bet.save()
        return bet


@transaction.atomic
def bj_action(user, action):
    bet = CasinoBet.objects.select_for_update().filter(user=user, game=G.BLACKJACK,
                                                       status=CasinoBet.Status.ACTIVE).first()
    if not bet:
        raise CasinoError("No hand in play — deal first")
    res = bet.result
    hand = res["hands"][res["current"]]
    cards = hand["cards"]
    if action == "hit":
        cards.append(_bj_draw(res))
    elif action == "stand":
        hand["done"] = True
    elif action == "double":
        if len(cards) != 2 or hand["split_aces"]:
            raise CasinoError("You can only double on your first two cards")
        extra = Decimal(hand["stake"])
        try:
            wallet.debit(user, extra, Transaction.Kind.CASINO_BET, note="Blackjack double")
        except wallet.InsufficientFunds:
            raise CasinoError("Insufficient balance to double")
        bet.amount += extra
        hand["stake"], hand["doubled"] = str(extra * 2), True
        cards.append(_bj_draw(res))
        hand["done"] = True
    elif action == "split":
        if len(res["hands"]) != 1 or len(cards) != 2 or games.bj_card_value(cards[0]) != games.bj_card_value(cards[1]):
            raise CasinoError("You can split a pair once")
        extra = Decimal(hand["stake"])
        try:
            wallet.debit(user, extra, Transaction.Kind.CASINO_BET, note="Blackjack split")
        except wallet.InsufficientFunds:
            raise CasinoError("Insufficient balance to split")
        bet.amount += extra
        aces = games.rank(cards[0]) == 0
        res["hands"] = [{"cards": [c, _bj_draw(res)], "stake": hand["stake"], "doubled": False,
                         "split_aces": aces, "done": aces, "outcome": None} for c in cards]
    else:
        raise CasinoError("Unknown action")
    _bj_advance(bet)
    bet.save()
    return bet
