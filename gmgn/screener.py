"""Smart-money screening logic: pure functions over already-fetched data.

No network/IO here — easy to unit test and to tune thresholds against without
hitting gmgn.ai at all.
"""
from __future__ import annotations

import time

from gmgn.config import ScreenerConfig
from gmgn.models import TokenSignal, TokenStats


class SmartMoneyScreener:
    def __init__(self, cfg: ScreenerConfig):
        self.cfg = cfg

    def evaluate(self, stats: TokenStats, now: float | None = None) -> TokenSignal | None:
        """Check one token's stats + smart-money buy/sell counts against the
        configured thresholds. Returns a TokenSignal if it passes everything,
        otherwise None.
        """
        now = now if now is not None else time.time()
        cfg = self.cfg
        reasons: list[str] = []

        if cfg.exclude_honeypot and stats.is_honeypot:
            return None
        if cfg.require_renounced and not stats.is_renounced:
            return None

        # Only enforced when the data source actually populates these
        # (see TokenStats) — a None value never fails the check.
        if stats.open_timestamp:
            age_minutes = (now - stats.open_timestamp) / 60.0
            if age_minutes > cfg.max_token_age_minutes:
                return None
        if stats.top_10_holder_pct is not None and stats.top_10_holder_pct > cfg.max_top_10_holder_pct:
            return None

        if stats.liquidity_usd < cfg.min_liquidity_usd:
            return None
        if stats.holder_count and stats.holder_count < cfg.min_holder_count:
            return None
        if cfg.min_market_cap_usd and stats.market_cap_usd < cfg.min_market_cap_usd:
            return None
        if cfg.max_market_cap_usd and stats.market_cap_usd > cfg.max_market_cap_usd:
            return None
        if cfg.max_buy_tax_pct and stats.buy_tax_pct is not None and stats.buy_tax_pct > cfg.max_buy_tax_pct:
            return None
        if cfg.max_sell_tax_pct and stats.sell_tax_pct is not None and stats.sell_tax_pct > cfg.max_sell_tax_pct:
            return None
        if cfg.max_sniper_count and stats.sniper_count is not None and stats.sniper_count > cfg.max_sniper_count:
            return None
        if (
            cfg.min_bluechip_owner_pct
            and stats.bluechip_owner_pct is not None
            and stats.bluechip_owner_pct < cfg.min_bluechip_owner_pct
        ):
            return None

        if stats.smart_buy_24h < cfg.min_smart_buy_24h:
            return None
        net_smart_buys = stats.smart_buy_24h - stats.smart_sell_24h
        if net_smart_buys < cfg.min_net_smart_buys:
            return None

        reasons.append(f"{stats.smart_buy_24h} smart-money buys vs {stats.smart_sell_24h} sells (net {net_smart_buys:+d})")
        if stats.bluechip_owner_pct is not None:
            reasons.append(f"bluechip owners: {stats.bluechip_owner_pct:.1f}%")
        if stats.buy_tax_pct or stats.sell_tax_pct:
            reasons.append(f"tax: buy {stats.buy_tax_pct or 0:.1f}% / sell {stats.sell_tax_pct or 0:.1f}%")

        score = self._score(stats, net_smart_buys)

        return TokenSignal(
            chain=stats.chain,
            address=stats.address,
            symbol=stats.symbol,
            score=score,
            smart_buy_24h=stats.smart_buy_24h,
            smart_sell_24h=stats.smart_sell_24h,
            net_smart_buys=net_smart_buys,
            reasons=reasons,
            stats=stats,
        )

    @staticmethod
    def _score(stats: TokenStats, net_smart_buys: int) -> float:
        """Higher is more interesting. Not calibrated against real outcomes —
        a simple, transparent ranking heuristic to sort a batch of signals,
        not a prediction of future price."""
        liquidity_factor = max(stats.liquidity_usd, 1.0) ** 0.5
        penalty = 1.0
        if stats.sniper_count:
            # docks score for heavily-sniped tokens without zeroing it out
            penalty *= max(0.3, 1.0 - min(stats.sniper_count, 50) / 50.0 * 0.7)
        return round(net_smart_buys * liquidity_factor * penalty / 100.0, 2)
