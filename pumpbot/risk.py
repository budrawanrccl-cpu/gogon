"""Risk management: position sizing limits, exposure caps, and a daily-loss
kill switch — same shape as bot/risk.py for the Polymarket bot, denominated
in SOL instead of USD.

Pure logic, no network/IO — easy to unit test and to reason about before
any real money is at stake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from pumpbot.config import RiskConfig


@dataclass
class Position:
    mint: str
    symbol: str
    token_amount: float  # tokens held
    cost_sol: float  # total SOL spent to acquire this position
    peak_price_sol: float  # highest observed price/token since entry, for trailing stop
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def avg_price_sol(self) -> float:
        return self.cost_sol / self.token_amount if self.token_amount else 0.0

    @property
    def hold_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.opened_at).total_seconds()


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.positions: dict[str, Position] = {}  # keyed by mint
        self.realized_pnl_today_sol: float = 0.0
        self._day: date = date.today()

    # -- bookkeeping -------------------------------------------------
    def _roll_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.realized_pnl_today_sol = 0.0

    @property
    def total_exposure_sol(self) -> float:
        return sum(p.cost_sol for p in self.positions.values())

    @property
    def daily_loss_limit_hit(self) -> bool:
        self._roll_day_if_needed()
        return self.realized_pnl_today_sol <= -abs(self.cfg.max_daily_loss_sol)

    # -- pre-trade checks ----------------------------------------------
    def can_open(self, mint: str, proposed_sol: float) -> tuple[bool, str]:
        """Check whether a new position of `proposed_sol` in `mint` is allowed.

        Returns (allowed, reason). reason is human-readable, empty if allowed.
        """
        self._roll_day_if_needed()

        if mint in self.positions:
            return False, f"already holding a position in {mint}"

        if proposed_sol < self.cfg.min_order_size_sol:
            return False, (
                f"order size {proposed_sol:.4f} SOL below minimum "
                f"{self.cfg.min_order_size_sol:.4f} SOL"
            )

        if self.daily_loss_limit_hit:
            return False, (
                f"daily loss limit reached ({self.realized_pnl_today_sol:.4f} SOL <= "
                f"-{self.cfg.max_daily_loss_sol:.4f} SOL); no new positions until UTC midnight"
            )

        if len(self.positions) >= self.cfg.max_concurrent_positions:
            return False, f"at max_concurrent_positions ({self.cfg.max_concurrent_positions})"

        if proposed_sol > self.cfg.max_position_sol:
            return False, (
                f"proposed {proposed_sol:.4f} SOL exceeds max_position_sol "
                f"{self.cfg.max_position_sol:.4f}"
            )

        total = self.total_exposure_sol
        if total + proposed_sol > self.cfg.max_total_exposure_sol:
            return False, (
                f"would exceed max_total_exposure_sol: {total:.4f} + {proposed_sol:.4f} "
                f"> {self.cfg.max_total_exposure_sol:.4f}"
            )

        return True, ""

    def max_affordable_sol(self) -> float:
        """Largest new position (SOL) currently allowed, given caps."""
        self._roll_day_if_needed()
        if self.daily_loss_limit_hit:
            return 0.0
        if len(self.positions) >= self.cfg.max_concurrent_positions:
            return 0.0
        total_room = max(0.0, self.cfg.max_total_exposure_sol - self.total_exposure_sol)
        return min(self.cfg.max_position_sol, total_room)

    # -- fill recording --------------------------------------------------
    def record_open(self, mint: str, symbol: str, token_amount: float, cost_sol: float) -> None:
        price = cost_sol / token_amount if token_amount else 0.0
        existing = self.positions.get(mint)
        if existing is None:
            self.positions[mint] = Position(
                mint=mint,
                symbol=symbol,
                token_amount=token_amount,
                cost_sol=cost_sol,
                peak_price_sol=price,
            )
        else:
            existing.token_amount += token_amount
            existing.cost_sol += cost_sol
            existing.peak_price_sol = max(existing.peak_price_sol, price)

    def update_peak(self, mint: str, current_price_sol: float) -> None:
        pos = self.positions.get(mint)
        if pos is not None and current_price_sol > pos.peak_price_sol:
            pos.peak_price_sol = current_price_sol

    def record_close(self, mint: str, token_amount: float, proceeds_sol: float) -> float:
        """Reduce/close a position, realize P&L, and return the realized P&L (SOL)."""
        self._roll_day_if_needed()
        pos = self.positions.get(mint)
        if pos is None or pos.token_amount <= 0:
            return 0.0

        amount = min(token_amount, pos.token_amount)
        cost_basis = pos.avg_price_sol * amount
        pnl = proceeds_sol - cost_basis

        pos.token_amount -= amount
        pos.cost_sol -= cost_basis
        if pos.token_amount <= 1e-9:
            del self.positions[mint]

        self.realized_pnl_today_sol += pnl
        return pnl
