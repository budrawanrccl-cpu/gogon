"""CSV trade journal — an audit trail of every signal the bot acted on."""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from bot.strategies.base import Signal

FIELDS = [
    "timestamp",
    "mode",
    "strategy",
    "market_id",
    "token_id",
    "outcome",
    "side",
    "price",
    "size_shares",
    "size_usd",
    "filled",
    "group_id",
    "reason",
]


class TradeJournal:
    def __init__(self, path: str = "data/trades.csv"):
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
                    signal.strategy,
                    signal.market_id,
                    signal.token_id,
                    signal.outcome,
                    signal.side,
                    f"{signal.limit_price:.4f}",
                    f"{signal.size_shares:.4f}",
                    f"{signal.size_usd:.4f}",
                    filled,
                    signal.group_id or "",
                    signal.reason,
                ]
            )
