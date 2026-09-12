"""Risk management: fixed-fractional position sizing, a daily-loss kill
switch, and a max-drawdown kill switch.

Pure logic, no network/IO — easy to unit test and to reason about before any
real money is at stake. This is what actually keeps a trend-following
strategy (which loses on most trades by design — see strategy.py) survivable:
no single trade or bad day/week can do lasting damage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from crypto_bot.models import ClosedTrade, Position


@dataclass
class RiskConfig:
    starting_equity_usd: float = 1000.0
    # Fraction of equity risked (distance from entry to stop) per trade.
    # This, not a fixed dollar amount, is what makes sizing scale sanely as
    # equity grows or shrinks.
    risk_per_trade_pct: float = 0.01
    # Kill switch: stop opening new positions for the rest of the UTC day
    # once realized P&L today reaches this fraction of equity-at-day-start.
    max_daily_loss_pct: float = 0.03
    # Kill switch: stop opening new positions entirely once drawdown from
    # the equity peak (realized + unrealized/mark-to-market) reaches this.
    # Does NOT auto-close open positions — their own stops handle that.
    max_drawdown_pct: float = 0.20
    max_concurrent_positions: int = 1
    min_order_size_usd: float = 10.0
    # Round-trip fee assumption (entry + exit), e.g. 0.001 = 0.1% each way.
    # Matters a lot for a strategy with a low win rate — always model it.
    fee_pct: float = 0.001


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.realized_equity = cfg.starting_equity_usd
        self.unrealized_pnl = 0.0
        self.peak_equity = cfg.starting_equity_usd
        self.open_positions: dict[str, Position] = {}
        self.closed_trades: list[ClosedTrade] = []

        self.realized_pnl_today = 0.0
        self._day: date = date.today()
        self._equity_at_day_start = cfg.starting_equity_usd
        self.halted_for_drawdown = False

    # -- bookkeeping ---------------------------------------------------
    def _roll_day_if_needed(self, today: date | None = None) -> None:
        today = today or date.today()
        if today != self._day:
            self._day = today
            self.realized_pnl_today = 0.0
            self._equity_at_day_start = self.current_equity

    @property
    def current_equity(self) -> float:
        return self.realized_equity + self.unrealized_pnl

    def mark_unrealized(self, pnl: float) -> None:
        """Update mark-to-market P&L on open positions. Call every bar/tick
        so drawdown reflects paper losses, not just closed ones."""
        self.unrealized_pnl = pnl
        self.peak_equity = max(self.peak_equity, self.current_equity)
        if self.drawdown_pct >= self.cfg.max_drawdown_pct:
            self.halted_for_drawdown = True

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity)

    @property
    def daily_loss_limit_hit(self) -> bool:
        self._roll_day_if_needed()
        return self.realized_pnl_today <= -abs(self.cfg.max_daily_loss_pct) * self._equity_at_day_start

    # -- pre-trade checks ------------------------------------------------
    def can_open(self, symbol: str) -> tuple[bool, str]:
        self._roll_day_if_needed()

        if self.halted_for_drawdown:
            return False, (
                f"max drawdown reached ({self.drawdown_pct:.1%} >= "
                f"{self.cfg.max_drawdown_pct:.1%}); no new positions"
            )
        if self.daily_loss_limit_hit:
            return False, (
                f"daily loss limit reached (${self.realized_pnl_today:.2f}); "
                "no new positions until UTC midnight"
            )
        if symbol in self.open_positions:
            return False, f"already holding a position in {symbol}"
        if len(self.open_positions) >= self.cfg.max_concurrent_positions:
            return False, (
                f"max_concurrent_positions ({self.cfg.max_concurrent_positions}) reached"
            )
        return True, ""

    def position_size(self, entry_price: float, stop_price: float) -> float:
        """Shares (base-asset units) sized so that a stop-out risks exactly
        `risk_per_trade_pct` of current equity — not the whole position."""
        stop_distance = entry_price - stop_price
        if stop_distance <= 0 or entry_price <= 0:
            return 0.0
        risk_usd = self.current_equity * self.cfg.risk_per_trade_pct
        size = risk_usd / stop_distance
        # Never risk more notional than equity actually available.
        max_size_by_equity = self.current_equity / entry_price
        return max(0.0, min(size, max_size_by_equity))

    # -- fill recording --------------------------------------------------
    def record_open(self, symbol: str, position: Position) -> None:
        self.open_positions[symbol] = position

    def record_close(self, symbol: str, exit_price: float, closed_at: int, reason: str) -> ClosedTrade | None:
        self._roll_day_if_needed()
        pos = self.open_positions.pop(symbol, None)
        if pos is None:
            return None

        entry_notional = pos.entry_price * pos.size
        exit_notional = exit_price * pos.size
        fees = (entry_notional + exit_notional) * self.cfg.fee_pct
        pnl = (exit_price - pos.entry_price) * pos.size - fees

        self.realized_equity += pnl
        self.realized_pnl_today += pnl
        self.unrealized_pnl = 0.0
        self.peak_equity = max(self.peak_equity, self.current_equity)
        if self.drawdown_pct >= self.cfg.max_drawdown_pct:
            self.halted_for_drawdown = True

        trade = ClosedTrade(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size=pos.size,
            opened_at=pos.opened_at,
            closed_at=closed_at,
            exit_reason=reason,
            fees_usd=fees,
        )
        self.closed_trades.append(trade)
        return trade
