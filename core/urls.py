from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("promos/", views.promos, name="promos"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    path("referral/", views.referral, name="referral"),
    path("help/", views.help_page, name="help"),
]
