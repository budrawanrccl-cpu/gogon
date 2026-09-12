"""Spot + perp hedge funding-rate arbitrage.

Why this works: perpetual futures use periodic funding payments to pull the
perp price back toward the index/spot price. When the funding rate is
positive, longs pay shorts. Going **short the perp** while holding an equal
**long spot** position is delta-neutral — spot and perp move together, so
price moves roughly cancel out — while the position collects the funding
payment every interval. The edge is the funding rate itself; the risks are
execution risk (legs fill at different prices/times), the funding rate
flipping/decaying before it's collected, and basis risk (mark price
diverging from spot, which this strategy bounds via `max_basis_pct`).

Negative funding rates (shorts pay longs) would need the reverse position —
short spot (margin-borrowed) + long perp — which this bot does not
implement yet (see `FundingArbitrageConfig.allow_negative_funding`), so only
the positive-funding side is ever traded here.
"""
from __future__ import annotations

import logging
import uuid

from funding_bot.config import FundingArbitrageConfig
from funding_bot.market_data import FundingSnapshot
from funding_bot.risk import RiskManager
from funding_bot.strategies.base import Leg, Signal

logger = logging.getLogger("fundingbot.strategy.funding_arbitrage")


class FundingArbitrageStrategy:
    name = "funding_arbitrage"

    def __init__(self, cfg: FundingArbitrageConfig, risk: RiskManager):
        self.cfg = cfg
        self.risk = risk
        self._warned_negative_funding = False

    def generate_signals(self, snapshot: FundingSnapshot) -> list[Signal]:
        if not self.cfg.enabled:
            return []

        existing = self.risk.positions.get(snapshot.base)
        if existing is not None:
            return self._maybe_close(snapshot, existing)
        return self._maybe_open(snapshot)

    # -- entry ------------------------------------------------------
    def _maybe_open(self, snapshot: FundingSnapshot) -> list[Signal]:
        if snapshot.funding_rate <= 0:
            if self.cfg.allow_negative_funding and not self._warned_negative_funding:
                logger.warning(
                    "allow_negative_funding is set but not implemented: collecting "
                    "negative funding requires shorting spot on margin, which this "
                    "bot does not support. Negative-funding symbols are skipped."
                )
                self._warned_negative_funding = True
            return []

        if abs(snapshot.basis_pct) > self.cfg.max_basis_pct:
            logger.debug(
                "%s: basis %.3f%% exceeds max_basis_pct %.3f%%, skipping",
                snapshot.base,
                snapshot.basis_pct * 100,
                self.cfg.max_basis_pct * 100,
            )
            return []

        net_apr = snapshot.apr - self.cfg.fee_buffer_apr
        if net_apr < self.cfg.min_funding_rate_apr:
            return []

        max_usd = self.risk.max_affordable_usd(snapshot.base)
        if max_usd < self.risk.cfg.min_order_size_usd:
            return []

        if snapshot.spot_price <= 0:
            return []

        qty = max_usd / snapshot.spot_price
        cost_usd = qty * snapshot.spot_price
        if qty <= 0 or cost_usd < self.risk.cfg.min_order_size_usd:
            return []

        group_id = str(uuid.uuid4())
        reason = (
            f"funding APR {snapshot.apr:.1%} (net {net_apr:.1%}) >= "
            f"min_funding_rate_apr {self.cfg.min_funding_rate_apr:.1%}; "
            f"basis {snapshot.basis_pct:.3%}"
        )

        logger.info(
            "Funding arb entry for %s: %s — long %.6f spot / short %.6f perp (~$%.2f)",
            snapshot.base,
            reason,
            qty,
            qty,
            cost_usd,
        )

        return [
            Signal(
                action="OPEN",
                leg=Leg.SPOT,
                symbol=snapshot.spot_symbol,
                base=snapshot.base,
                side="BUY",
                price=snapshot.spot_price,
                qty=qty,
                size_usd=cost_usd,
                reason=reason,
                group_id=group_id,
            ),
            Signal(
                action="OPEN",
                leg=Leg.PERP,
                symbol=snapshot.perp_symbol,
                base=snapshot.base,
                side="SELL",
                price=snapshot.mark_price,
                qty=qty,
                size_usd=qty * snapshot.mark_price,
                reason=reason,
                group_id=group_id,
            ),
        ]

    # -- exit ---------------------------------------------------------
    def _maybe_close(self, snapshot: FundingSnapshot, existing) -> list[Signal]:
        net_apr = snapshot.apr - self.cfg.fee_buffer_apr
        basis_blown_out = abs(snapshot.basis_pct) > self.cfg.max_basis_pct * 2

        if net_apr >= self.cfg.exit_funding_rate_apr and not basis_blown_out:
            return []  # edge still holds; keep collecting funding

        if basis_blown_out:
            reason = (
                f"basis {snapshot.basis_pct:.3%} exceeds 2x max_basis_pct "
                f"({self.cfg.max_basis_pct:.3%}); unwinding"
            )
        else:
            reason = (
                f"funding APR net {net_apr:.1%} dropped below "
                f"exit_funding_rate_apr {self.cfg.exit_funding_rate_apr:.1%}; closing"
            )

        group_id = str(uuid.uuid4())
        logger.info(
            "Funding arb exit for %s: %s (collected $%.2f funding so far)",
            snapshot.base,
            reason,
            existing.funding_collected_usd,
        )

        return [
            Signal(
                action="CLOSE",
                leg=Leg.SPOT,
                symbol=snapshot.spot_symbol,
                base=snapshot.base,
                side="SELL",
                price=snapshot.spot_price,
                qty=existing.spot_qty,
                size_usd=existing.spot_qty * snapshot.spot_price,
                reason=reason,
                group_id=group_id,
            ),
            Signal(
                action="CLOSE",
                leg=Leg.PERP,
                symbol=snapshot.perp_symbol,
                base=snapshot.base,
                side="BUY",
                price=snapshot.mark_price,
                qty=existing.perp_qty,
                size_usd=existing.perp_qty * snapshot.mark_price,
                reason=reason,
                group_id=group_id,
            ),
        ]
