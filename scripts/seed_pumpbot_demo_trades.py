"""Fill data/pumpbot_trades.csv with realistic-looking sample trades, purely
so you can preview what the dashboard (scripts/pumpbot_dashboard.py) looks
like once the bot has actually traded. This writes FAKE data — it does not
touch pump.fun, PumpPortal, your wallet, or send any real transaction.

Usage:
    python scripts/seed_pumpbot_demo_trades.py

Any existing data/pumpbot_trades.csv is backed up first (never overwritten
silently). To go back to your real (empty or in-progress) trade log
afterwards, see the instructions this script prints at the end.
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pumpbot.journal import FIELDS  # noqa: E402

TRADES_CSV = os.path.join(_ROOT, "data", "pumpbot_trades.csv")


def demo_rows() -> list[dict]:
    now = datetime.now(timezone.utc)

    def t(minutes_ago: float) -> str:
        return (now - timedelta(minutes=minutes_ago)).isoformat()

    rows = [
        # --- Winner: bought on momentum, hit take-profit ---
        dict(timestamp=t(48), mode="paper", strategy="momentum", mint="Do11arDemoMint1111111111111111111111111",
             symbol="DOGO", side="BUY", reference_price_sol="0.0000210000",
             size_sol="0.050000", filled="True", tx_signature="",
             reason="age=24s buyers=11 buy_vol=4.10SOL mcap=14.3SOL"),
        dict(timestamp=t(31), mode="paper", strategy="exit", mint="Do11arDemoMint1111111111111111111111111",
             symbol="DOGO", side="SELL", reference_price_sol="0.0000334950",
             size_sol="0.079750", filled="True", tx_signature="",
             reason="take_profit hit: +59.5%"),

        # --- Loser: bought on momentum, hit stop-loss ---
        dict(timestamp=t(40), mode="paper", strategy="momentum", mint="Cat22DemoMint2222222222222222222222222",
             symbol="MEOW", side="BUY", reference_price_sol="0.0000098000",
             size_sol="0.050000", filled="True", tx_signature="",
             reason="age=31s buyers=9 buy_vol=3.60SOL mcap=9.8SOL"),
        dict(timestamp=t(33), mode="paper", strategy="exit", mint="Cat22DemoMint2222222222222222222222222",
             symbol="MEOW", side="SELL", reference_price_sol="0.0000073500",
             size_sol="0.037500", filled="True", tx_signature="",
             reason="stop_loss hit: -25.0%"),

        # --- Winner, closed via trailing stop after a bigger run-up ---
        dict(timestamp=t(26), mode="paper", strategy="momentum", mint="Fr0gDemoMint3333333333333333333333333",
             symbol="FROG", side="BUY", reference_price_sol="0.0000450000",
             size_sol="0.050000", filled="True", tx_signature="",
             reason="age=20s buyers=14 buy_vol=6.20SOL mcap=22.1SOL"),
        dict(timestamp=t(12), mode="paper", strategy="exit", mint="Fr0gDemoMint3333333333333333333333333",
             symbol="FROG", side="SELL", reference_price_sol="0.0000610000",
             size_sol="0.067778", filled="True", tx_signature="",
             reason="trailing_stop hit: -15.0% from peak"),

        # --- Still-open position (no exit yet) ---
        dict(timestamp=t(6), mode="paper", strategy="momentum", mint="Pnk5DemoMint4444444444444444444444444",
             symbol="PNKY", side="BUY", reference_price_sol="0.0000175000",
             size_sol="0.050000", filled="True", tx_signature="",
             reason="age=22s buyers=8 buy_vol=3.05SOL mcap=11.0SOL"),

        # --- One skipped BUY signal, for realism (risk cap hit) ---
        dict(timestamp=t(3), mode="paper", strategy="momentum", mint="Skip6DemoMint555555555555555555555555",
             symbol="SKIP", side="BUY", reference_price_sol="0.0000082000",
             size_sol="0.050000", filled="False", tx_signature="",
             reason="skipped: would exceed max_total_exposure_sol"),
    ]
    return rows


def main() -> int:
    if os.path.exists(TRADES_CSV):
        backup_path = TRADES_CSV + f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        os.rename(TRADES_CSV, backup_path)
        print(f"Existing data/pumpbot_trades.csv backed up to: {backup_path}")

    os.makedirs(os.path.dirname(TRADES_CSV), exist_ok=True)
    with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in demo_rows():
            writer.writerow(row)

    print(f"Wrote {len(demo_rows())} demo trade rows to data/pumpbot_trades.csv")
    print()
    print("Now open/refresh the dashboard (python scripts/pumpbot_dashboard.py) to see it.")
    print()
    print("This is FAKE data for preview only — no real transactions were sent.")
    print("To go back to your real trade log:")
    print("  1. Delete data/pumpbot_trades.csv (the bot will recreate an empty one), or")
    print("  2. Restore your backup: rename the data/pumpbot_trades.csv.bak.* file back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
