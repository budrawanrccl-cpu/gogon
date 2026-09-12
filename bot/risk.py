"""Risk management: position sizing limits, exposure caps, and a daily-loss kill switch.

Pure logic, no network/IO — easy to unit test and to reason about before any
real money is at stake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from bot.config import RiskConfig

# Tolerance for cap comparisons. An order sized to spend exactly the
# remaining budget (proposed_usd == room) can come back a few ULPs over due
# to floating-point round-trip (e.g. shares = usd/price; usd2 = shares*price
# occasionally lands a hair above usd). Without this, such an order would be
# rejected even though it doesn't meaningfully exceed the cap.
_EPSILON_USD = 1e-6


@dataclass
class Position:
    market_id: str
    token_id: str
    outcome: str
    size: float  # shares held
    cost_usd: float  # total USD spent to acquire this position
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Name of the strategy that first opened this position (set on the first
    # record_open call, never overwritten by later averaging-down buys). Lets
    # a strategy avoid managing a position it doesn't own -- e.g. threshold
    # must not close out a hedge that HedgingStrategy bought on the opposite
    # token of a market threshold is also watching.
    opened_by: str = ""

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

    # -- cap helpers -----------------------------------------------------
    # A hedge is capped differently from a new entry (arbitrage/threshold):
    # it may push a market's committed capital above max_position_usd by up
    # to hedge_reserve_usd, and may draw on the full max_total_exposure_usd
    # instead of leaving that reserve untouched. can_open, max_affordable_usd,
    # and max_hedge_usd all derive their caps from these two methods so they
    # can never drift out of sync with each other.
    def _per_market_cap(self, is_hedge: bool) -> float:
        return self.cfg.max_position_usd + (self.cfg.hedge_reserve_usd if is_hedge else 0.0)

    def _total_cap(self, is_hedge: bool) -> float:
        if is_hedge:
            return self.cfg.max_total_exposure_usd
        return self.cfg.max_total_exposure_usd - self.cfg.hedge_reserve_usd

    # -- pre-trade checks ----------------------------------------------
    def can_open(self, market_id: str, proposed_usd: float, is_hedge: bool = False) -> tuple[bool, str]:
        """Check whether a new position of `proposed_usd` in `market_id` is allowed.

        `is_hedge` must match how the signal was sized (see `max_hedge_usd`
        vs. `max_affordable_usd`) or a correctly-sized hedge order can be
        rejected here under the stricter entry-strategy caps.

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

        per_market_cap = self._per_market_cap(is_hedge)
        market_exposure = self.market_exposure_usd(market_id)
        if market_exposure + proposed_usd > per_market_cap + _EPSILON_USD:
            return False, (
                f"would exceed max_position_usd for market {market_id}: "
                f"${market_exposure:.2f} + ${proposed_usd:.2f} > ${per_market_cap:.2f}"
            )

        total_cap = self._total_cap(is_hedge)
        total = self.total_exposure_usd
        if total + proposed_usd > total_cap + _EPSILON_USD:
            return False, (
                f"would exceed max_total_exposure_usd: "
                f"${total:.2f} + ${proposed_usd:.2f} > ${total_cap:.2f}"
            )

        return True, ""

    def max_affordable_usd(self, market_id: str) -> float:
        """Largest new entry-strategy position (USD) currently allowed for this
        market — i.e. what arbitrage/threshold may spend. Leaves
        `hedge_reserve_usd` of total exposure capacity untouched, so the
        hedging strategy (via `max_hedge_usd`) can still act after an entry
        strategy has otherwise used up the shared budget.
        """
        self._roll_day_if_needed()
        if self.daily_loss_limit_hit:
            return 0.0
        per_market_room = max(0.0, self._per_market_cap(is_hedge=False) - self.market_exposure_usd(market_id))
        total_room = max(0.0, self._total_cap(is_hedge=False) - self.total_exposure_usd)
        return min(per_market_room, total_room)

    def max_hedge_usd(self, market_id: str) -> float:
        """Largest hedge (USD) currently allowed for this market.

        Unlike `max_affordable_usd`, this may dip into `hedge_reserve_usd` and
        allows a market's total committed capital to exceed `max_position_usd`
        by up to that reserve. A hedge caps the loss on a position that's
        already open rather than adding a new speculative bet, so it isn't
        held to the same per-market entry limit — it's still bounded by the
        (unreduced) total exposure cap.
        """
        self._roll_day_if_needed()
        if self.daily_loss_limit_hit:
            return 0.0
        per_market_room = max(0.0, self._per_market_cap(is_hedge=True) - self.market_exposure_usd(market_id))
        total_room = max(0.0, self._total_cap(is_hedge=True) - self.total_exposure_usd)
        return min(per_market_room, total_room)

    # -- fill recording --------------------------------------------------
    def record_open(
        self, market_id: str, token_id: str, outcome: str, size: float, cost_usd: float, opened_by: str = ""
    ) -> None:
        existing = self.positions.get(token_id)
        if existing is None:
            self.positions[token_id] = Position(
                market_id=market_id,
                token_id=token_id,
                outcome=outcome,
                size=size,
                cost_usd=cost_usd,
                opened_by=opened_by,
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

    # -- startup recovery --------------------------------------------------
    def restore_from_fills(self, fills: list[dict]) -> None:
        """Reconstruct positions (and today's realized P&L) from a trade
        journal's fill history — rows shaped like bot.journal.FIELDS,
        already filtered to filled=="True" and sorted chronologically (see
        `bot.journal.load_fills`).

        RiskManager otherwise starts every process with empty state. Without
        this, restarting the bot (crash, redeploy, manual restart) makes it
        "forget" every open position and hedge even though nothing changed
        on Polymarket itself — the next cycle would then size new trades and
        check caps against a wallet it thinks is empty. Call once at
        startup, before the first scan cycle.

        Only today's (UTC) closes are added to realized_pnl_today, matching
        the daily-loss kill switch's own reset-at-UTC-midnight semantics —
        a loss realized yesterday must not count against today's limit.
        """
        self._roll_day_if_needed()
        today = datetime.now(timezone.utc).date()

        for f in fills:
            token_id = f["token_id"]
            size = float(f["size_shares"])
            usd = float(f["size_usd"])

            if f["side"] == "BUY":
                self.record_open(
                    f["market_id"], token_id, f["outcome"], size, usd, opened_by=f.get("strategy", "")
                )
                continue

            # SELL: replay the same average-cost math as record_close, but
            # only attribute the P&L to today's counter if the fill actually
            # happened today -- record_close itself always counts against
            # "today" (correct for live fills, wrong for historical replay).
            pos = self.positions.get(token_id)
            if pos is None or pos.size <= 0:
                continue
            sell_size = min(size, pos.size)
            cost_basis = pos.avg_price * sell_size
            pnl = usd - cost_basis
            pos.size -= sell_size
            pos.cost_usd -= cost_basis
            if pos.size <= 1e-9:
                del self.positions[token_id]

            try:
                fill_date = datetime.fromisoformat(f["timestamp"]).date()
            except (KeyError, ValueError):
                fill_date = today  # malformed/missing timestamp: err on counting it
            if fill_date == today:
                self.realized_pnl_today += pnl
