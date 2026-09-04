"""Position exit rules: take-profit, stop-loss, trailing stop, and a
max-hold-time forced exit. Evaluated every cycle against each open
position's latest known price.

Pure logic (given a price), no network/IO — unit-testable like risk.py.
"""
from __future__ import annotations

import logging

from pumpbot.risk import Position, RiskManager
from pumpbot.strategies.base import Signal

logger = logging.getLogger("pumpbot.exits")


def evaluate_exit(risk: RiskManager, pos: Position, current_price_sol: float | None) -> Signal | None:
    cfg = risk.cfg

    if current_price_sol is None or current_price_sol <= 0:
        # No live price yet — still enforce the time-based exit, since that
        # doesn't depend on price.
        if pos.hold_seconds >= cfg.max_hold_seconds:
            return _sell(pos, pos.avg_price_sol, f"max_hold_seconds ({cfg.max_hold_seconds}s) reached, no live price")
        return None

    risk.update_peak(pos.mint, current_price_sol)
    change_pct = (current_price_sol - pos.avg_price_sol) / pos.avg_price_sol if pos.avg_price_sol else 0.0
    drawdown_from_peak = (
        (pos.peak_price_sol - current_price_sol) / pos.peak_price_sol if pos.peak_price_sol else 0.0
    )

    if change_pct >= cfg.take_profit_pct:
        return _sell(pos, current_price_sol, f"take_profit hit: +{change_pct:.1%}")

    if change_pct <= -cfg.stop_loss_pct:
        return _sell(pos, current_price_sol, f"stop_loss hit: {change_pct:.1%}")

    # Trailing stop only arms once the position is in profit, so it never
    # triggers a "loss" exit tighter than stop_loss above.
    if change_pct > 0 and drawdown_from_peak >= cfg.trailing_stop_pct:
        return _sell(pos, current_price_sol, f"trailing_stop hit: -{drawdown_from_peak:.1%} from peak")

    if pos.hold_seconds >= cfg.max_hold_seconds:
        return _sell(pos, current_price_sol, f"max_hold_seconds ({cfg.max_hold_seconds}s) reached")

    return None


def _sell(pos: Position, price_sol: float, reason: str) -> Signal:
    return Signal(
        strategy="exit",
        mint=pos.mint,
        symbol=pos.symbol,
        side="SELL",
        reference_price_sol=price_sol,
        size_sol=pos.token_amount * price_sol,
        reason=reason,
    )
