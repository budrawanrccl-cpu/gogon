"""Shared strategy interface and trade signal type."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from bot.market_data import BookLevel, MarketInfo


@dataclass
class Signal:
    strategy: str
    market_id: str
    token_id: str
    outcome: str
    side: str  # "BUY" or "SELL"
    limit_price: float  # worst-case/reference price used for sizing and order submission
    size_shares: float
    size_usd: float
    reason: str
    group_id: str | None = None  # links multi-leg trades (e.g. both arbitrage legs)


GetBook = Callable[[str], BookLevel]


class Strategy(Protocol):
    name: str

    def generate_signals(self, market: MarketInfo, get_book: GetBook) -> list[Signal]:
        """Inspect one market's order books and return zero or more trade signals."""
        ...
