"""Fetch historical OHLCV data (with local caching) and backtest the
Donchian breakout strategy against it.

Usage:
    python scripts/run_crypto_backtest.py
    python scripts/run_crypto_backtest.py --symbol ETH/USDT --timeframe 1h --days 365
    python scripts/run_crypto_backtest.py --refresh   # ignore cache, re-download

Strategy and risk parameters come from config/crypto_settings.yaml (the same
file the live/paper bot reads) unless overridden on the command line, so a
backtest here is testing the same thing that would actually trade.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from crypto_bot import data
from crypto_bot.backtest import run_backtest
from crypto_bot.config import load_settings
from crypto_bot.exchange import build_exchange, fetch_ohlcv_history


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbol", default=None, help="Override symbol from config, e.g. ETH/USDT")
    p.add_argument("--timeframe", default=None, help="Override timeframe from config, e.g. 1h, 4h, 1d")
    p.add_argument("--days", type=int, default=365, help="How many days of history to test (default: 365)")
    p.add_argument("--refresh", action="store_true", help="Ignore the local cache and re-download from the exchange")
    p.add_argument(
        "--config",
        default=None,
        help="Path to a YAML config (default: CRYPTO_CONFIG_PATH env var or config/crypto_settings.yaml)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(config_path=args.config)

    symbol = args.symbol or settings.symbol
    timeframe = args.timeframe or settings.timeframe

    cache_file = data.cache_path(symbol, timeframe)
    bars = None
    if not args.refresh and os.path.exists(cache_file):
        try:
            bars = data.load_bars(cache_file)
        except Exception as e:
            print(f"[WARN] Could not read cache {cache_file}: {e}; will re-download")
            bars = None

    since_ms = int((time.time() - args.days * 86400) * 1000)
    need_download = bars is None or not bars or bars[0].timestamp > since_ms + 3 * 86400_000

    if need_download:
        print(f"Downloading {symbol} {timeframe} history from Binance (~{args.days} days)...")
        exchange = build_exchange(settings.exchange)
        bars = fetch_ohlcv_history(exchange, symbol, timeframe, since_ms=since_ms)
        data.save_bars(bars, cache_file)
        print(f"Cached {len(bars)} bars to {cache_file}")
    else:
        bars = [b for b in bars if b.timestamp >= since_ms]
        print(f"Using {len(bars)} cached bars from {cache_file} (pass --refresh to re-download)")

    if len(bars) < 50:
        print("[FAIL] Not enough bars to backtest meaningfully. Try a longer --days window.")
        return 1

    from crypto_bot.strategy import DonchianBreakoutStrategy

    strategy = DonchianBreakoutStrategy(settings.strategy)
    result = run_backtest(symbol, bars, strategy, settings.risk)

    print()
    print(result.summary())
    print()
    print(f"Bars tested:          {len(bars)}")
    print(f"Period:               {_fmt_ts(bars[0].timestamp)} -> {_fmt_ts(bars[-1].timestamp)}")
    print(f"Strategy params:      entry={settings.strategy.entry_period} exit={settings.strategy.exit_period} "
          f"atr={settings.strategy.atr_period} atr_mult={settings.strategy.atr_stop_mult} "
          f"trend_ema={settings.strategy.trend_filter_ema_period}")
    print(f"Risk per trade:       {settings.risk.risk_per_trade_pct:.1%} of equity")
    print(f"Fee assumption:       {settings.risk.fee_pct:.2%} per side")

    if result.trades:
        wins = [t for t in result.trades if t.pnl_usd > 0]
        losses = [t for t in result.trades if t.pnl_usd <= 0]
        print(f"Winning trades:       {len(wins)}  (avg {_avg_pct(wins):+.2%})")
        print(f"Losing trades:        {len(losses)}  (avg {_avg_pct(losses):+.2%})")

    print()
    print(
        "Reminder: this is one backtest on one symbol/timeframe/parameter set. "
        "Try several symbols and at least a couple of years of data before trusting "
        "the numbers, and paper-trade (python -m crypto_bot.main) before using real funds."
    )
    return 0


def _fmt_ts(ms: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")


def _avg_pct(trades) -> float:
    if not trades:
        return 0.0
    return sum(t.return_pct for t in trades) / len(trades)


if __name__ == "__main__":
    sys.exit(main())
