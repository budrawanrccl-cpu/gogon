"""CSV trade journal — an audit trail of every copy signal the bot acted on."""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from pumpfun_bot.copy_engine import CopySignal

FIELDS = [
    "timestamp",
    "mode",
    "source_wallet",
    "source_signature",
    "mint",
    "side",
    "sol_size",
    "filled",
    "tx_signature",
    "reason",
]


class TradeJournal:
    def __init__(self, path: str = "data/pumpfun_trades.csv"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(FIELDS)

    def record(self, signal: CopySignal, mode: str, filled: bool, tx_signature: str = "") -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    mode,
                    signal.source_wallet,
                    signal.source_signature,
                    signal.mint,
                    signal.side,
                    f"{signal.sol_size:.6f}",
                    filled,
                    tx_signature,
                    signal.reason,
                ]
            )
