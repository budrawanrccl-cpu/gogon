# gogon — Trading Bots

This repo hosts two independent, paper-trading-by-default bots:

- **[Polymarket auto-trading bot](#polymarket-auto-trading-bot)** (`bot/`) —
  complete-set arbitrage on Polymarket's CLOB.
- **[Funding-rate arbitrage bot](#funding-rate-arbitrage-bot-binance)**
  (`funding_bot/`) — spot + perpetual-futures hedge on Binance that collects
  funding payments.

They share no code or state and can be run independently.

> ⚠️ **This is trading software. It can lose real money.** Read the whole
> README, run in paper mode first, and never risk more than you can afford
> to lose. Nothing here is financial advice.

## Polymarket Auto-Trading Bot

An automated trading bot for [Polymarket](https://polymarket.com) built on
Polymarket's official CLOB (Central Limit Order Book) API. It scans active
markets, applies pluggable strategies, and executes trades through a risk
manager with hard position/exposure/loss caps.

### How it works

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

### Setup

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

### Running

```bash
# Sanity-check config, wallet, and connectivity before running for real:
python scripts/check_setup.py

# Run the bot:
python -m bot.main
```

Stop any time with `Ctrl+C` — it finishes the current cycle and exits
cleanly.

### Dashboard

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

### Safety notes

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

## Funding-Rate Arbitrage Bot (Binance)

A bot that collects perpetual-futures **funding payments** by holding a
delta-neutral hedge on Binance: **long spot + short perpetual futures** on
the same asset. It scans funding rates, opens hedges where the annualized
funding rate clears a configurable threshold, tracks them until the edge
decays, and closes them — all through the same paper/live, risk-capped
structure as the Polymarket bot.

### Why spot + short perp collects funding, risk-free-ish

Perpetual futures use funding payments to keep the perp price anchored to
the index/spot price. When the funding rate is **positive**, longs pay
shorts every interval (typically every 8h on Binance, though some symbols
now use 1h/4h). Going **short the perp** while holding an equal **long
spot** position is delta-neutral — price moves in spot and perp roughly
cancel out — so the position's P&L is dominated by the funding payments it
collects, not by which way the market moves.

The real risks: **execution risk** (one leg fills, the other doesn't —
mitigated by unwinding the filled leg immediately if the other fails, see
`funding_bot/execution.py`), **basis risk** (mark price drifting away from
spot, bounded here by `max_basis_pct`), and the **funding rate itself
changing or flipping** before you exit (mitigated by `exit_funding_rate_apr`
hysteresis and ongoing basis checks every cycle). This bot only trades the
**positive-funding** direction — collecting *negative* funding would require
shorting spot on margin, which isn't implemented (`allow_negative_funding`
is a documented no-op placeholder, not a working feature).

### Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env`:
- Leave `FUNDING_LIVE_TRADING=false` to run in **paper trading** (fully
  simulated, no funds at risk, no API key required). This is the default
  and the recommended starting point.
- To go live later, you'll need:
  - `BINANCE_API_KEY` / `BINANCE_API_SECRET` — create these at
    [Binance API Management](https://www.binance.com/en/my/settings/api-management).
    Only grant **Spot & Margin Trading** and **Futures** permissions — never
    **Withdrawals**. **Never commit these or paste them anywhere outside
    your local `.env`.**
  - Try `BINANCE_TESTNET=true` first against Binance's public testnet.
  - Then set `FUNDING_LIVE_TRADING=true`.

Tune strategy and risk parameters in `config/funding_settings.yaml` — in
particular `risk.max_position_usd`, `risk.max_total_exposure_usd`,
`funding_arbitrage.min_funding_rate_apr`, and
`funding_arbitrage.max_basis_pct`. Start small, and start with a manually
chosen `symbols.whitelist` (e.g. `["BTC", "ETH"]`) rather than
auto-discovery until you've watched it run for a while.

### Running

```bash
# Sanity-check config and connectivity before running for real:
python scripts/check_funding_setup.py

# Run the bot:
python -m funding_bot.main
```

Stop any time with `Ctrl+C` — it finishes the current cycle and exits
cleanly. It does **not** automatically close open hedges on shutdown; the
next run will pick up where its own bookkeeping left off in-memory only
(there's no position persistence across restarts yet — see Safety notes).

### Safety notes

- **Start in paper mode**, and on Binance's testnet before mainnet, and
  watch `data/funding_trades.csv` / `logs/funding_bot.log` for at least a
  few funding intervals before considering live trading with real funds.
- **Position state is in-memory only.** If the bot restarts while a hedge
  is open, it forgets about it — the real position still exists on Binance,
  but the bot will no longer manage or unwind it for you. Reconcile against
  your Binance account before and after any restart.
- The bot enforces a **daily loss kill-switch**
  (`risk.max_daily_loss_usd`, tracking price P&L *and* collected funding):
  once hit, it stops opening new positions until UTC midnight. It does not
  automatically close existing positions for you.
- Funding accrual in this bot is an **estimate** based on observed funding
  rates and settlement timestamps, not Binance's actual income ledger —
  periodically reconcile against Binance's Futures **Income History**
  before trusting the numbers for anything beyond a rough read.
- Only **one open position per symbol** is supported at a time.
- This code has not been run against the live Binance API from this
  environment (outbound network here is sandboxed) — treat
  `scripts/check_funding_setup.py` as your first real-world check, and
  review the code yourself before trusting it with funds.

## Running tests

```bash
python -m pytest
```

Covers both bots' pure logic (risk limits, arbitrage sizing/edge detection,
funding-rate hedge entry/exit, threshold signal generation) with no network
calls, so it's safe and fast to run anytime.

## Project layout

```
bot/                        # Polymarket bot
  config.py                   # loads .env + config/settings.yaml
  client.py                    # wraps py-clob-client's ClobClient
  market_data.py                 # market discovery + order book parsing
  risk.py                          # position/exposure/loss limits
  execution.py                      # paper vs. live order execution
  journal.py                          # CSV trade log
  main.py                               # the scan-evaluate-execute loop
  strategies/
    base.py                             # Signal + Strategy interface
    arbitrage.py                         # complete-set arbitrage (default, on)
    threshold.py                          # mean-reversion (default, off)
config/settings.yaml           # Polymarket bot strategy & risk parameters

funding_bot/                 # Funding-rate arbitrage bot
  config.py                    # loads .env + config/funding_settings.yaml
  client.py                     # builds ccxt Binance spot + USDT-M futures clients
  market_data.py                 # funding-rate/price discovery
  risk.py                          # position/exposure/loss limits + funding accrual
  execution.py                      # paper vs. live two-leg (spot+perp) execution
  journal.py                          # CSV trade + funding-settlement log
  main.py                               # the scan-evaluate-execute loop
  strategies/
    base.py                             # Signal/Leg types
    funding_arbitrage.py                 # spot+perp hedge entry/exit (default, on)
config/funding_settings.yaml   # funding bot strategy & risk parameters

.env.example                # secrets template for both bots (copy to .env)
scripts/check_setup.py         # Polymarket bot pre-flight sanity check
scripts/check_funding_setup.py # funding bot pre-flight sanity check
scripts/dashboard.py            # local trading-activity dashboard (Polymarket bot)
tests/                            # pytest unit tests for both bots, no network required
```
