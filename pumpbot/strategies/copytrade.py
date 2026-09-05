"""Copy-trading: mirror the buys/sells of specific wallets ("leaders").

Unlike MomentumEntryStrategy (which is called once per cycle for every
tracked mint), this strategy is event-driven: main.py hands it every raw
trade event from mints/wallets PumpPortal streams to us, and it decides,
per event, whether that event was made by a followed wallet and whether to
mirror it. There's no periodic "evaluate all candidates" pass here — a
copy-trade opportunity is a single instant (the leader's transaction),
not something that gets more or less true as time passes.

Read the risks section in the README before following any wallet: past
performance of a wallet is not predictive, wallets can be paid to shill a
token, and there is inherent latency between the leader's transaction and
yours — you are never trading at exactly their price.
"""
from __future__ import annotations

import logging

from pumpbot.config import CopyTradeConfig
from pumpbot.parsing import num, text
from pumpbot.risk import RiskManager
from pumpbot.strategies.base import Signal

logger = logging.getLogger("pumpbot.strategy.copytrade")


class CopyTradeStrategy:
    name = "copytrade"

    def __init__(self, cfg: CopyTradeConfig, risk: RiskManager):
        self.cfg = cfg
        self.risk = risk
        self._wallets = {w.strip() for w in cfg.wallets if w.strip()}

    @property
    def wallets(self) -> list[str]:
        return sorted(self._wallets)

    def on_trade_event(self, payload: dict) -> Signal | None:
        trader = text(payload, "traderPublicKey", "trader")
        if not trader or trader not in self._wallets:
            return None  # not one of our followed wallets

        mint = text(payload, "mint", "mintAddress")
        if not mint or mint in self.cfg.blacklist_mints:
            return None

        tx_type = text(payload, "txType", "type").lower()
        symbol = text(payload, "symbol")
        sol_amount = num(payload, "solAmount", default=0.0) or 0.0

        price = self._infer_price(payload)

        if tx_type == "buy":
            return self._on_leader_buy(trader, mint, symbol, sol_amount, price)
        if tx_type == "sell":
            return self._on_leader_sell(trader, mint, symbol, price)
        return None

    def _infer_price(self, payload: dict) -> float | None:
        v_tokens = num(payload, "vTokensInBondingCurve")
        v_sol = num(payload, "vSolInBondingCurve")
        if v_tokens and v_sol and v_tokens > 0:
            return v_sol / v_tokens
        return None

    def _on_leader_buy(self, trader: str, mint: str, symbol: str, leader_sol: float, price: float | None) -> Signal | None:
        if not self.cfg.copy_buys:
            return None
        if leader_sol < self.cfg.min_leader_buy_sol:
            return None
        if price is None or price <= 0:
            return None  # can't size or record a fill without a price

        if self.cfg.sizing_mode == "proportional":
            size_sol = min(leader_sol * self.cfg.copy_ratio, self.risk.max_affordable_sol())
        else:
            size_sol = self.risk.max_affordable_sol()

        if size_sol < self.risk.cfg.min_order_size_sol:
            return None

        allowed, reason = self.risk.can_open(mint, size_sol)
        if not allowed:
            logger.info("Not copying buy on %s (%s): %s", mint, symbol, reason)
            return None

        logger.info(
            "Copying BUY: leader %s bought %.4f SOL of %s (%s) — mirroring %.4f SOL",
            trader, leader_sol, mint, symbol, size_sol,
        )
        return Signal(
            strategy=self.name,
            mint=mint,
            symbol=symbol,
            side="BUY",
            reference_price_sol=price,
            size_sol=size_sol,
            reason=f"copying {trader[:8]}… buy of {leader_sol:.4f} SOL",
        )

    def _on_leader_sell(self, trader: str, mint: str, symbol: str, price: float | None) -> Signal | None:
        if not self.cfg.copy_sells:
            return None
        pos = self.risk.positions.get(mint)
        if pos is None:
            return None  # we don't hold this token; nothing to mirror

        sell_price = price if price and price > 0 else pos.avg_price_sol
        logger.info("Copying SELL: leader %s sold %s (%s) — closing our position", trader, mint, symbol)
        return Signal(
            strategy=self.name,
            mint=mint,
            symbol=symbol,
            side="SELL",
            reference_price_sol=sell_price,
            size_sol=pos.token_amount * sell_price,
            reason=f"leader {trader[:8]}… sold; mirroring exit",
        )
