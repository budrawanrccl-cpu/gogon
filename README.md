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

## Keuntungan menggunakan bot trading di Polymarket

Menjalankan strategi lewat bot ini (bukan manual lewat UI) punya beberapa
keuntungan konkret:

1. **Kecepatan eksekusi** — peluang arbitrase (YES+NO < $1) di orderbook
   sering hilang dalam hitungan detik. Bot bisa scan & submit order jauh
   lebih cepat daripada manusia, dan memakai order fill-or-kill supaya
   kedua kaki (YES & NO) tereksekusi bersamaan, mengurangi risiko "satu
   kaki fill, satu kaki tidak".
2. **Emosi nol, disiplin penuh** — bot menjalankan strategi persis sesuai
   parameter yang dikonfigurasi (`min_edge`, `fee_buffer`, dll), tidak
   terpengaruh FOMO, panik, atau balas dendam setelah rugi — sumber
   kesalahan terbesar trader manual.
3. **Monitoring 24/7 tanpa lelah** — market Polymarket berjalan terus; bot
   bisa memantau banyak market sekaligus tanpa henti, sesuatu yang sulit
   dilakukan manusia sendirian.
4. **Manajemen risiko otomatis & mengikat** — `risk.max_position_usd`,
   `risk.max_total_exposure_usd`, dan kill-switch harian
   `risk.max_daily_loss_usd` dipaksakan di setiap trade, jadi batas
   kerugian tidak bisa "terlewat sesaat" seperti sering terjadi saat
   trading manual.
5. **Bisa diuji tanpa risiko lebih dulu (paper trading)** — dengan
   `LIVE_TRADING=false`, semua trade disimulasikan memakai data pasar
   nyata tanpa menyentuh dana sungguhan, sehingga strategi dan parameter
   bisa divalidasi sebelum live.
6. **Jejak audit lengkap** — setiap sinyal (fill atau tidak) tercatat di
   `data/trades.csv`, plus log di `logs/bot.log`, memudahkan evaluasi
   performa dan rekonsiliasi dibanding trading manual yang jarang
   tercatat rapi.
7. **Konsisten & bisa direplikasi** — strategi yang sama berjalan persis
   sama setiap saat, memudahkan analisis apa yang berhasil dan tidak.
8. **Skalabilitas** — bot bisa mengevaluasi banyak market sekaligus dalam
   satu siklus, sesuatu yang tidak praktis dilakukan manual satu per
   satu.

Ini tidak menghilangkan risiko: risiko eksekusi (partial fill), perubahan
fee/aturan Polymarket, bug pada strategi, dan risiko pasar tetap ada — lihat
[Safety notes](#safety-notes). Selalu mulai dari paper mode dan modal kecil.

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
volume chart, strategy breakdown, open positions, recent trades, and the
**markets scanned in the bot's most recent cycle** (combined YES+NO ask,
edge vs. the arbitrage threshold, whether it currently qualifies) — read
straight from `data/trades.csv` and `data/scan_snapshot.json` (the latter
is a snapshot of the last cycle only, overwritten every cycle, not a
history). No extra dependencies, nothing leaves your machine.

```bash
# in a second terminal, alongside `python -m bot.main`:
python scripts/dashboard.py
```

It opens `http://127.0.0.1:8765` in your browser automatically and
refreshes every 5 seconds.

### Viewing it on your phone (e.g. iPhone)

By default the dashboard only listens on `127.0.0.1`, so it's only
reachable from the same computer. To check it from your phone while it's
on the **same Wi-Fi network**:

```bash
DASHBOARD_HOST=0.0.0.0 python scripts/dashboard.py
```

It will print a network URL like `http://192.168.1.23:8765` — open that
in Safari on your iPhone. This still runs entirely on your computer and
is only reachable on your local network, not the internet; it's
read-only data, but avoid doing this on a shared/public Wi-Fi. To reach
it over the internet (e.g. mobile data, away from home), put it behind a
tool like Tailscale or an SSH tunnel rather than exposing the port
directly.

## Running tests

```bash
python -m pytest
```

Tests cover the pure logic (risk limits, arbitrage sizing/edge detection,
threshold signal generation) with no network calls, so they're safe and
fast to run anytime.

## Safety notes

- ⚠️ **`py-clob-client` (this bot's trading library) has been archived by
  Polymarket and can no longer submit orders.** As of testing in
  September 2026, market/order-book reads still work, but
  `client.post_order()` fails with `{'error': 'invalid order version,
  please use the latest clob-client'}` regardless of which published
  version is installed — 0.34.6 is the last release and is itself
  rejected. Polymarket's replacement is the `polymarket-client` package
  (repo `Polymarket/py-sdk`), which has a different API (`PublicClient`/
  `SecureClient`, `create_limit_order()` + `place_limit_order()`, and a
  `token_id` vs `position_id` split between older and newer markets) and
  is still Beta. **Live trading (`LIVE_TRADING=true`) will not actually
  place orders until `bot/client.py`, `bot/market_data.py`, and
  `bot/execution.py` are migrated to that new SDK.** Paper trading is
  unaffected (it never calls `post_order()`), so it's still fine for
  watching the strategies run against real market data.
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
