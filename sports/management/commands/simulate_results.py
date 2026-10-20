import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from sports import services
from sports.models import Match


class Command(BaseCommand):
    help = "Demo: give random final scores to matches (past kickoff, or all with --all) and settle bets."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Finish every upcoming match now")

    def handle(self, *args, **opts):
        qs = Match.objects.filter(status__in=[Match.Status.UPCOMING, Match.Status.LIVE]).exclude(
            source=Match.Source.VIRTUAL)
        if not opts["all"]:
            qs = qs.filter(kickoff__lte=timezone.now())
        slips = 0
        for match in qs:
            match.home_score, match.away_score = random.randint(0, 4), random.randint(0, 3)
            match.ht_home = random.randint(0, match.home_score)
            match.ht_away = random.randint(0, match.away_score)
            match.status, match.period, match.minute = Match.Status.FINISHED, "FT", 90
            match.save()
            slips += services.settle_match(match)
        self.stdout.write(self.style.SUCCESS(f"Matches finished; settled {slips} slip(s)."))
