from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from wallet import services as wallet
from wallet.models import Transaction

from . import live, markets, services
from .models import League, Match, SportsBet


class SlipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("punter", password="x")
        wallet.credit(self.user, 1000, Transaction.Kind.DEPOSIT)
        league = League.objects.create(name="Test League")
        kick = timezone.now() + timedelta(hours=2)
        self.m1 = Match.objects.create(league=league, home_team="A", away_team="B", kickoff=kick,
                                       home_odds=Decimal("2.00"), draw_odds=Decimal("3.00"), away_odds=Decimal("4.00"))
        self.m2 = Match.objects.create(league=league, home_team="C", away_team="D", kickoff=kick,
                                       home_odds=Decimal("1.50"), draw_odds=Decimal("3.00"), away_odds=Decimal("5.00"))

    def finish(self, match, h, a):
        match.home_score, match.away_score, match.status = h, a, Match.Status.FINISHED
        match.save()
        services.settle_match(match)

    def test_accumulator_wins(self):
        bet = services.place_bet(self.user, 100, [{"match_id": self.m1.id, "pick": "1"},
                                                  {"match_id": self.m2.id, "pick": "1"}])
        assert bet.total_odds == Decimal("3.00")
        self.finish(self.m1, 2, 0)
        bet.refresh_from_db()
        assert bet.status == SportsBet.Status.OPEN
        self.finish(self.m2, 1, 0)
        bet.refresh_from_db()
        assert bet.status == SportsBet.Status.WON
        assert wallet.get_wallet(self.user).balance == Decimal("1200.00")

    def test_one_loss_loses_slip(self):
        bet = services.place_bet(self.user, 100, [{"match_id": self.m1.id, "pick": "X"}])
        self.finish(self.m1, 1, 0)
        bet.refresh_from_db()
        assert bet.status == SportsBet.Status.LOST

    def test_cancelled_match_is_void(self):
        bet = services.place_bet(self.user, 100, [{"match_id": self.m1.id, "pick": "2"}])
        self.m1.status = Match.Status.CANCELLED
        self.m1.save()
        services.settle_match(self.m1)
        bet.refresh_from_db()
        assert bet.status == SportsBet.Status.VOID
        assert wallet.get_wallet(self.user).balance == Decimal("1000.00")

    def test_started_match_goes_live_and_takes_inplay_bets(self):
        Match.objects.filter(pk=self.m1.pk).update(kickoff=timezone.now() - timedelta(minutes=30))
        live.tick(force=True)
        self.m1.refresh_from_db()
        assert self.m1.status == Match.Status.LIVE and self.m1.period == "1H" and self.m1.minute >= 30
        price = self.m1.odds_for("over", "ou_1.5")
        bet = services.place_bet(self.user, 100, [{"match_id": self.m1.id, "market": "ou_1.5", "pick": "over",
                                                   "odds": str(price)}])
        sel = bet.selections.get()
        assert sel.live and sel.odds == price
        # a goal suspends the market
        live.record_score(self.m1, 1, 0, 31, "1H")
        self.m1.save()
        with self.assertRaises(services.SlipError):
            services.place_bet(self.user, 100, [{"match_id": self.m2.id, "pick": "1"},
                                                {"match_id": self.m1.id, "market": "1x2", "pick": "1"}])

    def test_rejects_finished_match_and_duplicates(self):
        Match.objects.filter(pk=self.m1.pk).update(status=Match.Status.FINISHED)
        with self.assertRaises(services.SlipError):
            services.place_bet(self.user, 100, [{"match_id": self.m1.id, "pick": "1"}])
        with self.assertRaises(services.SlipError):
            services.place_bet(self.user, 100, [{"match_id": self.m2.id, "pick": "1"},
                                                {"match_id": self.m2.id, "pick": "2"}])

    def test_odds_changed_unless_accepted(self):
        live.reprice(self.m2)
        self.m2.save()
        real = self.m2.odds_for("yes", "btts")
        with self.assertRaises(services.OddsChanged) as ctx:
            services.place_bet(self.user, 100, [{"match_id": self.m2.id, "market": "btts", "pick": "yes",
                                                 "odds": str(real + Decimal("0.10"))}])
        assert ctx.exception.changed[str(self.m2.id)]["odds"] == str(real)
        bet = services.place_bet(self.user, 100, [{"match_id": self.m2.id, "market": "btts", "pick": "yes",
                                                   "odds": "9.99"}], accept_odds_changes=True)
        assert bet.total_odds == real

    def test_every_market_settles(self):
        live.reprice(self.m1)
        self.m1.save()
        picks = [("dc", "1X"), ("dnb", "1"), ("ou_2.5", "over"), ("btts", "yes"), ("ht_1x2", "X"),
                 ("htft", "X/1"), ("cs", "2-1"), ("oe", "odd"), ("home_ou_1.5", "over"), ("away_ou_0.5", "over")]
        bets = [services.place_bet(self.user, 10, [{"match_id": self.m1.id, "market": mk, "pick": pk}])
                for mk, pk in picks]
        self.m1.ht_home, self.m1.ht_away = 0, 0
        self.finish(self.m1, 2, 1)
        for b in bets:
            b.refresh_from_db()
            assert b.status == SportsBet.Status.WON, b.selections.get()
        dnb = services.place_bet  # draw-no-bet on a draw is void → stake back
        Match.objects.filter(pk=self.m2.pk).update(odds={})
        live.reprice(self.m2)
        self.m2.save()
        b = dnb(self.user, 50, [{"match_id": self.m2.id, "market": "dnb", "pick": "2"}])
        self.finish(self.m2, 1, 1)
        b.refresh_from_db()
        assert b.status == SportsBet.Status.VOID and b.payout == Decimal("50.00")


