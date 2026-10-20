from decimal import Decimal

from django.conf import settings
from django.db import models


class GameRound(models.Model):
    class Phase(models.TextChoices):
        BETTING = "betting", "Betting"
        FLYING = "flying", "Flying"
        CRASHED = "crashed", "Crashed"

    sequence = models.PositiveIntegerField(unique=True)
    server_seed = models.CharField(max_length=64)        # revealed only after the crash
    seed_hash = models.CharField(max_length=64)          # sha256(server_seed), shown before the round
    crash_point = models.DecimalField(max_digits=10, decimal_places=2)
    flight_starts_at = models.DateTimeField()
    crashes_at = models.DateTimeField()
    next_round_at = models.DateTimeField()
    settled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sequence"]

    def __str__(self):
        return f"Round #{self.sequence} @ {self.crash_point}x"

    def phase(self, now):
        if now < self.flight_starts_at:
            return self.Phase.BETTING
        if now < self.crashes_at:
            return self.Phase.FLYING
        return self.Phase.CRASHED

    @property
    def is_high(self):
        return self.crash_point >= 10


class AviatorBet(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        WON = "won", "Cashed out"
        LOST = "lost", "Lost"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="aviator_bets")
    round = models.ForeignKey(GameRound, on_delete=models.CASCADE, related_name="bets")
    panel = models.PositiveSmallIntegerField(default=1)  # 1 or 2 — the two bet panels
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    auto_cashout = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cashed_out_at = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payout = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "round", "panel"], name="one_bet_per_panel_per_round"),
        ]

    def __str__(self):
        return f"{self.user} {self.amount} on #{self.round.sequence}"
