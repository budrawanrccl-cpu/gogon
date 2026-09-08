"""Check what the wallet ACTUALLY holds on-chain right now, for every mint
ever seen in the trade journal — ground truth, independent of whether the
bot's/scripts' bookkeeping thinks a position is closed.

Why this exists: `filled=True` in data/pumpbot_trades.csv only means "the
transaction was submitted to the RPC without an error" (see
pumpbot/execution.py's _record_fill docstring) — it does NOT mean the
transaction actually confirmed on-chain, and a confirmed transaction can
still have its swap instruction fail while only the network fee gets
charged. scripts/list_open_positions.py's "open positions" view is built
from that same CSV and assumes every recorded SELL fully closed the
position, so it can say "no open positions" even when a sell never
actually landed. This script instead queries the real current token
balance for every mint via getTokenAccountsByOwner.

Usage:
    python scripts/check_wallet_holdings.py
"""
from __future__ import annotations

import csv
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pumpbot.config import load_settings
from pumpbot.solana_rpc import get_token_balance

TRADES_CSV = os.path.join(_ROOT, "data", "pumpbot_trades.csv")


def resolve_wallet_address(wallet_cfg) -> str | None:
    """Checking token balances is read-only and only needs the wallet's
    PUBLIC address — never the private key. Prefer SOLANA_WALLET_ADDRESS
    from .env; fall back to deriving it from SOLANA_PRIVATE_KEY only if
    that's the only thing set (same fallback order as
    scripts/pumpbot_dashboard.py's _resolve_wallet_address).
    """
    env_address = os.environ.get("SOLANA_WALLET_ADDRESS")
    if env_address:
        return env_address.strip()

    if not wallet_cfg.private_key:
        return None

    try:
        from pumpbot.wallet import load_keypair

        return str(load_keypair(wallet_cfg).pubkey())
    except Exception:
        return None


def load_trades() -> list[dict]:
    if not os.path.exists(TRADES_CSV):
        return []
    with open(TRADES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    wallet_address = resolve_wallet_address(settings.wallet)
    if not wallet_address:
        print(
            "[FAIL] Could not determine which wallet to check — set SOLANA_WALLET_ADDRESS "
            "(public address, no private key needed) or SOLANA_PRIVATE_KEY in .env."
        )
        return 1

    rpc_url = settings.wallet.rpc_url
    print(f"Wallet: {wallet_address}\n")

    rows = load_trades()
    if not rows:
        print(f"Tidak ada data trade di {TRADES_CSV}.")
        return 0

    # Unique mints in journal order, keeping the last-seen symbol for each.
    mints: dict[str, str] = {}
    for r in rows:
        mints[r["mint"]] = r.get("symbol") or mints.get(r["mint"], "")

    print(f"Mengecek saldo token on-chain untuk {len(mints)} mint (mohon tunggu)...\n")

    still_held = []
    errors = []
    for mint, symbol in mints.items():
        label = symbol or mint[:8] + "…"
        try:
            balance = get_token_balance(rpc_url, wallet_address, mint)
        except Exception as e:
            errors.append((label, mint, str(e)))
            print(f"  {label:<14} [ERROR] {e}")
            continue

        if balance > 0:
            still_held.append((label, mint, balance))
            print(f"  {label:<14} {balance:,.4f} token  <-- MASIH ADA DI WALLET")
        else:
            print(f"  {label:<14} 0 (kosong)")

        time.sleep(0.4)  # be gentle on the RPC endpoint — the public default is easily rate-limited

    print("\n=== Ringkasan ===")
    if still_held:
        print(f"{len(still_held)} mint masih punya saldo token di wallet — belum benar-benar terjual:\n")
        for label, mint, balance in still_held:
            print(f"  {label:<14} mint={mint}  balance={balance:,.4f}")
        print("\nJual ulang dengan:")
        for _, mint, _ in still_held:
            print(f"  python scripts/sell_token.py {mint}")
    else:
        print("Tidak ada token tersisa di wallet untuk mint manapun di journal — semua benar-benar kosong on-chain.")

    if errors:
        print(f"\n({len(errors)} mint gagal dicek karena error RPC — lihat di atas.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
