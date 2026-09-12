"""Data types shared across the gmgn screener."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SmartWallet:
    """One wallet on gmgn.ai's smart-money leaderboard."""

    address: str
    chain: str
    tags: list[str] = field(default_factory=list)
    winrate: float | None = None
    pnl_usd: float | None = None
    realized_profit_usd: float | None = None
    buy_count: int = 0
    sell_count: int = 0


@dataclass
class TokenStats:
    """A token row from gmgn.ai's rank/swaps leaderboard: trading stats, security
    flags, and smart-money buy/sell counts all in one response — no separate
    per-token activity fetch needed.
    """

    chain: str
    address: str
    symbol: str = ""
    name: str = ""
    price_usd: float = 0.0
    price_change_pct: float | None = None
    market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    volume_usd: float = 0.0
    holder_count: int = 0
    buys: int = 0
    sells: int = 0
    smart_buy_24h: int = 0
    smart_sell_24h: int = 0
    sniper_count: int | None = None
    bluechip_owner_pct: float | None = None
    buy_tax_pct: float | None = None
    sell_tax_pct: float | None = None
    lock_pct: float | None = None
    is_honeypot: bool | None = None
    is_renounced: bool | None = None
    # Not reliably present on the rank/swaps endpoint (kept for forward
    # compatibility / other endpoints that do return them) — filters that
    # depend on these simply don't trigger when left None.
    top_10_holder_pct: float | None = None
    open_timestamp: int | None = None  # unix seconds the pair was created


@dataclass
class TokenSignal:
    """A screener hit: a token that passed all configured smart-money filters."""

    chain: str
    address: str
    symbol: str
    score: float
    smart_buy_24h: int
    smart_sell_24h: int
    net_smart_buys: int
    reasons: list[str]
    stats: TokenStats
