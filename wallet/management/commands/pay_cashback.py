from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from wallet import services
from wallet.models import Transaction


class Command(BaseCommand):
    help = "Pay weekly cashback on net Aviator losses for the previous 7 days. Run every Monday 00:00."

    def handle(self, *args, **opts):
        since = timezone.now() - timedelta(days=7)
        pct = Decimal(settings.CASHBACK_PERCENT) / 100
        paid = 0
        for user in get_user_model().objects.filter(transactions__created_at__gte=since).distinct():
            if Transaction.objects.filter(user=user, kind=Transaction.Kind.CASHBACK, created_at__gte=since).exists():
                continue
            net = Transaction.objects.filter(
                user=user, created_at__gte=since,
                kind__in=[Transaction.Kind.AVIATOR_BET, Transaction.Kind.AVIATOR_WIN, Transaction.Kind.AVIATOR_REFUND],
            ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
            if net < 0:
                amount = services.money(-net * pct)
                if amount >= 1:
                    services.credit(user, amount, Transaction.Kind.CASHBACK, note=f"{settings.CASHBACK_PERCENT}% weekly cashback")
                    paid += 1
        self.stdout.write(self.style.SUCCESS(f"Cashback paid to {paid} user(s)."))
