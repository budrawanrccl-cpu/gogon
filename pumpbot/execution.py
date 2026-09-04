"""Turns strategy Signals into either simulated fills (paper mode) or real,
locally-signed Solana transactions (live mode), and updates risk/position
state.

Live mode uses PumpPortal's non-custodial "Local Transaction API"
(https://pumpportal.fun/api/trade-local): PumpPortal returns an *unsigned*
serialized transaction built from your requested trade parameters, you sign
it locally with your own keypair, and you broadcast it yourself via your
own RPC endpoint. Your private key is never sent to PumpPortal or anyone
else — it only ever exists in this process' memory (see pumpbot/wallet.py).

Field names and exact response shapes for third-party APIs like this one
change over time; the parsing below is defensive and logs the raw response
on failure rather than assuming a shape. Verify against a live call before
trusting this in size, and reconcile fills against your wallet's actual
token balance periodically rather than trusting the journal alone.
"""
from __future__ import annotations

import logging

import requests

from pumpbot.config import DataConfig, TradingConfig, WalletConfig
from pumpbot.journal import TradeJournal
from pumpbot.risk import RiskManager
from pumpbot.strategies.base import Signal

logger = logging.getLogger("pumpbot.execution")


class OrderExecutor:
    def __init__(
        self,
        risk: RiskManager,
        journal: TradeJournal,
        live: bool,
        data_cfg: DataConfig | None = None,
        trading_cfg: TradingConfig | None = None,
        wallet_cfg: WalletConfig | None = None,
        keypair=None,
    ):
        self.risk = risk
        self.journal = journal
        self.live = live
        self.data_cfg = data_cfg
        self.trading_cfg = trading_cfg
        self.wallet_cfg = wallet_cfg
        self.keypair = keypair  # solders.keypair.Keypair, only set when live

    def execute(self, signal: Signal) -> bool:
        if signal.side == "BUY":
            allowed, reason = self.risk.can_open(signal.mint, signal.size_sol)
            if not allowed:
                logger.info("Skipping BUY %s (%s): %s", signal.mint, signal.symbol, reason)
                return False

        if self.live:
            filled, tx_sig = self._execute_live(signal)
        else:
            filled, tx_sig = self._execute_paper(signal), ""

        self.journal.record(signal, mode="live" if self.live else "paper", filled=filled, tx_signature=tx_sig)
        return filled

    # -- paper mode: assume the signal's reference price fills immediately -----
    def _execute_paper(self, signal: Signal) -> bool:
        price = signal.reference_price_sol
        if price <= 0:
            logger.warning("Skipping paper fill for %s: no reference price", signal.mint)
            return False

        token_amount = signal.size_sol / price

        if signal.side == "BUY":
            self.risk.record_open(signal.mint, signal.symbol, token_amount, signal.size_sol)
        else:
            pos = self.risk.positions.get(signal.mint)
            sell_amount = pos.token_amount if pos else token_amount
            proceeds = sell_amount * price
            self.risk.record_close(signal.mint, sell_amount, proceeds)

        logger.info(
            "[PAPER] %s %s (%s) ~%.6f SOL @ %.10f SOL/token — %s",
            signal.side, signal.mint, signal.symbol, signal.size_sol, price, signal.reason,
        )
        return True

    # -- live mode: build via PumpPortal, sign locally, submit to your own RPC ---
    def _execute_live(self, signal: Signal) -> tuple[bool, str]:
        from solana.rpc.api import Client as SolanaClient
        from solders.transaction import VersionedTransaction

        try:
            resp = requests.post(
                self.data_cfg.trade_api_url,
                json={
                    "publicKey": str(self.keypair.pubkey()),
                    "action": "buy" if signal.side == "BUY" else "sell",
                    "mint": signal.mint,
                    "denominatedInSol": "true" if signal.side == "BUY" else "false",
                    "amount": signal.size_sol if signal.side == "BUY" else "100%",
                    "slippage": self.trading_cfg.slippage_pct,
                    "priorityFee": self.trading_cfg.priority_fee_sol,
                    "pool": self.trading_cfg.pool,
                },
                timeout=15,
            )
            resp.raise_for_status()
            raw_tx_bytes = resp.content  # PumpPortal returns the serialized unsigned tx bytes directly
        except Exception:
            logger.exception("Failed to fetch unsigned transaction from PumpPortal for %s", signal.mint)
            return False, ""

        try:
            unsigned_tx = VersionedTransaction.from_bytes(raw_tx_bytes)
            signed_tx = VersionedTransaction(unsigned_tx.message, [self.keypair])
        except Exception:
            logger.exception(
                "Failed to sign transaction for %s — response may not have been a raw tx "
                "(check for a JSON error body): %.300s",
                signal.mint, raw_tx_bytes[:300],
            )
            return False, ""

        try:
            rpc = SolanaClient(self.wallet_cfg.rpc_url)
            send_resp = rpc.send_raw_transaction(bytes(signed_tx))
            tx_sig = str(send_resp.value)
        except Exception:
            logger.exception("Failed to submit transaction for %s", signal.mint)
            return False, ""

        logger.info(
            "[LIVE] %s %s (%s) ~%.6f SOL — tx=%s — %s",
            signal.side, signal.mint, signal.symbol, signal.size_sol, tx_sig, signal.reason,
        )

        # NOTE: submission succeeding does not guarantee on-chain confirmation
        # or the exact fill price/slippage. Reconcile against your wallet's
        # actual SPL token balances periodically rather than trusting this
        # alone, same caveat as bot/execution.py for Polymarket.
        price = signal.reference_price_sol or 0.0
        token_amount = signal.size_sol / price if price > 0 else 0.0
        if signal.side == "BUY":
            self.risk.record_open(signal.mint, signal.symbol, token_amount, signal.size_sol)
        else:
            pos = self.risk.positions.get(signal.mint)
            sell_amount = pos.token_amount if pos else token_amount
            self.risk.record_close(signal.mint, sell_amount, signal.size_sol)

        return True, tx_sig
