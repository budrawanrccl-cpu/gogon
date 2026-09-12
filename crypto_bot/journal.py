"""CSV trade journal — an audit trail of every signal and fill, for the
crypto bot's live/paper loop (backtests keep their own in-memory trade list)."""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from crypto_bot.models import Signal

FIELDS = [
    "timestamp",
    "mode",
    "strategy",
    "symbol",
    "action",
    "price",
    "stop_price",
    "size",
    "reason",
]


class TradeJournal:
    def __init__(self, path: str = "data/crypto_trades.csv"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(FIELDS)

    def record(self, symbol: str, strategy: str, signal: Signal, mode: str, size: float = 0.0) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    mode,
                    strategy,
                    symbol,
                    signal.action,
                    f"{signal.price:.8g}",
                    f"{signal.stop_price:.8g}" if signal.stop_price is not None else "",
                    f"{size:.8g}",
                    signal.reason,
                ]
            )
