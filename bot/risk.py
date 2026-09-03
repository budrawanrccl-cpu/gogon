"""Risk management: position sizing limits, exposure caps, and a daily-loss kill switch.

Pure logic, no network/IO — easy to unit test and to reason about before any
real money is at stake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from bot.config import RiskConfig


@dataclass
class Position:
    market_id: str
    token_id: str
    outcome: str
    size: float  # shares held
    cost_usd: float  # total USD spent to acquire this position
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def avg_price(self) -> float:
        return self.cost_usd / self.size if self.size else 0.0


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.positions: dict[str, Position] = {}  # keyed by token_id
        self.realized_pnl_today: float = 0.0
        self._day: date = date.today()

    # -- bookkeeping -------------------------------------------------
    def _roll_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.realized_pnl_today = 0.0

    @property
    def total_exposure_usd(self) -> float:
        return sum(p.cost_usd for p in self.positions.values())

    def market_exposure_usd(self, market_id: str) -> float:
        return sum(p.cost_usd for p in self.positions.values() if p.market_id == market_id)

    @property
    def daily_loss_limit_hit(self) -> bool:
        self._roll_day_if_needed()
        return self.realized_pnl_today <= -abs(self.cfg.max_daily_loss_usd)

    # -- pre-trade checks ----------------------------------------------
    def can_open(self, market_id: str, proposed_usd: float) -> tuple[bool, str]:
        """Check whether a new position of `proposed_usd` in `market_id` is allowed.

        Returns (allowed, reason). reason is human-readable, empty if allowed.
        """
        self._roll_day_if_needed()

        if proposed_usd < self.cfg.min_order_size_usd:
            return False, (
                f"order size ${proposed_usd:.2f} below minimum "
                f"${self.cfg.min_order_size_usd:.2f}"
            )

        if self.daily_loss_limit_hit:
            return False, (
                f"daily loss limit reached (${self.realized_pnl_today:.2f} <= "
                f"-${self.cfg.max_daily_loss_usd:.2f}); no new positions until UTC midnight"
            )

        market_exposure = self.market_exposure_usd(market_id)
        if market_exposure + proposed_usd > self.cfg.max_position_usd:
            return False, (
                f"would exceed max_position_usd for market {market_id}: "
                f"${market_exposure:.2f} + ${proposed_usd:.2f} > ${self.cfg.max_position_usd:.2f}"
            )

        total = self.total_exposure_usd
        if total + proposed_usd > self.cfg.max_total_exposure_usd:
            return False, (
                f"would exceed max_total_exposure_usd: "
                f"${total:.2f} + ${proposed_usd:.2f} > ${self.cfg.max_total_exposure_usd:.2f}"
            )

        return True, ""

    def max_affordable_usd(self, market_id: str) -> float:
        """Largest position (USD) currently allowed for this market, given caps."""
        self._roll_day_if_needed()
        if self.daily_loss_limit_hit:
            return 0.0
        per_market_room = max(0.0, self.cfg.max_position_usd - self.market_exposure_usd(market_id))
        total_room = max(0.0, self.cfg.max_total_exposure_usd - self.total_exposure_usd)
        return min(per_market_room, total_room)

    # -- fill recording --------------------------------------------------
    def record_open(self, market_id: str, token_id: str, outcome: str, size: float, cost_usd: float) -> None:
        existing = self.positions.get(token_id)
        if existing is None:
            self.positions[token_id] = Position(
                market_id=market_id, token_id=token_id, outcome=outcome, size=size, cost_usd=cost_usd
            )
        else:
            existing.size += size
            existing.cost_usd += cost_usd

    def record_close(self, token_id: str, size: float, proceeds_usd: float) -> float:
        """Reduce/close a position, realize P&L, and return the realized P&L for this fill."""
        self._roll_day_if_needed()
        pos = self.positions.get(token_id)
        if pos is None or pos.size <= 0:
            return 0.0

        size = min(size, pos.size)
        cost_basis = pos.avg_price * size
        pnl = proceeds_usd - cost_basis

        pos.size -= size
        pos.cost_usd -= cost_basis
        if pos.size <= 1e-9:
            del self.positions[token_id]

        self.realized_pnl_today += pnl
        return pnl
