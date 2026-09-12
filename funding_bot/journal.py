"""CSV trade journal — an audit trail of every leg fill and funding
settlement, mirroring `bot/journal.py`."""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from funding_bot.strategies.base import Signal

FIELDS = [
    "timestamp",
    "mode",
    "event",  # "trade" or "funding"
    "action",
    "leg",
    "base",
    "symbol",
    "side",
    "price",
    "qty",
    "size_usd",
    "filled",
    "group_id",
    "reason",
]


class TradeJournal:
    def __init__(self, path: str = "data/funding_trades.csv"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(FIELDS)

    def record(self, signal: Signal, mode: str, filled: bool) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    mode,
                    "trade",
                    signal.action,
                    signal.leg.value,
                    signal.base,
                    signal.symbol,
                    signal.side,
                    f"{signal.price:.6f}",
                    f"{signal.qty:.6f}",
                    f"{signal.size_usd:.4f}",
                    filled,
                    signal.group_id,
                    signal.reason,
                ]
            )

    def record_funding(self, mode: str, base: str, amount_usd: float, funding_rate: float) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    mode,
                    "funding",
                    "",
                    "perp",
                    base,
                    "",
                    "",
                    "",
                    "",
                    f"{amount_usd:.4f}",
                    True,
                    "",
                    f"funding settlement at rate {funding_rate:.6f}",
                ]
            )
