"""Risk management: per-mint position sizing limits, exposure caps, and a
daily-loss kill switch — the pump.fun-bot analogue of bot/risk.py.

Pure logic, no network/IO — easy to unit test and to reason about before any
real SOL is at stake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from pumpfun_bot.config import RiskConfig


@dataclass
class Position:
    mint: str
    token_amount: float
    cost_sol: float  # total SOL spent to acquire this position
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def avg_price_sol(self) -> float:
        return self.cost_sol / self.token_amount if self.token_amount else 0.0


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.positions: dict[str, Position] = {}  # keyed by mint
        self.realized_pnl_today: float = 0.0
        self._day: date = date.today()

    # -- bookkeeping -------------------------------------------------
    def _roll_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.realized_pnl_today = 0.0

    @property
    def total_exposure_sol(self) -> float:
        return sum(p.cost_sol for p in self.positions.values())

    def position_exposure_sol(self, mint: str) -> float:
        pos = self.positions.get(mint)
        return pos.cost_sol if pos else 0.0

    @property
    def daily_loss_limit_hit(self) -> bool:
        self._roll_day_if_needed()
        return self.realized_pnl_today <= -abs(self.cfg.max_daily_loss_sol)

    # -- pre-trade checks ----------------------------------------------
    def can_open(self, mint: str, proposed_sol: float) -> tuple[bool, str]:
        """Check whether a new/added position of `proposed_sol` in `mint` is allowed.

        Returns (allowed, reason). reason is human-readable, empty if allowed.
        """
        self._roll_day_if_needed()

        if proposed_sol <= 0:
            return False, "proposed size is zero or negative"

        if self.daily_loss_limit_hit:
            return False, (
                f"daily loss limit reached ({self.realized_pnl_today:.4f} SOL <= "
                f"-{self.cfg.max_daily_loss_sol:.4f} SOL); no new positions until UTC midnight"
            )

        position_exposure = self.position_exposure_sol(mint)
        if position_exposure + proposed_sol > self.cfg.max_position_sol:
            return False, (
                f"would exceed max_position_sol for mint {mint}: "
                f"{position_exposure:.4f} + {proposed_sol:.4f} > {self.cfg.max_position_sol:.4f} SOL"
            )

        total = self.total_exposure_sol
        if total + proposed_sol > self.cfg.max_total_exposure_sol:
            return False, (
                f"would exceed max_total_exposure_sol: "
                f"{total:.4f} + {proposed_sol:.4f} > {self.cfg.max_total_exposure_sol:.4f} SOL"
            )

        return True, ""

    def max_affordable_sol(self, mint: str) -> float:
        """Largest position (SOL) currently allowed for this mint, given caps."""
        self._roll_day_if_needed()
        if self.daily_loss_limit_hit:
            return 0.0
        per_mint_room = max(0.0, self.cfg.max_position_sol - self.position_exposure_sol(mint))
        total_room = max(0.0, self.cfg.max_total_exposure_sol - self.total_exposure_sol)
        return min(per_mint_room, total_room)

    # -- fill recording --------------------------------------------------
    def record_open(self, mint: str, token_amount: float, cost_sol: float) -> None:
        existing = self.positions.get(mint)
        if existing is None:
            self.positions[mint] = Position(mint=mint, token_amount=token_amount, cost_sol=cost_sol)
        else:
            existing.token_amount += token_amount
            existing.cost_sol += cost_sol

    def record_close(self, mint: str, token_amount: float, proceeds_sol: float) -> float:
        """Reduce/close a position, realize P&L, and return the realized P&L for this fill."""
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

        self.realized_pnl_today += pnl
        return pnl
