from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import redirect, render

from aviator.models import AviatorBet
from sports.models import SportsBet

from .forms import LoginForm, RegisterForm


def register(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    form = RegisterForm(request.POST or None, initial={"referral_code": request.GET.get("ref", "")})
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome aboard, {user.username}! Make a deposit to start flying ✨")
        return redirect("wallet:deposit")
    return render(request, "accounts/register.html", {"form": form})


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def profile(request):
    user = request.user
    aviator = AviatorBet.objects.filter(user=user).aggregate(
        count=Count("id"),
        staked=Sum("amount"),
        won=Sum("payout"),
        best=Max("cashed_out_at"),
        wins=Count("id", filter=Q(status=AviatorBet.Status.WON)),
    )
    sports = SportsBet.objects.filter(user=user).aggregate(
        count=Count("id"), won=Count("id", filter=Q(status=SportsBet.Status.WON)),
    )
    staked = aviator["staked"] or Decimal(0)
    net = (aviator["won"] or Decimal(0)) - staked
    return render(request, "accounts/profile.html", {
        "aviator": aviator, "sports": sports, "net": net,
        "referral_link": request.build_absolute_uri(f"/accounts/register/?ref={user.profile.referral_code}"),
    })
