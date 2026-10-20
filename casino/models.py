import hashlib
import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models


def new_server_seed():
    return secrets.token_hex(32)


def new_client_seed():
    return secrets.token_hex(6)


class SeedPair(models.Model):
    """Per-player provably-fair seeds. The server seed is secret (only its hash is shown)
    until the player rotates to a new pair; every bet uses (server, client, nonce)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seed_pairs")
    server_seed = models.CharField(max_length=64, default=new_server_seed)
    server_seed_hash = models.CharField(max_length=64, editable=False)
    client_seed = models.CharField(max_length=64, default=new_client_seed)
    nonce = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revealed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.server_seed_hash = hashlib.sha256(self.server_seed.encode()).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} seeds ({'active' if self.active else 'revealed'})"


class CasinoBet(models.Model):
    class Game(models.TextChoices):
        DICE = "dice", "Dice"
        MINES = "mines", "Mines"
        PLINKO = "plinko", "Plinko"
        WHEEL = "wheel", "Wheel"
        ROULETTE = "roulette", "Roulette"
        BACCARAT = "baccarat", "Baccarat"
        BLACKJACK = "blackjack", "Blackjack"

    class Status(models.TextChoices):
        ACTIVE = "active", "In play"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="casino_bets")
    game = models.CharField(max_length=10, choices=Game.choices)
    seed_pair = models.ForeignKey(SeedPair, on_delete=models.CASCADE, related_name="bets")
    nonce = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    multiplier = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    payout = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    params = models.JSONField(default=dict)   # what the player chose
    result = models.JSONField(default=dict)   # what happened (mines positions stay server-side until the end)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["game", "created_at"]), models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.get_game_display()} {self.amount} by {self.user}"
