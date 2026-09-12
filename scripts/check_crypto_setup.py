"""Sanity-check your .env / config before running the crypto bot live.

Usage: python scripts/check_crypto_setup.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from crypto_bot.config import load_settings


def main() -> int:
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    print("Configuration loaded OK.")
    print(f"  Mode:                {'LIVE' if settings.exchange.live_trading else 'PAPER (simulation)'}")
    print(f"  Exchange:            {settings.exchange.exchange_id}")
    print(f"  Testnet/sandbox:     {settings.exchange.testnet}")
    print(f"  Symbol:              {settings.symbol}")
    print(f"  Timeframe:           {settings.timeframe}")
    print(f"  Polling interval:    {settings.polling_interval_seconds}s")
    print(f"  API key set:         {'yes' if settings.exchange.api_key else 'no'}")
    print(
        f"  Strategy:            donchian(entry={settings.strategy.entry_period}, "
        f"exit={settings.strategy.exit_period}, atr={settings.strategy.atr_period}, "
        f"atr_mult={settings.strategy.atr_stop_mult}, trend_ema={settings.strategy.trend_filter_ema_period})"
    )
    print(f"  Starting equity:     ${settings.risk.starting_equity_usd:.2f}")
    print(f"  Risk per trade:      {settings.risk.risk_per_trade_pct:.1%}")
    print(f"  Max daily loss:      {settings.risk.max_daily_loss_pct:.1%}")
    print(f"  Max drawdown:        {settings.risk.max_drawdown_pct:.1%}")

    print("\nAttempting to connect to the exchange...")
    try:
        from crypto_bot.exchange import build_exchange, fetch_last_price

        exchange = build_exchange(settings.exchange)
        print(f"[OK] Connected to {settings.exchange.exchange_id} "
              f"({'testnet' if settings.exchange.testnet else 'MAINNET — real market'}).")
        try:
            price = fetch_last_price(exchange, settings.symbol)
            print(f"[OK] Last price for {settings.symbol}: {price}")
        except Exception as e:
            print(f"[WARN] Could not fetch a ticker for {settings.symbol}: {e}")
    except Exception as e:
        print(f"[FAIL] Could not connect to the exchange: {e}")
        return 1

    if settings.exchange.live_trading:
        print(
            "\n*** LIVE_TRADING is ON. *** Real orders will be placed with real funds "
            "when you run `python -m crypto_bot.main`. Make sure you've backtested "
            "(scripts/run_crypto_backtest.py) and paper-traded first."
        )
    else:
        print(
            "\nPaper trading mode — the bot will simulate fills using live prices "
            "but never call the exchange's order-placement endpoints."
        )

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
