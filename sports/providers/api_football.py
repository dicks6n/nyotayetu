"""
API-Football (v3) connector: real fixtures, live minute/score and final results.

Docs: https://www.api-football.com/documentation-v3
  GET /fixtures?date=YYYY-MM-DD&timezone=Africa/Nairobi   -> fixtures for a day (all leagues)
  GET /fixtures?live=<league-ids>                         -> fixtures in play right now
  GET /odds?date=YYYY-MM-DD&bookmaker=<id>&page=<n>       -> pre-match odds (paginated)

We take each fixture's bookmaker 1X2 and Over/Under 2.5 prices only to fit the goal model;
every market we offer (and all in-play prices) comes from our own model in sports/markets.py.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .. import leagues as catalog
from .. import live, markets
from ..models import League, Match

log = logging.getLogger(__name__)
CFG = settings.FOOTBALL_API

LIVE_CODES = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"}
FINISHED_CODES = {"FT", "AET", "PEN"}
VOID_CODES = {"PST", "CANC", "ABD", "AWD", "WO"}


class FeedError(Exception):
    pass


def _get(path, **params):
    if not CFG["KEY"]:
        raise FeedError("FOOTBALL_API_KEY is not set")
    url = f"{CFG['BASE_URL']}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"x-apisports-key": CFG["KEY"], "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    if data.get("errors"):
        raise FeedError(str(data["errors"]))
    return data


# ---------------------------------------------------------------------------- mapping
def league_ids():
    """None = accept every league; otherwise the set of API-Football ids to import."""
    raw = str(CFG["LEAGUES"] or "").strip()
    if raw.lower() == "all":
        return None
    if raw:
        return {int(x) for x in raw.split(",") if x.strip()}
    return set(catalog.default_ids())


def _league(info) -> League:
    known = catalog.BY_API_ID.get(info["id"], {})
    league, created = League.objects.get_or_create(
        external_id=str(info["id"]),
        defaults={"name": known.get("name") or info.get("name", "League"),
                  "country": known.get("country") or info.get("country") or "",
                  "flag": known.get("flag") or "⚽", "priority": known.get("priority", 60)},
    )
    return league


def _period(short):
    return {"1H": "1H", "HT": "HT", "2H": "2H", "ET": "2H", "BT": "2H", "P": "2H"}.get(short, "")


def apply_fixture(item, now=None) -> Match | None:
    """Create or update one Match from an API-Football fixture object. Returns the match."""
    now = now or timezone.now()
    fx, teams, goals, score = item["fixture"], item["teams"], item.get("goals") or {}, item.get("score") or {}
    status = (fx.get("status") or {}).get("short", "NS")
    wanted = league_ids()
    if wanted is not None and item["league"]["id"] not in wanted:
        return None
    with transaction.atomic():
        match = Match.objects.select_for_update().filter(source=Match.Source.API, external_id=str(fx["id"])).first()
        if match is None:
            if status not in ("NS", "TBD") and status not in LIVE_CODES:
                return None   # don't import games we never priced
            match = Match(source=Match.Source.API, external_id=str(fx["id"]), league=_league(item["league"]),
                          home_odds=0, draw_odds=0, away_odds=0, lambda_home=1.45, lambda_away=1.15)
        match.home_team, match.away_team = teams["home"]["name"], teams["away"]["name"]
        match.kickoff = parse_datetime(fx["date"]) or match.kickoff
        ht = score.get("halftime") or {}
        if ht.get("home") is not None:
            match.ht_home, match.ht_away = ht["home"], ht["away"]

        if status in LIVE_CODES:
            match.status = Match.Status.LIVE
            live.record_score(match, goals.get("home") or 0, goals.get("away") or 0,
                              min((fx["status"].get("elapsed") or 0), 90), _period(status), now)
            if status == "SUSP":
                match.suspended_until = now + timedelta(minutes=5)
        elif status in FINISHED_CODES:
            ft = score.get("fulltime") or goals   # 90-minute result settles football markets
            match.status, match.period, match.minute = Match.Status.FINISHED, "FT", 90
            match.home_score, match.away_score = ft.get("home"), ft.get("away")
        elif status in VOID_CODES:
            match.status = Match.Status.CANCELLED
        live.reprice(match)
        match.save()
    if match.status in (Match.Status.FINISHED, Match.Status.CANCELLED):
        from ..services import settle_match
        settle_match(match)
    return match


def apply_odds(item):
    """Fit the goal model for a fixture from one bookmaker's 1X2 + O/U 2.5 prices."""
    match = Match.objects.filter(source=Match.Source.API, external_id=str(item["fixture"]["id"]),
                                 status=Match.Status.UPCOMING).first()
    if not match:
        return False
    for bm in item.get("bookmakers", []):
        bets = {b["name"]: {v["value"]: v["odd"] for v in b["values"]} for b in bm.get("bets", [])}
        mw = bets.get("Match Winner")
        if not mw or not all(k in mw for k in ("Home", "Draw", "Away")):
            continue
        ou = bets.get("Goals Over/Under", {})
        match.lambda_home, match.lambda_away = markets.lambdas_from_odds(
            mw["Home"], mw["Draw"], mw["Away"], ou.get("Over 2.5"), ou.get("Under 2.5"))
        live.reprice(match)
        match.save()
        return True
    return False


# ---------------------------------------------------------------------------- jobs
def sync_fixtures(days=3):
    today = timezone.localdate()
    count = 0
    for d in range(days):
        day = (today + timedelta(days=d)).isoformat()
        for item in _get("fixtures", date=day, timezone=settings.TIME_ZONE).get("response", []):
            if apply_fixture(item):
                count += 1
        page = 1
        while True:
            data = _get("odds", date=day, bookmaker=CFG["BOOKMAKER"], page=page)
            for item in data.get("response", []):
                apply_odds(item)
            paging = data.get("paging") or {}
            if page >= paging.get("total", 1):
                break
            page += 1
    return count


def sync_live():
    seen = 0
    # one call for every match in play; we filter to the leagues we offer
    for item in _get("fixtures", live="all").get("response", []):
        if apply_fixture(item):
            seen += 1
    # anything we think is live but the feed no longer lists has probably finished: re-check it
    for match in Match.objects.filter(source=Match.Source.API, status=Match.Status.LIVE):
        for item in _get("fixtures", id=match.external_id).get("response", []):
            apply_fixture(item)
    return seen
