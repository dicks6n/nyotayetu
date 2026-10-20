"""
Football market engine.

Every match is described by two numbers: the expected goals of each side over 90 minutes
(lambda_home, lambda_away). Goals follow independent Poisson processes, so from those two
numbers — plus the current minute and score when the match is live — we can price *every*
market consistently and re-price them in play.

Odds = 1 / (fair probability × (1 + margin)), so each market carries the configured margin.
"""
from __future__ import annotations

import math
from decimal import ROUND_DOWN, Decimal
from functools import lru_cache

from django.conf import settings

MAX_GOALS = 10
MIN_ODDS, MAX_ODDS = Decimal("1.01"), Decimal("250")
CLOSE_PROB = 0.985          # an outcome this certain closes its market (nothing left to bet on)

GOAL_LINES = ("0.5", "1.5", "2.5", "3.5", "4.5", "5.5")
TEAM_LINES = ("0.5", "1.5", "2.5")
CORRECT_SCORES = [f"{h}-{a}" for h in range(4) for a in range(4)]
HTFT = [f"{h}/{f}" for h in ("1", "X", "2") for f in ("1", "X", "2")]

# key -> (group, label, [(pick, label)])  —  "{home}" / "{away}" are filled in with team names
MARKETS: dict[str, tuple] = {
    "1x2": ("Main", "1X2 — Full time", [("1", "{home}"), ("X", "Draw"), ("2", "{away}")]),
    "dc": ("Main", "Double chance", [("1X", "{home} or draw"), ("12", "{home} or {away}"), ("X2", "Draw or {away}")]),
    "dnb": ("Main", "Draw no bet", [("1", "{home}"), ("2", "{away}")]),
    "btts": ("Goals", "Both teams to score (GG/NG)", [("yes", "GG — Yes"), ("no", "NG — No")]),
    **{f"ou_{l}": ("Goals", f"Total goals over/under {l}", [("over", f"Over {l}"), ("under", f"Under {l}")])
       for l in GOAL_LINES},
    "oe": ("Goals", "Total goals odd/even", [("odd", "Odd"), ("even", "Even")]),
    **{f"home_ou_{l}": ("Team goals", f"{{home}} goals over/under {l}", [("over", f"Over {l}"), ("under", f"Under {l}")])
       for l in TEAM_LINES},
    **{f"away_ou_{l}": ("Team goals", f"{{away}} goals over/under {l}", [("over", f"Over {l}"), ("under", f"Under {l}")])
       for l in TEAM_LINES},
    "ht_1x2": ("Half time", "1X2 — Half time", [("1", "{home}"), ("X", "Draw"), ("2", "{away}")]),
    "htft": ("Half time", "Half time / Full time", [(p, p) for p in HTFT]),
    "cs": ("Correct score", "Correct score", [(s, s) for s in CORRECT_SCORES] + [("other", "Any other")]),
}
GROUP_ORDER = ["Main", "Goals", "Team goals", "Half time", "Correct score"]
HT_MARKETS = {"ht_1x2", "htft"}


def margin() -> float:
    return settings.SPORTS["MARGIN_PERCENT"] / 100


# ---------------------------------------------------------------------------- probability core
@lru_cache(maxsize=4096)
def _pois(lam: float) -> tuple:
    lam = max(lam, 1e-9)
    return tuple(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(MAX_GOALS + 1))


