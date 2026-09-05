"""Sanity-check your .env / config before running the pump.fun bot live.

Usage: python scripts/check_pumpfun_setup.py
"""
from __future__ import annotations

import os
import sys

# Allow running this script directly (e.g. `python scripts/check_pumpfun_setup.py`)
# by making sure the project root (containing the `pumpfun_bot` package) is on
# sys.path, regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pumpfun_bot.config import load_settings


def main() -> int:
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    print("Configuration loaded OK.")
    print(f"  Mode:                {'LIVE' if settings.wallet.live_trading else 'PAPER (simulation)'}")
    print(f"  RPC URL:             {settings.wallet.rpc_url}")
    print(f"  Private key set:     {'yes' if settings.wallet.private_key else 'no'}")
    print(f"  Wallets watched:     {len(settings.wallets_to_watch.watch)}")
    for addr in settings.wallets_to_watch.watch:
        print(f"    - {addr}")
    print(f"  Polling interval:    {settings.polling_interval_seconds}s")
    print(f"  Copy size ratio:     {settings.copy.size_ratio:.0%}")
    print(f"  Max SOL/trade:       {settings.copy.max_sol_per_trade}")
    print(f"  Mirror sells:        {settings.copy.mirror_sells}")
    print(f"  Max position:        {settings.risk.max_position_sol} SOL")
    print(f"  Max exposure:        {settings.risk.max_total_exposure_sol} SOL")
    print(f"  Max daily loss:      {settings.risk.max_daily_loss_sol} SOL")
    print(f"  Slippage tolerance:  {settings.execution.slippage_bps} bps")

    if settings.wallet.live_trading:
        print("\nAttempting to connect and load the signing wallet (LIVE mode)...")
        try:
            from pumpfun_bot.rpc import SolanaRpcClient
            from pumpfun_bot.wallet import load_keypair

            keypair = load_keypair(settings.wallet.private_key)
            print(f"[OK] Loaded signing keypair for {keypair.pubkey()}")

            rpc = SolanaRpcClient(settings.wallet.rpc_url)
            try:
                lamports = rpc.get_balance_lamports(str(keypair.pubkey()))
                print(f"[OK] Wallet SOL balance: {lamports / 1_000_000_000:.6f} SOL")
            except Exception as e:
                print(f"[WARN] Could not fetch wallet balance: {e}")
        except Exception as e:
            print(f"[FAIL] Could not load wallet / connect to RPC: {e}")
            return 1
    else:
        print("\nPaper trading mode — skipping live wallet check.")
        print("Set PF_LIVE_TRADING=true in .env (with SOLANA_PRIVATE_KEY filled")
        print("in) when you're ready to copy trades with real SOL.")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
