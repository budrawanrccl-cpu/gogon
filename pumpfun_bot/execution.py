"""Turns a CopySignal into either a simulated fill (paper mode) or a real,
signed pump.fun buy/sell transaction (live mode), and updates risk/position
state.
"""
from __future__ import annotations

import base64
import logging

from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from pumpfun_bot.config import ExecutionConfig
from pumpfun_bot.copy_engine import CopySignal
from pumpfun_bot.journal import TradeJournal
from pumpfun_bot.pumpfun_program import (
    LAMPORTS_PER_SOL,
    TOKEN_DECIMALS,
    apply_slippage,
    build_buy_instruction,
    build_create_ata_idempotent_instruction,
    build_sell_instruction,
    compute_buy_tokens_out,
    compute_sell_sol_out,
    find_bonding_curve_pda,
    find_global_pda,
    parse_bonding_curve_account,
    parse_global_account,
)
from pumpfun_bot.risk import RiskManager
from pumpfun_bot.rpc import SolanaRpcClient

logger = logging.getLogger("pumpfunbot.execution")


class TradeExecutor:
    def __init__(
        self,
        rpc: SolanaRpcClient,
        risk: RiskManager,
        journal: TradeJournal,
        execution_cfg: ExecutionConfig,
        live: bool,
        keypair: Keypair | None = None,
    ):
        self.rpc = rpc
        self.risk = risk
        self.journal = journal
        self.cfg = execution_cfg
        self.live = live
        self.keypair = keypair
        if live and keypair is None:
            raise ValueError("live=True requires a signing keypair")

    def execute(self, signal: CopySignal) -> bool:
        if signal.side == "BUY":
            allowed, reason = self.risk.can_open(signal.mint, signal.sol_size)
            if not allowed:
                logger.info("Skipping BUY %s: %s", signal.mint, reason)
                return False

        if self.live:
            filled, tx_sig = self._execute_live(signal)
        else:
            filled, tx_sig = self._execute_paper(signal), ""

        self.journal.record(signal, mode="live" if self.live else "paper", filled=filled, tx_signature=tx_sig)
        return filled

    # -- paper mode: assume the trade fills at the current bonding-curve price --
    def _execute_paper(self, signal: CopySignal) -> bool:
        try:
            bonding_curve = find_bonding_curve_pda(Pubkey.from_string(signal.mint))
            account = self.rpc.get_account_info(str(bonding_curve))
            if account:
                data = base64.b64decode(account["data"][0])
                curve = parse_bonding_curve_account(data)
                lamports = int(signal.sol_size * LAMPORTS_PER_SOL)
                if signal.side == "BUY":
                    token_amount_raw = compute_buy_tokens_out(
                        curve.virtual_sol_reserves, curve.virtual_token_reserves, lamports
                    )
                else:
                    token_amount_raw = 0
                token_amount = token_amount_raw / (10**TOKEN_DECIMALS)
            else:
                token_amount = 0.0
        except Exception:
            logger.exception("Paper fill: could not fetch bonding curve for %s, using 0 tokens", signal.mint)
            token_amount = 0.0

        if signal.side == "BUY":
            self.risk.record_open(signal.mint, token_amount, signal.sol_size)
        else:
            self.risk.record_close(signal.mint, token_amount, signal.sol_size)

        logger.info(
            "[PAPER] %s %.6f SOL of mint %s — %s",
            signal.side,
            signal.sol_size,
            signal.mint,
            signal.reason,
        )
        return True

    # -- live mode: build, sign, and submit a real buy/sell against the bonding curve --
    def _execute_live(self, signal: CopySignal) -> tuple[bool, str]:
        assert self.keypair is not None
        mint = Pubkey.from_string(signal.mint)
        owner = self.keypair.pubkey()

        try:
            global_account_data = self.rpc.get_account_info(str(find_global_pda()))
            bonding_curve_pda = find_bonding_curve_pda(mint)
            curve_account = self.rpc.get_account_info(str(bonding_curve_pda))
            if not global_account_data or not curve_account:
                logger.warning("Missing global/bonding-curve account for mint %s; skipping live trade", signal.mint)
                return False, ""

            global_account = parse_global_account(base64.b64decode(global_account_data["data"][0]))
            curve = parse_bonding_curve_account(base64.b64decode(curve_account["data"][0]))
            if curve.complete:
                logger.info("Bonding curve for %s already completed (migrated); skipping", signal.mint)
                return False, ""

            lamports = int(signal.sol_size * LAMPORTS_PER_SOL)

            if signal.side == "BUY":
                token_amount_raw = compute_buy_tokens_out(
                    curve.virtual_sol_reserves, curve.virtual_token_reserves, lamports
                )
                max_sol_cost = apply_slippage(lamports, self.cfg.slippage_bps, worse_direction=True)
                instructions = [
                    build_create_ata_idempotent_instruction(owner, owner, mint),
                    build_buy_instruction(
                        buyer=owner,
                        mint=mint,
                        fee_recipient=global_account.fee_recipient,
                        token_amount_raw=token_amount_raw,
                        max_sol_cost_lamports=max_sol_cost,
                    ),
                ]
            else:
                pos = self.risk.positions.get(signal.mint)
                if pos is None or pos.token_amount <= 0:
                    logger.info("No open position in %s to sell; skipping", signal.mint)
                    return False, ""
                token_amount_raw = int(pos.token_amount * (10**TOKEN_DECIMALS))
                expected_sol_out = compute_sell_sol_out(
                    curve.virtual_sol_reserves, curve.virtual_token_reserves, token_amount_raw
                )
                min_sol_output = apply_slippage(expected_sol_out, self.cfg.slippage_bps, worse_direction=False)
                instructions = [
                    build_sell_instruction(
                        seller=owner,
                        mint=mint,
                        fee_recipient=global_account.fee_recipient,
                        token_amount_raw=token_amount_raw,
                        min_sol_output_lamports=min_sol_output,
                    )
                ]

            blockhash = Hash.from_string(self.rpc.get_latest_blockhash())
            message = Message.new_with_blockhash(instructions, owner, blockhash)
            tx = Transaction.new_unsigned(message)
            tx.sign([self.keypair], blockhash)
            raw_b64 = base64.b64encode(bytes(tx)).decode("ascii")

            signature = self.rpc.send_raw_transaction(raw_b64)
        except Exception:
            logger.exception("Live execution failed for %s %s", signal.side, signal.mint)
            return False, ""

        # NOTE: `sendTransaction` only confirms the RPC accepted and forwarded
        # the transaction, not that it landed/succeeded on-chain. Confirm the
        # signature (e.g. getSignatureStatuses) and reconcile your actual
        # token/SOL balances before trusting this state for anything beyond
        # a log line.
        logger.info(
            "[LIVE] %s %.6f SOL of mint %s -> signature=%s",
            signal.side,
            signal.sol_size,
            signal.mint,
            signature,
        )

        if signal.side == "BUY":
            token_amount = token_amount_raw / (10**TOKEN_DECIMALS)
            self.risk.record_open(signal.mint, token_amount, signal.sol_size)
        else:
            token_amount = token_amount_raw / (10**TOKEN_DECIMALS)
            self.risk.record_close(signal.mint, token_amount, signal.sol_size)

        return True, signature
