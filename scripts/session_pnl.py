"""Compute exact realized P&L for this trading session, straight from
on-chain data.

Why this exists: data/pumpbot_trades.csv logs `size_sol` as 0.0 for any
manual sell done via scripts/sell_token.py (it sells "100% of whatever
the wallet holds" without knowing the actual proceeds in advance — see
that script's docstring), so the CSV alone can't total profit/loss once
manual sells are involved. This script instead looks up each recorded
transaction on-chain and reads exactly how much the wallet's SOL balance
changed in that transaction (via getTransaction's pre/postBalances,
which already nets out the network/priority fee) — summing that gives an
exact total, and per-mint, realized P&L without needing a "balance
before/after" snapshot.

Usage:
    python scripts/session_pnl.py
"""
from __future__ import annotations

import csv
import os
import sys
import time
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pumpbot.config import load_settings
from pumpbot.solana_rpc import get_transaction_sol_delta

TRADES_CSV = os.path.join(_ROOT, "data", "pumpbot_trades.csv")


def resolve_wallet_address(wallet_cfg) -> str | None:
    """Reading transaction balance deltas is read-only and only needs the
    wallet's PUBLIC address — never the private key. Prefer
    SOLANA_WALLET_ADDRESS from .env; fall back to deriving it from
    SOLANA_PRIVATE_KEY only if that's the only thing set (same fallback
    order as scripts/pumpbot_dashboard.py's _resolve_wallet_address).
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
    filled_rows = [
        r for r in rows
        if r.get("filled", "").strip().lower() == "true" and r.get("tx_signature", "").strip()
    ]
    if not filled_rows:
        print("Tidak ada trade dengan tx_signature di data/pumpbot_trades.csv.")
        return 0

    per_mint: dict[str, dict] = defaultdict(lambda: {"symbol": "", "delta": 0.0, "trades": 0})
    total_delta = 0.0
    errors: list[str] = []

    print(f"Mengecek {len(filled_rows)} transaksi on-chain (mohon tunggu)...\n")
    for r in filled_rows:
        sig = r["tx_signature"].strip()
        mint = r["mint"]
        symbol = r["symbol"] or mint[:8] + "…"
        side = r["side"]
        try:
            delta = get_transaction_sol_delta(rpc_url, sig, wallet_address)
        except Exception as e:
            errors.append(f"  {side:<4} {symbol:<12} sig={sig[:12]}…  [ERROR] {e}")
            continue

        per_mint[mint]["symbol"] = symbol
        per_mint[mint]["delta"] += delta
        per_mint[mint]["trades"] += 1
        total_delta += delta
        sign = "+" if delta >= 0 else ""
        print(f"  {side:<4} {symbol:<12} {sign}{delta:.6f} SOL   (tx {sig[:12]}…)")

        time.sleep(0.4)  # be gentle on the RPC endpoint — the public default is easily rate-limited

    if errors:
        print("\nBeberapa transaksi gagal dicek (RPC error / belum final / dsb):")
        for line in errors:
            print(line)

    print("\n--- Ringkasan per token ---")
    for mint, d in sorted(per_mint.items(), key=lambda kv: kv[1]["delta"]):
        sign = "+" if d["delta"] >= 0 else ""
        print(f"  {d['symbol']:<12} {sign}{d['delta']:.6f} SOL  ({d['trades']} tx)")

    sign = "+" if total_delta >= 0 else ""
    print(f"\n=== TOTAL P&L sesi (net semua fee jaringan): {sign}{total_delta:.6f} SOL ===")
    if errors:
        print("(Catatan: total di atas TIDAK termasuk transaksi yang gagal dicek — lihat daftar error di atas.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
