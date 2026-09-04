# gogon — Polymarket Auto-Trading Bot

An automated trading bot for [Polymarket](https://polymarket.com) built on
Polymarket's official CLOB (Central Limit Order Book) API. It scans active
markets, applies pluggable strategies, and executes trades through a risk
manager with hard position/exposure/loss caps.

> ⚠️ **This is trading software. It can lose real money.** Read the whole
> README, run in paper mode first, and never risk more than you can afford
> to lose. Nothing here is financial advice.

## How it works

```
main loop
  ├─ market_data: scans active markets from the CLOB API
  ├─ strategies:  turn order-book data into buy/sell Signals
  │    ├─ arbitrage  (default, ON)  — buy YES+NO when combined price < $1
  │    └─ threshold  (default, OFF) — mean-reversion on price swings
  ├─ risk:        approves/rejects each Signal against position & loss caps
  └─ execution:   simulates the fill (paper) or signs & submits an order (live)
```

Every signal, filled or not, is appended to `data/trades.csv` as an audit
trail. Logs go to the console and to `logs/bot.log` (rotating).

### Why arbitrage is the default strategy

A binary Polymarket market always pays exactly $1 to the winning outcome's
shares and $0 to the losing side. Buying **one YES share and one NO share**
therefore always resolves to exactly $1 combined, no matter which side wins.
If the combined ask price of YES + NO is reliably below `$1 - fees`, the gap
is close to risk-free profit at resolution. The real risks are execution
risk (one leg fills, the other doesn't — mitigated here by using
fill-or-kill orders) and Polymarket's own fee/rule changes — which is why
`min_edge` and `fee_buffer` exist as safety margins in the config.

The threshold (mean-reversion) strategy is included as a second option but
ships **disabled**, because it's directional and can lose money in a
trending market — only turn it on if you understand that risk.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env`:
- Leave `LIVE_TRADING=false` to run in **paper trading** (fully simulated,
  no funds at risk, no wallet required). This is the default and the
  recommended starting point.
- To go live later, you'll need:
  - `POLY_PRIVATE_KEY` — the private key of the wallet that signs orders.
    **Never commit this or paste it anywhere outside your local `.env`.**
  - `POLY_FUNDER_ADDRESS` — the address holding your USDC. If you trade
    through the polymarket.com website, this is your **proxy wallet**
    address (shown on your Polymarket profile), and `POLY_SIGNATURE_TYPE`
    should be `2`. If you trade with a plain EOA wallet directly, use your
    wallet address and `POLY_SIGNATURE_TYPE=0`.
  - Then set `LIVE_TRADING=true`.

Tune strategy and risk parameters in `config/settings.yaml` — in
particular `risk.max_position_usd`, `risk.max_total_exposure_usd`, and
`risk.max_daily_loss_usd`. Start small.

## Running

```bash
# Sanity-check config, wallet, and connectivity before running for real:
python scripts/check_setup.py

# Run the bot:
python -m bot.main
```

Stop any time with `Ctrl+C` — it finishes the current cycle and exits
cleanly.

## Dashboard

A local, read-only dashboard shows live trading activity — KPIs, cumulative
volume chart, strategy breakdown, open positions, and recent trades — read
straight from `data/trades.csv`. No extra dependencies, nothing leaves your
machine.

```bash
# in a second terminal, alongside `python -m bot.main`:
python scripts/dashboard.py
```

It opens `http://127.0.0.1:8765` in your browser automatically and
refreshes every 5 seconds.

## Running tests

```bash
python -m pytest
```

Tests cover the pure logic (risk limits, arbitrage sizing/edge detection,
threshold signal generation) with no network calls, so they're safe and
fast to run anytime.

## Safety notes

- **Start in paper mode** and watch `data/trades.csv` / `logs/bot.log` for
  at least a few days before considering live trading.
- **Start with small caps** in `config/settings.yaml` when you do go live.
- The bot enforces a **daily loss kill-switch** (`risk.max_daily_loss_usd`):
  once hit, it stops opening new positions until UTC midnight. It does not
  automatically close existing positions for you.
- In live mode, order fills are tracked based on the CLOB API's response to
  each order submission. Periodically reconcile against
  `client.get_trades()` / the Polymarket UI — don't rely solely on the
  bot's in-memory position tracking for anything you haven't verified.
- The arbitrage strategy currently only handles simple **binary
  (two-outcome)** markets.
- This code has not been run against the live Polymarket API from this
  environment (no network access here) — treat `scripts/check_setup.py`
  as your first real-world check, and review the code yourself before
  trusting it with funds.

## Project layout

```
bot/
  config.py          # loads .env + config/settings.yaml
  client.py           # wraps py-clob-client's ClobClient
  market_data.py       # market discovery + order book parsing
  risk.py               # position/exposure/loss limits
  execution.py           # paper vs. live order execution
  journal.py              # CSV trade log
  main.py                  # the scan-evaluate-execute loop
  strategies/
    base.py                # Signal + Strategy interface
    arbitrage.py            # complete-set arbitrage (default, on)
    threshold.py             # mean-reversion (default, off)
config/settings.yaml    # strategy & risk parameters (no secrets)
.env.example             # secrets template (copy to .env)
scripts/check_setup.py    # pre-flight sanity check
scripts/dashboard.py       # local trading-activity dashboard
tests/                      # pytest unit tests, no network required
```

---

# pump.fun Momentum Bot (Solana)

A second, independent bot in this repo: an automated, **paper-trading-by-default**
bot for [pump.fun](https://pump.fun) (Solana meme-coin bonding-curve launches),
using the third-party [PumpPortal](https://pumpportal.fun) API for market data
and non-custodial trade execution.

> ⚠️ **Read this whole section before running this bot, especially before
> ever setting `LIVE_TRADING=true`.** This is not the Polymarket bot above —
> it trades a fundamentally more dangerous asset class. **The honest,
> well-documented base rate is that the large majority of pump.fun tokens
> lose most or all of their value**, many are deliberately designed as
> pump-and-dump or honeypot scams, and bot vs. bot competition for the
> fastest entries is intense. This code gives you a systematic,
> risk-capped way to test a strategy — it does **not** give you an edge
> against that reality, and it can lose all the SOL you fund it with.
> Nothing here is financial advice.

## How it works — and what it deliberately does *not* do

```
main loop
  ├─ market_data: streams new-token + trade events from PumpPortal's
  │                public WebSocket feed (read-only, no wallet involved)
  ├─ strategy:    momentum  — buys only tokens that already show broad,
  │                real public buying interest (min unique buyers, min buy
  │                volume, sane market-cap range, no obvious net sell
  │                pressure, creator not holding an outsized share)
  ├─ risk:        approves/rejects each entry against position/exposure/
  │                daily-loss/concurrent-position caps (all in SOL)
  ├─ exits:       take-profit, stop-loss, trailing-stop, and a hard
  │                max-hold-time close — checked every cycle for every
  │                open position
  └─ execution:   simulates the fill (paper) or signs & submits a real
                   Solana transaction (live)
```

**This bot intentionally does not try to be the fastest sniper.** It waits
`filters.min_token_age_seconds` (20s by default) before considering a new
token at all, specifically so it isn't racing to buy in the same
block/slot as token creation or trying to front-run other traders'
pending transactions. Instead it only acts once a token already shows
real, broad-based public interest (multiple distinct buyers, real buy
volume). That's still highly speculative — it can and will lose money —
but it's a rules-based filter you can explain out loud, not a latency
arms race against professional MEV infrastructure that retail hardware
realistically can't win anyway. It also does **not** implement any
volume-faking / wash-trading behavior, and it will not evade platform
rate limits or bot-detection — don't add that yourself.

Every signal, filled or not, is appended to `data/pumpbot_trades.csv`.
Logs go to the console and to `logs/pumpbot.log` (rotating).

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # includes solders, solana, websocket-client

cp .env.example .env   # if you haven't already for the Polymarket bot
```

Edit `.env` (pump.fun section at the bottom):
- Leave `LIVE_TRADING=false` (shared with the Polymarket bot above) to run
  in **paper trading** — fully simulated, no transactions broadcast, no
  wallet required. This is the default and the recommended starting point,
  for a good while.
- To go live later, you'll need:
  - `SOLANA_PRIVATE_KEY` — base58 secret key (Phantom/Solflare export
    format) or a `solana-keygen` JSON array, for the wallet that funds and
    signs trades. **Never commit this or paste it anywhere outside your
    local `.env`.** Signing happens locally in this process — the key is
    never sent to PumpPortal or any RPC.
  - `SOLANA_RPC_URL` — get a real (paid) RPC endpoint (Helius, QuickNode,
    Triton, etc.) before going live; the free public endpoint is
    rate-limited and unreliable for anything time-sensitive.
  - Fund that wallet with a **small** amount of SOL you can fully afford
    to lose. Start with an amount you'd be fine seeing go to zero.
  - Then set `LIVE_TRADING=true`.

Tune filters and risk parameters in `config/pumpbot_settings.yaml` — in
particular `risk.max_position_sol`, `risk.max_total_exposure_sol`, and
`risk.max_daily_loss_sol`. Start as small as the platform allows.

## Running

```bash
# Sanity-check config and (in live mode) wallet/RPC connectivity:
python scripts/check_pumpbot_setup.py

# Run the bot:
python -m pumpbot.main
```

Stop any time with `Ctrl+C` — it finishes the current cycle and exits
cleanly (open positions are **not** auto-closed on exit; check them
yourself).

## Dashboard

A local, read-only dashboard shows live trading activity — wallet balance,
KPIs, cumulative volume + realized P&L charts, strategy breakdown, open
positions, and recent trades — read straight from `data/pumpbot_trades.csv`.

```bash
# in a second terminal, alongside `python -m pumpbot.main`:
python scripts/pumpbot_dashboard.py
```

It opens `http://127.0.0.1:8766` in your browser automatically and
refreshes every 5 seconds (the wallet balance panel every 15 seconds).

The trade log is 100% local. The one exception is the **wallet balance
panel**, which makes a small, read-only `getBalance` JSON-RPC call to your
configured `SOLANA_RPC_URL` — it needs only a **public** address, resolved
from `SOLANA_WALLET_ADDRESS` if set, otherwise derived from
`SOLANA_PRIVATE_KEY` if that's set. It never sends your private key
anywhere. If neither is set, the panel just shows "not configured" and the
rest of the dashboard works normally.

Want to see what it looks like before the bot has traded anything real?

```bash
python scripts/seed_pumpbot_demo_trades.py   # writes FAKE demo trades
python scripts/pumpbot_dashboard.py
```

Your real `data/pumpbot_trades.csv` (if any) is backed up first, never
overwritten silently — the seed script prints how to restore it.

## Risks (read this)

- **Most pump.fun tokens are worth ~zero shortly after launch.** Buying
  early public momentum does not change the base rate meaningfully — it
  just filters out the very thinnest/earliest noise.
- **Rug pulls and honeypots are common**: a token can be sellable when you
  buy and unsellable minutes later if liquidity is pulled or the contract
  is malicious. Position and exposure caps limit how much any single
  token can cost you — they do not prevent this from happening.
  `filters.max_creator_holding_pct` is a **partial** safeguard at best:
  the field it checks is often unavailable from the public feed, and when
  it's unknown the bot does **not** block the trade on that basis alone.
  It cannot detect creator wallets that are disguised, funded through
  intermediaries, or a liquidity pull executed after purchase.
- **This is not a guaranteed edge.** The momentum filters (buyer count,
  volume, price range) are a reasonable systematic heuristic, not a proven
  profitable strategy — treat paper-mode results as informative, not
  predictive, since paper fills assume your full order fills instantly at
  the last observed reference price with no slippage.
- **PumpPortal is an unofficial, third-party API**, not operated by
  pump.fun. Its endpoints, fees, rate limits, and payload field names can
  change without notice — `pumpbot/market_data.py` and
  `pumpbot/execution.py` parse defensively and log on unexpected shapes,
  but you should verify against a live connection yourself before trusting
  it in size.
- **This code has not been run against the live PumpPortal/Solana APIs
  from this environment** (no network access here) — treat
  `scripts/check_pumpbot_setup.py` and a small, closely-watched live run
  as your first real-world checks, and review the code yourself before
  funding it.
- The daily loss kill-switch (`risk.max_daily_loss_sol`) stops the bot
  from *opening new* positions once hit — it does not automatically close
  existing ones.

## Project layout

```
pumpbot/
  config.py          # loads .env + config/pumpbot_settings.yaml
  wallet.py            # local Solana keypair loading (signing only, live mode)
  market_data.py         # PumpPortal WebSocket feed + per-mint stat tracking
  risk.py                  # position/exposure/concurrency/daily-loss limits (SOL)
  exits.py                   # take-profit / stop-loss / trailing-stop / max-hold
  execution.py                 # paper vs. live (sign-locally, submit-yourself) execution
  journal.py                     # CSV trade log
  main.py                          # the stream-evaluate-execute loop
  strategies/
    base.py                        # Signal + Strategy interface
    momentum.py                     # early-momentum entry filter (only strategy)
config/pumpbot_settings.yaml    # filters & risk parameters, all in SOL (no secrets)
scripts/check_pumpbot_setup.py   # pre-flight sanity check
scripts/pumpbot_dashboard.py      # local trading-activity dashboard + wallet balance
scripts/seed_pumpbot_demo_trades.py # writes fake demo trades to preview the dashboard
tests/test_pumpbot_*.py           # pytest unit tests, no network required
```
