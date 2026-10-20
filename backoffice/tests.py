from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from aviator import engine
from wallet import services as wallet
from wallet.models import Transaction

from . import analytics


class BackofficeTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("boss", password="x", is_staff=True)
        self.player = User.objects.create_user("player", password="x")
        wallet.credit(self.player, 1000, Transaction.Kind.DEPOSIT)
        engine.current_round()
        engine.place_bet(self.player, 200, 1)

    def test_staff_only(self):
        self.client.force_login(self.player)
        assert self.client.get("/backoffice/").status_code == 302
        self.client.force_login(self.staff)
        for url in ("/backoffice/", "/backoffice/?period=all", "/backoffice/players/",
                    f"/backoffice/players/{self.player.id}/"):
            assert self.client.get(url).status_code == 200, url

    def test_player_house_net(self):
        p = analytics.players_queryset().get(pk=self.player.pk)
        assert p.deposits == Decimal("1000") and p.staked == Decimal("200") and p.house_net == Decimal("200")

    @override_settings(DEMO_PAYMENTS=True)
    def test_seed_demo_data_and_clear(self):
        call_command("seed_demo_data", players=5, days=2, rounds_per_day=20, seed=1, stdout=open("/dev/null", "w"))
        assert User.objects.filter(email__endswith="@demo.local").count() == 5
        assert not Transaction.objects.filter(balance_after__lt=0).exists()
        s = analytics.summary(None)
        assert s["aviator"]["bets"] > 0
        call_command("seed_demo_data", clear=True, stdout=open("/dev/null", "w"))
        assert not User.objects.filter(email__endswith="@demo.local").exists()
