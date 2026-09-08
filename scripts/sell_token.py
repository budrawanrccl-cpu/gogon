"""Manually sell 100% of your wallet's holdings of a specific token.

Why this exists: pumpbot does not persist open positions across restarts
(RiskManager starts empty every time `python -m pumpbot.main` runs — see
README). If a SELL attempt failed (e.g. the BlockhashNotFound issue fixed
elsewhere in this repo) and the bot was then restarted before it
succeeded, the bot "forgets" it ever held that token — even though the
tokens are still sitting in your wallet on-chain. This script sells a
token by mint address directly, independent of the bot's own tracking,
using the exact same PumpPortal Local Transaction API path pumpbot uses
for live trades (fetch unsigned tx -> sign locally -> submit, with
skipPreflight + retries).

Usage:
    python scripts/sell_token.py <mint_address>
    python scripts/sell_token.py <mint_address> --yes   # skip confirmation

Requires LIVE_TRADING=true and SOLANA_PRIVATE_KEY set in .env — this sends
a REAL transaction selling 100% of whatever your wallet actually holds
for that mint. There is no partial-sell option here; if you need that,
use Phantom/Solflare's built-in swap feature instead.
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pumpbot.config import load_settings
from pumpbot.execution import OrderExecutor
from pumpbot.journal import TradeJournal
from pumpbot.risk import RiskManager
from pumpbot.strategies.base import Signal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mint", help="Token mint address to sell 100%% of")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    if not settings.wallet.live_trading:
        print("[FAIL] LIVE_TRADING is not 'true' in .env — this script only sends real transactions.")
        print("       Set LIVE_TRADING=true first (same switch the bot itself uses).")
        return 1

    if not settings.wallet.private_key:
        print("[FAIL] SOLANA_PRIVATE_KEY is not set in .env.")
        return 1

    from pumpbot.wallet import load_keypair

    try:
        keypair = load_keypair(settings.wallet)
    except Exception as e:
        print(f"[FAIL] Could not load signing wallet: {e}")
        return 1

    print(f"Wallet:        {keypair.pubkey()}")
    print(f"Mint to sell:  {args.mint}")
    print("Amount:        100% of whatever this wallet actually holds for that mint")
    print()

    if not args.yes:
        confirm = input("Kirim transaksi JUAL sungguhan sekarang? Ketik 'yes' untuk lanjut: ")
        if confirm.strip().lower() != "yes":
            print("Dibatalkan — tidak ada transaksi dikirim.")
            return 0

    risk = RiskManager(settings.risk)
    journal = TradeJournal()
    executor = OrderExecutor(
        risk=risk,
        journal=journal,
        live=True,
        data_cfg=settings.data,
        trading_cfg=settings.trading,
        wallet_cfg=settings.wallet,
        keypair=keypair,
    )

    signal = Signal(
        strategy="manual",
        mint=args.mint,
        symbol="",
        side="SELL",
        reference_price_sol=0.0,  # unused for the real on-chain sell; PumpPortal sells 100% of actual holdings regardless
        size_sol=0.0,
        reason="manual sell via scripts/sell_token.py",
    )

    print("\nMengirim transaksi jual...")
    filled = executor.execute(signal)

    if filled:
        print("\n[OK] Transaksi berhasil dikirim. Cek data/pumpbot_trades.csv atau logs/pumpbot.log untuk tx signature-nya,")
        print("     lalu verifikasi di https://solscan.io dengan tx signature itu.")
        return 0
    else:
        print("\n[FAIL] Gagal setelah beberapa percobaan. Cek logs/pumpbot.log untuk detail errornya:")
        print("       Select-String -Path logs\\pumpbot.log -Pattern 'Failed to|ERROR' | Select-Object -Last 20")
        return 1


if __name__ == "__main__":
    sys.exit(main())
