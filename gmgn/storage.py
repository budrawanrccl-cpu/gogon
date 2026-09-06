"""Local persistence: alert de-duplication and a CSV audit trail of signals."""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone

from gmgn.models import TokenSignal

FIELDS = [
    "timestamp",
    "chain",
    "address",
    "symbol",
    "score",
    "smart_buy_24h",
    "smart_sell_24h",
    "net_smart_buys",
    "liquidity_usd",
    "market_cap_usd",
    "top_10_holder_pct",
    "reasons",
]


class SeenCache:
    """Tracks the last time each token address was alerted on, so the bot
    doesn't spam the same signal every polling cycle. Backed by a small JSON
    file so it survives restarts.
    """

    def __init__(self, path: str = "data/gmgn_seen.json"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._last_alerted: dict[str, float] = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._last_alerted = json.load(f)
            except (ValueError, OSError):
                self._last_alerted = {}

    def should_alert(self, address: str, cooldown_minutes: int, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        last = self._last_alerted.get(address)
        if last is None:
            return True
        return (now - last) >= cooldown_minutes * 60.0

    def mark(self, address: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._last_alerted[address] = now
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._last_alerted, f)


class SignalJournal:
    """CSV audit trail of every signal the screener has emitted."""

    def __init__(self, path: str = "data/gmgn_signals.csv"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(FIELDS)

    def record(self, signal: TokenSignal) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    signal.chain,
                    signal.address,
                    signal.symbol,
                    signal.score,
                    signal.smart_buy_24h,
                    signal.smart_sell_24h,
                    signal.net_smart_buys,
                    f"{signal.stats.liquidity_usd:.2f}",
                    f"{signal.stats.market_cap_usd:.2f}",
                    "" if signal.stats.top_10_holder_pct is None else f"{signal.stats.top_10_holder_pct:.2f}",
                    "; ".join(signal.reasons),
                ]
            )
