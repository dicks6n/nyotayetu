import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError

from sports import live


class Command(BaseCommand):
    help = "Keep live matches moving: clocks, goals, re-pricing, virtual schedule and settlement."

    def handle(self, *args, **o):
        self.stdout.write(self.style.SUCCESS("Live engine running. Ctrl+C to stop."))
        while True:
            try:
                live.tick(force=True)
            except OperationalError as exc:   # e.g. SQLite busy — try again next tick
                self.stderr.write(f"tick skipped: {exc}")
            time.sleep(settings.SPORTS["TICK_SECONDS"])
