from django.contrib import admin

from .models import Transaction, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "updated_at")
    search_fields = ("user__username",)
    readonly_fields = ("balance",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "status", "amount", "balance_after", "reference")
    list_filter = ("kind", "status", "created_at")
    search_fields = ("user__username", "reference")
    actions = ["mark_completed"]

    @admin.action(description="Mark selected as completed (e.g. withdrawals paid)")
    def mark_completed(self, request, queryset):
        queryset.update(status=Transaction.Status.COMPLETED)
