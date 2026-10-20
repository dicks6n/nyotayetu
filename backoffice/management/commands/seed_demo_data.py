"""
DEMO ONLY: fill a development database with sample players and N days of history so the
back office has something to show. Rounds use the real provably-fair crash formula and
matches are decided by their (margin-free) probabilities, so the house edge you see in the
dashboard is the genuine mathematical result, not a made-up number.

Demo accounts have an @demo.local email and an unusable password.
Remove them with:  python manage.py seed_demo_data --clear
"""
import hashlib
import heapq
import itertools
import random
import secrets
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile
from aviator import engine
from aviator.models import AviatorBet, GameRound
from casino import fair, games
from casino.models import CasinoBet, SeedPair
from sports.models import League, Match, Selection, SportsBet
from wallet.models import Transaction, Wallet

K = Transaction.Kind
DEMO_DOMAIN = "demo.local"
NAMES = ["kamau", "wanjiru", "otieno", "achieng", "mwangi", "njeri", "kiprop", "chebet", "omondi", "wambui",
         "mutua", "akinyi", "kibet", "nyambura", "odhiambo", "wairimu", "barasa", "maina", "atieno", "brian",
         "kevin", "faith", "mercy", "dennis", "sharon", "collins", "ivy", "juma", "halima", "baraka", "zawadi",
         "tony", "grace", "eric", "lucy", "moses", "esther", "peter", "joy", "sam"]
TEAMS = ["Gor Mahia", "AFC Leopards", "Tusker", "Shabana", "Bandari", "KCB", "Police FC", "Kakamega Homeboyz",
         "Arsenal", "Chelsea", "Liverpool", "Man City", "Real Madrid", "Barcelona", "Inter", "Napoli"]


def q(v):
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


