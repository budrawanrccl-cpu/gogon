"""Smart-money screening logic: pure functions over already-fetched data.

No network/IO here — easy to unit test and to tune thresholds against without
hitting gmgn.ai at all.
"""
from __future__ import annotations

import time

from gmgn.config import ScreenerConfig
from gmgn.models import TokenActivity, TokenSignal, TokenStats


class SmartMoneyScreener:
    def __init__(self, cfg: ScreenerConfig):
        self.cfg = cfg

    def evaluate(
        self, stats: TokenStats, activities: list[TokenActivity], now: float | None = None
    ) -> TokenSignal | None:
        """Check one token's stats + recent tagged-wallet activity against the
        configured thresholds. Returns a TokenSignal if it passes everything,
        otherwise None.
        """
        now = now if now is not None else time.time()
        cfg = self.cfg
        reasons: list[str] = []

        if cfg.exclude_honeypot and stats.is_honeypot:
            return None

        if stats.open_timestamp:
            age_minutes = (now - stats.open_timestamp) / 60.0
            if age_minutes > cfg.max_token_age_minutes:
                return None

        if stats.liquidity_usd < cfg.min_liquidity_usd:
            return None
        if stats.holder_count and stats.holder_count < cfg.min_holder_count:
            return None
        if stats.top_10_holder_pct is not None and stats.top_10_holder_pct > cfg.max_top_10_holder_pct:
            return None
        if cfg.min_market_cap_usd and stats.market_cap_usd < cfg.min_market_cap_usd:
            return None
        if cfg.max_market_cap_usd and stats.market_cap_usd > cfg.max_market_cap_usd:
            return None

        cutoff = now - cfg.lookback_minutes * 60.0
        recent = [a for a in activities if a.timestamp >= cutoff]

        if cfg.required_tags:
            required = set(cfg.required_tags)
            recent = [a for a in recent if required.intersection(a.wallet_tags)]

        buy_wallets = {a.wallet_address for a in recent if a.side == "buy"}
        if len(buy_wallets) < cfg.min_smart_wallets:
            return None

        buy_usd = sum(a.amount_usd for a in recent if a.side == "buy")
        sell_usd = sum(a.amount_usd for a in recent if a.side == "sell")
        net_buy_usd = buy_usd - sell_usd
        if net_buy_usd < cfg.min_net_buy_usd:
            return None

        reasons.append(f"{len(buy_wallets)} distinct tagged wallets bought in the last {cfg.lookback_minutes}m")
        reasons.append(f"net smart-money flow ${net_buy_usd:,.0f} (buys ${buy_usd:,.0f} / sells ${sell_usd:,.0f})")
        if stats.top_10_holder_pct is not None:
            reasons.append(f"top-10 holders own {stats.top_10_holder_pct:.1f}%")

        score = self._score(len(buy_wallets), net_buy_usd, stats)

        return TokenSignal(
            chain=stats.chain,
            address=stats.address,
            symbol=stats.symbol,
            score=score,
            smart_wallet_count=len(buy_wallets),
            net_smart_buy_usd=net_buy_usd,
            buy_wallets=sorted(buy_wallets),
            reasons=reasons,
            stats=stats,
        )

    @staticmethod
    def _score(smart_wallet_count: int, net_buy_usd: float, stats: TokenStats) -> float:
        """Higher is more interesting. Not calibrated against real outcomes —
        a simple, transparent ranking heuristic to sort a batch of signals,
        not a prediction of future price."""
        concentration_penalty = 1.0
        if stats.top_10_holder_pct is not None:
            # scale 0-100% down to a 0.3-1.0 multiplier so heavy concentration
            # docks score without ever zeroing it out entirely.
            concentration_penalty = max(0.3, 1.0 - stats.top_10_holder_pct / 100.0 * 0.7)
        return round(smart_wallet_count * (net_buy_usd ** 0.5) * concentration_penalty, 2)
