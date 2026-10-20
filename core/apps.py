from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _sqlite_tuning(sender, connection, **kwargs):
    """WAL lets the web server, the live engine and Aviator write at the same time without
    'database is locked' errors. (Production should use PostgreSQL anyway.)"""
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=20000;")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        connection_created.connect(_sqlite_tuning)
