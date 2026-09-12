"""Turns strategy Signals into either simulated fills (paper mode) or real
market orders on Binance spot + USDT-M futures (live mode), and updates
risk/position state.

Each hedge is two legs (spot + perp) that should both fill or neither should
be left open. Market orders are used deliberately: funding-rate edge is not
price-sensitive at the tick level, so the priority is getting both legs on
(or off) together rather than resting a limit order and risking a
one-legged position.
"""
from __future__ import annotations

import logging

from funding_bot.journal import TradeJournal
from funding_bot.market_data import FundingSnapshot
from funding_bot.risk import RiskManager
from funding_bot.strategies.base import Leg, Signal

logger = logging.getLogger("fundingbot.execution")


class OrderExecutor:
    def __init__(self, spot_client, futures_client, risk: RiskManager, journal: TradeJournal, live: bool):
        self.spot_client = spot_client
        self.futures_client = futures_client
        self.risk = risk
        self.journal = journal
        self.live = live

    def execute_group(self, signals: list[Signal], snapshot: FundingSnapshot) -> bool:
        if not signals:
            return False
        action = signals[0].action
        if action == "OPEN":
            return self._execute_open(signals, snapshot)
        return self._execute_close(signals)

    # -- entry: both legs or neither --------------------------------
    def _execute_open(self, signals: list[Signal], snapshot: FundingSnapshot) -> bool:
        spot_sig = next(s for s in signals if s.leg == Leg.SPOT)
        perp_sig = next(s for s in signals if s.leg == Leg.PERP)

        allowed, reason = self.risk.can_open(spot_sig.base, spot_sig.size_usd)
        if not allowed:
            logger.info("Skipping open for %s: %s", spot_sig.base, reason)
            return False

        spot_filled, spot_price = self._execute_leg(spot_sig)
        if not spot_filled:
            self.journal.record(spot_sig, mode=self._mode, filled=False)
            return False
        self.journal.record(spot_sig, mode=self._mode, filled=True)

        perp_filled, perp_price = self._execute_leg(perp_sig)
        self.journal.record(perp_sig, mode=self._mode, filled=perp_filled)

        if not perp_filled:
            logger.error(
                "Perp leg failed to open for %s after spot leg filled — unwinding spot "
                "immediately to avoid a naked directional position.",
                spot_sig.base,
            )
            unwind = Signal(
                action="CLOSE",
                leg=Leg.SPOT,
                symbol=spot_sig.symbol,
                base=spot_sig.base,
                side="SELL",
                price=spot_price,
                qty=spot_sig.qty,
                size_usd=spot_sig.qty * spot_price,
                reason="unwind: perp leg failed to open",
                group_id=spot_sig.group_id,
            )
            unwind_filled, _ = self._execute_leg(unwind)
            self.journal.record(unwind, mode=self._mode, filled=unwind_filled)
            if not unwind_filled:
                logger.critical(
                    "Failed to unwind spot leg for %s — bot now holds an UNHEDGED spot "
                    "position. Manual intervention required.",
                    spot_sig.base,
                )
            return False

        self.risk.record_open(
            base=spot_sig.base,
            spot_qty=spot_sig.qty,
            perp_qty=perp_sig.qty,
            spot_price=spot_price,
            perp_price=perp_price,
            notional_usd=spot_sig.size_usd,
            entry_funding_apr=snapshot.apr,
            funding_rate=snapshot.funding_rate,
            funding_time_ms=snapshot.next_funding_time_ms,
        )
        return True

    # -- exit: best-effort both legs -----------------------------------
    def _execute_close(self, signals: list[Signal]) -> bool:
        spot_sig = next(s for s in signals if s.leg == Leg.SPOT)
        perp_sig = next(s for s in signals if s.leg == Leg.PERP)

        spot_filled, spot_price = self._execute_leg(spot_sig)
        self.journal.record(spot_sig, mode=self._mode, filled=spot_filled)

        perp_filled, perp_price = self._execute_leg(perp_sig)
        self.journal.record(perp_sig, mode=self._mode, filled=perp_filled)

        if not (spot_filled and perp_filled):
            logger.error(
                "Close for %s only partially filled (spot=%s perp=%s) — position may "
                "still be open on the exchange; reconcile manually.",
                spot_sig.base,
                spot_filled,
                perp_filled,
            )

        pnl = self.risk.record_close(
            base=spot_sig.base,
            spot_proceeds_usd=spot_sig.qty * spot_price,
            perp_proceeds_usd=perp_sig.qty * perp_price,
        )
        logger.info("Closed %s: price P&L $%.2f", spot_sig.base, pnl)
        return spot_filled and perp_filled

    @property
    def _mode(self) -> str:
        return "live" if self.live else "paper"

    # -- single-leg fill: paper simulates at the reference price -------
    def _execute_leg(self, signal: Signal) -> tuple[bool, float]:
        if not self.live:
            logger.info(
                "[PAPER] %s %s %.6f %s @ %.4f (%s) — %s",
                signal.action,
                signal.side,
                signal.qty,
                signal.symbol,
                signal.price,
                signal.leg.value,
                signal.reason,
            )
            return True, signal.price

        client = self.spot_client if signal.leg == Leg.SPOT else self.futures_client
        side = "buy" if signal.side == "BUY" else "sell"
        params = {}
        if signal.leg == Leg.PERP and signal.action == "CLOSE":
            params["reduceOnly"] = True

        try:
            order = client.create_order(signal.symbol, "market", side, signal.qty, params=params)
        except Exception:
            logger.exception("Order failed: %s %s %.6f %s", signal.action, side, signal.qty, signal.symbol)
            return False, signal.price

        fill_price = order.get("average") or order.get("price") or signal.price
        try:
            fill_price = float(fill_price)
        except (TypeError, ValueError):
            fill_price = signal.price

        logger.info(
            "[LIVE] %s %s %.6f %s @ %.4f (%s) -> order=%s",
            signal.action,
            signal.side,
            signal.qty,
            signal.symbol,
            fill_price,
            signal.leg.value,
            order.get("id", "?"),
        )
        return True, fill_price
