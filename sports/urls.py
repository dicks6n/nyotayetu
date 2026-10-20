from django.urls import path

from . import views

app_name = "sports"
urlpatterns = [
    path("", views.match_list, name="list"),
    path("match/<int:pk>/", views.match_detail, name="match"),
    path("bet/", views.place_bet, name="place_bet"),
    path("my-bets/", views.my_bets, name="my_bets"),
    path("api/live/", views.api_live, name="api_live"),
    path("api/ticker/", views.api_ticker, name="api_ticker"),
]
