import time

from django.core.management.base import BaseCommand, CommandError

from sports.providers import api_football


class Command(BaseCommand):
    help = "Import real fixtures, odds, live scores and results from API-Football (needs FOOTBALL_API_KEY)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3, help="Days of fixtures to import")
        parser.add_argument("--live", action="store_true", help="Only refresh matches in play")
        parser.add_argument("--loop", type=int, default=0, help="Repeat live refresh every N seconds")

    def handle(self, *args, **o):
        try:
            if not o["live"]:
                n = api_football.sync_fixtures(o["days"])
                self.stdout.write(self.style.SUCCESS(f"Imported/updated {n} fixtures."))
            while True:
                n = api_football.sync_live()
                self.stdout.write(f"Live: {n} match(es) in play.")
                if not o["loop"]:
                    break
                time.sleep(o["loop"])
        except api_football.FeedError as exc:
            raise CommandError(str(exc))
