from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class League(models.Model):
    name = models.CharField(max_length=100)
    external_id = models.CharField(max_length=40, blank=True, db_index=True)
    country = models.CharField(max_length=60, blank=True)
    flag = models.CharField(max_length=8, blank=True, help_text="Emoji flag")
    priority = models.PositiveSmallIntegerField(default=10, help_text="Lower shows first")

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self):
        return self.name


class MatchQuerySet(models.QuerySet):
    def upcoming(self):
        return self.filter(status=Match.Status.UPCOMING, kickoff__gt=timezone.now()).order_by("kickoff")

    def live(self):
        return self.filter(status=Match.Status.LIVE).order_by("kickoff")


class Match(models.Model):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        LIVE = "live", "Live"
        FINISHED = "finished", "Finished"
        CANCELLED = "cancelled", "Cancelled"

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="matches")
    home_team = models.CharField(max_length=80)
    away_team = models.CharField(max_length=80)
    kickoff = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UPCOMING)
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual (admin)"
        API = "api", "Data feed"
        VIRTUAL = "virtual", "Virtual"

    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    external_id = models.CharField(max_length=40, blank=True, db_index=True)
    # 1X2 opening odds — the whole price book is derived from these via the goal model
    home_odds = models.DecimalField(max_digits=6, decimal_places=2)
    draw_odds = models.DecimalField(max_digits=6, decimal_places=2)
    away_odds = models.DecimalField(max_digits=6, decimal_places=2)
    lambda_home = models.FloatField(null=True, blank=True, help_text="Expected home goals (auto-fitted)")
    lambda_away = models.FloatField(null=True, blank=True, help_text="Expected away goals (auto-fitted)")
    odds = models.JSONField(default=dict, blank=True, help_text="Current prices for every market")
    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)
    ht_home = models.PositiveSmallIntegerField(null=True, blank=True)
    ht_away = models.PositiveSmallIntegerField(null=True, blank=True)
    minute = models.PositiveSmallIntegerField(default=0)
    period = models.CharField(max_length=3, blank=True)        # 1H, HT, 2H, FT
    events = models.JSONField(default=list, blank=True)        # [{"minute": 23, "team": "home"}]
    script = models.JSONField(default=list, blank=True)        # virtual matches only: pre-drawn goals (secret)
    suspended_until = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MatchQuerySet.as_manager()

    class Meta:
        ordering = ["kickoff"]
        verbose_name_plural = "matches"

    def __str__(self):
        return f"{self.home_team} vs {self.away_team}"

    def odds_for(self, pick, market="1x2"):
        if market == "1x2" and not self.odds:
            return {"1": self.home_odds, "X": self.draw_odds, "2": self.away_odds}[pick]
        value = (self.odds.get(market) or {}).get(pick)
        return Decimal(value) if value else None

    @property
    def is_live(self):
        return self.status == self.Status.LIVE

    @property
    def is_suspended(self):
        return bool(self.suspended_until and self.suspended_until > timezone.now())

    @property
    def market_count(self):
        return sum(len(v) for v in self.odds.values()) if self.odds else 3

    @property
    def ht_result_score(self):
        return (self.ht_home, self.ht_away) if self.ht_home is not None else None

    @property
    def result(self):
        if self.home_score is None or self.away_score is None:
            return None
        if self.home_score > self.away_score:
            return "1"
        if self.home_score < self.away_score:
            return "2"
        return "X"

    @property
    def is_open(self):
        if self.status == self.Status.LIVE:
            return not self.is_suspended and self.period != "FT"
        return self.status == self.Status.UPCOMING and self.kickoff > timezone.now()


class SportsBet(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        VOID = "void", "Void"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sports_bets")
    stake = models.DecimalField(max_digits=12, decimal_places=2)
    total_odds = models.DecimalField(max_digits=12, decimal_places=2)
    potential_win = models.DecimalField(max_digits=14, decimal_places=2)
    payout = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Slip #{self.pk} {self.user} {self.stake} @ {self.total_odds}"

    @property
    def code(self):
        return f"LB{self.pk:06d}"


class Selection(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        VOID = "void", "Void"

    bet = models.ForeignKey(SportsBet, on_delete=models.CASCADE, related_name="selections")
    match = models.ForeignKey(Match, on_delete=models.PROTECT, related_name="selections")
    market = models.CharField(max_length=16, default="1x2")
    pick = models.CharField(max_length=8)
    live = models.BooleanField(default=False, help_text="Placed while the match was in play")
    odds = models.DecimalField(max_digits=6, decimal_places=2)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bet", "match"], name="one_pick_per_match")]

    def __str__(self):
        return f"{self.match} — {self.market}:{self.pick} @ {self.odds}"

    @property
    def market_label(self):
        from .markets import market_label
        return market_label(self.market, self.match.home_team, self.match.away_team)

    @property
    def pick_label(self):
        from .markets import pick_label
        return pick_label(self.market, self.pick, self.match.home_team, self.match.away_team)
