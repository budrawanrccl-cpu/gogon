# gogon — Trading Bots

Two independent, standalone trading bots live in this repo:

1. **[Polymarket auto-trading bot](#part-1-polymarket-auto-trading-bot)**
   (`bot/`) — scans Polymarket markets and trades a pluggable strategy.
2. **[pump.fun wallet copy-trading bot](#part-2-pumpfun-wallet-copy-trading-bot)**
   (`pumpfun_bot/`) — watches Solana wallets and mirrors their pump.fun
   bonding-curve buys/sells.

They share nothing but a repo and a README — each has its own config,
`.env` variables, entry point, and tests, and can be run independently of
the other.

> ⚠️ **This is trading software. It can lose real money.** Read the whole
> README for whichever bot you're using, run in paper mode first, and never
> risk more than you can afford to lose. Nothing here is financial advice.

# Part 1: Polymarket Auto-Trading Bot

An automated trading bot for [Polymarket](https://polymarket.com) built on
Polymarket's official CLOB (Central Limit Order Book) API. It scans active
markets, applies pluggable strategies, and executes trades through a risk
manager with hard position/exposure/loss caps.

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

# Part 2: pump.fun Wallet Copy-Trading Bot

Watches one or more Solana wallets you choose and mirrors the trades they
make against [pump.fun](https://pump.fun)'s bonding-curve program — scaled
down to a fraction of their size and gated by the same kind of hard
position/exposure/loss caps as Part 1's risk manager.

> ⚠️ pump.fun tokens are extremely high-risk, often-illiquid meme coins, and
> copy-trading in general only works as well as the wallet you're copying —
> you have no way to verify a target wallet isn't the token's own creator
> about to dump on you. Start in paper mode, watch it for a while, and only
> ever risk SOL you can afford to lose completely.

## How it works

```
main loop (per watched wallet, every polling_interval_seconds)
  ├─ scan:    fetch the wallet's recent transaction signatures
  ├─ detect:  for each new one, read its pre/post SOL & token balances to
  │           recognize a pump.fun buy or sell (no instruction-decoding —
  │           the same balance deltas any block explorer reads)
  ├─ size:    scale the copy to `copy.size_ratio` of the target's SOL size,
  │           capped by `copy.max_sol_per_trade` and by the risk manager's
  │           per-mint / total-exposure / daily-loss budget
  └─ execute: simulate the fill (paper) or build, sign, and submit a real
             pump.fun buy/sell transaction (live)
```

Every copied (or attempted) trade is appended to `data/pumpfun_trades.csv`
as an audit trail. Logs go to the console and to `logs/pumpfun.log`
(rotating). On startup, each watched wallet's *current* newest transaction
is used as the starting point — the bot never replays a wallet's past
history as fresh copies when you restart it.

### Why detection reads balances instead of decoding instructions

A transaction's `meta` already carries pre/post SOL balances and pre/post
SPL token balances for every account involved — the same ground truth block
explorers use to show "+1,204,000 TOKEN / -1.02 SOL". Reading that instead
of hand-parsing pump.fun's raw instruction bytes is more robust: it doesn't
need to track pump.fun's exact instruction layout, and it can't be fooled by
a program upgrade that changes byte offsets. It does mean the reported SOL
size is *approximate* — it includes network fees and any one-time
associated-token-account rent, not just the trade itself.

### How live execution talks to pump.fun

There's no off-the-shelf SDK dependency here — `pumpfun_bot/pumpfun_program.py`
builds pump.fun's `buy`/`sell` instructions directly from its public,
on-chain program interface: PDA seeds (`"global"`, `"bonding-curve"`,
`"__event_authority"`), the constant-product bonding-curve formula, and
Anchor's standard `sha256("global:<name>")[:8]` instruction discriminators
(computed at runtime, not hardcoded, so it can't silently drift). PDA
derivation was cross-checked against pump.fun's known, publicly documented
mainnet addresses (see `tests/test_pumpfun_program.py`) — but the live buy/sell
path itself has **not** been exercised against mainnet from this sandboxed,
network-restricted dev environment. Treat `scripts/check_pumpfun_setup.py`
and a trivial-size first live trade as your real-world check before trusting
it with meaningful funds.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env` (see the "pump.fun wallet copy-trading bot" section at the
bottom of the file):
- Leave `PF_LIVE_TRADING=false` to run in **paper trading** (fully
  simulated, no funds at risk, no wallet required). This is the default and
  the recommended starting point.
- `SOLANA_RPC_URL` — a public RPC works for light testing but is rate-limited
  and unreliable; use a private RPC (Helius, QuickNode, Triton, etc.) for
  anything more serious.
- To go live later:
  - `SOLANA_PRIVATE_KEY` — your wallet's exported private key (base58, the
    format Phantom/Solflare give you) or a Solana CLI keypair JSON array
    pasted as one line. **Never commit this or paste it anywhere outside
    your local `.env`.**
  - Then set `PF_LIVE_TRADING=true`.

Edit `config/pumpfun_settings.yaml`:
- `wallets.watch` — **required**: add at least one Solana wallet address to
  copy trades from. The bot refuses to start with an empty list.
- Tune `copy.size_ratio`, `copy.max_sol_per_trade`, and the `risk.*` caps
  before running live. Start small.

## Running

```bash
# Sanity-check config, wallet, and RPC connectivity before running for real:
python scripts/check_pumpfun_setup.py

# Run the bot:
python -m pumpfun_bot.main
```

Stop any time with `Ctrl+C` — it finishes the current cycle and exits
cleanly.

## Running tests

```bash
python -m pytest tests/test_pumpfun_*.py
```

Covers bonding-curve math, PDA derivation (cross-checked against pump.fun's
known mainnet addresses), trade detection from canned transaction payloads,
copy-sizing/filter logic, and the risk manager — all pure logic, no network
calls.

## Safety notes

- **Start in paper mode** and watch `data/pumpfun_trades.csv` /
  `logs/pumpfun.log` for a while before considering live trading.
- **Start with a tiny `copy.max_sol_per_trade`** and tight `risk.*` caps in
  `config/pumpfun_settings.yaml` when you do go live.
- The bot enforces a **daily loss kill-switch** (`risk.max_daily_loss_sol`):
  once hit, it stops opening new positions until UTC midnight. It does not
  automatically close existing positions for you.
- `sendTransaction` only confirms the RPC *accepted* your transaction, not
  that it landed or succeeded on-chain — periodically reconcile against your
  actual wallet balance rather than trusting the bot's in-memory position
  tracking alone.
- Detected SOL trade sizes are approximate (they include network fees /
  one-time rent), which only affects copy *sizing*, not detection itself.
- A bonding curve that has "completed" (migrated off pump.fun, e.g. to a
  DEX) is skipped — this bot only trades the pump.fun bonding-curve phase.
- This code has not been run against the live Solana/pump.fun mainnet from
  this environment (no such network access here) — review it yourself, and
  verify with a trivial live trade before trusting it with real funds.

## Project layout

```
pumpfun_bot/
  config.py             # loads .env + config/pumpfun_settings.yaml
  rpc.py                  # minimal Solana JSON-RPC client
  pumpfun_program.py        # program constants, PDAs, bonding-curve math, instruction builders
  trade_detector.py           # wallet polling + balance-delta trade detection
  copy_engine.py                # sizing/filters -> CopySignal
  risk.py                        # per-mint position/exposure/loss limits
  execution.py                    # paper vs. live trade execution
  journal.py                       # CSV trade log
  wallet.py                         # loads a signing Keypair from .env
  main.py                            # the scan-detect-copy loop
config/pumpfun_settings.yaml    # watch list, sizing, risk parameters (no secrets)
scripts/check_pumpfun_setup.py    # pre-flight sanity check
tests/test_pumpfun_*.py             # pytest unit tests, no network required
```
