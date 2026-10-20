from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from wallet import services as wallet
from wallet.models import Transaction

from . import engine
from .models import AviatorBet, GameRound


class EngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pilot", password="x")
        wallet.credit(self.user, 1000, Transaction.Kind.DEPOSIT)

    def balance(self):
        return wallet.get_wallet(self.user).balance

    def shift(self, game_round, seconds):
        """Move a round's timeline into the past by `seconds`."""
        delta = timedelta(seconds=seconds)
        GameRound.objects.filter(pk=game_round.pk).update(
            flight_starts_at=game_round.flight_starts_at - delta,
            crashes_at=game_round.crashes_at - delta,
            next_round_at=game_round.next_round_at - delta,
        )
        game_round.refresh_from_db()

    def test_crash_point_is_deterministic_and_bounded(self):
        assert engine.crash_point_from_seed("abc") == engine.crash_point_from_seed("abc")
        for i in range(500):
            cp = engine.crash_point_from_seed(f"seed{i}")
            assert Decimal("1.00") <= cp <= Decimal(10000)

    def test_house_edge_holds_for_every_strategy(self):
        # Expected return of cashing out at target x is x * P(crash > x) = 1 - edge.
        crashes = [engine.crash_point_from_seed(f"rtp-{i}") for i in range(40000)]
        edge = settings.AVIATOR["HOUSE_EDGE_PERCENT"] / 100
        for target in (Decimal("1.5"), Decimal("2"), Decimal("5")):
            rtp = float(target) * sum(c > target for c in crashes) / len(crashes)
            assert abs(rtp - (1 - edge)) < 0.03, (target, rtp)

    def test_bet_and_manual_cashout(self):
        r = engine.current_round()
        GameRound.objects.filter(pk=r.pk).update(crash_point=Decimal("50.00"))
        r.refresh_from_db()
        r.crashes_at = r.flight_starts_at + timedelta(seconds=engine.seconds_to_reach(50))
        r.next_round_at = r.crashes_at + timedelta(seconds=3)
        r.save()
        bet = engine.place_bet(self.user, 100, 1)
        assert self.balance() == Decimal("900.00")
        # 10 seconds into the flight
        self.shift(r, (r.flight_starts_at - timezone.now()).total_seconds() + 10)
        bet = engine.cash_out(self.user, bet.id)
        assert bet.status == AviatorBet.Status.WON
        assert bet.cashed_out_at >= Decimal("2.00")
        assert self.balance() == Decimal("900.00") + bet.payout
        # second cash out is a no-op
        engine.cash_out(self.user, bet.id)
        assert self.balance() == Decimal("900.00") + bet.payout

    def test_lost_bet_and_auto_cashout_on_settle(self):
        r = engine.current_round()
        GameRound.objects.filter(pk=r.pk).update(crash_point=Decimal("3.00"))
        lose = engine.place_bet(self.user, 100, 1)
        win = engine.place_bet(self.user, 100, 2, auto_cashout="2.00")
        r.refresh_from_db()
        self.shift(r, (r.next_round_at - timezone.now()).total_seconds() + 1)
        new = engine.current_round()
        assert new.sequence == r.sequence + 1
        lose.refresh_from_db(); win.refresh_from_db()
        assert lose.status == AviatorBet.Status.LOST
        assert win.status == AviatorBet.Status.WON and win.payout == Decimal("200.00")
        assert self.balance() == Decimal("1000.00")

    def test_cannot_bet_during_flight_or_overdraw(self):
        r = engine.current_round()
        with self.assertRaises(engine.GameError):
            engine.place_bet(self.user, 5000, 1)
        self.shift(r, (r.flight_starts_at - timezone.now()).total_seconds() + 0.1)
        if r.phase(timezone.now()) == GameRound.Phase.FLYING:
            with self.assertRaises(engine.GameError):
                engine.place_bet(self.user, 10, 1)

    def test_float_auto_cashout_is_exact(self):
        engine.current_round()
        bet = engine.place_bet(self.user, 10.1, 1, auto_cashout=1.2)
        assert bet.amount == Decimal("10.10") and bet.auto_cashout == Decimal("1.20")

    def test_cancel_refunds(self):
        engine.current_round()
        bet = engine.place_bet(self.user, 250, 1)
        engine.cancel_bet(self.user, bet.id)
        assert self.balance() == Decimal("1000.00")

    def test_state_api(self):
        self.client.force_login(self.user)
        data = self.client.get("/aviator/api/state/").json()
        assert data["round"]["phase"] == "betting"
        assert data["round"]["crash_point"] is None  # never leaked before the crash
        res = self.client.post("/aviator/api/bet/", {"amount": 50, "panel": 1}, content_type="application/json")
        assert res.status_code == 200, res.content
        assert res.json()["state"]["balance"] == "950.00"
