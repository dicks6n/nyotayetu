from django.conf import settings
from django.db import transaction

from wallet import services as wallet_services
from wallet.models import Transaction

from .models import Profile


@transaction.atomic
def reward_referrer_on_first_deposit(user):
    profile = Profile.objects.select_for_update().get(user=user)
    if profile.referred_by_id and not profile.referral_rewarded and settings.REFERRAL_BONUS > 0:
        wallet_services.credit(
            profile.referred_by, settings.REFERRAL_BONUS, Transaction.Kind.BONUS,
            note=f"Referral bonus for {user.username}",
        )
        profile.referral_rewarded = True
        profile.save(update_fields=["referral_rewarded"])
