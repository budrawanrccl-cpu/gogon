"""Rules-based "early momentum" entry filter.

This deliberately does *not* try to be the fastest bot in the room —
it does not race to buy in the same block/slot as token creation, and it
does not try to front-run other traders' pending transactions. Instead it
waits a short window (filters.min_token_age_seconds) and only buys tokens
that already show real, broad-based public interest: enough distinct
buyers, enough buy volume, and a creator that (as far as the public feed
lets us tell) doesn't hold an outsized share of supply. That is still
speculative and can absolutely lose money — pump.fun tokens fail far more
often than not — but it's a systematic filter rather than a latency race
against other bots, and it's the kind of signal a human analyst could
reasonably describe out loud.

Every threshold below is configurable in config/pumpbot_settings.yaml.
"""
from __future__ import annotations

import logging

from pumpbot.config import FilterConfig
from pumpbot.market_data import TokenStats
from pumpbot.risk import RiskManager
from pumpbot.strategies.base import Signal

logger = logging.getLogger("pumpbot.strategy.momentum")


class MomentumEntryStrategy:
    name = "momentum"

    def __init__(self, cfg: FilterConfig, risk: RiskManager):
        self.cfg = cfg
        self.risk = risk

    def evaluate(self, stats: TokenStats) -> Signal | None:
        if stats.decided:
            return None

        if stats.mint in self.cfg.blacklist_mints:
            stats.decided = True
            return None

        age = stats.age_seconds
        if age < self.cfg.min_token_age_seconds:
            return None  # still too early to judge — check again next cycle
        if age > self.cfg.max_token_age_seconds:
            stats.decided = True  # window closed without qualifying; stop watching
            logger.debug("Passing on %s (%s): outside age window (%.0fs)", stats.mint, stats.symbol, age)
            return None

        # From here on, every failed check permanently disqualifies this
        # mint for this run (age window won't get more favorable).
        if stats.market_cap_sol is None or stats.last_price_sol_per_token is None:
            return None  # not enough data yet; keep waiting within the window

        if len(stats.unique_buyers) < self.cfg.min_unique_buyers:
            return None
        if stats.buy_volume_sol < self.cfg.min_buy_volume_sol:
            return None
        if stats.net_buy_volume_sol <= 0:
            stats.decided = True
            logger.debug("Passing on %s (%s): net sell pressure", stats.mint, stats.symbol)
            return None
        if not (self.cfg.min_market_cap_sol <= stats.market_cap_sol <= self.cfg.max_market_cap_sol):
            stats.decided = True
            return None
        if stats.creator_holding_pct is not None and stats.creator_holding_pct > self.cfg.max_creator_holding_pct:
            stats.decided = True
            logger.info(
                "Passing on %s (%s): creator holds %.1f%% > max %.1f%%",
                stats.mint, stats.symbol, stats.creator_holding_pct, self.cfg.max_creator_holding_pct,
            )
            return None

        size_sol = self.risk.max_affordable_sol()
        if size_sol < self.risk.cfg.min_order_size_sol:
            return None  # filters passed, but risk budget is exhausted — try the next candidate

        stats.decided = True
        reason = (
            f"age={age:.0f}s buyers={len(stats.unique_buyers)} "
            f"buy_vol={stats.buy_volume_sol:.2f}SOL mcap={stats.market_cap_sol:.1f}SOL"
        )
        logger.info("Momentum entry: %s (%s) — %s", stats.mint, stats.symbol, reason)

        return Signal(
            strategy=self.name,
            mint=stats.mint,
            symbol=stats.symbol,
            side="BUY",
            reference_price_sol=stats.last_price_sol_per_token,
            size_sol=size_sol,
            reason=reason,
        )
