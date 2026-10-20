from decimal import Decimal

from django.conf import settings
from django.db import models


class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} — {self.balance}"


class Transaction(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        AVIATOR_BET = "aviator_bet", "Aviator bet"
        AVIATOR_WIN = "aviator_win", "Aviator win"
        AVIATOR_REFUND = "aviator_refund", "Aviator refund"
        SPORTS_BET = "sports_bet", "Sports bet"
        SPORTS_WIN = "sports_win", "Sports win"
        SPORTS_REFUND = "sports_refund", "Sports refund"
        CASINO_BET = "casino_bet", "Casino bet"
        CASINO_WIN = "casino_win", "Casino win"
        BONUS = "bonus", "Bonus"
        CASHBACK = "cashback", "Cashback"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    # Positive = money in, negative = money out.
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "kind", "created_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} ({self.user})"

    @property
    def is_credit(self):
        return self.amount >= 0
