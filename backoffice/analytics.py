"""Read-only business metrics for the staff back office."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Avg, Count, DecimalField, F, Max, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from aviator.models import AviatorBet, GameRound
from casino.models import CasinoBet
from sports.models import SportsBet
from wallet.models import Transaction, Wallet

K = Transaction.Kind
ZERO = Decimal("0")
STAKE_KINDS = [K.AVIATOR_BET, K.SPORTS_BET, K.CASINO_BET]
RETURN_KINDS = [K.AVIATOR_WIN, K.AVIATOR_REFUND, K.SPORTS_WIN, K.SPORTS_REFUND, K.CASINO_WIN]

PERIODS = {"today": "Today", "7d": "7 days", "30d": "30 days", "all": "All time"}


def dsum(field, **filter_kwargs):
    """Sum that returns Decimal 0 instead of None."""
    q = Q(**filter_kwargs) if filter_kwargs else None
    return Coalesce(Sum(field, filter=q), Value(ZERO), output_field=DecimalField(max_digits=16, decimal_places=2))


def period_start(key):
    now = timezone.localtime()
    if key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if key == "7d":
        return now - timedelta(days=7)
    if key == "30d":
        return now - timedelta(days=30)
    return None


def _since(qs, since, field="created_at"):
    return qs.filter(**{f"{field}__gte": since}) if since else qs


def pct(part, whole):
    return (Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1")) if whole else None


# ---------------------------------------------------------------------------- dashboard
def summary(since):
    tx = _since(Transaction.objects.all(), since).aggregate(
        deposits=dsum("amount", kind=K.DEPOSIT, status=Transaction.Status.COMPLETED),
        withdrawals=dsum("amount", kind=K.WITHDRAWAL),
        bonuses=dsum("amount", kind__in=[K.BONUS, K.CASHBACK]),
    )
    withdrawals = -tx["withdrawals"]

    av = _since(AviatorBet.objects.exclude(status=AviatorBet.Status.CANCELLED), since).aggregate(
        turnover=dsum("amount"), payouts=dsum("payout"), bets=Count("id"),
        wins=Count("id", filter=Q(status=AviatorBet.Status.WON)), players=Count("user", distinct=True),
        avg_cashout=Avg("cashed_out_at", filter=Q(status=AviatorBet.Status.WON)),
    )
    av_ggr = av["turnover"] - av["payouts"]

    sp_qs = _since(SportsBet.objects.all(), since)
    sp = sp_qs.aggregate(
        stakes=dsum("stake"), bets=Count("id"), players=Count("user", distinct=True),
        settled_stakes=dsum("stake", status__in=[SportsBet.Status.WON, SportsBet.Status.LOST, SportsBet.Status.VOID]),
        payouts=dsum("payout", status__in=[SportsBet.Status.WON, SportsBet.Status.VOID]),
        open_bets=Count("id", filter=Q(status=SportsBet.Status.OPEN)),
    )
    sp_ggr = sp["settled_stakes"] - sp["payouts"]
    open_liability = SportsBet.objects.filter(status=SportsBet.Status.OPEN).aggregate(v=dsum("potential_win"))["v"]

    rounds = _since(GameRound.objects.filter(settled=True), since, "flight_starts_at").aggregate(
        count=Count("id"), avg=Avg("crash_point"), instant=Count("id", filter=Q(crash_point__lt=Decimal("1.01"))),
        high=Max("crash_point"),
    )

    settled_casino = _since(CasinoBet.objects.exclude(status=CasinoBet.Status.ACTIVE), since)
    casino_games = []
    for row in settled_casino.values("game").annotate(
            turnover=dsum("amount"), payouts=dsum("payout"), bets=Count("id"),
            players=Count("user", distinct=True)).order_by("-turnover"):
        row["ggr"] = row["turnover"] - row["payouts"]
        row["hold_pct"] = pct(row["ggr"], row["turnover"])
        row["name"] = CasinoBet.Game(row["game"]).label
        casino_games.append(row)
    cs = {
        "turnover": sum((g["turnover"] for g in casino_games), ZERO),
        "payouts": sum((g["payouts"] for g in casino_games), ZERO),
        "bets": sum(g["bets"] for g in casino_games),
        "players": settled_casino.values("user").distinct().count(),
        "games": casino_games,
        "in_play": CasinoBet.objects.filter(status=CasinoBet.Status.ACTIVE).aggregate(n=Count("id"), v=dsum("amount")),
    }
    cs["ggr"] = cs["turnover"] - cs["payouts"]
    cs["hold_pct"] = pct(cs["ggr"], cs["turnover"])

    active_ids = set(_since(AviatorBet.objects.all(), since).values_list("user_id", flat=True).distinct())
    active_ids |= set(settled_casino.values_list("user_id", flat=True).distinct())
    active_ids |= set(sp_qs.values_list("user_id", flat=True).distinct())
    ten_min_ago = timezone.now() - timedelta(minutes=10)
    online = set(AviatorBet.objects.filter(created_at__gte=ten_min_ago).values_list("user_id", flat=True))
    online |= set(SportsBet.objects.filter(created_at__gte=ten_min_ago).values_list("user_id", flat=True))
    online |= set(CasinoBet.objects.filter(created_at__gte=ten_min_ago).values_list("user_id", flat=True))
    depositors = _since(Transaction.objects.filter(kind=K.DEPOSIT, status=Transaction.Status.COMPLETED), since) \
        .values("user").distinct().count()

    ggr = av_ggr + sp_ggr + cs["ggr"]
    turnover = av["turnover"] + sp["stakes"] + cs["turnover"]
    return {
        "users_total": User.objects.count(),
        "users_new": _since(User.objects.all(), since, "date_joined").count(),
        "players_active": len(active_ids),
        "players_online": len(online),
        "depositors": depositors,
        "deposits": tx["deposits"],
        "withdrawals": withdrawals,
        "net_deposits": tx["deposits"] - withdrawals,
        "bonuses": tx["bonuses"],
        "turnover": turnover,
        "ggr": ggr,
        "ngr": ggr - tx["bonuses"],
        "hold_pct": pct(ggr, turnover),
        "player_funds": Wallet.objects.aggregate(v=dsum("balance"))["v"],
        "pending_withdrawals": Transaction.objects.filter(kind=K.WITHDRAWAL, status=Transaction.Status.PENDING)
                                                  .aggregate(n=Count("id"), v=dsum("amount")),
        "aviator": {**av, "ggr": av_ggr, "hold_pct": pct(av_ggr, av["turnover"]),
                    "win_rate": pct(av["wins"], av["bets"])},
        "sports": {**sp, "ggr": sp_ggr, "hold_pct": pct(sp_ggr, sp["settled_stakes"]),
                   "open_liability": open_liability},
        "casino": cs,
        "rounds": {**rounds, "instant_pct": pct(rounds["instant"], rounds["count"])},
    }


def daily_series(days=14):
    """Per-day GGR (Aviator + casino + settled sports) and active players for the last `days` days."""
    tz = timezone.get_current_timezone()
    start = (timezone.localtime() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    dates = [(start + timedelta(days=i)).date() for i in range(days)]
    rows = {d: {"date": d, "turnover": ZERO, "payouts": ZERO, "sports_ggr": ZERO, "casino_ggr": ZERO,
                "casino_players": 0, "players": 0, "new_users": 0}
            for d in dates}

    av = (AviatorBet.objects.exclude(status=AviatorBet.Status.CANCELLED).filter(created_at__gte=start)
          .annotate(day=TruncDate("created_at", tzinfo=tz)).values("day")
          .annotate(turnover=dsum("amount"), payouts=dsum("payout"), players=Count("user", distinct=True)))
    for r in av:
        if r["day"] in rows:
            rows[r["day"]].update(turnover=r["turnover"], payouts=r["payouts"], players=r["players"])
    sp = (SportsBet.objects.filter(settled_at__gte=start).annotate(day=TruncDate("settled_at", tzinfo=tz))
          .values("day").annotate(stake=dsum("stake"), payout=dsum("payout")))
    for r in sp:
        if r["day"] in rows:
            rows[r["day"]]["sports_ggr"] = r["stake"] - r["payout"]
    cb = (CasinoBet.objects.exclude(status=CasinoBet.Status.ACTIVE).filter(created_at__gte=start)
          .annotate(day=TruncDate("created_at", tzinfo=tz)).values("day")
          .annotate(stake=dsum("amount"), payout=dsum("payout"), players=Count("user", distinct=True)))
    for r in cb:
        if r["day"] in rows:
            rows[r["day"]]["casino_ggr"] = r["stake"] - r["payout"]
            rows[r["day"]]["casino_players"] = r["players"]
    nu = (User.objects.filter(date_joined__gte=start).annotate(day=TruncDate("date_joined", tzinfo=tz))
          .values("day").annotate(n=Count("id")))
    for r in nu:
        if r["day"] in rows:
            rows[r["day"]]["new_users"] = r["n"]

    out = []
    for d in dates:
        r = rows[d]
        r["ggr"] = r["turnover"] - r["payouts"] + r["sports_ggr"] + r["casino_ggr"]
        out.append(r)
    return out


def bar_chart(series, key, width=720, height=200, pad_top=14, pad_bottom=24):
    """Pre-compute SVG bar geometry (supports negative values around a zero baseline)."""
    values = [float(r[key]) for r in series]
    hi, lo = max(values + [0]), min(values + [0])
    span = (hi - lo) or 1
    plot_h = height - pad_top - pad_bottom
    zero_y = pad_top + plot_h * hi / span
    slot = width / max(len(series), 1)
    bar_w = max(4, slot - 6)
    bars = []
    for i, (r, v) in enumerate(zip(series, values)):
        h = max(abs(v) / span * plot_h, 1.5 if v else 0)
        bars.append({
            "x": round(i * slot + (slot - bar_w) / 2, 1), "w": round(bar_w, 1),
            "y": round(zero_y - h if v >= 0 else zero_y, 1), "h": round(h, 1),
            "positive": v >= 0, "value": r[key], "date": r["date"],
            "label_x": round(i * slot + slot / 2, 1), "show_label": i % 2 == (len(series) - 1) % 2,
            "hit_x": round(i * slot, 1), "hit_w": round(slot, 1),
        })
    return {"bars": bars, "zero_y": round(zero_y, 1), "width": width, "height": height,
            "label_y": height - 6, "max": hi, "min": lo}


# ---------------------------------------------------------------------------- players
def players_queryset():
    t = "transactions__"
    return (User.objects.select_related("profile", "wallet").annotate(
        deposits=dsum(t + "amount", transactions__kind=K.DEPOSIT, transactions__status=Transaction.Status.COMPLETED),
        withdrawn_neg=dsum(t + "amount", transactions__kind=K.WITHDRAWAL),
        staked_neg=dsum(t + "amount", transactions__kind__in=STAKE_KINDS),
        returned=dsum(t + "amount", transactions__kind__in=RETURN_KINDS),
        bonuses=dsum(t + "amount", transactions__kind__in=[K.BONUS, K.CASHBACK]),
        last_seen=Max(t + "created_at"),
    ).annotate(
        withdrawn=-F("withdrawn_neg"),
        staked=-F("staked_neg"),
        house_net=-F("staked_neg") - F("returned"),
    ))


PLAYER_SORTS = {
    "house_net": "-house_net", "winners": "house_net", "staked": "-staked", "deposits": "-deposits",
    "last_seen": "-last_seen", "joined": "-date_joined", "balance": "-wallet__balance",
}


def player_stats(user):
    av = AviatorBet.objects.filter(user=user).exclude(status=AviatorBet.Status.CANCELLED).aggregate(
        bets=Count("id"), staked=dsum("amount"), won=dsum("payout"),
        wins=Count("id", filter=Q(status=AviatorBet.Status.WON)),
        avg_bet=Avg("amount"), avg_cashout=Avg("cashed_out_at", filter=Q(status=AviatorBet.Status.WON)),
        best=Max("cashed_out_at"), biggest_win=Max("payout"), last_bet=Max("created_at"),
    )
    sp = SportsBet.objects.filter(user=user).aggregate(
        bets=Count("id"), staked=dsum("stake"), won=dsum("payout"),
        wins=Count("id", filter=Q(status=SportsBet.Status.WON)), open=Count("id", filter=Q(status=SportsBet.Status.OPEN)),
    )
    av["net"] = av["staked"] - av["won"]
    av["win_rate"] = pct(av["wins"], av["bets"])
    sp["net"] = sp["staked"] - sp["won"]
    casino = list(CasinoBet.objects.filter(user=user).exclude(status=CasinoBet.Status.ACTIVE).values("game").annotate(
        bets=Count("id"), staked=dsum("amount"), won=dsum("payout"), best=Max("multiplier")).order_by("-staked"))
    for g in casino:
        g["name"], g["net"] = CasinoBet.Game(g["game"]).label, g["staked"] - g["won"]
    return {"aviator": av, "sports": sp, "casino": casino}
