import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from accounts.services import reward_referrer_on_first_deposit

from . import services
from .forms import DepositForm, WithdrawForm
from .models import Transaction


@login_required
def deposit(request):
    form = DepositForm(request.POST or None, initial={"phone": getattr(request.user.profile, "phone", "")})
    if request.method == "POST" and form.is_valid():
        amount = form.cleaned_data["amount"]
        ref = "DEP" + uuid.uuid4().hex[:10].upper()
        if settings.DEMO_PAYMENTS:
            services.credit(request.user, amount, Transaction.Kind.DEPOSIT, reference=ref,
                            note=f"M-Pesa {form.cleaned_data['phone']} (demo)")
            reward_referrer_on_first_deposit(request.user)
            messages.success(request, f"{settings.CURRENCY} {amount:,.2f} deposited successfully. Good luck!")
        else:
            # TODO: trigger M-Pesa STK push here and credit the wallet from the callback view.
            Transaction.objects.create(
                user=request.user, kind=Transaction.Kind.DEPOSIT, status=Transaction.Status.PENDING,
                amount=amount, balance_after=services.get_wallet(request.user).balance, reference=ref,
                note=f"M-Pesa {form.cleaned_data['phone']}",
            )
            messages.info(request, "Check your phone and enter your M-Pesa PIN to complete the deposit.")
        return redirect(request.POST.get("next") or "core:home")
    return render(request, "wallet/deposit.html", {"form": form, "quick_amounts": [100, 250, 500, 1000, 2500, 5000]})


@login_required
def withdraw(request):
    form = WithdrawForm(request.POST or None, initial={"phone": getattr(request.user.profile, "phone", "")})
    if request.method == "POST" and form.is_valid():
        amount = form.cleaned_data["amount"]
        try:
            services.debit(
                request.user, amount, Transaction.Kind.WITHDRAWAL,
                reference="WDR" + uuid.uuid4().hex[:10].upper(),
                note=f"To M-Pesa {form.cleaned_data['phone']}",
                status=Transaction.Status.PENDING,
            )
        except services.InsufficientFunds:
            form.add_error("amount", "You don't have enough balance for this withdrawal.")
        else:
            messages.success(request, "Withdrawal requested. It will be processed shortly.")
            return redirect("wallet:transactions")
    return render(request, "wallet/withdraw.html", {"form": form})


@login_required
def transactions(request):
    qs = request.user.transactions.all()
    kind = request.GET.get("kind")
    if kind in Transaction.Kind.values:
        qs = qs.filter(kind=kind)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "wallet/transactions.html", {"page": page, "kinds": Transaction.Kind.choices, "kind": kind})
