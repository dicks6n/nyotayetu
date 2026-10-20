"""
DEMO ONLY: runs a handful of clearly-named demo accounts that place real bets on the
Aviator game so you can see the live bets table working on a local dev server.
Refuses to run unless settings.DEMO_PAYMENTS is True.
"""
import random
import time
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from aviator import engine
from aviator.models import GameRound
from wallet import services
from wallet.models import Transaction


class Command(BaseCommand):
    help = "Demo only: simulated players that bet & cash out so the live table has activity."

    def add_arguments(self, parser):
        parser.add_argument("--players", type=int, default=12)

    def handle(self, *args, **opts):
        if not settings.DEMO_PAYMENTS:
            raise CommandError("Demo players are disabled when DEMO_PAYMENTS is False.")
        players = []
        for i in range(opts["players"]):
            user, _ = User.objects.get_or_create(username=f"demo_pilot{i + 1:02d}")
            if services.get_wallet(user).balance < 1000:
                services.credit(user, 50000, Transaction.Kind.DEPOSIT, note="Demo funds")
            players.append(user)
        self.stdout.write(self.style.SUCCESS(f"{len(players)} demo pilots flying. Ctrl+C to stop."))

        handled_round, targets = None, {}
        while True:
            game_round = engine.current_round()
            phase = game_round.phase(timezone.now())
            if phase == GameRound.Phase.BETTING and handled_round != game_round.id:
                handled_round, targets = game_round.id, {}
                for user in random.sample(players, k=random.randint(len(players) // 2, len(players))):
                    amount = random.choice([20, 50, 100, 100, 200, 250, 500, 1000, 1500])
                    auto = random.choice([None, None, Decimal("1.5"), Decimal("2.00"), Decimal("3.00")])
                    try:
                        bet = engine.place_bet(user, amount, 1, auto)
                        targets[bet.id] = (user, Decimal(str(round(random.lognormvariate(0.5, 0.6) + 1, 2))))
                    except engine.GameError:
                        pass
            elif phase == GameRound.Phase.FLYING:
                m = engine.multiplier_at(engine.elapsed(game_round, timezone.now()))
                for bet_id, (user, target) in list(targets.items()):
                    if m >= target:
                        try:
                            engine.cash_out(user, bet_id)
                        except engine.GameError:
                            pass
                        targets.pop(bet_id)
            time.sleep(0.3)
