"""
Pure game maths. Every game pays (1 - edge) of the stake on average:

* Dice   — multiplier = (1 - edge) / win_chance
* Mines  — multiplier after k safe picks = (1 - edge) / P(k safe picks in a row)
* Plinko — bin multipliers shaped by risk, then scaled so Σ P(bin)·mult = 1 - edge
* Wheel  — segment multipliers shaped by risk, then scaled so mean(mult) = 1 - edge
"""
from __future__ import annotations

import math
from decimal import ROUND_DOWN, Decimal
from functools import lru_cache

from django.conf import settings


def edge() -> float:
    return settings.CASINO["HOUSE_EDGE_PERCENT"] / 100


def _floor(value: float, places: int = 2) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


# ----------------------------------------------------------------------------- Dice
DICE_MIN_CHANCE, DICE_MAX_CHANCE = 1.0, 95.0


def dice_chance(target: float, over: bool) -> float:
    """Roll is 0.00–99.99 (10,000 outcomes). Over T wins on roll > T; under T on roll < T."""
    return round(99.99 - target, 2) if over else round(target, 2)


def dice_multiplier(chance: float) -> Decimal:
    return _floor((1 - edge()) * 100 / chance, 4)


def dice_roll(f: float) -> Decimal:
    return Decimal(math.floor(f * 10000)) / 100


# ----------------------------------------------------------------------------- Mines
MINES_TILES = 25


def mines_positions(fs: list[float], mines: int) -> list[int]:
    tiles = list(range(MINES_TILES))
    for i in range(mines):
        j = i + math.floor(fs[i] * (MINES_TILES - i))
        tiles[i], tiles[j] = tiles[j], tiles[i]
    return sorted(tiles[:mines])


def mines_multiplier(mines: int, revealed: int) -> Decimal:
    if revealed == 0:
        return Decimal("1")
    p = math.comb(MINES_TILES - mines, revealed) / math.comb(MINES_TILES, revealed)
    return _floor((1 - edge()) / p, 4)


# ----------------------------------------------------------------------------- Plinko
PLINKO_ROWS = (8, 12, 16)
PLINKO_RISKS = ("low", "medium", "high")
_PLINKO_CURVE = {8: {"low": 0.55, "medium": 0.9, "high": 1.25},
                 12: {"low": 0.45, "medium": 0.78, "high": 1.1},
                 16: {"low": 0.38, "medium": 0.7, "high": 1.02}}


@lru_cache(maxsize=None)
def _plinko_table(rows: int, risk: str, edge_pct: float) -> tuple:
    probs = [math.comb(rows, k) / 2 ** rows for k in range(rows + 1)]
    c = _PLINKO_CURVE[rows][risk]
    shape = [math.exp(c * abs(k - rows / 2)) for k in range(rows + 1)]
    target, floor_mult = 1 - edge_pct / 100, 0.1
    clamped = set()
    for _ in range(rows):   # bins that hit the 0.1x floor are fixed; rescale the rest to hit the target RTP
        fixed = sum(probs[k] * floor_mult for k in clamped)
        scale = (target - fixed) / sum(probs[k] * shape[k] for k in range(rows + 1) if k not in clamped)
        newly = {k for k in range(rows + 1) if k not in clamped and shape[k] * scale < floor_mult}
        if not newly:
            break
        clamped |= newly
    mults = [floor_mult if k in clamped else shape[k] * scale for k in range(rows + 1)]
    return tuple(_floor(m, 2 if m < 100 else 0) for m in mults)


def plinko_table(rows: int, risk: str) -> list[Decimal]:
    return list(_plinko_table(rows, risk, settings.CASINO["HOUSE_EDGE_PERCENT"]))


def plinko_rtp(rows: int, risk: str) -> float:
    return sum(math.comb(rows, k) / 2 ** rows * float(m) for k, m in enumerate(plinko_table(rows, risk)))


def plinko_drop(fs: list[float]) -> tuple[list[int], int]:
    path = [1 if f >= 0.5 else 0 for f in fs]   # 1 = bounce right
    return path, sum(path)


