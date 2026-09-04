"""Sanity-check your .env / config before running the pump.fun bot live.

Usage: python scripts/check_pumpbot_setup.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pumpbot.config import load_settings


def main() -> int:
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    print("Configuration loaded OK.")
    print(f"  Mode:                  {'LIVE' if settings.wallet.live_trading else 'PAPER (simulation)'}")
    print(f"  RPC URL:               {settings.wallet.rpc_url}")
    print(f"  Private key set:       {'yes' if settings.wallet.private_key else 'no'}")
    print(f"  PumpPortal WS:         {settings.data.ws_url}")
    print(f"  PumpPortal trade API:  {settings.data.trade_api_url}")
    print(f"  Polling interval:      {settings.polling_interval_seconds}s")
    print(f"  Entry window:          {settings.filters.min_token_age_seconds}s - {settings.filters.max_token_age_seconds}s")
    print(f"  Min unique buyers:     {settings.filters.min_unique_buyers}")
    print(f"  Max position:          {settings.risk.max_position_sol} SOL")
    print(f"  Max exposure:          {settings.risk.max_total_exposure_sol} SOL")
    print(f"  Max daily loss:        {settings.risk.max_daily_loss_sol} SOL")
    print(f"  Take profit / stop:    +{settings.risk.take_profit_pct:.0%} / -{settings.risk.stop_loss_pct:.0%}")

    if settings.wallet.live_trading:
        print("\nAttempting to load signing wallet and reach your RPC (LIVE mode)...")
        try:
            from pumpbot.wallet import load_keypair

            keypair = load_keypair(settings.wallet)
            print(f"[OK] Signing wallet loaded: {keypair.pubkey()}")
        except Exception as e:
            print(f"[FAIL] Could not load signing wallet: {e}")
            return 1

        try:
            from solana.rpc.api import Client as SolanaClient

            rpc = SolanaClient(settings.wallet.rpc_url)
            balance = rpc.get_balance(keypair.pubkey()).value
            print(f"[OK] RPC reachable. Wallet balance: {balance / 1_000_000_000:.6f} SOL")
            if balance == 0:
                print("[WARN] Wallet balance is 0 — fund it before going live.")
        except Exception as e:
            print(f"[WARN] Could not fetch wallet balance from RPC: {e}")
    else:
        print("\nPaper trading mode — skipping live wallet/RPC check.")
        print("Set LIVE_TRADING=true in .env (with SOLANA_PRIVATE_KEY filled in and")
        print("a funded wallet) when you're ready to go live. Read the README risks")
        print("section first — most pump.fun tokens go to zero.")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
