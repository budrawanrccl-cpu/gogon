"""Watches a Solana wallet's transaction history and detects pump.fun
bonding-curve buys/sells it makes.

Detection deliberately does *not* try to decode pump.fun's raw instruction
bytes. Instead it reads the same pre/post SOL and token balance snapshots
that every Solana transaction already carries in its `meta` — the same data
block explorers use — which is far more robust than hand-parsing instruction
data and doesn't drift if pump.fun changes its instruction layout.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pumpfun_bot.pumpfun_program import PUMPFUN_PROGRAM_ID
from pumpfun_bot.rpc import RpcError, SolanaRpcClient

logger = logging.getLogger("pumpfunbot.trade_detector")

_PUMPFUN_PROGRAM_ID_STR = str(PUMPFUN_PROGRAM_ID)


@dataclass
class DetectedTrade:
    signature: str
    wallet: str
    mint: str
    side: str  # "BUY" or "SELL"
    sol_amount: float  # approximate — includes network fee and any rent for new accounts
    token_amount: float
    block_time: int | None


def _all_program_ids(tx: dict) -> set[str]:
    ids: set[str] = set()
    message = tx.get("transaction", {}).get("message", {})
    for ix in message.get("instructions", []) or []:
        pid = ix.get("programId")
        if pid:
            ids.add(pid)
    for inner in tx.get("meta", {}).get("innerInstructions", []) or []:
        for ix in inner.get("instructions", []) or []:
            pid = ix.get("programId")
            if pid:
                ids.add(pid)
    return ids


def _instruction_side_from_logs(logs: list[str]) -> str | None:
    for line in logs or []:
        if "Instruction: Buy" in line:
            return "BUY"
        if "Instruction: Sell" in line:
            return "SELL"
    return None


def _account_index(tx: dict, wallet: str) -> int | None:
    message = tx.get("transaction", {}).get("message", {})
    for idx, acct in enumerate(message.get("accountKeys", []) or []):
        pubkey = acct.get("pubkey") if isinstance(acct, dict) else acct
        if pubkey == wallet:
            return idx
    return None


def _wallet_token_delta(tx: dict, wallet: str, side: str) -> tuple[str, float] | None:
    """Return (mint, abs(ui amount delta)) for the wallet-owned token balance that
    moved in the direction implied by `side`. None if nothing matches."""
    meta = tx.get("meta", {}) or {}
    pre = {(b.get("accountIndex"), b.get("mint")): b for b in (meta.get("preTokenBalances") or [])}
    post = {(b.get("accountIndex"), b.get("mint")): b for b in (meta.get("postTokenBalances") or [])}

    keys = set(pre.keys()) | set(post.keys())
    best: tuple[str, float] | None = None
    for key in keys:
        pre_bal = pre.get(key)
        post_bal = post.get(key)
        owner = (post_bal or pre_bal or {}).get("owner")
        if owner != wallet:
            continue
        mint = key[1]
        pre_ui = ((pre_bal or {}).get("uiTokenAmount") or {}).get("uiAmount") or 0.0
        post_ui = ((post_bal or {}).get("uiTokenAmount") or {}).get("uiAmount") or 0.0
        delta = post_ui - pre_ui
        if side == "BUY" and delta > 0:
            if best is None or delta > best[1]:
                best = (mint, delta)
        elif side == "SELL" and delta < 0:
            if best is None or abs(delta) > best[1]:
                best = (mint, abs(delta))
    return best


def parse_pumpfun_trade(tx: dict | None, wallet: str, signature: str) -> DetectedTrade | None:
    """Inspect one confirmed transaction; return a DetectedTrade if `wallet`
    made a pump.fun buy/sell in it, else None."""
    if not tx:
        return None
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return None  # failed transaction, nothing actually happened on-chain

    if _PUMPFUN_PROGRAM_ID_STR not in _all_program_ids(tx):
        return None

    side = _instruction_side_from_logs(meta.get("logMessages") or [])
    if side is None:
        return None

    match = _wallet_token_delta(tx, wallet, side)
    if match is None:
        return None
    mint, token_amount = match

    idx = _account_index(tx, wallet)
    sol_amount = 0.0
    if idx is not None:
        pre_balances = meta.get("preBalances") or []
        post_balances = meta.get("postBalances") or []
        if idx < len(pre_balances) and idx < len(post_balances):
            delta_lamports = pre_balances[idx] - post_balances[idx]
            sol_amount = abs(delta_lamports) / 1_000_000_000

    return DetectedTrade(
        signature=signature,
        wallet=wallet,
        mint=mint,
        side=side,
        sol_amount=sol_amount,
        token_amount=token_amount,
        block_time=tx.get("blockTime"),
    )


class WalletWatcher:
    """Tracks one wallet's last-seen signature and yields newly detected trades.

    The first poll after startup never yields trades — it just seeds
    `last_signature` to the wallet's current newest transaction, so restarting
    the bot doesn't replay a wallet's entire trade history as fresh copies.
    """

    def __init__(self, wallet: str, signatures_per_poll: int = 20):
        self.wallet = wallet
        self.signatures_per_poll = signatures_per_poll
        self.last_signature: str | None = None
        self._seeded = False

    def poll(self, rpc: SolanaRpcClient) -> list[DetectedTrade]:
        try:
            entries = rpc.get_signatures_for_address(self.wallet, limit=self.signatures_per_poll)
        except RpcError:
            logger.exception("Failed to fetch signatures for %s", self.wallet)
            return []

        if not entries:
            return []

        if not self._seeded:
            # Nothing to copy yet — just establish the starting point.
            self.last_signature = entries[0]["signature"]
            self._seeded = True
            logger.info("Watching %s from signature %s onward", self.wallet, self.last_signature)
            return []

        # entries are newest-first; take everything before our last-seen signature.
        new_entries = []
        for entry in entries:
            if entry["signature"] == self.last_signature:
                break
            new_entries.append(entry)

        if not new_entries:
            return []

        self.last_signature = entries[0]["signature"]

        trades: list[DetectedTrade] = []
        for entry in reversed(new_entries):  # oldest first
            if entry.get("err") is not None:
                continue
            sig = entry["signature"]
            try:
                tx = rpc.get_transaction(sig)
            except RpcError:
                logger.exception("Failed to fetch transaction %s", sig)
                continue
            trade = parse_pumpfun_trade(tx, self.wallet, sig)
            if trade is not None:
                trades.append(trade)
        return trades
