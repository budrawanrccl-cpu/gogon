"""Complete-set arbitrage: buy equal shares of every outcome in a binary
market when their combined ask price is reliably below $1.

Why this is the "safe default" strategy: a binary Polymarket market pays out
exactly $1 to the winning outcome's shares and $0 to the losing one. Holding
one YES share and one NO share therefore always resolves to exactly $1,
regardless of which side wins. If you can buy one of each for less than
$1 - fees, the difference is locked-in profit at resolution — the only real
risks are execution risk (one leg fills, the other doesn't) and the
possibility that on-chain fees/rules change. `fee_buffer` and `min_edge`
exist to keep a safety margin around both.
"""
from __future__ import annotations

import logging
import uuid

from bot.config import ArbitrageConfig
from bot.market_data import MarketInfo
from bot.risk import RiskManager
from bot.strategies.base import GetBook, Signal

logger = logging.getLogger("polybot.strategy.arbitrage")


class ArbitrageStrategy:
    name = "arbitrage"

    def __init__(self, cfg: ArbitrageConfig, risk: RiskManager):
        self.cfg = cfg
        self.risk = risk

    def generate_signals(self, market: MarketInfo, get_book: GetBook) -> list[Signal]:
        if not self.cfg.enabled:
            return []
        # Only handles simple binary (two-outcome) markets for now.
        if len(market.tokens) != 2:
            return []

        token_a, token_b = market.tokens[0], market.tokens[1]
        book_a = get_book(token_a.token_id)
        book_b = get_book(token_b.token_id)

        if book_a.best_ask is None or book_b.best_ask is None:
            return []
        if book_a.best_ask_size <= 0 or book_b.best_ask_size <= 0:
            return []

        combined_ask = book_a.best_ask + book_b.best_ask
        edge = 1.0 - combined_ask - self.cfg.fee_buffer
        if edge < self.cfg.min_edge:
            return []

        max_usd = self.risk.max_affordable_usd(market.condition_id)
        if max_usd < self.risk.cfg.min_order_size_usd:
            return []

        # Arbitrage requires buying the SAME number of shares of both legs
        # (1 YES + 1 NO always resolves to $1). Size is bounded by: available
        # liquidity at the best ask on each leg, and the risk budget.
        shares_by_liquidity = min(book_a.best_ask_size, book_b.best_ask_size)
        shares_by_budget = max_usd / combined_ask if combined_ask > 0 else 0.0
        shares = min(shares_by_liquidity, shares_by_budget)

        cost_usd = shares * combined_ask
        if shares <= 0 or cost_usd < self.risk.cfg.min_order_size_usd:
            return []

        group_id = str(uuid.uuid4())
        reason = (
            f"combined ask {combined_ask:.4f} < 1.0 - {self.cfg.fee_buffer:.4f}; "
            f"edge={edge:.4f}"
        )

        logger.info(
            "Arbitrage found in market %s: %s — buying %.2f shares each leg (~$%.2f)",
            market.condition_id,
            market.question,
            shares,
            cost_usd,
        )

        return [
            Signal(
                strategy=self.name,
                market_id=market.condition_id,
                token_id=token_a.token_id,
                outcome=token_a.outcome,
                side="BUY",
                limit_price=book_a.best_ask,
                size_shares=shares,
                size_usd=shares * book_a.best_ask,
                reason=reason,
                group_id=group_id,
            ),
            Signal(
                strategy=self.name,
                market_id=market.condition_id,
                token_id=token_b.token_id,
                outcome=token_b.outcome,
                side="BUY",
                limit_price=book_b.best_ask,
                size_shares=shares,
                size_usd=shares * book_b.best_ask,
                reason=reason,
                group_id=group_id,
            ),
        ]
