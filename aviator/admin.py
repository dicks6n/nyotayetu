from django.contrib import admin

from .models import AviatorBet, GameRound


class BetInline(admin.TabularInline):
    model = AviatorBet
    extra = 0
    readonly_fields = ("user", "panel", "amount", "auto_cashout", "cashed_out_at", "payout", "status")
    can_delete = False


@admin.register(GameRound)
class GameRoundAdmin(admin.ModelAdmin):
    list_display = ("sequence", "crash_point", "flight_starts_at", "settled", "bet_count")
    list_filter = ("settled",)
    readonly_fields = [f.name for f in GameRound._meta.fields]
    inlines = [BetInline]

    @admin.display(description="Bets")
    def bet_count(self, obj):
        return obj.bets.count()


@admin.register(AviatorBet)
class AviatorBetAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "round", "amount", "auto_cashout", "cashed_out_at", "payout", "status")
    list_filter = ("status",)
    search_fields = ("user__username",)
