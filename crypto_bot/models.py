"""Shared plain-data types: OHLCV bars, signals, positions, closed trades."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["LONG", "FLAT"]


@dataclass(frozen=True)
class Bar:
    """One OHLCV candle. `timestamp` is milliseconds since epoch (UTC), matching ccxt."""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    """A strategy's instruction, evaluated against risk before it becomes an order.

    `action` is one of:
      - "ENTER_LONG": open a new long position
      - "EXIT_LONG":  close the current long position
    `stop_price` is required on ENTER_LONG (used for position sizing and as the
    initial protective stop) and updated on subsequent bars while the position
    is held (trailing stop), even without a new signal — see PaperTrader/backtest.
    """

    action: Literal["ENTER_LONG", "EXIT_LONG"]
    price: float
    stop_price: float | None
    reason: str


@dataclass
class Position:
    symbol: str
    side: Side
    entry_price: float
    size: float  # base-asset units (e.g. BTC)
    stop_price: float
    opened_at: int  # bar timestamp (ms)


@dataclass
class ClosedTrade:
    symbol: str
    side: Side
    entry_price: float
    exit_price: float
    size: float
    opened_at: int
    closed_at: int
    exit_reason: str
    fees_usd: float = 0.0

    @property
    def pnl_usd(self) -> float:
        """Net of fees — what actually happened to equity."""
        return (self.exit_price - self.entry_price) * self.size - self.fees_usd

    @property
    def return_pct(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price if self.entry_price else 0.0
