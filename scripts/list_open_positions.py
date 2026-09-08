"""List currently-open positions with their FULL mint addresses, and print
ready-to-copy `python scripts/sell_token.py <mint>` commands for each one.

Why this exists: the dashboard's "Posisi Terbuka" table truncates mint
addresses for display (e.g. "9JnRu4L9…"), so copying a real address out of
it means hovering for a tooltip or reading the raw CSV by hand. This script
does the same open-position reconstruction the dashboard does (replaying
data/pumpbot_trades.csv fills with average-cost accounting — see
scripts/pumpbot_dashboard.py's build_summary()) and prints the untruncated
addresses directly, ready to paste into a terminal.

Usage:
    python scripts/list_open_positions.py
"""
from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

TRADES_CSV = os.path.join(_ROOT, "data", "pumpbot_trades.csv")


def load_trades() -> list[dict]:
    if not os.path.exists(TRADES_CSV):
        return []
    with open(TRADES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def compute_open_positions(rows: list[dict]) -> list[dict]:
    filled_rows = [r for r in rows if r.get("filled", "").strip().lower() == "true"]

    # Same average-cost replay as scripts/pumpbot_dashboard.py build_summary()
    # and pumpbot/risk.py — kept in sync deliberately so this list matches
    # what the dashboard shows.
    positions: dict[str, dict] = defaultdict(
        lambda: {"token_amount": 0.0, "cost_sol": 0.0, "symbol": ""}
    )

    for r in sorted(filled_rows, key=lambda r: r["timestamp"]):
        mint = r["mint"]
        price = float(r["reference_price_sol"]) if r["reference_price_sol"] else 0.0
        sol = float(r["size_sol"])
        token_amount = sol / price if price > 0 else 0.0
        pos = positions[mint]
        pos["symbol"] = r["symbol"]

        if r["side"] == "BUY":
            pos["token_amount"] += token_amount
            pos["cost_sol"] += sol
        else:  # SELL — the bot always sells the full remaining position
            sell_amount = min(token_amount, pos["token_amount"]) or pos["token_amount"]
            avg_price = pos["cost_sol"] / pos["token_amount"] if pos["token_amount"] else 0.0
            cost_basis = avg_price * sell_amount
            pos["token_amount"] -= sell_amount
            pos["cost_sol"] -= cost_basis

    open_positions = [
        {"mint": mint, **p} for mint, p in positions.items() if p["token_amount"] > 1e-9
    ]
    return sorted(open_positions, key=lambda p: -p["cost_sol"])


def main() -> int:
    rows = load_trades()
    if not rows:
        print(f"[INFO] Tidak ada data trade di {TRADES_CSV} — belum ada posisi.")
        return 0

    open_positions = compute_open_positions(rows)
    if not open_positions:
        print("Tidak ada posisi terbuka saat ini.")
        return 0

    print(f"Ditemukan {len(open_positions)} posisi terbuka:\n")
    for p in open_positions:
        label = p["symbol"] or p["mint"]
        print(f"  {label:<12} mint={p['mint']}  cost={p['cost_sol']:.4f} SOL")

    print("\nPerintah jual (copy-paste satu per satu, tunggu selesai sebelum lanjut ke berikutnya):\n")
    for p in open_positions:
        print(f"python scripts/sell_token.py {p['mint']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
