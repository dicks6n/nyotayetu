from django.contrib import admin

from .models import CasinoBet, SeedPair


@admin.register(CasinoBet)
class CasinoBetAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "game", "amount", "multiplier", "payout", "status")
    list_filter = ("game", "status")
    search_fields = ("user__username",)
    readonly_fields = [f.name for f in CasinoBet._meta.fields]


@admin.register(SeedPair)
class SeedPairAdmin(admin.ModelAdmin):
    list_display = ("user", "server_seed_hash", "client_seed", "nonce", "active", "created_at")
    list_filter = ("active",)
    search_fields = ("user__username",)
    # The live server seed must stay secret — even from staff — until the player rotates it.
    exclude = ("server_seed",)
    readonly_fields = ("user", "server_seed_hash", "client_seed", "nonce", "active", "revealed_at")
