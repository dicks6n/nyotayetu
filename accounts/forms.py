from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Profile


class RegisterForm(UserCreationForm):
    phone = forms.RegexField(
        regex=r"^(?:\+?254|0)?[17]\d{8}$",
        error_messages={"invalid": "Enter a valid phone number e.g. 0712345678"},
        widget=forms.TextInput(attrs={"placeholder": "07XX XXX XXX", "inputmode": "tel"}),
    )
    referral_code = forms.CharField(required=False, max_length=12,
                                    widget=forms.TextInput(attrs={"placeholder": "Optional"}))
    age_confirm = forms.BooleanField(label="I am 18 years or older and accept the terms",
                                     error_messages={"required": "You must be 18+ to play."})

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)

    def clean_phone(self):
        phone = self.cleaned_data["phone"].replace("+", "")
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        elif not phone.startswith("254"):
            phone = "254" + phone
        if Profile.objects.filter(phone=phone).exists():
            raise forms.ValidationError("An account with this phone number already exists.")
        return phone

    def clean_referral_code(self):
        code = self.cleaned_data.get("referral_code", "").strip().upper()
        if code and not Profile.objects.filter(referral_code=code).exists():
            raise forms.ValidationError("That referral code doesn't exist.")
        return code

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile = user.profile
            profile.phone = self.cleaned_data["phone"]
            code = self.cleaned_data.get("referral_code")
            if code:
                profile.referred_by = Profile.objects.get(referral_code=code).user
            profile.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"placeholder": "Username", "autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Password"}))
