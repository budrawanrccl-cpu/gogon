"""Sanity-check your funding-bot .env / config before running it live.

Usage: python scripts/check_funding_setup.py
"""
from __future__ import annotations

import os
import sys

# Allow running this script directly by making sure the project root
# (containing the `funding_bot` package) is on sys.path.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from funding_bot.config import load_settings


def main() -> int:
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    print("Configuration loaded OK.")
    print(f"  Mode:                 {'LIVE' if settings.exchange.live_trading else 'PAPER (simulation)'}")
    print(f"  Testnet:              {settings.exchange.testnet}")
    print(f"  API key set:          {'yes' if settings.exchange.api_key else 'no'}")
    print(f"  Polling interval:     {settings.polling_interval_seconds}s")
    print(f"  Funding arb enabled:  {settings.funding_arbitrage.enabled}")
    print(f"  Symbol whitelist:     {settings.symbols.whitelist or '(auto-discover)'}")
    print(f"  Min funding APR:      {settings.funding_arbitrage.min_funding_rate_apr:.1%}")
    print(f"  Exit funding APR:     {settings.funding_arbitrage.exit_funding_rate_apr:.1%}")
    print(f"  Max position:         ${settings.risk.max_position_usd}")
    print(f"  Max exposure:         ${settings.risk.max_total_exposure_usd}")
    print(f"  Max daily loss:       ${settings.risk.max_daily_loss_usd}")

    print("\nAttempting to connect to Binance (public market-data endpoints)...")
    try:
        from funding_bot.client import build_clients
        from funding_bot.market_data import discover_symbols

        spot_client, futures_client = build_clients(settings.exchange)
        print("[OK] Connected to Binance spot + futures markets.")

        symbols = settings.symbols.whitelist or discover_symbols(futures_client, settings.symbols)
        print(f"[OK] Symbols to scan: {symbols}")
    except Exception as e:
        print(f"[FAIL] Could not connect to Binance: {e}")
        return 1

    if settings.exchange.live_trading:
        print("\n*** LIVE TRADING is enabled. ***")
        print("This script does not place any orders, but the bot will as soon as you run it.")
    else:
        print("\nPaper trading mode — no real orders will ever be sent.")
        print("Set FUNDING_LIVE_TRADING=true in .env (with BINANCE_API_KEY/SECRET filled in)")
        print("when you're ready to go live. Try BINANCE_TESTNET=true first.")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
