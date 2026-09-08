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

Transactions are submitted via pumpbot.solana_rpc's plain JSON-RPC
sendTransaction call rather than the `solana` package's RPC client — see
that module's docstring for why.
"""
from __future__ import annotations

import logging
import time

import requests

from pumpbot.config import DataConfig, TradingConfig, WalletConfig
from pumpbot.journal import TradeJournal
from pumpbot.risk import RiskManager
from pumpbot.solana_rpc import send_raw_transaction as _send_raw_transaction
from pumpbot.solana_rpc import wait_for_confirmation as _wait_for_confirmation
from pumpbot.strategies.base import Signal

logger = logging.getLogger("pumpbot.execution")

# skipPreflight=true (solana_rpc.py) already fixes the main cause of
# repeated BlockhashNotFound failures. These retries are a second safety
# net for ordinary transient issues (a slow response, a brief network
# blip) — each attempt re-fetches a fresh transaction from PumpPortal
# (fresh blockhash) rather than resubmitting stale signed bytes.
MAX_SUBMIT_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 1.5


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
        # Each attempt fetches a *fresh* unsigned transaction from PumpPortal
        # (i.e. a fresh recent-blockhash) rather than retrying the same signed
        # bytes — a Solana transaction's blockhash expires after ~60-90s, so
        # retrying a stale one would just fail again with the same
        # "BlockhashNotFound" error. This is common with slow/congested or
        # free public RPC endpoints; get a dedicated RPC (Helius, QuickNode,
        # Triton, etc.) if this keeps happening — see the README.
        last_error = ""
        for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
            tx_sig, error = self._attempt_live_trade(signal)
            if tx_sig:
                # A signature back from sendTransaction only means the RPC
                # node accepted it for forwarding — NOT that it landed or
                # succeeded on-chain (it can still fail while the network
                # fee is charged, or get dropped if its blockhash expires
                # before a leader includes it). Confirm before recording
                # this as a fill; see wait_for_confirmation's docstring for
                # why this matters — this is the fix for real capital
                # getting spent on "successful" trades that never actually
                # happened.
                confirmed, confirm_error = _wait_for_confirmation(self.wallet_cfg.rpc_url, tx_sig)
                if confirmed:
                    logger.info(
                        "[LIVE] %s %s (%s) ~%.6f SOL — tx=%s confirmed — %s",
                        signal.side, signal.mint, signal.symbol, signal.size_sol, tx_sig, signal.reason,
                    )
                    self._record_fill(signal)
                    return True, tx_sig

                error = f"sent (tx={tx_sig}) but not confirmed: {confirm_error}"

            last_error = error
            if attempt < MAX_SUBMIT_ATTEMPTS:
                logger.warning(
                    "Live %s attempt %d/%d failed for %s (%s): %s — retrying",
                    signal.side, attempt, MAX_SUBMIT_ATTEMPTS, signal.mint, signal.symbol, error,
                )
                time.sleep(RETRY_DELAY_SECONDS)

        logger.error(
            "Live %s failed for %s (%s) after %d attempts: %s",
            signal.side, signal.mint, signal.symbol, MAX_SUBMIT_ATTEMPTS, last_error,
        )
        return False, ""

    def _attempt_live_trade(self, signal: Signal) -> tuple[str, str]:
        """One fetch-sign-submit attempt. Returns (tx_signature, "") on
        success, or ("", error_message) on failure.
        """
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
        except Exception as e:
            logger.exception("Failed to fetch unsigned transaction from PumpPortal for %s", signal.mint)
            return "", f"fetch failed: {e}"

        try:
            unsigned_tx = VersionedTransaction.from_bytes(raw_tx_bytes)
            signed_tx = VersionedTransaction(unsigned_tx.message, [self.keypair])
        except Exception as e:
            logger.exception(
                "Failed to sign transaction for %s — response may not have been a raw tx "
                "(check for a JSON error body): %.300s",
                signal.mint, raw_tx_bytes[:300],
            )
            return "", f"sign failed: {e}"

        try:
            tx_sig = _send_raw_transaction(self.wallet_cfg.rpc_url, bytes(signed_tx))
        except Exception as e:
            logger.exception("Failed to submit transaction for %s", signal.mint)
            return "", f"submit failed: {e}"

        return tx_sig, ""

    def _record_fill(self, signal: Signal) -> None:
        # Only called after wait_for_confirmation() has verified the
        # transaction actually confirmed with no on-chain error — this is
        # NOT called for a submission that merely got a signature back
        # (see _execute_live). It still doesn't know the *exact* fill
        # price/slippage (that would need parsing the confirmed tx's token
        # balance changes), so size_sol/reference_price_sol here are still
        # the intended amounts, not verified proceeds — reconcile against
        # your wallet's actual SPL token balances periodically (e.g.
        # scripts/check_wallet_holdings.py) rather than trusting this
        # alone, same caveat as bot/execution.py for Polymarket.
        price = signal.reference_price_sol or 0.0
        token_amount = signal.size_sol / price if price > 0 else 0.0
        if signal.side == "BUY":
            self.risk.record_open(signal.mint, signal.symbol, token_amount, signal.size_sol)
        else:
            pos = self.risk.positions.get(signal.mint)
            sell_amount = pos.token_amount if pos else token_amount
            self.risk.record_close(signal.mint, sell_amount, signal.size_sol)
