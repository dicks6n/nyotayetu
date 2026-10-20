from django.contrib import admin, messages
from django.utils import timezone

from . import live, services
from .models import League, Match, Selection, SportsBet


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "flag", "priority", "external_id")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("__str__", "league", "source", "kickoff", "status", "period", "minute", "home_score",
                    "away_score", "home_odds", "draw_odds", "away_odds", "is_featured")
    list_filter = ("status", "source", "league", "is_featured")
    search_fields = ("home_team", "away_team")
    readonly_fields = ("odds", "events", "lambda_home", "lambda_away", "period", "minute", "suspended_until")
    exclude = ("script",)   # virtual goal scripts stay secret, even from staff
    fieldsets = (
        (None, {"fields": ("league", "home_team", "away_team", "kickoff", "source", "external_id", "is_featured")}),
        ("Pricing", {"fields": ("home_odds", "draw_odds", "away_odds", "lambda_home", "lambda_away", "odds"),
                     "description": "Enter 1X2 odds — every other market is derived automatically."}),
        ("Live / result", {"fields": ("status", "home_score", "away_score", "ht_home", "ht_away",
                                      "period", "minute", "events", "suspended_until"),
                           "description": "For manual matches: type the score while it is live (goals suspend "
                                          "betting briefly), set half-time score, then set status Finished."}),
    )
    actions = ["settle", "suspend"]

    def save_model(self, request, obj, form, change):
        if {"home_odds", "draw_odds", "away_odds"} & set(form.changed_data):
            obj.lambda_home = obj.lambda_away = None      # refit the goal model
        if change and obj.status == Match.Status.LIVE and {"home_score", "away_score"} & set(form.changed_data):
            old = Match.objects.get(pk=obj.pk)
            new_h, new_a = obj.home_score or 0, obj.away_score or 0
            obj.home_score, obj.away_score = old.home_score, old.away_score
            live.record_score(obj, new_h, new_a, obj.minute, obj.period)
        if obj.status == Match.Status.FINISHED:
            obj.period, obj.minute = "FT", 90
        live.reprice(obj)
        super().save_model(request, obj, form, change)
        n = services.settle_match(obj)
        if n:
            messages.info(request, f"Settled selections on {n} slip(s) for {obj}.")

    @admin.action(description="Settle bets for selected finished / cancelled matches")
    def settle(self, request, queryset):
        self.message_user(request, f"Updated {sum(services.settle_match(m) for m in queryset)} slip(s).")

    @admin.action(description="Suspend betting for 2 minutes")
    def suspend(self, request, queryset):
        queryset.update(suspended_until=timezone.now() + timezone.timedelta(minutes=2))


class SelectionInline(admin.TabularInline):
    model = Selection
    extra = 0
    readonly_fields = ("match", "market", "pick", "odds", "live", "status")


@admin.register(SportsBet)
class SportsBetAdmin(admin.ModelAdmin):
    list_display = ("code", "user", "stake", "total_odds", "potential_win", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("user__username",)
    inlines = [SelectionInline]
