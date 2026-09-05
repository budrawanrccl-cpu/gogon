"""Minimal Solana JSON-RPC client (HTTP, no websockets).

Deliberately thin — just the handful of RPC methods this bot needs, wrapped
with basic error handling. Wallet scanning uses only free, read-only calls
(`getSignaturesForAddress`, `getTransaction`); a signing key is only ever
needed for `sendTransaction` in live mode.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("pumpfunbot.rpc")


class RpcError(Exception):
    pass


class SolanaRpcClient:
    def __init__(self, rpc_url: str, timeout: float = 20.0):
        self.rpc_url = rpc_url
        self.timeout = timeout
        self._session = requests.Session()
        self._next_id = 1

    def _call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._next_id += 1
        resp = self._session.post(self.rpc_url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RpcError(f"{method} failed: {body['error']}")
        return body.get("result")

    # -- read-only, used for wallet scanning --------------------------------
    def get_signatures_for_address(
        self, address: str, limit: int = 20, before: str | None = None
    ) -> list[dict]:
        opts: dict[str, Any] = {"limit": limit}
        if before:
            opts["before"] = before
        result = self._call("getSignaturesForAddress", [address, opts])
        return result or []

    def get_transaction(self, signature: str) -> dict | None:
        opts = {
            "encoding": "jsonParsed",
            "commitment": "confirmed",
            "maxSupportedTransactionVersion": 0,
        }
        return self._call("getTransaction", [signature, opts])

    def get_account_info(self, address: str) -> dict | None:
        result = self._call("getAccountInfo", [address, {"encoding": "base64"}])
        return result.get("value") if result else None

    def get_balance_lamports(self, address: str) -> int:
        result = self._call("getBalance", [address])
        return int(result.get("value", 0)) if result else 0

    def get_latest_blockhash(self) -> str:
        result = self._call("getLatestBlockhash", [{"commitment": "confirmed"}])
        return result["value"]["blockhash"]

    # -- write, only used in live mode --------------------------------------
    def send_raw_transaction(self, raw_tx_base64: str) -> str:
        """Submit a signed, base64-encoded transaction. Returns the signature."""
        opts = {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}
        return self._call("sendTransaction", [raw_tx_base64, opts])
