"""Turns a DetectedTrade (something a watched wallet just did) into a sized,
risk-checked CopySignal — or a skip reason. Pure logic, no network/IO.
"""
from __future__ import annotations

from dataclasses import dataclass

from pumpfun_bot.config import CopyConfig, MintFilterConfig
from pumpfun_bot.risk import RiskManager
from pumpfun_bot.trade_detector import DetectedTrade


@dataclass
class CopySignal:
    source_wallet: str
    source_signature: str
    mint: str
    side: str  # "BUY" or "SELL"
    sol_size: float
    reason: str


def _mint_allowed(mint: str, cfg: MintFilterConfig) -> bool:
    if cfg.blacklist and mint in cfg.blacklist:
        return False
    if cfg.whitelist and mint not in cfg.whitelist:
        return False
    return True


def build_copy_signal(
    trade: DetectedTrade, copy_cfg: CopyConfig, mint_cfg: MintFilterConfig, risk: RiskManager
) -> CopySignal | None:
    """Decide whether/how to copy `trade`. Returns None if it should be skipped."""
    if not _mint_allowed(trade.mint, mint_cfg):
        return None

    if trade.side == "SELL":
        if not copy_cfg.mirror_sells:
            return None
        # Only mirror a sell on a mint we actually hold — otherwise there is
        # nothing to sell and no reason to open a fresh short-like position.
        pos = risk.positions.get(trade.mint)
        if pos is None or pos.token_amount <= 0:
            return None
        # We don't know what fraction of the target's own balance this sell
        # represents from a single transaction, so instead of trying to
        # infer their remaining position we sell the same size_ratio-scaled
        # slice of *our* position — the same knob that sizes buys.
        sol_size = pos.cost_sol * min(1.0, copy_cfg.size_ratio)
        if sol_size <= 0:
            return None
        return CopySignal(
            source_wallet=trade.wallet,
            source_signature=trade.signature,
            mint=trade.mint,
            side="SELL",
            sol_size=sol_size,
            reason=f"mirroring sell by {trade.wallet[:6]}… ({trade.sol_amount:.4f} SOL)",
        )

    # BUY
    if trade.sol_amount < copy_cfg.min_target_trade_sol:
        return None
    if copy_cfg.skip_if_already_holding and trade.mint in risk.positions:
        return None

    proposed = min(trade.sol_amount * copy_cfg.size_ratio, copy_cfg.max_sol_per_trade)
    allowed_by_budget = risk.max_affordable_sol(trade.mint)
    sol_size = min(proposed, allowed_by_budget)
    if sol_size <= 0:
        return None

    return CopySignal(
        source_wallet=trade.wallet,
        source_signature=trade.signature,
        mint=trade.mint,
        side="BUY",
        sol_size=sol_size,
        reason=f"copying buy by {trade.wallet[:6]}… ({trade.sol_amount:.4f} SOL @ {copy_cfg.size_ratio:.0%})",
    )
