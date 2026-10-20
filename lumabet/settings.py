"""Django settings for the Nyota Yetu project."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "accounts",
    "wallet",
    "aviator",
    "sports",
    "casino",
    "backoffice",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "lumabet.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "lumabet.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

# ---------------------------------------------------------------------------
# Site / betting configuration
# ---------------------------------------------------------------------------
SITE_NAME = "Nyota Yetu"
CURRENCY = "KES"

# When True, deposits are credited instantly (no real payment gateway).
# Wire up M-Pesa STK push in wallet/views.py before turning this off.
DEMO_PAYMENTS = True

MIN_DEPOSIT = 10
MIN_WITHDRAWAL = 100
REFERRAL_BONUS = 50          # credited to referrer when a referred user makes a first deposit
CASHBACK_PERCENT = 5         # weekly cashback on net Aviator losses

AVIATOR = {
    "BETTING_SECONDS": 7,     # time window to place bets before take-off
    "CRASHED_SECONDS": 4,     # pause showing "flew away" before next round
    "GROWTH_RATE": 0.075,     # multiplier = e^(rate * seconds)
    "MIN_BET": 10,
    "MAX_BET": 20000,
    "MAX_MULTIPLIER": 10000,
    # The house keeps exactly this % of all money bet in the long run, whatever cash-out
    # strategy players use (RTP = 100 - edge). 3–5% is typical for crash games.
    "HOUSE_EDGE_PERCENT": 5,
    "MAX_WIN": 1000000,       # cap on a single bet's payout (risk control, shown in Help)
}

# Instant casino games (Dice, Mines, Plinko, Wheel). Every payout table is derived from
# HOUSE_EDGE_PERCENT, so the house keeps exactly that share of stakes in the long run.
CASINO = {
    "HOUSE_EDGE_PERCENT": 4,
    "MIN_BET": 10,
    "MAX_BET": 20000,
    "MAX_WIN": 1000000,
}

SPORTS = {
    "MIN_STAKE": 10,
    "MAX_STAKE": 100000,
    "MAX_SELECTIONS": 20,
    "MAX_PAYOUT": 1000000,
    "MARGIN_PERCENT": 6,      # bookmaker margin applied to every market
    "TICK_SECONDS": 2,        # how often live matches are re-priced
    "GOAL_SUSPEND_SECONDS": 30,
    "HALF_TIME_MINUTES": 15,
    "VIRTUAL": {              # ⚡ simulated league, clearly labelled VIRTUAL on the site
        "ENABLED": True,
        "LEAGUE_NAME": "Virtual Ligi Kuu",
        "MINUTE_SECONDS": 4,  # one match minute lasts 4 real seconds (~6.5 minute matches)
        "HT_SECONDS": 20,
        "INTERVAL_MINUTES": 3,
        "UPCOMING": 6,
        "GOAL_SUSPEND_SECONDS": 6,
    },
}

# Real fixtures & live scores from API-Football (https://www.api-football.com — free tier available).
# Set FOOTBALL_API_KEY in the environment, then: python manage.py sync_football --loop 60
FOOTBALL_API = {
    "KEY": os.environ.get("FOOTBALL_API_KEY", ""),
    "BASE_URL": "https://v3.football.api-sports.io",
    # Which competitions to import: empty = every league in sports/leagues.py (Kenya, top European,
    # African, American & Asian leagues, cups and internationals); "all" = anything the feed covers;
    # or a comma list of API-Football league ids, e.g. "276,39,140".
    "LEAGUES": os.environ.get("FOOTBALL_LEAGUES", ""),
    "BOOKMAKER": 8,           # whose 1X2 + O/U 2.5 odds seed our goal model (8 = Bet365 on API-Football)
}
