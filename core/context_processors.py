from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone


def _casino_games():
    from casino.views import GAMES
    return GAMES


def _live_count():
    from sports.models import Match
    return Match.objects.live().count()


def site(request):
    now = timezone.localtime()
    next_monday = datetime.combine((now + timedelta(days=7 - now.weekday())).date(), time.min,
                                   tzinfo=now.tzinfo)
    ctx = {
        "SITE_NAME": settings.SITE_NAME,
        "CURRENCY": settings.CURRENCY,
        "CASHBACK_PERCENT": settings.CASHBACK_PERCENT,
        "cashback_at": int(next_monday.timestamp() * 1000),
        "balance": None,
        "CASINO_GAMES": _casino_games(),
        "LIVE_COUNT": _live_count(),
    }
    if request.user.is_authenticated:
        from wallet.services import get_wallet
        ctx["balance"] = get_wallet(request.user).balance
    return ctx
