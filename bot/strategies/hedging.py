"""Loss-triggered hedging: cap the downside on directional positions by
buying the opposite outcome once a position has moved against you.

Unlike arbitrage (which buys both legs together at entry) or threshold
(which is purely directional), this strategy watches *existing* open
positions. When a held position's unrealized loss reaches
`trigger_loss_pct`, it buys enough of the opposite outcome's shares to
bring the pair up to `hedge_ratio` of the original position size. A binary
market always pays exactly $1 total across both outcomes, so once a
position is fully hedged (hedge_ratio=1.0 and matched 1:1), further moves
in the market no longer change the combined payout — the loss already
taken is locked in instead of growing.

This strategy is disabled by default: it only does something useful when
another strategy (typically `threshold`) is opening single-sided
directional positions for it to protect.

Sizing uses `RiskManager.max_hedge_usd` rather than `max_affordable_usd`:
entry strategies (arbitrage/threshold) spend their entire available budget
on every trade, which otherwise leaves nothing for a hedge to act on
immediately afterward. Set `risk.hedge_reserve_usd` in config/settings.yaml
to carve out capital reserved specifically for hedging.
"""
from __future__ import annotations

import logging

from bot.config import HedgingConfig
from bot.market_data import MarketInfo
from bot.risk import RiskManager
from bot.strategies.base import GetBook, Signal

logger = logging.getLogger("polybot.strategy.hedging")


class HedgingStrategy:
    name = "hedging"

    def __init__(self, cfg: HedgingConfig, risk: RiskManager):
        self.cfg = cfg
        self.risk = risk

    def generate_signals(self, market: MarketInfo, get_book: GetBook) -> list[Signal]:
        if not self.cfg.enabled:
            return []
        # Only handles simple binary (two-outcome) markets for now.
        if len(market.tokens) != 2:
            return []

        token_a, token_b = market.tokens[0], market.tokens[1]
        pos_a = self.risk.positions.get(token_a.token_id)
        pos_b = self.risk.positions.get(token_b.token_id)

        signals: list[Signal] = []
        for primary_token, primary_pos, opposite_token, opposite_pos in (
            (token_a, pos_a, token_b, pos_b),
            (token_b, pos_b, token_a, pos_a),
        ):
            signal = self._maybe_hedge(
                market, primary_token, primary_pos, opposite_token, opposite_pos, get_book
            )
            if signal is not None:
                signals.append(signal)
        return signals

    def _maybe_hedge(self, market, primary_token, primary_pos, opposite_token, opposite_pos, get_book):
        if primary_pos is None or primary_pos.size <= 0 or primary_pos.avg_price <= 0:
            return None

        # Already hedged up to the configured ratio? Nothing to do.
        already_hedged_size = opposite_pos.size if opposite_pos else 0.0
        target_hedge_size = primary_pos.size * self.cfg.hedge_ratio
        remaining_shares = target_hedge_size - already_hedged_size
        if remaining_shares <= 1e-9:
            return None

        book = get_book(primary_token.token_id)
        if book.best_bid is None or book.best_ask is None:
            return None
        mid = (book.best_bid + book.best_ask) / 2
        loss_pct = (primary_pos.avg_price - mid) / primary_pos.avg_price
        if loss_pct < self.cfg.trigger_loss_pct:
            return None

        opp_book = get_book(opposite_token.token_id)
        if opp_book.best_ask is None or opp_book.best_ask_size <= 0:
            return None

        max_usd = self.risk.max_hedge_usd(market.condition_id)
        shares_by_liquidity = min(remaining_shares, opp_book.best_ask_size)
        shares_by_budget = max_usd / opp_book.best_ask if opp_book.best_ask > 0 else 0.0
        shares = min(shares_by_liquidity, shares_by_budget)

        cost_usd = shares * opp_book.best_ask
        if shares <= 0 or cost_usd < self.risk.cfg.min_order_size_usd:
            return None

        reason = (
            f"hedging {primary_token.outcome} position down {loss_pct:.1%} "
            f"(avg {primary_pos.avg_price:.3f} vs mid {mid:.3f}); "
            f"buying {shares:.2f} {opposite_token.outcome} shares"
        )
        logger.info(
            "Hedge triggered in market %s: %s — %s",
            market.condition_id,
            market.question,
            reason,
        )

        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            token_id=opposite_token.token_id,
            outcome=opposite_token.outcome,
            side="BUY",
            limit_price=opp_book.best_ask,
            size_shares=shares,
            size_usd=cost_usd,
            reason=reason,
            is_hedge=True,
        )