class MarketTests(TestCase):
    def test_probabilities_are_consistent(self):
        pr = markets.probabilities(1.6, 1.1)
        for key in ("1x2", "dc", "btts", "ou_2.5", "oe", "cs", "ht_1x2", "htft"):
            total = sum(pr[key].values())
            assert abs(total - (2 if key == "dc" else 1)) < 1e-5, key   # tails beyond 10 goals ≈ 1e-6

    def test_margin_is_applied_to_every_market(self):
        for key, row in markets.price(1.5, 1.2).items():
            book = sum(1 / float(o) for o in row.values())
            expected = 2 if key == "dc" else 1
            assert book > expected * (1 + markets.margin()) - 0.03, key   # overround ≥ margin (rounding down)

    def test_inplay_closes_decided_markets(self):
        o = markets.price(1.5, 1.2, minute=60, score=(2, 1), ht_score=(1, 1))
        assert "ou_1.5" not in o and "ou_0.5" not in o and "btts" not in o
        assert "ht_1x2" not in o and "ou_3.5" in o

    def test_fit_recovers_lambdas(self):
        o = markets.price(1.8, 0.9)
        lh, la = markets.lambdas_from_odds(o["1x2"]["1"], o["1x2"]["X"], o["1x2"]["2"],
                                           o["ou_2.5"]["over"], o["ou_2.5"]["under"])
        assert abs(lh - 1.8) < 0.15 and abs(la - 0.9) < 0.15


class VirtualLeagueTests(TestCase):
    def test_virtual_match_plays_out_and_settles(self):
        user = User.objects.create_user("v", password="x")
        wallet.credit(user, 1000, Transaction.Kind.DEPOSIT)
        live.ensure_virtual_schedule()
        m = Match.objects.filter(source=Match.Source.VIRTUAL).order_by("kickoff").first()
        assert m and m.odds and Match.objects.filter(source=Match.Source.VIRTUAL).count() == settings.SPORTS["VIRTUAL"]["UPCOMING"]
        bet = services.place_bet(user, 100, [{"match_id": m.id, "market": "ou_0.5", "pick": "over"}])
        v = settings.SPORTS["VIRTUAL"]
        # jump to the 50th minute
        Match.objects.filter(pk=m.pk).update(kickoff=timezone.now() - timedelta(seconds=49 * v["MINUTE_SECONDS"] + v["HT_SECONDS"]))
        live.tick(force=True)
        m.refresh_from_db()
        assert m.status == Match.Status.LIVE and m.period == "2H" and m.ht_home is not None
        assert m.home_score == sum(1 for g in m.script if g["team"] == "home" and g["minute"] <= m.minute)
        # and to full time
        Match.objects.filter(pk=m.pk).update(kickoff=timezone.now() - timedelta(seconds=95 * v["MINUTE_SECONDS"] + v["HT_SECONDS"]))
        live.tick(force=True)
        m.refresh_from_db()
        bet.refresh_from_db()
        assert m.status == Match.Status.FINISHED and m.home_score + m.away_score == len(m.script)
        assert bet.status == (SportsBet.Status.WON if m.script else SportsBet.Status.LOST)

    def test_live_api_never_leaks_script(self):
        live.ensure_virtual_schedule()
        m = Match.objects.filter(source=Match.Source.VIRTUAL).first()
        data = self.client.get(f"/sports/api/live/?ids={m.id}&full={m.id}").json()
        assert "script" not in str(data)


