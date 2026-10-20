from django.urls import path

from . import views

app_name = "aviator"
urlpatterns = [
    path("", views.play, name="play"),
    path("provably-fair/", views.fairness, name="fairness"),
    path("api/state/", views.api_state, name="api_state"),
    path("api/bet/", views.api_bet, name="api_bet"),
    path("api/cancel/", views.api_cancel, name="api_cancel"),
    path("api/cashout/", views.api_cashout, name="api_cashout"),
    path("api/history/", views.api_history, name="api_history"),
]
