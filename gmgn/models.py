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
class TokenActivity:
    """A single buy/sell event on a token, attributed to a tagged wallet."""

    chain: str
    token_address: str
    wallet_address: str
    wallet_tags: list[str]
    side: str  # "buy" or "sell"
    amount_usd: float
    price_usd: float
    timestamp: int  # unix seconds


@dataclass
class TokenStats:
    """Aggregated stats/security info for one token, as reported by gmgn.ai."""

    chain: str
    address: str
    symbol: str = ""
    name: str = ""
    price_usd: float = 0.0
    market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    holder_count: int = 0
    top_10_holder_pct: float | None = None
    open_timestamp: int | None = None  # unix seconds the pair was created
    is_honeypot: bool | None = None
    is_renounced: bool | None = None
    burn_ratio: float | None = None


@dataclass
class TokenSignal:
    """A screener hit: a token that passed all configured smart-money filters."""

    chain: str
    address: str
    symbol: str
    score: float
    smart_wallet_count: int
    net_smart_buy_usd: float
    buy_wallets: list[str]
    reasons: list[str]
    stats: TokenStats
