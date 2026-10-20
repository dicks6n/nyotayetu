from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Nyota Yetu Admin 🇰🇪"
admin.site.site_title = "Nyota Yetu"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("wallet/", include("wallet.urls")),
    path("aviator/", include("aviator.urls")),
    path("sports/", include("sports.urls")),
    path("casino/", include("casino.urls")),
    path("backoffice/", include("backoffice.urls")),
    path("", include("core.urls")),
]
