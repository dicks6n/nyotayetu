from django.urls import path

from . import views

app_name = "backoffice"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("players/", views.players, name="players"),
    path("players/<int:user_id>/", views.player_detail, name="player"),
]
