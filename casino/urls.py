from django.urls import path

from . import views

app_name = "casino"
urlpatterns = [
    path("", views.lobby, name="lobby"),
    path("dice/", views.dice, name="dice"),
    path("mines/", views.mines, name="mines"),
    path("plinko/", views.plinko, name="plinko"),
    path("wheel/", views.wheel, name="wheel"),
    path("roulette/", views.roulette, name="roulette"),
    path("baccarat/", views.baccarat, name="baccarat"),
    path("blackjack/", views.blackjack, name="blackjack"),
    path("provably-fair/", views.fairness, name="fairness"),
    path("api/roulette/", views.api_roulette, name="api_roulette"),
    path("api/baccarat/", views.api_baccarat, name="api_baccarat"),
    path("api/blackjack/deal/", views.api_blackjack_deal, name="api_blackjack_deal"),
    path("api/blackjack/action/", views.api_blackjack_action, name="api_blackjack_action"),
    path("api/blackjack/state/", views.api_blackjack_state, name="api_blackjack_state"),
    path("api/dice/", views.api_dice, name="api_dice"),
    path("api/plinko/", views.api_plinko, name="api_plinko"),
    path("api/wheel/", views.api_wheel, name="api_wheel"),
    path("api/mines/start/", views.api_mines_start, name="api_mines_start"),
    path("api/mines/reveal/", views.api_mines_reveal, name="api_mines_reveal"),
    path("api/mines/cashout/", views.api_mines_cashout, name="api_mines_cashout"),
    path("api/mines/state/", views.api_mines_state, name="api_mines_state"),
    path("api/feed/", views.api_feed, name="api_feed"),
]
