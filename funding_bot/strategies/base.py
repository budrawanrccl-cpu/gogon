"""Shared trade-signal type for the funding-arbitrage strategy.

Unlike the Polymarket bot's single-market Signal, each funding-arb trade is
a two-leg hedge (spot + perp), and positions are held across many cycles
until the funding edge disappears — so signals carry an explicit `action`
(OPEN/CLOSE) and `leg` (SPOT/PERP), and both legs of one hedge share a
`group_id`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Leg(str, Enum):
    SPOT = "spot"
    PERP = "perp"


@dataclass
class Signal:
    action: str  # "OPEN" or "CLOSE"
    leg: Leg
    symbol: str  # ccxt unified symbol for this leg (spot or perp)
    base: str  # base asset, e.g. "BTC" — used as the position key
    side: str  # "BUY" or "SELL"
    price: float  # reference price used for sizing/journaling
    qty: float  # base-asset quantity
    size_usd: float
    reason: str
    group_id: str
