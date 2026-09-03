"""Turns strategy Signals into either simulated fills (paper mode) or real
orders on the Polymarket CLOB (live mode), and updates risk/position state.
"""
from __future__ import annotations

import logging

from bot.journal import TradeJournal
from bot.risk import RiskManager
from bot.strategies.base import Signal

logger = logging.getLogger("polybot.execution")


class OrderExecutor:
    def __init__(self, client, risk: RiskManager, journal: TradeJournal, live: bool):
        self.client = client
        self.risk = risk
        self.journal = journal
        self.live = live

    def execute(self, signal: Signal) -> bool:
        if signal.side == "BUY":
            allowed, reason = self.risk.can_open(signal.market_id, signal.size_usd)
            if not allowed:
                logger.info("Skipping BUY %s/%s: %s", signal.market_id, signal.outcome, reason)
                return False

        filled = self._execute_live(signal) if self.live else self._execute_paper(signal)
        self.journal.record(signal, mode="live" if self.live else "paper", filled=filled)
        return filled

    # -- paper mode: assume the observed best bid/ask fills immediately -----
    def _execute_paper(self, signal: Signal) -> bool:
        if signal.side == "BUY":
            self.risk.record_open(
                signal.market_id, signal.token_id, signal.outcome, signal.size_shares, signal.size_usd
            )
        else:
            self.risk.record_close(signal.token_id, signal.size_shares, signal.size_usd)

        logger.info(
            "[PAPER] %s %.4f %s shares @ %.4f (market=%s) — %s",
            signal.side,
            signal.size_shares,
            signal.outcome,
            signal.limit_price,
            signal.market_id,
            signal.reason,
        )
        return True

    # -- live mode: sign and submit a real fill-or-kill order --------------
    def _execute_live(self, signal: Signal) -> bool:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        side = BUY if signal.side == "BUY" else SELL
        order_args = OrderArgs(
            token_id=signal.token_id,
            price=round(signal.limit_price, 4),
            size=round(signal.size_shares, 2),
            side=side,
        )

        try:
            signed_order = self.client.create_order(order_args)
            # FOK: fills completely and immediately, or not at all — no resting
            # order is left on the book, which minimizes one-leg-only arb risk.
            response = self.client.post_order(signed_order, OrderType.FOK)
        except Exception:
            logger.exception("Order submission failed for %s/%s", signal.market_id, signal.outcome)
            return False

        # NOTE: verify this against the actual API response shape before
        # relying on it — reconcile positions periodically via
        # client.get_trades()/get_orders() rather than trusting this alone.
        success = bool(response) and not (isinstance(response, dict) and response.get("error"))

        logger.info(
            "[LIVE] %s %.4f %s shares @ %.4f (market=%s) -> response=%s",
            signal.side,
            signal.size_shares,
            signal.outcome,
            signal.limit_price,
            signal.market_id,
            response,
        )

        if success:
            if signal.side == "BUY":
                self.risk.record_open(
                    signal.market_id, signal.token_id, signal.outcome, signal.size_shares, signal.size_usd
                )
            else:
                self.risk.record_close(signal.token_id, signal.size_shares, signal.size_usd)
        else:
            logger.warning("Order for %s/%s did not confirm success: %s", signal.market_id, signal.outcome, response)

        return success