def _matrix(lh: float, la: float):
    ph, pa = _pois(round(lh, 4)), _pois(round(la, 4))
    return [[ph[i] * pa[j] for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]


def _res(h, a):
    return "1" if h > a else "2" if a > h else "X"


def remaining_fraction(minute: int, upto: int = 90) -> float:
    return max(0.0, (upto - minute) / 90)


def probabilities(lh: float, la: float, minute: int = 0, score=(0, 0), ht_score=None) -> dict:
    """Fair probabilities for every market and pick, given the current state of the match."""
    sh, sa = score
    rem = remaining_fraction(minute)
    m = _matrix(lh * rem, la * rem)                       # goals still to come
    final = {}
    for i, row in enumerate(m):
        for j, p in enumerate(row):
            key = (sh + i, sa + j)
            final[key] = final.get(key, 0) + p

    out = {k: {} for k in MARKETS}
    for (h, a), p in final.items():
        r, t = _res(h, a), h + a
        out["1x2"][r] = out["1x2"].get(r, 0) + p
        for pick in ("1X", "12", "X2"):
            if r in pick:
                out["dc"][pick] = out["dc"].get(pick, 0) + p
        out["btts"]["yes" if h and a else "no"] = out["btts"].get("yes" if h and a else "no", 0) + p
        for l in GOAL_LINES:
            k = "over" if t > float(l) else "under"
            out[f"ou_{l}"][k] = out[f"ou_{l}"].get(k, 0) + p
        out["oe"]["odd" if t % 2 else "even"] = out["oe"].get("odd" if t % 2 else "even", 0) + p
        for l in TEAM_LINES:
            kh, ka = ("over" if h > float(l) else "under"), ("over" if a > float(l) else "under")
            out[f"home_ou_{l}"][kh] = out[f"home_ou_{l}"].get(kh, 0) + p
            out[f"away_ou_{l}"][ka] = out[f"away_ou_{l}"].get(ka, 0) + p
        cs = f"{h}-{a}" if f"{h}-{a}" in CORRECT_SCORES else "other"
        out["cs"][cs] = out["cs"].get(cs, 0) + p
    p1, p2 = out["1x2"].get("1", 0), out["1x2"].get("2", 0)
    if p1 + p2 > 0:
        out["dnb"] = {"1": p1 / (p1 + p2), "2": p2 / (p1 + p2)}

    # Half-time markets: first-half goals still to come + second half on top for HT/FT
    if minute < 45 and ht_score is None:
        rem1, rem2 = remaining_fraction(minute, 45), 0.5
        m1, m2 = _matrix(lh * rem1, la * rem1), _matrix(lh * rem2, la * rem2)
        for i, row in enumerate(m1):
            for j, p in enumerate(row):
                hh, ha = sh + i, sa + j
                if p < 1e-9:
                    continue
                hr = _res(hh, ha)
                out["ht_1x2"][hr] = out["ht_1x2"].get(hr, 0) + p
                for x, row2 in enumerate(m2):
                    for y, q in enumerate(row2):
                        key = f"{hr}/{_res(hh + x, ha + y)}"
                        out["htft"][key] = out["htft"].get(key, 0) + p * q
    else:
        out.pop("ht_1x2")
        out.pop("htft")
    return out


def to_odds(p: float, mg: float) -> Decimal | None:
    if p <= 0.004:
        return None
    o = Decimal(str(1 / (p * (1 + mg)))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return min(max(o, MIN_ODDS), MAX_ODDS)


def price(lh: float, la: float, minute: int = 0, score=(0, 0), ht_score=None) -> dict:
    """{market: {pick: "odds"}} — closed markets/picks are left out."""
    mg, priced = margin(), {}
    for key, picks in probabilities(lh, la, minute, score, ht_score).items():
        if not picks or max(picks.values()) >= CLOSE_PROB:
            continue
        row = {pick: str(o) for pick, p in picks.items() if (o := to_odds(p, mg)) is not None}
        if len(row) >= 2:
            priced[key] = row
    return priced


# ---------------------------------------------------------------------------- fitting
def fit_lambdas(p1: float, px: float, p2: float, p_over25: float | None = None) -> tuple[float, float]:
    """Find expected goals that reproduce given (normalised) 1X2 [and O/U 2.5] probabilities."""
    def err(lh, la):
        pr = probabilities(lh, la)
        e = (pr["1x2"].get("1", 0) - p1) ** 2 + (pr["1x2"].get("X", 0) - px) ** 2 + (pr["1x2"].get("2", 0) - p2) ** 2
        if p_over25 is not None:
            e += (pr["ou_2.5"].get("over", 0) - p_over25) ** 2
        return e

    best, step = (1.4, 1.1), 0.4
    best_e = err(*best)
    while step > 0.01:
        improved = True
        while improved:
            improved = False
            for dh, da in ((step, 0), (-step, 0), (0, step), (0, -step), (step, step), (-step, -step)):
                cand = (min(max(best[0] + dh, 0.1), 5), min(max(best[1] + da, 0.1), 5))
                e = err(*cand)
                if e < best_e - 1e-12:
                    best, best_e, improved = cand, e, True
        step /= 2
    return round(best[0], 3), round(best[1], 3)


def lambdas_from_odds(o1, ox, o2, over25=None, under25=None):
    inv = [1 / float(o) for o in (o1, ox, o2)]
    s = sum(inv)
    p_over = None
    if over25 and under25:
        a, b = 1 / float(over25), 1 / float(under25)
        p_over = a / (a + b)
    return fit_lambdas(inv[0] / s, inv[1] / s, inv[2] / s, p_over)


# ---------------------------------------------------------------------------- grading
def grade(market: str, pick: str, ft, ht=None) -> str:
    """'won' | 'lost' | 'void' for a pick, given full-time (and half-time) scores."""
    h, a = ft
    t = h + a
    if market == "1x2":
        return "won" if _res(h, a) == pick else "lost"
    if market == "dc":
        return "won" if _res(h, a) in pick else "lost"
    if market == "dnb":
        r = _res(h, a)
        return "void" if r == "X" else ("won" if r == pick else "lost")
    if market == "btts":
        return "won" if (pick == "yes") == bool(h and a) else "lost"
    if market.startswith("ou_"):
        return "won" if (pick == "over") == (t > float(market[3:])) else "lost"
    if market.startswith("home_ou_"):
        return "won" if (pick == "over") == (h > float(market[8:])) else "lost"
    if market.startswith("away_ou_"):
        return "won" if (pick == "over") == (a > float(market[8:])) else "lost"
    if market == "oe":
        return "won" if (pick == "odd") == bool(t % 2) else "lost"
    if market == "cs":
        actual = f"{h}-{a}" if f"{h}-{a}" in CORRECT_SCORES else "other"
        return "won" if actual == pick else "lost"
    if market in HT_MARKETS:
        if ht is None:
            return "void"
        hr = _res(*ht)
        if market == "ht_1x2":
            return "won" if hr == pick else "lost"
        return "won" if f"{hr}/{_res(h, a)}" == pick else "lost"
    return "void"


# ---------------------------------------------------------------------------- labels
def market_label(key: str, home: str, away: str) -> str:
    return MARKETS[key][1].format(home=home, away=away) if key in MARKETS else key


def pick_label(key: str, pick: str, home: str, away: str) -> str:
    if key in MARKETS:
        for p, label in MARKETS[key][2]:
            if p == pick:
                return label.format(home=home, away=away)
    return pick


def grouped(odds: dict, home: str, away: str) -> list:
    """For templates: [(group, [(key, label, [(pick, label, odds)])])] in display order."""
    groups = {g: [] for g in GROUP_ORDER}
    for key, (group, label, picks) in MARKETS.items():
        row = odds.get(key)
        groups[group].append((key, label.format(home=home, away=away),
                              [(p, pl.format(home=home, away=away), (row or {}).get(p)) for p, pl in picks]))
    return [(g, ms) for g, ms in groups.items() if ms]
