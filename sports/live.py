"""
Live match engine.

* Upcoming matches are priced from their goal model (lambdas fitted from the 1X2 odds).
* At kickoff a match goes LIVE. Its clock comes from:
    - VIRTUAL matches: an accelerated clock (SPORTS["VIRTUAL"]); goals were drawn secretly at creation.
    - API matches: the data feed (sports.providers.api_football) updates minute/score.
    - MANUAL matches: the real clock; staff enter goals and the result in the admin.
* Every tick re-prices all markets from the current minute and score. A goal suspends the match for a
  few seconds (no bets accepted) before new prices are offered.
* At full time virtual matches settle themselves; API/manual matches settle when the result arrives.

tick() is cheap and throttled, so it is called lazily from sports requests; `manage.py run_live`
runs it in a loop so matches progress and settle even with no visitors.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone

from . import markets
from .models import League, Match

log = logging.getLogger(__name__)
CFG = settings.SPORTS
VCFG = CFG["VIRTUAL"]
_rng = random.SystemRandom()
_last_tick = 0.0

VIRTUAL_TEAMS = [
    ("Nairobi Lions", 1.25), ("Mombasa Sharks", 1.15), ("Kisumu Flamingos", 1.0), ("Nakuru Rhinos", 1.1),
    ("Eldoret Eagles", 1.2), ("Thika Buffaloes", 0.95), ("Machakos Leopards", 0.9), ("Nyeri Hornbills", 0.85),
    ("Kakamega Cheetahs", 1.05), ("Malindi Dolphins", 0.9), ("Garissa Camels", 0.8), ("Naivasha Hippos", 0.95),
    ("Kericho Tea Kings", 1.0), ("Lamu Dhows", 0.85), ("Kitale Zebras", 0.9), ("Embu Elephants", 1.1),
]


# ---------------------------------------------------------------------------- pricing
def ensure_lambdas(match: Match):
    if match.lambda_home is None or match.lambda_away is None:
        match.lambda_home, match.lambda_away = markets.lambdas_from_odds(
            match.home_odds, match.draw_odds, match.away_odds)


def reprice(match: Match):
    ensure_lambdas(match)
    if match.status == Match.Status.LIVE:
        score = (match.home_score or 0, match.away_score or 0)
        match.odds = markets.price(match.lambda_home, match.lambda_away, match.minute, score,
                                   match.ht_result_score)
    elif match.status == Match.Status.UPCOMING:
        match.odds = markets.price(match.lambda_home, match.lambda_away)
        one = match.odds.get("1x2", {})
        if len(one) == 3:   # keep the headline columns in sync with the model
            match.home_odds, match.draw_odds, match.away_odds = one["1"], one["X"], one["2"]
    else:
        match.odds = {}


# ---------------------------------------------------------------------------- clocks
def _clock(elapsed_s: float, minute_s: float, ht_s: float):
    """(period, minute) from seconds since kickoff for a 45 + break + 45 match."""
    half = 45 * minute_s
    if elapsed_s < half:
        return "1H", int(elapsed_s // minute_s) + 1
    if elapsed_s < half + ht_s:
        return "HT", 45
    second = elapsed_s - half - ht_s
    if second < half:
        return "2H", 45 + int(second // minute_s) + 1
    return "FT", 90


def _goal(match: Match, team: str, minute: int, now, suspend=True):
    match.events = (match.events or []) + [{"minute": minute, "team": team}]
    if not suspend:
        return
    seconds = VCFG["GOAL_SUSPEND_SECONDS"] if match.source == Match.Source.VIRTUAL else CFG["GOAL_SUSPEND_SECONDS"]
    match.suspended_until = now + timedelta(seconds=seconds)


def is_demo_fixture(match: Match) -> bool:
    """Fixtures made by `seed_matches` for local development play themselves out — only in demo mode."""
    return bool(settings.DEMO_PAYMENTS and match.source == Match.Source.MANUAL
                and match.external_id.startswith("demo-") and match.script is not None)


def advance_virtual(match: Match, now, minute_s=None, ht_s=None):
    period, minute = _clock((now - match.kickoff).total_seconds(),
                            minute_s or VCFG["MINUTE_SECONDS"], VCFG["HT_SECONDS"] if ht_s is None else ht_s)
    match.status, match.period, match.minute = Match.Status.LIVE, period, min(minute, 90)
    seen = len(match.events or [])
    scored = [g for g in match.script if g["minute"] <= match.minute]
    for g in scored[seen:]:
        # only a goal that has just happened freezes betting (not ones we're catching up on)
        _goal(match, g["team"], g["minute"], now, suspend=match.minute - g["minute"] <= 2)
    match.home_score = sum(1 for g in scored if g["team"] == "home")
    match.away_score = len(scored) - match.home_score
    if period in ("HT", "2H", "FT") and match.ht_home is None:
        first = [g for g in match.script if g["minute"] <= 45]
        match.ht_home = sum(1 for g in first if g["team"] == "home")
        match.ht_away = len(first) - match.ht_home
    if period == "FT":
        match.status = Match.Status.FINISHED


def advance_manual(match: Match, now):
    """Real-time clock for admin-run matches; staff type goals into the admin."""
    if match.status == Match.Status.UPCOMING:
        match.status = Match.Status.LIVE
        match.home_score = match.home_score or 0
        match.away_score = match.away_score or 0
    period, minute = _clock((now - match.kickoff).total_seconds(), 60, CFG["HALF_TIME_MINUTES"] * 60)
    if period == "FT":
        # wait for staff to confirm the result; no betting meanwhile
        period, minute = "2H", 90
        match.suspended_until = now + timedelta(minutes=5)
    match.period, match.minute = period, minute


# ---------------------------------------------------------------------------- virtual schedule
@transaction.atomic
def ensure_virtual_schedule(now=None):
    if not VCFG["ENABLED"]:
        return
    now = now or timezone.now()
    league, _ = League.objects.get_or_create(name=VCFG["LEAGUE_NAME"], defaults={"flag": "⚡", "priority": 50})
    upcoming = Match.objects.filter(source=Match.Source.VIRTUAL, status=Match.Status.UPCOMING, kickoff__gt=now)
    last = Match.objects.filter(source=Match.Source.VIRTUAL).order_by("-kickoff").first()
    next_ko = max(last.kickoff + timedelta(minutes=VCFG["INTERVAL_MINUTES"]) if last else now,
                  now + timedelta(seconds=45))
    for _ in range(VCFG["UPCOMING"] - upcoming.count()):
        (home, hs), (away, as_) = _rng.sample(VIRTUAL_TEAMS, 2)
        lh = round(1.45 * hs / as_ ** 0.5 * _rng.uniform(0.9, 1.1), 3)
        la = round(1.15 * as_ / hs ** 0.5 * _rng.uniform(0.9, 1.1), 3)
        script = sorted(
            [{"minute": _rng.randint(1, 90), "team": "home"} for _ in range(_poisson(lh))] +
            [{"minute": _rng.randint(1, 90), "team": "away"} for _ in range(_poisson(la))],
            key=lambda g: g["minute"])
        m = Match(league=league, home_team=home, away_team=away, kickoff=next_ko.replace(second=0, microsecond=0),
                  source=Match.Source.VIRTUAL, lambda_home=lh, lambda_away=la, script=script,
                  home_odds=0, draw_odds=0, away_odds=0)
        reprice(m)
        m.save()
        next_ko += timedelta(minutes=VCFG["INTERVAL_MINUTES"])
    # tidy up old virtual fixtures nobody bet on
    Match.objects.filter(source=Match.Source.VIRTUAL, status=Match.Status.FINISHED,
                         kickoff__lt=now - timedelta(days=2), selections__isnull=True).delete()


def _poisson(lam):
    # Knuth's algorithm — fine for small lambdas
    l, k, p = pow(2.718281828459045, -lam), 0, 1.0
    while True:
        p *= _rng.random()
        if p <= l:
            return k
        k += 1


# ---------------------------------------------------------------------------- the tick
def tick(force=False):
    """Advance clocks / re-price. A momentary database lock just skips this tick (the next one catches up)."""
    global _last_tick
    if not force and time.monotonic() - _last_tick < CFG["TICK_SECONDS"]:
        return
    _last_tick = time.monotonic()
    try:
        _tick()
    except OperationalError as exc:
        log.warning("live tick skipped: %s", exc)
        if force:
            raise


def _tick():
    from .services import settle_match
    now = timezone.now()
    ensure_virtual_schedule(now)
    due = Match.objects.filter(status__in=[Match.Status.UPCOMING, Match.Status.LIVE], kickoff__lte=now)
    for match in due.select_related("league"):
        with transaction.atomic():
            match = Match.objects.select_for_update().get(pk=match.pk)
            if match.status not in (Match.Status.UPCOMING, Match.Status.LIVE):
                continue
            if match.source == Match.Source.VIRTUAL:
                advance_virtual(match, now)
            elif is_demo_fixture(match):
                advance_virtual(match, now, 60, CFG["HALF_TIME_MINUTES"] * 60)   # real-time clock
            elif match.source == Match.Source.MANUAL:
                advance_manual(match, now)
            elif match.status == Match.Status.UPCOMING:   # API: feed hasn't confirmed kickoff yet
                match.status, match.period, match.minute = Match.Status.LIVE, "1H", 1
                match.home_score, match.away_score = match.home_score or 0, match.away_score or 0
            reprice(match)
            match.save()
            if match.status == Match.Status.FINISHED:
                settle_match(match)


def record_score(match: Match, home: int, away: int, minute: int, period: str, now=None):
    """Used by data feeds and the admin: apply a new live score, emitting goal events."""
    now = now or timezone.now()
    old_h, old_a = match.home_score or 0, match.away_score or 0
    for _ in range(max(0, home - old_h)):
        _goal(match, "home", minute, now)
    for _ in range(max(0, away - old_a)):
        _goal(match, "away", minute, now)
    match.home_score, match.away_score, match.minute, match.period = home, away, minute, period


# ---------------------------------------------------------------------------- serialisation
MAIN_MARKETS = ("1x2", "ou_2.5", "btts", "dc")


def state(match: Match, full=False) -> dict:
    data = {
        "id": match.id, "status": match.status, "period": match.period, "minute": match.minute,
        "score": [match.home_score, match.away_score], "ht": [match.ht_home, match.ht_away],
        "suspended": match.is_suspended, "events": match.events or [],
        "kickoff": match.kickoff.isoformat(), "markets": len(match.odds or {}),
    }
    odds = match.odds or {}
    data["odds"] = odds if full else {k: odds[k] for k in MAIN_MARKETS if k in odds}
    return data
