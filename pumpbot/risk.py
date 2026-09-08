"""Risk management: position sizing limits, exposure caps, and a daily-loss
kill switch — same shape as bot/risk.py for the Polymarket bot, denominated
in SOL instead of USD.

Pure logic, no network/IO — easy to unit test and to reason about before
any real money is at stake.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from pumpbot.config import RiskConfig

logger = logging.getLogger("pumpbot.risk")


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

    def to_dict(self) -> dict:
        return {
            "mint": self.mint,
            "symbol": self.symbol,
            "token_amount": self.token_amount,
            "cost_sol": self.cost_sol,
            "peak_price_sol": self.peak_price_sol,
            "opened_at": self.opened_at.isoformat(),
        }

    @staticmethod
    def from_dict(d: dict) -> "Position":
        return Position(
            mint=d["mint"],
            symbol=d["symbol"],
            token_amount=d["token_amount"],
            cost_sol=d["cost_sol"],
            peak_price_sol=d["peak_price_sol"],
            opened_at=datetime.fromisoformat(d["opened_at"]),
        )


class RiskManager:
    def __init__(self, cfg: RiskConfig, state_path: str | None = None):
        self.cfg = cfg
        self.positions: dict[str, Position] = {}  # keyed by mint
        self.realized_pnl_today_sol: float = 0.0
        self._day: date = date.today()
        # Opt-in (None by default, so this stays "pure logic, no IO" for
        # tests and any other caller that doesn't pass it): when set,
        # every mutation is persisted to this JSON file and reloaded on
        # construction. Without this, open positions only ever lived in
        # this process' memory — a restart (e.g. to pick up a config
        # change) silently "forgot" every open position while the real
        # SOL spent on them stayed gone from the wallet, so the bot would
        # never generate an exit for them again and risk caps would reset
        # as if nothing were open. main.py passes a real path; scripts
        # like sell_token.py that build a short-lived RiskManager just to
        # satisfy OrderExecutor's constructor intentionally don't, since
        # they sell 100% of actual on-chain holdings regardless of what
        # any position-tracking file says.
        self.state_path = state_path
        if self.state_path:
            self._load_state()

    def _load_state(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.positions = {mint: Position.from_dict(p) for mint, p in data.get("positions", {}).items()}
            self.realized_pnl_today_sol = data.get("realized_pnl_today_sol", 0.0)
            day_str = data.get("day")
            if day_str:
                self._day = date.fromisoformat(day_str)
            if self.positions:
                logger.info(
                    "Restored %d open position(s) from %s: %s",
                    len(self.positions), self.state_path,
                    ", ".join(f"{m} ({p.symbol})" for m, p in self.positions.items()),
                )
        except Exception:
            logger.exception(
                "Failed to load persisted risk state from %s — starting with no known open "
                "positions. If any positions are actually still open, reconcile against your "
                "wallet's real token balances (scripts/check_wallet_holdings.py) before trusting "
                "risk caps.",
                self.state_path,
            )

    def _save_state(self) -> None:
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            tmp_path = self.state_path + ".tmp"
            data = {
                "positions": {mint: p.to_dict() for mint, p in self.positions.items()},
                "realized_pnl_today_sol": self.realized_pnl_today_sol,
                "day": self._day.isoformat(),
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp_path, self.state_path)  # atomic — never leaves a half-written file
        except Exception:
            logger.exception("Failed to persist risk state to %s", self.state_path)

    # -- bookkeeping -------------------------------------------------
    def _roll_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.realized_pnl_today_sol = 0.0
            self._save_state()

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
        self._save_state()

    def update_peak(self, mint: str, current_price_sol: float) -> None:
        pos = self.positions.get(mint)
        if pos is not None and current_price_sol > pos.peak_price_sol:
            pos.peak_price_sol = current_price_sol
            self._save_state()

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
        self._save_state()
        return pnl
