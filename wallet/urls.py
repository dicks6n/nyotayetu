from django.urls import path

from . import views

app_name = "wallet"
urlpatterns = [
    path("deposit/", views.deposit, name="deposit"),
    path("withdraw/", views.withdraw, name="withdraw"),
    path("transactions/", views.transactions, name="transactions"),
]
