"""Shared strategy interface and trade signal type."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Signal:
    strategy: str
    mint: str
    symbol: str
    side: str  # "BUY" or "SELL"
    reference_price_sol: float  # last known price/token, used for paper sizing/logging
    size_sol: float  # for BUY: SOL to spend. For SELL: informational only (we sell the full position).
    reason: str


class Strategy(Protocol):
    name: str

    def evaluate(self, stats) -> Signal | None:
        """Inspect one token's running TokenStats and return a BUY Signal, or
        None if it doesn't (yet, or ever) qualify. Called once per cycle for
        every tracked, not-yet-decided mint.
        """
        ...