class ApiFootballTests(TestCase):
    def fixture(self, status, elapsed=None, goals=(None, None), ht=(None, None), ft=(None, None)):
        return {"fixture": {"id": 999, "date": (timezone.now() + timedelta(hours=1)).isoformat(),
                            "status": {"short": status, "elapsed": elapsed}},
                "league": {"id": 39, "name": "Premier League", "country": "England"},
                "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
                "goals": {"home": goals[0], "away": goals[1]},
                "score": {"halftime": {"home": ht[0], "away": ht[1]}, "fulltime": {"home": ft[0], "away": ft[1]}}}

    def test_fixture_lifecycle(self):
        from .providers import api_football as feed
        user = User.objects.create_user("api", password="x")
        wallet.credit(user, 1000, Transaction.Kind.DEPOSIT)
        m = feed.apply_fixture(self.fixture("NS"))
        assert m.status == Match.Status.UPCOMING and m.odds
        assert feed.apply_odds({"fixture": {"id": 999}, "bookmakers": [{"bets": [
            {"name": "Match Winner", "values": [{"value": "Home", "odd": "1.80"}, {"value": "Draw", "odd": "3.60"},
                                                {"value": "Away", "odd": "4.50"}]},
            {"name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": "1.85"}, {"value": "Under 2.5", "odd": "1.95"}]}]}]})
        m.refresh_from_db()
        assert m.lambda_home > m.lambda_away
        bet = services.place_bet(user, 100, [{"match_id": m.id, "market": "btts", "pick": "yes"}])
        m = feed.apply_fixture(self.fixture("1H", 23, goals=(1, 0)))
        assert m.status == Match.Status.LIVE and m.minute == 23 and m.events and m.is_suspended
        m = feed.apply_fixture(self.fixture("FT", 90, goals=(2, 1), ht=(1, 0), ft=(2, 1)))
        bet.refresh_from_db()
        assert m.status == Match.Status.FINISHED and bet.status == SportsBet.Status.WON


class FlashscoreBoardTests(TestCase):
    @override_settings(DEMO_PAYMENTS=True)
    def setUp(self):
        call_command("seed_matches", days=2, stdout=StringIO())

    def test_seed_covers_every_status_and_many_leagues(self):
        statuses = set(Match.objects.exclude(source=Match.Source.VIRTUAL).values_list("status", flat=True))
        assert {"finished", "upcoming"} <= statuses
        assert League.objects.exclude(external_id="").count() >= 30

    def test_seed_refuses_outside_demo(self):
        with override_settings(DEMO_PAYMENTS=False):
            with self.assertRaises(CommandError):
                call_command("seed_matches", stdout=StringIO())

    def test_board_filters(self):
        today = timezone.localdate()
        for qs in ("", "?status=live", "?status=finished", "?status=scheduled", "?tab=virtual", "?tab=live",
                   f"?date={(today - timedelta(days=1)).isoformat()}&status=finished", "?date=garbage"):
            assert self.client.get("/sports/" + qs).status_code == 200, qs
        r = self.client.get(f"/sports/?date={(today - timedelta(days=1)).isoformat()}&status=finished")
        assert all(m.status in ("finished", "cancelled") for m in r.context["matches"])
        assert all(m.status == "live" for m in self.client.get("/sports/?status=live").context["matches"])
        leagues = [m.league_id for m in r.context["matches"]]
        assert leagues == sorted(leagues, key=leagues.index)   # each league appears as one block

    @override_settings(DEMO_PAYMENTS=True)
    def test_demo_fixture_plays_out_on_real_clock(self):
        m = Match.objects.filter(external_id__startswith="demo-", status=Match.Status.UPCOMING).first()
        Match.objects.filter(pk=m.pk).update(kickoff=timezone.now() - timedelta(minutes=120))
        live.tick(force=True)
        m.refresh_from_db()
        assert m.status == Match.Status.FINISHED and m.home_score + m.away_score == len(m.script)

    def test_real_manual_fixture_waits_for_staff(self):
        league = League.objects.first()
        m = Match.objects.create(league=league, home_team="A", away_team="B", source=Match.Source.MANUAL,
                                 kickoff=timezone.now() - timedelta(minutes=130), home_odds=2, draw_odds=3, away_odds=4)
        live.tick(force=True)
        m.refresh_from_db()
        assert m.status == Match.Status.LIVE and m.minute == 90 and m.is_suspended   # no invented result


class FeedLeagueConfigTests(TestCase):
    def test_league_selection(self):
        from .providers import api_football as feed
        with self.settings(FOOTBALL_API={**settings.FOOTBALL_API, "LEAGUES": ""}):
            feed.CFG = settings.FOOTBALL_API
            assert 276 in feed.league_ids() and 39 in feed.league_ids() and len(feed.league_ids()) >= 40
        with self.settings(FOOTBALL_API={**settings.FOOTBALL_API, "LEAGUES": "all"}):
            feed.CFG = settings.FOOTBALL_API
            assert feed.league_ids() is None
        with self.settings(FOOTBALL_API={**settings.FOOTBALL_API, "LEAGUES": "39, 276"}):
            feed.CFG = settings.FOOTBALL_API
            assert feed.league_ids() == {39, 276}
        feed.CFG = settings.FOOTBALL_API
