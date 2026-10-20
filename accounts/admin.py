from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "referral_code", "referred_by", "referral_rewarded", "created_at")
    search_fields = ("user__username", "phone", "referral_code")
