# 🇰🇪 Nyota Yetu — Aviator, Casino & Sports Betting (Django)

A full Django betting platform in the colours of the Kenyan flag 🇰🇪 (black #000000 · red #BB0000 ·
green #006600 · white #FFFFFF, with the Maasai shield-and-star logo in `static/img/nyota-logo.svg`):
a **provably-fair Aviator crash game**, a **live in-play sportsbook** with every major football market,
a ⚡ virtual league, seven casino games, an M-Pesa-style wallet, referrals, cashback, leaderboards and
a staff back office.

## Quick start

Works on **Python 3.9+** with Django 4.2 LTS, or Python 3.10+ with Django 5.x.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser                       # for /admin
python manage.py seed_matches                          # demo fixtures for every league (development only)
python manage.py runserver
```

Open http://127.0.0.1:8000, create an account, deposit (demo mode credits instantly) and fly.

Keep matches moving even when nobody is browsing (live clocks, virtual league, settlement):

```bash
python manage.py run_live          # second terminal
```

Optional, in a second terminal — demo accounts that place real bets so the live table has activity:

```bash
python manage.py aviator_demo_players --players 10     # only runs while DEMO_PAYMENTS = True
```

Sample history for the back office (dev only — demo accounts use `@demo.local` emails and can't log in):

```bash
python manage.py seed_demo_data --players 40 --days 14   # ~5 seconds
python manage.py seed_demo_data --clear                  # remove all demo accounts + history
```

Run the tests: `python manage.py test`

## Casino games — `/casino/`

| Game | Rules | House edge |
|------|-------|------------|
| 🎲 **Dice** | Roll 0.00–99.99 over/under a target you choose (1–95% win chance) | `CASINO["HOUSE_EDGE_PERCENT"]` (4%) |
| 💎 **Mines** | 5×5 grid, 1–24 mines; reveal gems and cash out any time | 4% |
| 🔮 **Plinko** | 8/12/16 rows × low/medium/high risk; up to 232x | 4% (tables auto-scaled) |
| 🎡 **Wheel** | 20 segments × low/medium/high risk | 4% |
| 🎯 **Roulette** | European single zero; straight 35:1, dozens/columns 2:1, even-money 1:1 | 2.70% (the zero) |
| 👑 **Baccarat** | Punto banco, standard third-card rules; Banker pays 0.95:1, Tie 8:1, tie pushes main bets | 1.06% Banker · 1.24% Player · 14.4% Tie |
| 🃏 **Blackjack** | Dealer stands on all 17s, peeks; blackjack 3:2; double any 2 cards; split once | ≈0.5–1% with good play |

- Every result is **provably fair per player**: `HMAC_SHA256(server_seed, "client_seed:nonce:cursor")` → floats.
  Players see the server-seed hash, choose their own client seed, and can rotate to reveal and verify past
  bets in the browser at `/casino/provably-fair/` (the admin hides live server seeds, even from staff).
- All money moves through the wallet ledger (`casino_bet` / `casino_win` transactions). Mines and Blackjack
  are stateful: one game in play per player, row-locked, resumable after a page reload; mine positions,
  the shoe and the dealer's hole card never leave the server until the hand ends.
- The back office shows casino GGR and hold per game, and every player's casino history.

## The house edge — how the house wins

The house's profit comes from **math, not manipulation**:

- **Aviator** — `AVIATOR["HOUSE_EDGE_PERCENT"]` (default **5%**). Crash points are generated as
  `crash = (1 − edge) / (1 − r)`, which makes `P(crash > x) = (1 − edge) / x`. So a player cashing out at
  *any* target gets back 95% on average: **whatever strategy they use, the house keeps 5% of everything
  staked** over time. A test simulates 40,000 rounds to prove it. `AVIATOR["MAX_WIN"]` caps a single payout.
- **Sports** — the bookmaker margin `SPORTS["MARGIN_PERCENT"]` (default 6%) is built into the odds, so
  implied probabilities add up to 106%.
- Short-term, individual players and individual days *can* beat the house (that's what keeps players
  coming back); the dashboard's "actual hold vs target" shows the edge converging.
- Results are never adjusted per player or per bet. That's what keeps the provably-fair page honest and
  the business licensable — rigged outcomes are fraud and grounds for losing a licence.

## Back office (staff only) — `/backoffice/`

Log in as a staff user (`createsuperuser`), then open **Menu → Staff → Back office**.

- **KPIs** for today / 7 / 30 days / all time: GGR, NGR, hold %, deposits, withdrawals, active players,
  players online now, registered & new users, player funds held, open sports liability.
- **Charts**: daily GGR (house won vs lost) and daily active players, with a data table.
- **Aviator & sports breakdowns**: staked, paid out, actual vs target hold, win rate, average cash-out,
  instant-bust rate.
- **Live round**: who is betting right now, with real usernames. The crash point stays hidden until it
  happens, even for staff (insider protection).
- **Most valuable players**, **players beating the house** (risk review), biggest wins, pending withdrawals,
  newest sign-ups.
- **Players list** (`/backoffice/players/`): search by name/phone/email, sort by value, winners, stake,
  deposits, balance, recent activity; every player has a detail page with full stats, Aviator bets, sports
  slips, wallet ledger and referrals.

## Apps

| App | What it does |
|-----|--------------|
| `core` | Home (Aviator), promos, leaderboard, referral, help; global context (balance, cashback countdown) |
| `accounts` | Registration (phone, 18+ check, referral code), login/logout, profile & stats. Auto‑creates `Profile` + `Wallet` |
| `wallet` | `Wallet`, `Transaction` ledger. **All** balance changes go through `wallet/services.py` (`credit` / `debit`, row‑locked). Deposit / withdraw / history |
| `aviator` | `GameRound`, `AviatorBet`, game engine (`aviator/engine.py`), JSON API, provably‑fair page |
| `sports` | `League`, `Match`, `SportsBet`, `Selection`; betslip placement with server‑side odds; auto settlement |
| `casino` | Dice, Mines, Plinko, Wheel, Roulette, Baccarat, Blackjack: `games.py` (maths), `services.py` (money), per-player seeds |
| `backoffice` | Staff dashboard, player list & player profiles (`backoffice/analytics.py`), `seed_demo_data` command |

## How Aviator works

- Rounds are driven by wall‑clock time — **no Celery / websockets needed**. Each API call lazily
  advances the game: `BETTING (7s) → FLYING (until crash) → CRASHED (4s) → next round`.
- Multiplier = `e^(0.075·t)`. The crash point is fixed before betting opens from
  `HMAC_SHA256(server_seed, "lumabet-aviator")` (exact configurable house edge, default 5%). The seed’s SHA‑256 hash is shown
  during the round; the seed is revealed after. Anyone can verify on `/aviator/provably-fair/`.
- The browser never knows the crash point in advance. It polls `/aviator/api/state/` (~350 ms in flight),
  syncs its clock to the server and animates locally. Cash outs are priced **on the server** at the
  server's current multiplier.
- Two bet panels, each with **Auto bet** (re‑bet every round) and **Auto cash out** (settled server‑side
  even if the tab is closed). Clicking Bet mid‑flight queues the bet for the next round.
- Double‑payout safety: wins use a conditional `UPDATE … WHERE status='active'`, so a bet can only pay once.

API: `GET api/state/`, `POST api/bet/ {amount, panel, auto_cashout}`, `POST api/cancel/ {bet_id}`,
`POST api/cashout/ {bet_id}`, `GET api/history/?tab=previous|mine`.

## Sports

- Odds always come from the database, never from the browser. Matches close at kickoff.
- Settle from **Admin → Matches**: set status *Finished* + scores (or *Cancelled*) and save — every slip is
  graded and winners paid automatically. Cancelled legs are voided (odds removed).
- Demo: `python manage.py simulate_results --all` gives random scores to all open matches and settles them.

## Live sportsbook

**Markets (pre-match and in-play):** 1X2 · Double Chance · Draw No Bet · GG/NG · Over/Under 0.5–5.5 ·
Odd/Even · each team's goals O/U 0.5–2.5 · Half-time 1X2 · HT/FT · Correct Score.

- **One goal model prices everything** (`sports/markets.py`): each match has expected goals per side,
  fitted from its 1X2 odds (plus O/U 2.5 when the feed has it). Every market's price follows from a Poisson score
  model with the margin `SPORTS["MARGIN_PERCENT"]` (6%), so markets never contradict each other.
- **In play** (`sports/live.py`): prices are recalculated from the current minute and score every
  `TICK_SECONDS`. Decided markets close (e.g. Over 1.5 after the 2nd goal), half-time markets close at the break, and a
  goal suspends betting briefly. Bets are checked against the latest state before they are accepted, and if the
  price moved the player is asked to confirm unless they ticked *Accept any odds changes*.
- **Where live matches come from:**
  0. **Leagues:** `sports/leagues.py` lists 41 common competitions (Kenya Premier League first, then the big
     European leagues and cups, African, American, Asian and international football) with API-Football ids,
     flags and display order. `FOOTBALL_LEAGUES` can narrow it (`276,39,...`) or open it up (`all`).
     The sports page works like Flashscore: pick a day (yesterday → +5 days), filter All / Live / Finished /
     Scheduled, and leagues are grouped under their country.
  1. **Real fixtures: API-Football.** Get a key at api-football.com, then
     `export FOOTBALL_API_KEY=...` (optionally `FOOTBALL_LEAGUES=39,140,...`) and run
     `python manage.py sync_football --days 3` (fixtures + odds) and `python manage.py sync_football --live --loop 60`
     (live minute/score, results; bets settle automatically). Check league ids in your API-Football dashboard.
  2. **Manual matches** (admin): go live automatically at kickoff on a real clock; staff type goals in the admin
     (betting pauses briefly), then set the half-time score and status *Finished* to settle.
  3. **⚡ Virtual Ligi Kuu**: simulated matches with fictional Kenyan teams, a new kickoff every 3 minutes
     (`SPORTS["VIRTUAL"]`). Goals are drawn secretly when the match is created. They're always labelled VIRTUAL,
     because simulations must never be passed off as real football.
- The live ticker in the header shows every match in play.

### Demo fixtures (development only)

`seed_matches` creates pretend fixtures across every league (yesterday's results, today's live games, the next days)
so the board isn't empty locally. They play out on the real clock **only while `DEMO_PAYMENTS = True`**,
and the command refuses to run otherwise. On a real site every fixture, score and result must come from the feed
or from staff, because the matches use real team names. `seed_matches --clear` removes them.

## Background

`static/js/bg.js` draws the animated full-page background, decorative only:
- flowing Kenyan-flag ribbons, a perspective grid, and a constellation with red/green signals
- scrolling bars of real Aviator results, and falling live scores/odds from the site's own feeds
- a flag-coloured scan line and a status readout

It runs at ~30 fps, pauses in background tabs and stays still for users who prefer reduced motion.

## Cashback & referrals

- `python manage.py pay_cashback` — pays `CASHBACK_PERCENT`% of last week's net Aviator losses.
  Schedule it every Monday 00:00 (cron / Task Scheduler).
- Referrers get `REFERRAL_BONUS` when a referred friend makes their first deposit.

## Configuration (`lumabet/settings.py`)

`SITE_NAME`, `CURRENCY`, `DEMO_PAYMENTS`, `MIN_DEPOSIT`, `MIN_WITHDRAWAL`, `REFERRAL_BONUS`,
`CASHBACK_PERCENT`, `AVIATOR{HOUSE_EDGE_PERCENT, MAX_WIN, BETTING_SECONDS, CRASHED_SECONDS, GROWTH_RATE, MIN_BET, MAX_BET, …}`,
`CASINO{HOUSE_EDGE_PERCENT, MIN_BET, MAX_BET, MAX_WIN}`, `SPORTS{MARGIN_PERCENT, MIN_STAKE, MAX_STAKE, MAX_SELECTIONS, MAX_PAYOUT}`.

## Before going live ⚠️

1. **Licensing** — real‑money betting needs a licence (in Kenya: the Betting Control and Licensing Board), plus KYC/age verification.
2. **Payments** — set `DEMO_PAYMENTS = False` and integrate M‑Pesa Daraja STK Push in `wallet/views.py`
   (credit the wallet from the callback, verify signatures). Withdrawals are created as *pending* for admin approval.
3. **Database** — use PostgreSQL (real row locking via `select_for_update`). SQLite is for development.
4. **Security** — set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, HTTPS, and run `collectstatic`.
5. **Scale** — for many concurrent players, move the round loop into a single worker and push state over
   Django Channels/websockets instead of polling.
6. **Responsible gambling** — deposit limits, self‑exclusion and reality checks.