class Command(BaseCommand):
    help = "Demo only: create sample players with Aviator + sports history for the back office."

    def add_arguments(self, parser):
        parser.add_argument("--players", type=int, default=40)
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--rounds-per-day", type=int, default=90)
        parser.add_argument("--clear", action="store_true", help="Delete all demo accounts and their history")
        parser.add_argument("--seed", type=int, default=None, help="Random seed for repeatable data")

    def handle(self, *args, **o):
        if not settings.DEMO_PAYMENTS:
            raise CommandError("Refusing to create demo data while DEMO_PAYMENTS is False.")
        if o["clear"]:
            n, _ = User.objects.filter(email__endswith="@" + DEMO_DOMAIN).delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted demo accounts ({n} rows incl. history)."))
            return
        rng = random.Random(o["seed"])
        with transaction.atomic():
            self.build(rng, o["players"], o["days"], o["rounds_per_day"])

    # ------------------------------------------------------------------ helpers
    def tx(self, user, kind, amount, at, note="", status=Transaction.Status.COMPLETED):
        bal = self.balances[user.id] + amount
        self.balances[user.id] = bal
        self.txs.append((Transaction(user=user, kind=kind, amount=amount, balance_after=bal,
                                     note=note, status=status), at))

    def ensure_funds(self, rng, p, stake, at):
        if self.balances[p["user"].id] >= stake:
            return True
        if rng.random() < 0.15 and p["deposits"] > 3:   # some players simply stop
            return False
        amount = q(rng.choice([1, 2, 2, 5, 10, 20]) * p["deposit_size"])
        self.tx(p["user"], K.DEPOSIT, amount, at - timedelta(minutes=rng.randint(1, 20)), note="M-Pesa (demo)")
        p["deposits"] += 1
        return self.balances[p["user"].id] >= stake

    def maybe_withdraw(self, rng, p, at, recent):
        bal = self.balances[p["user"].id]
        if bal > p["deposit_size"] * 8 and rng.random() < 0.25:
            amount = q(bal * Decimal(rng.choice(["0.5", "0.7", "0.9"])))
            status = Transaction.Status.PENDING if recent and rng.random() < 0.5 else Transaction.Status.COMPLETED
            self.tx(p["user"], K.WITHDRAWAL, -amount, at, note="To M-Pesa (demo)", status=status)

    def casino_play(self, rng, p, at):
        """One instant casino bet using the real provably-fair maths and a real seed pair."""
        user = p["user"]
        stake = q(max(settings.CASINO["MIN_BET"], float(p["stake"]) * rng.choice([0.5, 1, 2])))
        if not self.ensure_funds(rng, p, stake, at):
            return
        pair = self.seed_pairs.get(user.id) or SeedPair.objects.create(user=user)
        self.seed_pairs[user.id] = pair
        nonce = pair.nonce
        pair.nonce += 1
        game = rng.choice(p["games"])
        fs = fair.floats(pair.server_seed, pair.client_seed, nonce, 24)
        params, result, payout = {}, {}, Decimal(0)
        if game == "dice":
            chance = rng.choice([10, 25, 49.5, 49.5, 66, 80])
            target = round(99.99 - chance, 2)
            roll = games.dice_roll(fs[0])
            won = roll > Decimal(str(target))
            payout = q(stake * games.dice_multiplier(chance)) if won else Decimal(0)
            params, result = {"target": target, "over": True, "chance": chance}, {"roll": str(roll), "won": won}
        elif game == "plinko":
            rows, risk = rng.choice(games.PLINKO_ROWS), rng.choice(games.PLINKO_RISKS)
            path, slot = games.plinko_drop(fs[:rows])
            payout = q(stake * games.plinko_table(rows, risk)[slot])
            params, result = {"rows": rows, "risk": risk}, {"path": path, "slot": slot}
        elif game == "wheel":
            risk = rng.choice(games.WHEEL_RISKS)
            seg = games.wheel_segment(fs[0], risk)
            payout = q(stake * games.wheel_table(risk)[seg])
            params, result = {"risk": risk}, {"segment": seg}
        elif game == "roulette":
            n = int(fs[0] * 37)
            kind, value = rng.choice([("red", None), ("black", None), ("number", rng.randint(0, 36)), ("dozen", rng.randint(1, 3))])
            if games.roulette_wins(kind, value, n):
                payout = stake * (games.ROULETTE_PAYS[kind] + 1)
            params = {"chips": [{"type": kind, "value": value, "amount": str(stake)}]}
            result = {"number": n, "winners": [0] if payout else []}
        elif game == "baccarat":
            side = rng.choice(["banker", "banker", "player", "tie"])
            deal = games.baccarat_deal(games.cards_from(fs[:6]))
            if deal["winner"] == side:
                payout = stake * games.BACCARAT_PAYS[side]
            elif deal["winner"] == "tie":
                payout = stake          # push
            params, result = {side: str(stake)}, deal
        else:  # mines: reveal a few tiles, cash out if all safe
            mines = rng.choice([1, 3, 3, 5, 10])
            positions = games.mines_positions(fs, mines)
            picks = rng.sample(range(25), rng.randint(1, 5))
            hit = next((t for t in picks if t in positions), None)
            if hit is None:
                payout = q(stake * games.mines_multiplier(mines, len(picks)))
            params, result = {"mines": mines}, {"positions": positions, "revealed": picks, "hit": hit}
        payout = min(q(payout), Decimal(settings.CASINO["MAX_WIN"]))
        mult = (payout / stake).quantize(Decimal("0.0001"))
        self.tx(user, K.CASINO_BET, -stake, at, note=game.title())
        if payout:
            self.tx(user, K.CASINO_WIN, payout, at + timedelta(seconds=3), note=f"{game.title()} {mult.normalize():f}x")
        self.casino_bets.append((CasinoBet(user=user, game=game, seed_pair=pair, nonce=nonce, amount=stake,
                                           multiplier=mult, payout=payout, params=params, result=result,
                                           status=CasinoBet.Status.WON if mult >= 1 else CasinoBet.Status.LOST), at))

    # ------------------------------------------------------------------ main
    def build(self, rng, n_players, days, rounds_per_day):
        now = timezone.now()
        start = now - timedelta(days=days)
        self.txs, self.balances, self.casino_bets, self.seed_pairs = [], {}, [], {}
        cfg = settings.AVIATOR

        # players with different personas
        players = []
        for _ in range(n_players):
            name = f"{rng.choice(NAMES)}{rng.choice(['', '_', ''])}{rng.randint(1, 9999)}"
            while User.objects.filter(username=name).exists():
                name += str(rng.randint(0, 9))
            joined = start + timedelta(seconds=rng.uniform(0, days * 86400 * 0.7))
            user = User.objects.create(username=name, email=f"{name}@{DEMO_DOMAIN}", date_joined=joined)
            user.set_unusable_password()
            user.save(update_fields=["password"])
            Profile.objects.filter(user=user).update(phone=f"2547{rng.randint(10000000, 99999999)}")
            self.balances[user.id] = Decimal("0")
            style = rng.choices(["cautious", "balanced", "risky"], weights=[4, 4, 2])[0]
            players.append({
                "user": user, "joined": joined, "style": style, "deposits": 0,
                "stake": q(max(cfg["MIN_BET"], rng.lognormvariate(4.3, 0.9))),           # ~75 median
                "deposit_size": q(rng.choice([100, 200, 250, 500, 1000, 2000])),
                "activity": rng.uniform(0.04, 0.3),
                "sports_rate": rng.uniform(0.0, 0.6),
                "casino_rate": rng.choice([0, 0.02, 0.05, 0.1, 0.15]),
                "games": rng.sample(["dice", "plinko", "wheel", "roulette", "baccarat", "mines"], k=rng.randint(1, 3)),
            })
        # referrals between some demo players
        for p in players[1:]:
            if rng.random() < 0.2:
                ref = rng.choice(players[:players.index(p)])
                Profile.objects.filter(user=p["user"]).update(referred_by=ref["user"])

        def target_for(p):
            if p["style"] == "cautious":
                return q(rng.uniform(1.15, 1.7))
            if p["style"] == "balanced":
                return q(rng.uniform(1.5, 3.2))
            return q(min(1 + rng.lognormvariate(1.0, 0.9), 100))

        # ---------------- Sports: fixtures + slips become time-ordered events
        league, _ = League.objects.get_or_create(name="Demo League", defaults={"flag": "🏟️", "priority": 99})
        margin = 1 + settings.SPORTS["MARGIN_PERCENT"] / 100
        slips, events, counter = [], [], itertools.count()

        def place_slip(p, at, legs):
            stake = q(max(settings.SPORTS["MIN_STAKE"], float(p["stake"]) * rng.choice([1, 2])))
            if not self.ensure_funds(rng, p, stake, at):
                return
            picks = [(m, rng.choices(list(pr), weights=list(pr.values()))[0]) for m, pr in legs]
            total_odds = Decimal("1")
            for m, pick in picks:
                total_odds *= m.odds_for(pick)
            total_odds = total_odds.quantize(Decimal("0.01"))
            won = all(m.result == pick for m, pick in picks)
            settled = max(m.kickoff for m, _ in picks) + timedelta(hours=2)
            slip = SportsBet(user=p["user"], stake=stake, total_odds=total_odds,
                             potential_win=min(q(stake * total_odds), Decimal(settings.SPORTS["MAX_PAYOUT"])),
                             status=SportsBet.Status.WON if won else SportsBet.Status.LOST, settled_at=settled)
            slip.payout = slip.potential_win if won else Decimal("0")
            self.tx(p["user"], K.SPORTS_BET, -stake, at, note=f"{len(picks)}-leg slip")
            if won:
                heapq.heappush(events, (settled, next(counter),
                                        lambda: self.tx(p["user"], K.SPORTS_WIN, slip.payout, settled)))
            slips.append((slip, at, picks))

        for d in range(days):
            day_matches = []
            for _ in range(6):
                home, away = rng.sample(TEAMS, 2)
                ph, pd = rng.uniform(0.25, 0.6), rng.uniform(0.2, 0.3)
                probs = {"1": ph, "X": pd, "2": max(0.1, 1 - ph - pd)}
                total = sum(probs.values())
                probs = {k: v / total for k, v in probs.items()}
                odds = {k: q(max(1.05, 1 / (v * margin))) for k, v in probs.items()}
                result = rng.choices(list(probs), weights=list(probs.values()))[0]
                hs, as_ = rng.randint(0, 3), rng.randint(0, 3)
                if result == "1" and hs <= as_:
                    hs = as_ + 1
                elif result == "2" and as_ <= hs:
                    as_ = hs + 1
                elif result == "X":
                    as_ = hs
                kickoff = start + timedelta(days=d, hours=rng.choice([14, 16, 18, 20, 21]))
                if kickoff + timedelta(hours=2) > now:
                    continue
                m = Match.objects.create(league=league, home_team=home, away_team=away, kickoff=kickoff,
                                         status=Match.Status.FINISHED, home_odds=odds["1"], draw_odds=odds["X"],
                                         away_odds=odds["2"], home_score=hs, away_score=as_)
                day_matches.append((m, probs))
            if not day_matches:
                continue
            first_kickoff = min(m.kickoff for m, _ in day_matches)
            for p in players:
                at = first_kickoff - timedelta(hours=rng.uniform(1, 6))
                if p["joined"] > at or rng.random() > p["sports_rate"] * 0.5:
                    continue
                legs = rng.sample(day_matches, k=min(len(day_matches), rng.choice([1, 1, 2, 3])))
                heapq.heappush(events, (at, next(counter), lambda p=p, at=at, legs=legs: place_slip(p, at, legs)))

        def run_events_until(t):
            while events and events[0][0] <= t:
                heapq.heappop(events)[2]()

        # ---------------- Aviator rounds
        seq = (GameRound.objects.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
        bets, round_count = [], 0
        step = 86400 / rounds_per_day
        for d in range(days):
            for r in range(rounds_per_day):
                at = start + timedelta(days=d, seconds=r * step + rng.uniform(0, step * 0.3))
                if at > now - timedelta(minutes=5):
                    break
                run_events_until(at)
                seed = secrets.token_hex(32)
                crash = engine.crash_point_from_seed(seed)
                flight = at + timedelta(seconds=cfg["BETTING_SECONDS"])
                crashes = flight + timedelta(seconds=engine.seconds_to_reach(crash))
                rnd = GameRound.objects.create(
                    sequence=seq, server_seed=seed, seed_hash=hashlib.sha256(seed.encode()).hexdigest(),
                    crash_point=crash, flight_starts_at=flight, crashes_at=crashes,
                    next_round_at=crashes + timedelta(seconds=cfg["CRASHED_SECONDS"]), settled=True,
                )
                seq += 1
                round_count += 1
                # busier evenings: scale activity by hour of day
                hour = timezone.localtime(at).hour
                busy = 1.6 if 18 <= hour <= 23 else (0.35 if 1 <= hour <= 6 else 1.0)
                for p in players:
                    if p["joined"] <= at and rng.random() < p["casino_rate"] * busy:
                        self.casino_play(rng, p, at + timedelta(seconds=rng.randint(20, int(step * 0.6))))
                    if p["joined"] > at or rng.random() > p["activity"] * busy:
                        continue
                    stake = q(max(cfg["MIN_BET"], float(p["stake"]) * rng.choice([0.5, 1, 1, 1, 2])))
                    if not self.ensure_funds(rng, p, stake, at):
                        continue
                    user = p["user"]
                    self.tx(user, K.AVIATOR_BET, -stake, at, note=f"Round {rnd.sequence}")
                    target = target_for(p)
                    bet = AviatorBet(user=user, round=rnd, panel=1, amount=stake,
                                     auto_cashout=target if rng.random() < 0.4 else None)
                    if target < crash:
                        payout = min(q(stake * target), Decimal(cfg["MAX_WIN"]))
                        bet.status, bet.cashed_out_at, bet.payout = AviatorBet.Status.WON, target, payout
                        self.tx(user, K.AVIATOR_WIN, payout, crashes, note=f"Cashed out @ {target}x")
                    else:
                        bet.status = AviatorBet.Status.LOST
                    bets.append((bet, at))
                    self.maybe_withdraw(rng, p, crashes + timedelta(minutes=2), recent=(now - at).days < 2)

        run_events_until(now)

        # ---------------- persist in bulk, then backdate auto timestamps
        AviatorBet.objects.bulk_create([b for b, _ in bets], batch_size=1000)
        for b, at in bets:
            b.created_at = at
        AviatorBet.objects.bulk_update([b for b, _ in bets], ["created_at"], batch_size=1000)

        CasinoBet.objects.bulk_create([b for b, _ in self.casino_bets], batch_size=1000)
        for b, at in self.casino_bets:
            b.created_at = at
        CasinoBet.objects.bulk_update([b for b, _ in self.casino_bets], ["created_at"], batch_size=1000)
        for pair in self.seed_pairs.values():
            pair.save(update_fields=["nonce"])

        SportsBet.objects.bulk_create([s for s, _, _ in slips], batch_size=500)
        sels = []
        for s, at, picks in slips:
            s.created_at = at
            for m, pick in picks:
                sels.append(Selection(bet=s, match=m, pick=pick, odds=m.odds_for(pick),
                                      status=Selection.Status.WON if m.result == pick else Selection.Status.LOST))
        SportsBet.objects.bulk_update([s for s, _, _ in slips], ["created_at"], batch_size=500)
        Selection.objects.bulk_create(sels, batch_size=1000)

        self.txs.sort(key=lambda t: t[1])
        # recompute running balances in chronological order; where events generated out of order
        # would dip a wallet below zero, insert the top-up deposit the player would have made
        running = {uid: Decimal("0") for uid in self.balances}
        size = {p["user"].id: p["deposit_size"] for p in players}
        ordered = []
        for t, at in self.txs:
            if running[t.user_id] + t.amount < 0:
                need = -(running[t.user_id] + t.amount)
                top_up = size[t.user_id] * (int(need // size[t.user_id]) + 1)
                running[t.user_id] += top_up
                ordered.append((Transaction(user_id=t.user_id, kind=K.DEPOSIT, amount=top_up,
                                            balance_after=running[t.user_id], note="M-Pesa (demo)"),
                                at - timedelta(seconds=30)))
            running[t.user_id] += t.amount
            t.balance_after = running[t.user_id]
            ordered.append((t, at))
        self.txs = ordered
        Transaction.objects.bulk_create([t for t, _ in self.txs], batch_size=1000)
        for t, at in self.txs:
            t.created_at = at
        Transaction.objects.bulk_update([t for t, _ in self.txs], ["created_at"], batch_size=1000)

        for p in players:
            Wallet.objects.filter(user=p["user"]).update(balance=running[p["user"].id])
            Profile.objects.filter(user=p["user"]).update(created_at=p["joined"])

        staked = sum((b.amount for b, _ in bets), Decimal(0))
        paid = sum((b.payout for b, _ in bets), Decimal(0))
        self.stdout.write(self.style.SUCCESS(
            f"Created {len(players)} demo players, {round_count} rounds, {len(bets)} Aviator bets "
            f"(hold {((staked - paid) / staked * 100) if staked else 0:.1f}%), {len(self.casino_bets)} casino bets, "
            f"{len(slips)} sports slips, "
            f"{len(self.txs)} transactions."))
