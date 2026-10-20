from django import forms
from django.conf import settings


class DepositForm(forms.Form):
    phone = forms.RegexField(
        regex=r"^(?:\+?254|0)?7\d{8}$|^(?:\+?254|0)?1\d{8}$",
        error_messages={"invalid": "Enter a valid Safaricom number e.g. 0712345678"},
        widget=forms.TextInput(attrs={"placeholder": "07XX XXX XXX", "inputmode": "tel"}),
    )
    amount = forms.DecimalField(
        min_value=settings.MIN_DEPOSIT, max_value=300000, decimal_places=2,
        widget=forms.NumberInput(attrs={"placeholder": "Amount", "step": "1"}),
    )


class WithdrawForm(forms.Form):
    phone = DepositForm.base_fields["phone"]
    amount = forms.DecimalField(
        min_value=settings.MIN_WITHDRAWAL, max_value=150000, decimal_places=2,
        widget=forms.NumberInput(attrs={"placeholder": "Amount", "step": "1"}),
    )
