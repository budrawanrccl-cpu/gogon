"""Risk management for the funding-arbitrage bot: position sizing limits,
exposure caps, a daily-loss kill switch, and funding-payment accrual.

Pure logic, no network/IO — easy to unit test and to reason about before any
real money is at stake. Mirrors `bot/risk.py`'s structure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from funding_bot.config import RiskConfig


@dataclass
class FundingPosition:
    """One open spot+perp hedge. `perp_qty` is a short (perp side sold to
    open) in the (currently only supported) positive-funding direction."""

    base: str
    spot_qty: float
    perp_qty: float
    entry_spot_price: float
    entry_perp_price: float
    entry_funding_apr: float
    notional_usd: float  # cost basis used against risk caps
    # The funding rate currently "pending" for the next settlement, and the
    # timestamp of that settlement, as last observed. When the observed
    # timestamp advances, the pending rate just settled and gets credited —
    # see `RiskManager.accrue_funding`.
    pending_funding_rate: float
    pending_funding_time_ms: int | None
    funding_collected_usd: float = 0.0
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.positions: dict[str, FundingPosition] = {}  # keyed by base asset
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
        return sum(p.notional_usd for p in self.positions.values())

    @property
    def daily_loss_limit_hit(self) -> bool:
        self._roll_day_if_needed()
        return self.realized_pnl_today <= -abs(self.cfg.max_daily_loss_usd)

    # -- pre-trade checks ----------------------------------------------
    def can_open(self, base: str, proposed_usd: float) -> tuple[bool, str]:
        """Check whether a new `proposed_usd` hedge in `base` is allowed.

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

        if base in self.positions:
            return False, f"{base} already has an open funding-arb position"

        if proposed_usd > self.cfg.max_position_usd:
            return False, (
                f"would exceed max_position_usd for {base}: "
                f"${proposed_usd:.2f} > ${self.cfg.max_position_usd:.2f}"
            )

        total = self.total_exposure_usd
        if total + proposed_usd > self.cfg.max_total_exposure_usd:
            return False, (
                f"would exceed max_total_exposure_usd: "
                f"${total:.2f} + ${proposed_usd:.2f} > ${self.cfg.max_total_exposure_usd:.2f}"
            )

        return True, ""

    def max_affordable_usd(self, base: str) -> float:
        """Largest new hedge (USD) currently allowed for this base asset."""
        self._roll_day_if_needed()
        if self.daily_loss_limit_hit or base in self.positions:
            return 0.0
        per_symbol_room = self.cfg.max_position_usd
        total_room = max(0.0, self.cfg.max_total_exposure_usd - self.total_exposure_usd)
        return min(per_symbol_room, total_room)

    # -- position bookkeeping -------------------------------------------
    def record_open(
        self,
        base: str,
        spot_qty: float,
        perp_qty: float,
        spot_price: float,
        perp_price: float,
        notional_usd: float,
        entry_funding_apr: float,
        funding_rate: float,
        funding_time_ms: int | None,
    ) -> None:
        self.positions[base] = FundingPosition(
            base=base,
            spot_qty=spot_qty,
            perp_qty=perp_qty,
            entry_spot_price=spot_price,
            entry_perp_price=perp_price,
            entry_funding_apr=entry_funding_apr,
            notional_usd=notional_usd,
            pending_funding_rate=funding_rate,
            pending_funding_time_ms=funding_time_ms,
        )

    def record_close(self, base: str, spot_proceeds_usd: float, perp_proceeds_usd: float) -> float:
        """Close a hedge and realize its price P&L (funding P&L was already
        realized incrementally via `accrue_funding`). Returns the realized
        price P&L for this close."""
        self._roll_day_if_needed()
        pos = self.positions.pop(base, None)
        if pos is None:
            return 0.0

        spot_cost = pos.spot_qty * pos.entry_spot_price
        perp_cost = pos.perp_qty * pos.entry_perp_price  # perp was opened short (sold)

        spot_pnl = spot_proceeds_usd - spot_cost
        # Perp leg was opened by selling (short); closing buys it back, so
        # P&L is entry proceeds minus close cost.
        perp_pnl = perp_cost - perp_proceeds_usd

        pnl = spot_pnl + perp_pnl
        self.realized_pnl_today += pnl
        return pnl

    def accrue_funding(self, base: str, funding_rate: float, mark_price: float, funding_time_ms: int | None) -> float:
        """Check whether the funding settlement pending on this position has
        occurred (the exchange advances `funding_time_ms` once it has), and
        if so credit it at the rate that was actually pending — not the new
        rate now quoted for the *next* interval. Returns the USD amount
        credited (0.0 if nothing new settled this cycle).

        Being short the perp collects funding when the rate is positive
        (longs pay shorts) — which is the only direction this bot currently
        opens positions in. This is a paper-mode/estimate mechanism; live
        positions should be reconciled against the exchange's actual income
        history rather than trusted blindly.
        """
        self._roll_day_if_needed()
        pos = self.positions.get(base)
        if pos is None:
            return 0.0
        if funding_time_ms is None or funding_time_ms == pos.pending_funding_time_ms:
            return 0.0  # nothing has settled since we last checked

        amount = pos.perp_qty * mark_price * pos.pending_funding_rate
        pos.funding_collected_usd += amount
        pos.pending_funding_rate = funding_rate
        pos.pending_funding_time_ms = funding_time_ms
        self.realized_pnl_today += amount
        return amount
