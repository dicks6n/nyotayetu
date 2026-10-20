"""
DEMO ONLY: fill a development database with fixtures across every league in sports/leagues.py
(yesterday's results, today's live & scheduled games, the next few days) so the Flashscore-style
sports page has something to show. In demo mode these fixtures play themselves out on the real
clock. Production fixtures, live scores and results come from the data feed (`sync_football`)
or from staff in the admin — never from this command.
"""
import random
import uuid
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from sports import live
from sports.leagues import LEAGUES
from sports.models import League, Match


def _goals(rng, lam):
    l, k, p = pow(2.718281828459045, -lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


class Command(BaseCommand):
    help = "Demo only: realistic fixtures for every common league (results, live, scheduled)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=5, help="Days ahead to schedule")
        parser.add_argument("--clear", action="store_true", help="Remove demo fixtures nobody has bet on")
        parser.add_argument("--force", action="store_true", help="Allow even when DEMO_PAYMENTS is off")

    def handle(self, *args, **o):
        if not settings.DEMO_PAYMENTS and not o["force"]:
            raise CommandError("seed_matches makes pretend fixtures and is for development only "
                               "(DEMO_PAYMENTS is False). Use `sync_football` for real fixtures.")
        if o["clear"]:
            n, _ = Match.objects.filter(external_id__startswith="demo-", selections__isnull=True).delete()
            self.stdout.write(self.style.SUCCESS(f"Removed {n} demo fixtures."))
            return
        rng = random.Random()
        tz = timezone.get_current_timezone()
        now = timezone.now()
        today = timezone.localdate()
        made = 0
        for spec in LEAGUES:
            league, _ = League.objects.update_or_create(
                external_id=str(spec["api_id"]),
                defaults={"name": spec["name"], "country": spec["country"], "flag": spec["flag"],
                          "priority": spec["priority"]})
            big = spec["priority"] <= 12
            for d in range(-1, o["days"] + 1):
                day = today + timedelta(days=d)
                weekend = day.weekday() >= 5
                n = rng.choice([0, 1, 1, 2, 2, 3]) if (big or weekend) else rng.choice([0, 0, 1, 1, 2])
                teams = spec["teams"][:]
                rng.shuffle(teams)
                for i in range(min(n, len(teams) // 2)):
                    home, away = teams[2 * i], teams[2 * i + 1]
                    if d == 0 and i == 0 and rng.random() < 0.7:
                        kickoff = now - timedelta(minutes=rng.randint(3, 100))        # in play (or just finished)
                    else:
                        hh = rng.choice([13, 15, 16, 17, 18, 19, 20, 21, 22])
                        kickoff = datetime.combine(day, time(hh, rng.choice([0, 15, 30, 45])), tzinfo=tz)
                    strength = rng.uniform(0.75, 1.35)
                    lh, la = round(1.45 * strength * rng.uniform(.9, 1.1), 3), round(1.15 / strength * rng.uniform(.9, 1.1), 3)
                    script = sorted(
                        [{"minute": rng.randint(1, 90), "team": "home"} for _ in range(_goals(rng, lh))] +
                        [{"minute": rng.randint(1, 90), "team": "away"} for _ in range(_goals(rng, la))],
                        key=lambda g: g["minute"])
                    m = Match(league=league, home_team=home, away_team=away, kickoff=kickoff,
                              source=Match.Source.MANUAL, external_id=f"demo-{uuid.uuid4().hex[:12]}",
                              lambda_home=lh, lambda_away=la, script=script, home_odds=0, draw_odds=0, away_odds=0,
                              is_featured=big and rng.random() < 0.25)
                    live.reprice(m)
                    if kickoff + timedelta(minutes=110) < now:          # yesterday's (or this morning's) results
                        m.status, m.period, m.minute = Match.Status.FINISHED, "FT", 90
                        m.home_score = sum(1 for g in script if g["team"] == "home")
                        m.away_score = len(script) - m.home_score
                        first = [g for g in script if g["minute"] <= 45]
                        m.ht_home = sum(1 for g in first if g["team"] == "home")
                        m.ht_away = len(first) - m.ht_home
                        m.events = [{"minute": g["minute"], "team": g["team"]} for g in script]
                        m.odds = {}
                    m.save()
                    made += 1
        live.tick(force=True)   # anything that has already kicked off goes live now
        self.stdout.write(self.style.SUCCESS(f"Created {made} demo fixtures across {len(LEAGUES)} leagues."))
