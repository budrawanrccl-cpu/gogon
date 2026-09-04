"""CSV trade journal — an audit trail of every signal the bot acted on."""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from pumpbot.strategies.base import Signal

FIELDS = [
    "timestamp",
    "mode",
    "strategy",
    "mint",
    "symbol",
    "side",
    "reference_price_sol",
    "size_sol",
    "filled",
    "tx_signature",
    "reason",
]


class TradeJournal:
    def __init__(self, path: str = "data/pumpbot_trades.csv"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(FIELDS)

    def record(self, signal: Signal, mode: str, filled: bool, tx_signature: str = "") -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    mode,
                    signal.strategy,
                    signal.mint,
                    signal.symbol,
                    signal.side,
                    f"{signal.reference_price_sol:.10f}",
                    f"{signal.size_sol:.6f}",
                    filled,
                    tx_signature,
                    signal.reason,
                ]
            )
