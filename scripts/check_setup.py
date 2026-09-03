"""Sanity-check your .env / config before running the bot live.

Usage: python scripts/check_setup.py
"""
from __future__ import annotations

import sys

from bot.config import load_settings


def main() -> int:
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    print("Configuration loaded OK.")
    print(f"  Mode:              {'LIVE' if settings.wallet.live_trading else 'PAPER (simulation)'}")
    print(f"  CLOB host:         {settings.wallet.clob_host}")
    print(f"  Chain id:          {settings.wallet.chain_id}")
    print(f"  Signature type:    {settings.wallet.signature_type}")
    print(f"  Funder address:    {settings.wallet.funder_address or '(not set)'}")
    print(f"  Private key set:   {'yes' if settings.wallet.private_key else 'no'}")
    print(f"  Polling interval:  {settings.polling_interval_seconds}s")
    print(f"  Arbitrage enabled: {settings.arbitrage.enabled}")
    print(f"  Threshold enabled: {settings.threshold.enabled}")
    print(f"  Max position:      ${settings.risk.max_position_usd}")
    print(f"  Max exposure:      ${settings.risk.max_total_exposure_usd}")
    print(f"  Max daily loss:    ${settings.risk.max_daily_loss_usd}")

    if settings.wallet.live_trading:
        print("\nAttempting to connect and derive API credentials (LIVE mode)...")
        try:
            from bot.client import build_client

            client = build_client(settings.wallet)
            print("[OK] Connected and authenticated with the Polymarket CLOB.")
            try:
                book = client.get_sampling_markets()
                n = len(book.get("data", [])) if isinstance(book, dict) else 0
                print(f"[OK] Fetched sampling markets ({n} returned).")
            except Exception as e:
                print(f"[WARN] Could not fetch sampling markets: {e}")
        except Exception as e:
            print(f"[FAIL] Could not connect/authenticate: {e}")
            return 1
    else:
        print("\nPaper trading mode — skipping live authentication check.")
        print("Set LIVE_TRADING=true in .env (with POLY_PRIVATE_KEY and")
        print("POLY_FUNDER_ADDRESS filled in) when you're ready to go live.")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
