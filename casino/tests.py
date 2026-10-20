import math
import random
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from wallet import services as wallet
from wallet.models import Transaction

from . import fair, games, services
from .models import CasinoBet

EDGE = settings.CASINO["HOUSE_EDGE_PERCENT"] / 100


def card(rank_index, suit=0):
    """rank_index: 0=A, 1=2 … 9=10, 12=K"""
    return suit * 13 + rank_index


class MathTests(TestCase):
    def test_fair_floats_are_deterministic(self):
        a = fair.floats("s", "c", 7, 20)
        assert a == fair.floats("s", "c", 7, 20) and len(a) == 20 and all(0 <= f < 1 for f in a)
        assert a != fair.floats("s", "c", 8, 20)

    def test_every_instant_game_keeps_the_edge(self):
        for chance in (2, 10, 49.5, 90):
            assert float(games.dice_multiplier(chance)) * chance / 100 <= 1 - EDGE
        for mines in (1, 3, 10, 24):
            for k in range(1, 26 - mines):
                p = math.comb(25 - mines, k) / math.comb(25, k)
                assert float(games.mines_multiplier(mines, k)) * p <= 1 - EDGE + 1e-9
        for rows in games.PLINKO_ROWS:
            for risk in games.PLINKO_RISKS:
                assert 1 - EDGE - 0.01 < games.plinko_rtp(rows, risk) <= 1 - EDGE
        for risk in games.WHEEL_RISKS:
            t = games.wheel_table(risk)
            assert 1 - EDGE - 0.01 < sum(map(float, t)) / len(t) <= 1 - EDGE

    def test_mines_positions_are_unique(self):
        fs = fair.floats("x", "y", 0, 24)
        for m in (1, 5, 24):
            pos = games.mines_positions(fs, m)
            assert len(set(pos)) == m and all(0 <= p < 25 for p in pos)

    def test_roulette_edge_is_single_zero(self):
        for kind, value in [("number", 17), ("red", None), ("dozen", 2), ("column", 3), ("low", None)]:
            wins = sum(games.roulette_wins(kind, value, n) for n in range(37))
            rtp = wins * (games.ROULETTE_PAYS[kind] + 1) / 37
            assert abs(rtp - 36 / 37) < 1e-9, kind

    def test_baccarat_rules_and_edge(self):
        # Natural 9 vs 7: no draws
        d = games.baccarat_deal([card(8), card(6), card(0 + 9), card(0 + 10), card(1), card(1)])
        assert d["player_total"] == 9 and len(d["player"]) == 2 and d["winner"] == "player"
        # Player 0 draws a 3rd card; banker on 3 does NOT draw against an 8
        d = games.baccarat_deal([card(9), card(1), card(10), card(0), card(7), card(5)])
        assert len(d["player"]) == 3 and d["banker_total"] == 3 and len(d["banker"]) == 2
        rng, n = random.Random(1), 100000
        res = {"player": 0, "banker": 0, "tie": 0}
        for _ in range(n):
            res[games.baccarat_deal([rng.randrange(52) for _ in range(6)])["winner"]] += 1
        p, b, t = (res[k] / n for k in ("player", "banker", "tie"))
        assert abs(p - 0.4462) < 0.01 and abs(b - 0.4586) < 0.01 and abs(t - 0.0952) < 0.006
        banker_rtp = b * 1.95 + t
        assert 0.975 < banker_rtp < 1.0          # ~1.06% edge

    def test_blackjack_values(self):
        assert games.bj_value([card(0), card(12)]) == (21, True)
        assert games.bj_value([card(0), card(0), card(8)]) == (21, True)
        assert games.bj_value([card(9), card(5), card(0)]) == (17, False)
        assert games.bj_is_blackjack([card(0), card(10)])


class ServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("gambler", password="x")
        wallet.credit(self.user, 10000, Transaction.Kind.DEPOSIT)

    def bal(self):
        return wallet.get_wallet(self.user).balance

    def test_instant_games_settle_and_ledger_balances(self):
        for _ in range(30):
            services.play_dice(self.user, 10, 50.5, True)
            services.play_plinko(self.user, 10, 16, "high")
            services.play_wheel(self.user, 10, "medium")
        staked = Decimal(900)
        paid = sum(b.payout for b in CasinoBet.objects.filter(user=self.user))
        assert self.bal() == Decimal(10000) - staked + paid
        nonces = list(CasinoBet.objects.filter(user=self.user).order_by("nonce").values_list("nonce", flat=True))
        assert nonces == list(range(90))

    def test_mines_flow_never_leaks_positions(self):
        from .views import serialize
        bet = services.mines_start(self.user, 100, 3)
        data = serialize(bet, self.user)
        assert "positions" not in data["result"]
        safe = [i for i in range(25) if i not in bet.result["positions"]]
        services.mines_reveal(self.user, safe[0])
        bet = services.mines_cashout(self.user)
        assert bet.status == "won" and bet.payout == wallet.money(100 * games.mines_multiplier(3, 1))
        bet = services.mines_start(self.user, 100, 3)
        bet = services.mines_reveal(self.user, bet.result["positions"][0])
        assert bet.status == "lost" and bet.payout == 0

    def test_roulette_payout(self):
        with mock.patch("casino.fair.floats", return_value=[17.5 / 37]):
            bet = services.play_roulette(self.user, [
                {"type": "number", "value": 17, "amount": 10}, {"type": "black", "amount": 20},
                {"type": "even", "amount": 30}])
        # 17 is black & odd: 10*36 + 20*2 = 400 on 60 staked
        assert bet.result["number"] == 17 and bet.payout == Decimal("400.00")

    def test_baccarat_tie_pushes_main_bets(self):
        tie = [card(9), card(9), card(8), card(8), card(1), card(1)]   # 9 v 9
        with mock.patch("casino.fair.floats", return_value=[(c + .5) / 52 for c in tie]):
            bet = services.play_baccarat(self.user, {"player": 50, "banker": 30, "tie": 10})
        assert bet.result["winner"] == "tie" and bet.payout == Decimal("170.00")   # 90 + 50 + 30

    def _bj(self, shoe):
        fs = [(c + .5) / 52 for c in shoe] + [0.01] * (60 - len(shoe))
        return mock.patch("casino.fair.floats", return_value=fs)

    def test_blackjack_natural_pays_3_to_2(self):
        with self._bj([card(0), card(5), card(12), card(6)]):   # player A,K  dealer 6,7
            bet = services.bj_start(self.user, 100)
        assert bet.status == "won" and bet.payout == Decimal("250.00")

    def test_blackjack_double_and_dealer_bust(self):
        # player 5,6 (11) dealer 10,6 → double draws 9 (20); dealer hits 16 draws K → bust
        with self._bj([card(4), card(9), card(5), card(5), card(8), card(12)]):
            services.bj_start(self.user, 100)
            bet = services.bj_action(self.user, "double")
        assert bet.amount == Decimal(200) and bet.payout == Decimal("400.00")
        assert self.bal() == Decimal(10200)

    def test_blackjack_split_and_hidden_hole_card(self):
        from .views import serialize
        # player 8,8  dealer 10,9 (19); split hands get 10 → 18 and 3 → 11, hit 10 → 21
        with self._bj([card(7), card(9), card(7, 1), card(8), card(9, 2), card(2), card(9, 3)]):
            bet = services.bj_start(self.user, 100)
            data = serialize(bet, self.user)
            assert len(data["result"]["dealer"]) == 1 and "shoe" not in data["result"]
            assert data["can"]["split"]
            services.bj_action(self.user, "split")
            services.bj_action(self.user, "stand")            # 18
            bet = services.bj_action(self.user, "hit")       # 11 + 10 = 21 → auto stand → dealer 19
        outcomes = [h["outcome"] for h in bet.result["hands"]]
        assert outcomes == ["lose", "win"] and bet.amount == Decimal(200) and bet.payout == Decimal(200)

    def test_blackjack_simulated_edge(self):
        """Basic-ish strategy over many hands: the house keeps a small edge."""
        rng = random.Random(3)
        staked = paid = Decimal(0)
        for i in range(3000):
            with mock.patch("casino.fair.floats", return_value=[rng.random() for _ in range(60)]):
                bet = services.bj_start(self.user, 10)
                while bet.status == "active":
                    res = bet.result
                    h = res["hands"][res["current"]]
                    total, soft = games.bj_value(h["cards"])
                    up = games.bj_card_value(res["dealer"][0])
                    if len(h["cards"]) == 2 and total in (10, 11) and up < total - 1 and self.bal() > 50:
                        action = "double"
                    elif total < 12 or (total < 17 and up >= 7) or (soft and total < 18):
                        action = "hit"
                    else:
                        action = "stand"
                    bet = services.bj_action(self.user, action)
            staked += bet.amount
            paid += bet.payout
            if self.bal() < 100:
                wallet.credit(self.user, 10000, Transaction.Kind.DEPOSIT)
        rtp = float(paid / staked)
        assert 0.9 < rtp < 1.03, rtp
