from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Sum
from django.shortcuts import render
from django.utils import timezone

from aviator.models import AviatorBet
from aviator.views import play


def home(request):
    return play(request)


def promos(request):
    return render(request, "core/promos.html", {
        "referral_bonus": settings.REFERRAL_BONUS,
    })


def leaderboard(request):
    period = request.GET.get("period", "week")
    since = timezone.now() - {"day": timedelta(days=1), "week": timedelta(days=7),
                              "month": timedelta(days=30)}.get(period, timedelta(days=7))
    won = AviatorBet.objects.filter(status=AviatorBet.Status.WON, created_at__gte=since)
    top_wins = won.select_related("user", "round").order_by("-payout")[:20]
    top_multipliers = won.select_related("user", "round").order_by("-cashed_out_at", "-payout")[:20]
    top_players = (won.values("user__username").annotate(total=Sum("payout"), wins=Count("id"),
                                                         best=Max("cashed_out_at")).order_by("-total")[:20])
    return render(request, "core/leaderboard.html", {
        "period": period, "top_wins": top_wins, "top_multipliers": top_multipliers, "top_players": top_players,
    })


@login_required
def referral(request):
    profile = request.user.profile
    referrals = request.user.referrals.select_related("user").order_by("-created_at")
    return render(request, "core/referral.html", {
        "link": request.build_absolute_uri(f"/accounts/register/?ref={profile.referral_code}"),
        "referrals": referrals,
        "rewarded": referrals.filter(referral_rewarded=True).count(),
        "bonus": settings.REFERRAL_BONUS,
    })


def help_page(request):
    return render(request, "core/help.html", {
        "aviator": settings.AVIATOR, "min_withdrawal": settings.MIN_WITHDRAWAL,
        "rtp": 100 - settings.AVIATOR["HOUSE_EDGE_PERCENT"],
    })
