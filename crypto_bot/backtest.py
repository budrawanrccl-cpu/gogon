"""Single-symbol backtest engine: replays historical bars through a strategy
and a risk manager exactly the way the live paper/live loop does (same
`strategy.evaluate()` call, same `RiskManager`), so backtest results are a
reasonable guide to live behavior — not a separate code path that quietly
diverges from what actually trades.

Simplifications worth knowing before trusting the numbers:
- Entries/channel exits fill at the *same bar's close* where the signal
  fires (a common simplification for 1h+ timeframes; add a bar of latency
  or use next-bar-open fills for a more conservative test).
- Stop-outs fill at the stop price exactly — real fills can slip past it in
  a fast/illiquid move, especially on altcoins.
- No exchange downtime, partial fills, or rate limits.
- Any position still open at the end of the data is force-closed at the
  last bar's close so the metrics are complete; that final trade is an
  artifact of the backtest window, not a real exit signal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from crypto_bot.models import Bar, ClosedTrade, Position
from crypto_bot.risk import RiskConfig, RiskManager
from crypto_bot.strategy import DonchianBreakoutStrategy


@dataclass
class BacktestResult:
    symbol: str
    starting_equity: float
    final_equity: float
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    trades: list[ClosedTrade] = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return (self.final_equity - self.starting_equity) / self.starting_equity

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl_usd > 0)
        return wins / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl_usd for t in self.trades if t.pnl_usd > 0)
        gross_loss = sum(-t.pnl_usd for t in self.trades if t.pnl_usd < 0)
        if gross_loss == 0:
            return math.inf if gross_win > 0 else 0.0
        return gross_win / gross_loss

    @property
    def avg_trade_pct(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.return_pct for t in self.trades) / len(self.trades)

    @property
    def max_drawdown_pct(self) -> float:
        peak = -math.inf
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            if peak > 0:
                max_dd = max(max_dd, (peak - eq) / peak)
        return max_dd

    def summary(self) -> str:
        pf = "inf" if math.isinf(self.profit_factor) else f"{self.profit_factor:.2f}"
        return (
            f"{self.symbol}: {self.num_trades} trades | "
            f"return {self.total_return_pct:+.1%} "
            f"(${self.starting_equity:.2f} -> ${self.final_equity:.2f}) | "
            f"win rate {self.win_rate:.1%} | profit factor {pf} | "
            f"max drawdown {self.max_drawdown_pct:.1%} | "
            f"avg trade {self.avg_trade_pct:+.2%}"
        )


def run_backtest(
    symbol: str,
    bars: list[Bar],
    strategy: DonchianBreakoutStrategy,
    risk_cfg: RiskConfig,
) -> BacktestResult:
    if len(bars) < 2:
        raise ValueError("need at least 2 bars to backtest")

    risk = RiskManager(risk_cfg)
    ind = strategy.precompute(bars)
    position: Position | None = None
    equity_curve: list[tuple[int, float]] = []

    for i, bar in enumerate(bars):
        signal, new_stop = strategy.evaluate(bars, ind, i, position)

        if signal is not None and signal.action == "EXIT_LONG" and position is not None:
            risk.record_close(symbol, signal.price, bar.timestamp, signal.reason)
            position = None
        elif signal is not None and signal.action == "ENTER_LONG" and position is None:
            allowed, _reason = risk.can_open(symbol)
            if allowed and signal.stop_price is not None:
                size = risk.position_size(signal.price, signal.stop_price)
                notional = size * signal.price
                if size > 0 and notional >= risk_cfg.min_order_size_usd:
                    position = Position(
                        symbol=symbol,
                        side="LONG",
                        entry_price=signal.price,
                        size=size,
                        stop_price=signal.stop_price,
                        opened_at=bar.timestamp,
                    )
                    risk.record_open(symbol, position)
        elif position is not None and new_stop is not None:
            position.stop_price = new_stop

        if position is not None:
            risk.mark_unrealized((bar.close - position.entry_price) * position.size)
        else:
            risk.mark_unrealized(0.0)
        equity_curve.append((bar.timestamp, risk.current_equity))

    if position is not None:
        last = bars[-1]
        risk.record_close(symbol, last.close, last.timestamp, "backtest end (forced close)")
        equity_curve[-1] = (last.timestamp, risk.current_equity)

    return BacktestResult(
        symbol=symbol,
        starting_equity=risk_cfg.starting_equity_usd,
        final_equity=risk.current_equity,
        equity_curve=equity_curve,
        trades=risk.closed_trades,
    )