# ----------------------------------------------------------------------------- Wheel
WHEEL_RISKS = ("low", "medium", "high")
_WHEEL_SHAPE = {
    "low": [1.5, 1.2, 1.2, 0, 1.2, 1.5, 1.2, 0, 1.2, 1.2] * 2,
    "medium": [0, 1.5, 0, 2, 0, 1.5, 0, 3, 0, 1.5, 0, 2, 0, 1.5, 0, 5, 0, 1.5, 0, 2],
    "high": [0] * 19 + [1],
}


@lru_cache(maxsize=None)
def _wheel_table(risk: str, edge_pct: float) -> tuple:
    shape = _WHEEL_SHAPE[risk]
    scale = (1 - edge_pct / 100) * len(shape) / sum(shape)
    return tuple(_floor(s * scale, 2) for s in shape)


def wheel_table(risk: str) -> list[Decimal]:
    return list(_wheel_table(risk, settings.CASINO["HOUSE_EDGE_PERCENT"]))


def wheel_segment(f: float, risk: str) -> int:
    return math.floor(f * len(_WHEEL_SHAPE[risk]))


# ----------------------------------------------------------------------------- Cards (shared)
# A card is an int 0..51: rank = c % 13 (0 = Ace … 12 = King), suit = c // 13.
# Infinite-deck dealing from provably-fair floats: card = floor(f * 52).
def cards_from(fs: list[float]) -> list[int]:
    return [math.floor(f * 52) for f in fs]


def rank(card: int) -> int:
    return card % 13


# ----------------------------------------------------------------------------- Roulette (European, single zero)
# The house edge comes from the green 0: every bet pays as if there were 36 numbers.
ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_PAYS = {"number": 35, "red": 1, "black": 1, "odd": 1, "even": 1, "low": 1, "high": 1,
                 "dozen": 2, "column": 2}


def roulette_wins(kind: str, value, n: int) -> bool:
    if kind == "number":
        return int(value) == n
    if n == 0:
        return False
    return {
        "red": n in ROULETTE_RED, "black": n not in ROULETTE_RED,
        "odd": n % 2 == 1, "even": n % 2 == 0, "low": n <= 18, "high": n >= 19,
        "dozen": kind == "dozen" and (n - 1) // 12 + 1 == int(value or 0),
        "column": kind == "column" and (n - 1) % 3 + 1 == int(value or 0),
    }[kind]


# ----------------------------------------------------------------------------- Baccarat (punto banco)
BACCARAT_PAYS = {"player": Decimal("2"), "banker": Decimal("1.95"), "tie": Decimal("9")}   # returns incl. stake


def baccarat_value(card: int) -> int:
    return min(rank(card) + 1, 10) % 10


def baccarat_total(hand) -> int:
    return sum(baccarat_value(c) for c in hand) % 10


def baccarat_deal(cards: list[int]) -> dict:
    player, banker, i = [cards[0], cards[2]], [cards[1], cards[3]], 4
    p, b = baccarat_total(player), baccarat_total(banker)
    if p < 8 and b < 8:                      # no natural
        third = None
        if p <= 5:
            third = baccarat_value(cards[i])
            player.append(cards[i]); i += 1
        b = baccarat_total(banker)
        if third is None:
            draw = b <= 5
        else:
            draw = (b <= 2 or (b == 3 and third != 8) or (b == 4 and 2 <= third <= 7)
                    or (b == 5 and 4 <= third <= 7) or (b == 6 and third in (6, 7)))
        if draw:
            banker.append(cards[i]); i += 1
    p, b = baccarat_total(player), baccarat_total(banker)
    winner = "player" if p > b else "banker" if b > p else "tie"
    return {"player": player, "banker": banker, "player_total": p, "banker_total": b, "winner": winner}


# ----------------------------------------------------------------------------- Blackjack
# Rules: infinite deck, dealer stands on soft 17, dealer peeks for blackjack, blackjack pays 3:2,
# double on any first two cards, one split (split aces receive one card each).
def bj_card_value(card: int) -> int:
    r = rank(card)
    return 11 if r == 0 else min(r + 1, 10)


def bj_value(hand) -> tuple[int, bool]:
    """(best total, is_soft)"""
    total = sum(bj_card_value(c) for c in hand)
    aces = sum(1 for c in hand if rank(c) == 0)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def bj_is_blackjack(hand) -> bool:
    return len(hand) == 2 and bj_value(hand)[0] == 21
