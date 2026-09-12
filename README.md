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

## Crypto Trend-Following Bot (Binance)

A second, independent bot lives in `crypto_bot/` — a long-only trend-following
system for crypto spot markets on Binance (via [ccxt](https://github.com/ccxt/ccxt),
so swapping to another ccxt-supported exchange is mostly a config change).

> ⚠️ **Read this before running it.** There is no such thing as a bot that is
> guaranteed to profit — if there were, nobody would give it away. What
> follows is a strategy with a long public track record of *positive
> expectancy over many trades*, not a way to win most trades or every week.
> Backtest it yourself, paper-trade it, and only then consider real funds.

### The strategy

**Donchian channel breakout with an ATR trailing stop** — the same family of
rules as the original "Turtle Trading" system:

- **Entry**: buy when price closes above its highest high of the last N bars
  (`donchian_entry_period`) — a possible new trend forming.
- **Stop**: initial stop at `entry - atr_stop_mult × ATR`; trails up with
  price, never down.
- **Exit**: whichever comes first — the trailing stop, or price closing below
  its lowest low of the last M bars (`donchian_exit_period`), i.e. the trend
  looks over.
- **Optional regime filter**: only take entries when price is at/above a
  longer-term EMA (`trend_filter_ema_period`), to skip some breakouts in a
  broader downtrend at the cost of missing some early moves.

Why this and not something claiming a bigger edge: simple trend-following
breakout rules have decades of public track record across many markets,
precisely *because* they're simple enough that the edge doesn't fully
arbitrage away. But that edge shows up as a **low win rate with a few large
winners paying for many small losers** — expect long streaks of small stopped-
out losses even when the system is working exactly as designed. It loses
money in sideways/choppy markets ("whipsaw"). See `crypto_bot/strategy.py`
for the full reasoning.

Risk is capped by `crypto_bot/risk.py`: every trade risks a fixed fraction of
equity (`risk_per_trade_pct`, not a fixed dollar amount), plus a daily-loss
kill switch and a max-drawdown kill switch that stops new entries (existing
positions keep managing their own stops).

### Setup

```bash
pip install -r requirements.txt   # adds ccxt on top of the Polymarket bot's deps
```

`.env` additions (see `.env.example`): `BINANCE_API_KEY` / `BINANCE_API_SECRET`
are only needed for live trading or Binance testnet order placement — not for
backtesting or paper trading against public market data. `BINANCE_TESTNET=true`
is the default; get testnet keys at https://testnet.binance.vision/.
`CRYPTO_LIVE_TRADING=true` enables real order placement — off by default.

Tune strategy/risk parameters in `config/crypto_settings.yaml`.

### Backtest first — this is the whole point

```bash
python scripts/run_crypto_backtest.py                              # BTC/USDT, 4h, 1 year
python scripts/run_crypto_backtest.py --symbol ETH/USDT --timeframe 1h --days 730
```

Downloads (and locally caches, in `data/ohlcv/`) historical candles and runs
them through the exact same `strategy.evaluate()` + `RiskManager` code the
live bot uses, so the backtest isn't a separate code path that quietly
diverges from what actually trades. Prints trade count, win rate, profit
factor, max drawdown, and return. **Test several symbols and at least a
couple of years of data — and remember a good backtest still doesn't
guarantee future results, since markets change regime.**

Known simplifications (see `crypto_bot/backtest.py` for the full list):
entries/channel-exits fill at the signal bar's close; stop-outs fill exactly
at the stop price with no slippage; fees are modeled as a flat round-trip
percentage.

### Paper trade, then (optionally) go live

```bash
python scripts/check_crypto_setup.py   # sanity-check config + exchange connectivity
python -m crypto_bot.main              # paper trading by default — no real orders
```

Runs the live loop against real market data, simulating fills, so you can
watch it behave in real time before risking anything. Logs go to
`logs/crypto_bot.log`; every signal is journaled to `data/crypto_trades.csv`.
Flip `CRYPTO_LIVE_TRADING=true` (with API keys set) only after you've watched
it paper-trade for a while and are comfortable with the position sizes
`risk_per_trade_pct` produces at your configured `starting_equity_usd`.

### Running tests

```bash
python -m pytest tests/test_crypto_*.py
```

Covers indicators, strategy signal generation, risk sizing/kill-switches, and
the backtest engine — all pure logic, no network calls.

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

crypto_bot/                    # Binance trend-following bot (independent of bot/ above)
  config.py                     # loads .env + config/crypto_settings.yaml
  models.py                      # Bar / Signal / Position / ClosedTrade
  indicators.py                   # EMA, ATR, Donchian channels (pure functions)
  strategy.py                      # Donchian breakout + ATR trailing stop
  risk.py                           # fixed-fractional sizing + kill switches
  backtest.py                       # single-symbol backtest engine
  exchange.py                        # ccxt wrapper (history fetch + orders)
  data.py                             # OHLCV caching to data/ohlcv/*.csv
  journal.py                          # CSV trade log
  main.py                              # the live/paper trading loop
config/crypto_settings.yaml    # strategy & risk parameters (no secrets)

.env.example             # secrets template (copy to .env)
scripts/check_setup.py    # Polymarket bot pre-flight sanity check
scripts/check_crypto_setup.py  # crypto bot pre-flight sanity check
scripts/run_crypto_backtest.py # fetch history + backtest the crypto bot
scripts/dashboard.py       # local trading-activity dashboard (Polymarket bot)
tests/                      # pytest unit tests, no network required
```
