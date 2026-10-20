"""All balance changes go through these helpers so every movement is recorded."""
from decimal import ROUND_DOWN, Decimal

from django.db import transaction as db_transaction

from .models import Transaction, Wallet


class InsufficientFunds(Exception):
    pass


def money(value) -> Decimal:
    # str() first so floats from JSON (e.g. 1.2) don't become 1.1999… and round down.
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def get_wallet(user, lock=False) -> Wallet:
    qs = Wallet.objects.select_for_update() if lock else Wallet.objects
    wallet, _ = qs.get_or_create(user=user)
    return wallet


@db_transaction.atomic
def credit(user, amount, kind, reference="", note="", status=Transaction.Status.COMPLETED) -> Transaction:
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Credit amount must be positive")
    wallet = get_wallet(user, lock=True)
    wallet.balance = money(wallet.balance + amount)
    wallet.save(update_fields=["balance", "updated_at"])
    return Transaction.objects.create(
        user=user, kind=kind, amount=amount, balance_after=wallet.balance,
        reference=reference, note=note, status=status,
    )


@db_transaction.atomic
def debit(user, amount, kind, reference="", note="", status=Transaction.Status.COMPLETED) -> Transaction:
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Debit amount must be positive")
    wallet = get_wallet(user, lock=True)
    if wallet.balance < amount:
        raise InsufficientFunds("Insufficient balance")
    wallet.balance = money(wallet.balance - amount)
    wallet.save(update_fields=["balance", "updated_at"])
    return Transaction.objects.create(
        user=user, kind=kind, amount=-amount, balance_after=wallet.balance,
        reference=reference, note=note, status=status,
    )
