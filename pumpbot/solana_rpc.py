"""Minimal Solana JSON-RPC helpers over plain `requests` calls.

Deliberately does not depend on the `solana` package's RPC client: that
package has changed its module layout across versions (some recent
versions removed the sync `solana.rpc.api.Client` in favor of an
async-only client), which would make anything built on it break depending
on exactly which version happens to be installed. A JSON-RPC call is a
handful of lines and a stable wire format — see
https://solana.com/docs/rpc/http for the methods used here.
"""
from __future__ import annotations

import base64

import requests


def get_balance_sol(rpc_url: str, address: str, timeout: float = 10.0) -> float:
    """Return the SOL balance of `address` via the getBalance RPC method.
    Raises on any network/RPC-level error — callers decide how to handle it.
    """
    resp = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"RPC getBalance error: {payload['error']}")
    lamports = payload["result"]["value"]
    return lamports / 1_000_000_000


def send_raw_transaction(rpc_url: str, raw_tx: bytes, timeout: float = 20.0) -> str:
    """Submit a fully-signed transaction via the sendTransaction RPC method.
    Returns the transaction signature. Raises on any RPC-level error.
    """
    resp = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(raw_tx).decode("ascii"),
                {"encoding": "base64", "skipPreflight": False, "maxRetries": 3},
            ],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"RPC sendTransaction error: {payload['error']}")
    return str(payload["result"])
