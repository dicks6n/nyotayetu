from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from wallet import services as wallet
from wallet.models import Transaction

from .models import Match, Selection, SportsBet

CFG = settings.SPORTS


class SlipError(Exception):
    pass


class OddsChanged(SlipError):
    def __init__(self, changed):
        super().__init__("Odds have changed — review your slip")
        self.changed = changed


def place_bet(user, stake, picks, accept_odds_changes=False) -> SportsBet:
    """
    picks: [{"match_id", "market", "pick", "odds"}]. Prices always come from the server; if the
    player saw different odds and didn't tick "accept odds changes", OddsChanged is raised with
    the current prices so the slip can be updated.
    """
    from . import live
    live.tick(force=True)   # make sure nothing has happened since the player last looked

    try:
        stake = wallet.money(stake)
    except Exception:
        raise SlipError("Enter a valid stake")
    if stake < CFG["MIN_STAKE"] or stake > CFG["MAX_STAKE"]:
        raise SlipError(f"Stake must be between {CFG['MIN_STAKE']} and {CFG['MAX_STAKE']:,}")
    if not picks:
        raise SlipError("Your betslip is empty")
    if len(picks) > CFG["MAX_SELECTIONS"]:
        raise SlipError(f"Maximum {CFG['MAX_SELECTIONS']} selections per slip")

    chosen = {}
    for p in picks:
        try:
            match_id, market, pick = int(p["match_id"]), str(p.get("market") or "1x2"), str(p["pick"])
        except (KeyError, TypeError, ValueError):
            raise SlipError("Invalid selection")
        if match_id in chosen:
            raise SlipError("Only one pick per match is allowed")
        chosen[match_id] = (market, pick, p.get("odds"))

    matches = Match.objects.in_bulk(chosen.keys())
    total, changed, lines = Decimal("1"), {}, []
    for match_id, (market, pick, seen) in chosen.items():
        match = matches.get(match_id)
        if not match or not match.is_open:
            what = f"{match}" if match else "A match"
            raise SlipError(f"{what} is suspended or closed for betting" if match and match.is_live
                            else f"{what} is no longer available for betting")
        price = match.odds_for(pick, market)
        if price is None:
            raise SlipError(f"That market is closed for {match}")
        if seen is not None and not accept_odds_changes:
            try:
                if Decimal(str(seen)) != price:
                    changed[str(match_id)] = {"market": market, "pick": pick, "odds": str(price)}
            except Exception:
                raise SlipError("Invalid odds")
        total *= price
        lines.append((match, market, pick, price))
    if changed:
        raise OddsChanged(changed)
    total = total.quantize(Decimal("0.01"))
    potential = min(wallet.money(stake * total), Decimal(CFG["MAX_PAYOUT"]))

    with transaction.atomic():
        try:
            wallet.debit(user, stake, Transaction.Kind.SPORTS_BET, note=f"{len(lines)}-leg slip")
        except wallet.InsufficientFunds:
            raise SlipError("Insufficient balance — please deposit")
        bet = SportsBet.objects.create(user=user, stake=stake, total_odds=total, potential_win=potential)
        Selection.objects.bulk_create([
            Selection(bet=bet, match=m, market=mk, pick=pk, odds=price, live=m.is_live)
            for m, mk, pk, price in lines
        ])
    return bet


def _settle_slip(bet: SportsBet):
    statuses = list(bet.selections.values_list("status", "odds"))
    if any(s == Selection.Status.PENDING for s, _ in statuses):
        return
    now = timezone.now()
    if any(s == Selection.Status.LOST for s, _ in statuses):
        bet.status, bet.settled_at = SportsBet.Status.LOST, now
        bet.save(update_fields=["status", "settled_at"])
        return
    live = [o for s, o in statuses if s == Selection.Status.WON]
    if not live:  # every leg void
        bet.status, bet.payout, bet.settled_at = SportsBet.Status.VOID, bet.stake, now
        bet.save(update_fields=["status", "payout", "settled_at"])
        wallet.credit(bet.user, bet.stake, Transaction.Kind.SPORTS_REFUND, reference=bet.code)
        return
    odds = Decimal("1")
    for o in live:
        odds *= o
    payout = min(wallet.money(bet.stake * odds), Decimal(CFG["MAX_PAYOUT"]))
    bet.status, bet.payout, bet.settled_at = SportsBet.Status.WON, payout, now
    bet.save(update_fields=["status", "payout", "settled_at"])
    wallet.credit(bet.user, payout, Transaction.Kind.SPORTS_WIN, reference=bet.code)


@transaction.atomic
def settle_match(match: Match):
    """Grade all pending selections for a finished/cancelled match and settle completed slips."""
    from .markets import grade
    if match.status == Match.Status.CANCELLED:
        ft = None
    elif match.status == Match.Status.FINISHED and match.home_score is not None and match.away_score is not None:
        ft = (match.home_score, match.away_score)
    else:
        return 0
    ht = match.ht_result_score
    pending = match.selections.filter(status=Selection.Status.PENDING).select_related("bet")
    slips = set()
    for sel in pending:
        sel.status = Selection.Status.VOID if ft is None else grade(sel.market, sel.pick, ft, ht)
        sel.save(update_fields=["status"])
        slips.add(sel.bet_id)
    for bet in SportsBet.objects.select_for_update().filter(pk__in=slips, status=SportsBet.Status.OPEN):
        _settle_slip(bet)
    return len(slips)
