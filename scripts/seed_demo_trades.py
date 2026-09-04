"""Fill data/trades.csv with realistic-looking sample trades, purely so you
can preview what the dashboard (scripts/dashboard.py) looks like once the
bot has actually traded. This writes FAKE data — it does not touch
Polymarket, your wallet, or place any real orders.

Usage:
    python scripts/seed_demo_trades.py

Any existing data/trades.csv is backed up first (never overwritten silently).
To go back to your real (empty or in-progress) trade log afterwards, see the
instructions this script prints at the end.
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bot.journal import FIELDS  # noqa: E402

TRADES_CSV = os.path.join(_ROOT, "data", "trades.csv")


def demo_rows() -> list[dict]:
    now = datetime.now(timezone.utc)

    def t(minutes_ago: float) -> str:
        return (now - timedelta(minutes=minutes_ago)).isoformat()

    rows = [
        # --- Arbitrage: 3 completed pairs across 3 markets ---
        dict(timestamp=t(42), mode="paper", strategy="arbitrage", market_id="0xabc111",
             token_id="tok_yes_1", outcome="YES", side="BUY", price="0.4700",
             size_shares="12.5000", size_usd="5.8750", filled="True", group_id="grp-1",
             reason="combined ask 0.9600 < 1.0 - 0.0050; edge=0.0350"),
        dict(timestamp=t(42), mode="paper", strategy="arbitrage", market_id="0xabc111",
             token_id="tok_no_1", outcome="NO", side="BUY", price="0.4900",
             size_shares="12.5000", size_usd="6.1250", filled="True", group_id="grp-1",
             reason="combined ask 0.9600 < 1.0 - 0.0050; edge=0.0350"),

        dict(timestamp=t(31), mode="paper", strategy="arbitrage", market_id="0xdef222",
             token_id="tok_yes_2", outcome="YES", side="BUY", price="0.5300",
             size_shares="9.0000", size_usd="4.7700", filled="True", group_id="grp-2",
             reason="combined ask 0.9750 < 1.0 - 0.0050; edge=0.0200"),
        dict(timestamp=t(31), mode="paper", strategy="arbitrage", market_id="0xdef222",
             token_id="tok_no_2", outcome="NO", side="BUY", price="0.4450",
             size_shares="9.0000", size_usd="4.0050", filled="True", group_id="grp-2",
             reason="combined ask 0.9750 < 1.0 - 0.0050; edge=0.0200"),

        # --- Threshold: one closed round-trip (realized profit) ---
        dict(timestamp=t(25), mode="paper", strategy="threshold", market_id="0xghi333",
             token_id="tok_yes_3", outcome="YES", side="BUY", price="0.3000",
             size_shares="15.0000", size_usd="4.5000", filled="True", group_id="",
             reason="mid 0.300 is 12.4% below 20-tick avg 0.342"),
        dict(timestamp=t(14), mode="paper", strategy="threshold", market_id="0xghi333",
             token_id="tok_yes_3", outcome="YES", side="SELL", price="0.3800",
             size_shares="15.0000", size_usd="5.7000", filled="True", group_id="",
             reason="mid 0.380 is 11.1% above avg 0.342; closing"),

        # --- Threshold: one still-open position ---
        dict(timestamp=t(9), mode="paper", strategy="threshold", market_id="0xjkl444",
             token_id="tok_no_4", outcome="NO", side="BUY", price="0.2200",
             size_shares="20.0000", size_usd="4.4000", filled="True", group_id="",
             reason="mid 0.220 is 9.8% below 20-tick avg 0.244"),

        # --- One more arbitrage pair, most recent ---
        dict(timestamp=t(4), mode="paper", strategy="arbitrage", market_id="0xmno555",
             token_id="tok_yes_5", outcome="YES", side="BUY", price="0.5100",
             size_shares="7.0000", size_usd="3.5700", filled="True", group_id="grp-3",
             reason="combined ask 0.9700 < 1.0 - 0.0050; edge=0.0250"),
        dict(timestamp=t(4), mode="paper", strategy="arbitrage", market_id="0xmno555",
             token_id="tok_no_5", outcome="NO", side="BUY", price="0.4600",
             size_shares="7.0000", size_usd="3.2200", filled="True", group_id="grp-3",
             reason="combined ask 0.9700 < 1.0 - 0.0050; edge=0.0250"),

        # --- One skipped signal, for realism (risk cap hit) ---
        dict(timestamp=t(2), mode="paper", strategy="arbitrage", market_id="0xpqr666",
             token_id="tok_yes_6", outcome="YES", side="BUY", price="0.5000",
             size_shares="10.0000", size_usd="5.0000", filled="False", group_id="grp-4",
             reason="skipped: would exceed max_total_exposure_usd"),
    ]
    return rows


def main() -> int:
    if os.path.exists(TRADES_CSV):
        backup_path = TRADES_CSV + f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        os.rename(TRADES_CSV, backup_path)
        print(f"Existing data/trades.csv backed up to: {backup_path}")

    os.makedirs(os.path.dirname(TRADES_CSV), exist_ok=True)
    with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in demo_rows():
            writer.writerow(row)

    print(f"Wrote {len(demo_rows())} demo trade rows to data/trades.csv")
    print()
    print("Now open/refresh the dashboard (python scripts/dashboard.py) to see it.")
    print()
    print("This is FAKE data for preview only — no real orders were placed.")
    print("To go back to your real trade log:")
    print("  1. Delete data/trades.csv (the bot will recreate an empty one), or")
    print("  2. Restore your backup: rename the data/trades.csv.bak.* file back to data/trades.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
