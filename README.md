# gogon

This repo hosts two independent, unrelated bots:

1. **[Polymarket Auto-Trading Bot](#polymarket-auto-trading-bot)** (`bot/`) —
   places trades.
2. **[Smart Money Screener for gmgn.ai](#smart-money-screener-for-gmgnai)**
   (`gmgn/`) — read-only, never trades; just watches and alerts.

They share no code, no config, and no data files, and can be run
independently (in separate terminals, or not at all).

## Polymarket Auto-Trading Bot

An automated trading bot for [Polymarket](https://polymarket.com) built on
Polymarket's official CLOB (Central Limit Order Book) API. It scans active
markets, applies pluggable strategies, and executes trades through a risk
manager with hard position/exposure/loss caps.

> ⚠️ **This is trading software. It can lose real money.** Read the whole
> section, run in paper mode first, and never risk more than you can afford
> to lose. Nothing here is financial advice.

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

#### Why arbitrage is the default strategy

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

## Smart Money Screener for gmgn.ai

A read-only bot that watches [gmgn.ai](https://gmgn.ai) — a popular
Solana/multi-chain DEX analytics site — for newly-launched tokens that
tagged **"smart money" wallets** (proven, profitable traders gmgn.ai itself
labels `smart_degen`, `kol`, etc.) are actively accumulating. It never
places trades; it only screens and alerts, so you can act on the signal
yourself.

> ⚠️ **gmgn.ai has no official public API.** This bot calls the same
> undocumented JSON endpoints gmgn.ai's own website uses. They can change or
> disappear without notice, and gmgn.ai's Cloudflare bot-protection may
> reject requests outright. Treat this as a best-effort tool, verify it
> works with `scripts/gmgn_check_setup.py --live` before relying on it, and
> respect gmgn.ai's terms of use / robots.txt for however you use it. This
> is not financial advice — smart-money activity is a signal, not a
> guarantee.

### How it works

```
poll loop (every poll_interval_seconds)
  ├─ client:    fetch gmgn.ai's rank/swaps leaderboard — tokens ranked by
  │             smart-money buying, with trading stats, tax/sniper/holder
  │             quality flags, and smart buy/sell counts all in one response
  ├─ screener:  keep tokens with enough net smart-money buying, within your
  │             liquidity / market-cap / tax / sniper-count filters
  └─ notifier:  alert (console + optional Telegram/Discord), deduped by a
               per-token cooldown so you're not re-alerted every cycle
```

Every signal that passes the filters is appended to `data/gmgn_signals.csv`
as an audit trail, whether or not it was still in cooldown. Logs go to the
console and to `logs/gmgn.log` (rotating).

### Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Nothing in `.env` is required to run — by default the screener only logs
to the console/`logs/gmgn.log`. Optional settings:
- `GMGN_COOKIE` / `GMGN_USER_AGENT` — if gmgn.ai starts returning HTTP 403
  (Cloudflare bot-protection), set `GMGN_COOKIE` to a `cf_clearance`/session
  cookie captured from a real, logged-out gmgn.ai browser tab's dev tools,
  and/or `GMGN_USER_AGENT` to a current browser User-Agent string.
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — also push alerts to a
  Telegram chat via a bot you control.
- `DISCORD_WEBHOOK_URL` — also push alerts to a Discord channel webhook.

Tune screening thresholds in `config/gmgn_settings.yaml` — in particular
`screener.min_smart_buy_24h`, `screener.min_net_smart_buys`, and
`screener.min_liquidity_usd`. Optional safety filters (`max_buy_tax_pct`,
`max_sniper_count`, `min_bluechip_owner_pct`, `require_renounced`) are off
by default (`0` / `false`) — turn them on once you've seen what gmgn.ai
actually returns for your chain. The shipped defaults are a reasonable
starting point, not a recommendation — tighten them if you're getting
noise, loosen them if you're getting nothing.

### Running

```bash
# Sanity-check config (and, with --live, try one real request to gmgn.ai):
python scripts/gmgn_check_setup.py --live

# Run the screener:
python -m gmgn.main
```

Stop any time with `Ctrl+C` — it finishes the current cycle and exits
cleanly.

### Safety / accuracy notes

- **This bot only reads data and sends notifications — it never signs or
  submits any transaction.** There is no wallet, private key, or funds
  involved anywhere in `gmgn/`.
- gmgn.ai's "smart money" tags reflect **past** profitability, not future
  performance. Coordinated wallets, wash trading, and sniper/insider
  activity can also produce the exact same on-chain pattern this bot looks
  for. Always do your own research before acting on a signal.
- The main endpoint (`get_smart_money_tokens`, `/rank/{chain}/swaps/{period}`)
  follows gmgn.ai's most consistently community-documented shape; the wallet
  leaderboard endpoint (`get_smart_wallets`) is less consistently documented
  and more speculative. Neither is from official documentation (none
  exists) and either may need adjusting if gmgn.ai changes its site.
  Parsing is deliberately defensive (tries several known field-name
  variants, skips rows it can't parse) rather than crashing the whole cycle.
- The client rate-limits itself (`api.min_request_interval_seconds`) and
  backs off on 429/5xx — it's built for light personal screening, not
  high-frequency polling or bulk scraping.
- This code has not been exercised against the live gmgn.ai API from this
  environment (outbound access to gmgn.ai is blocked here) — treat
  `scripts/gmgn_check_setup.py --live` as your first real-world check.

## Running tests

```bash
python -m pytest
```

Both bots' pure logic is unit tested with no network calls: risk limits,
arbitrage sizing/edge detection, and threshold signal generation for the
Polymarket bot; screening thresholds/scoring, response parsing, and
alert-dedup/journal storage for the gmgn.ai screener.

## Repository layout

```
bot/                        # Polymarket auto-trading bot
  config.py                    # loads .env + config/settings.yaml
  client.py                     # wraps py-clob-client's ClobClient
  market_data.py                 # market discovery + order book parsing
  risk.py                          # position/exposure/loss limits
  execution.py                      # paper vs. live order execution
  journal.py                          # CSV trade log
  main.py                              # the scan-evaluate-execute loop
  strategies/
    base.py                            # Signal + Strategy interface
    arbitrage.py                        # complete-set arbitrage (default, on)
    threshold.py                         # mean-reversion (default, off)
config/settings.yaml            # Polymarket bot strategy & risk parameters

gmgn/                        # gmgn.ai smart-money screener (read-only)
  config.py                    # loads .env + config/gmgn_settings.yaml
  client.py                     # gmgn.ai HTTP client + response parsing
  models.py                      # SmartWallet / TokenStats / TokenSignal
  screener.py                     # pure filtering + scoring logic
  notifier.py                      # console / Telegram / Discord alerts
  storage.py                        # alert-cooldown cache + CSV signal journal
  main.py                            # the poll-screen-alert loop
config/gmgn_settings.yaml    # screener thresholds & gmgn.ai endpoint config

.env.example                 # secrets template for both bots (copy to .env)
scripts/check_setup.py           # Polymarket bot pre-flight sanity check
scripts/gmgn_check_setup.py       # gmgn.ai screener pre-flight sanity check
scripts/dashboard.py               # local Polymarket trading-activity dashboard
tests/                              # pytest unit tests for both bots, no network required
```
