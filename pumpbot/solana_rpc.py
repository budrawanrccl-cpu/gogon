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
import time

import requests


def _post_with_retry(rpc_url: str, body: dict, timeout: float, max_retries: int = 5) -> dict:
    """POST a JSON-RPC request, retrying with exponential backoff on 429
    (rate limited). Public RPC endpoints (the default,
    api.mainnet-beta.solana.com) have very tight rate limits — bulk checks
    like scripts/check_wallet_holdings.py can trip these hard, especially
    with a low-throughput RPC. A paid RPC (e.g. Helius, via SOLANA_RPC_URL)
    has much higher limits and rarely needs this, but the retry is cheap
    insurance either way. Raises the underlying HTTPError if still rate
    limited after `max_retries` attempts.
    """
    delay = 1.0
    for attempt in range(max_retries + 1):
        resp = requests.post(rpc_url, json=body, timeout=timeout)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        if attempt == max_retries:
            resp.raise_for_status()  # exhausted retries — surface the 429
        retry_after = resp.headers.get("Retry-After")
        wait = float(retry_after) if retry_after else delay
        time.sleep(wait)
        delay = min(delay * 2, 30.0)
    raise RuntimeError("unreachable")  # loop always returns or raises above


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


def get_transaction_sol_delta(
    rpc_url: str, signature: str, wallet_address: str, timeout: float = 15.0
) -> float:
    """Return the net SOL change (positive or negative) for `wallet_address`
    in a single confirmed transaction, via the getTransaction RPC method.

    Uses pre/postBalances from the transaction's metadata rather than
    re-deriving it from instruction data — this is exact and already nets
    out the network/priority fee (the fee payer's postBalance already
    reflects it), so summing this across a session's transactions gives an
    exact realized P&L without needing a "balance before/after" snapshot.

    Raises RuntimeError if the transaction isn't found (e.g. wrong network,
    not yet finalized, or an invalid signature) or if `wallet_address`
    doesn't appear in the transaction's account keys.
    """
    payload = _post_with_retry(
        rpc_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        },
        timeout,
    )
    if "error" in payload:
        raise RuntimeError(f"RPC getTransaction error: {payload['error']}")
    result = payload["result"]
    if result is None:
        raise RuntimeError(f"Transaction {signature} not found (wrong network, or not finalized yet)")

    account_keys = result["transaction"]["message"]["accountKeys"]
    idx = next((i for i, ak in enumerate(account_keys) if ak["pubkey"] == wallet_address), None)
    if idx is None:
        raise RuntimeError(f"Wallet {wallet_address} not found in accountKeys of transaction {signature}")

    meta = result["meta"]
    pre_lamports = meta["preBalances"][idx]
    post_lamports = meta["postBalances"][idx]
    return (post_lamports - pre_lamports) / 1_000_000_000


def get_token_balance(
    rpc_url: str, owner_address: str, mint_address: str, timeout: float = 15.0
) -> float:
    """Return how many units of `mint_address` `owner_address` actually
    holds right now, via getTokenAccountsByOwner. Ground truth for "did I
    actually still hold this after a sell" — unlike the trade journal CSV,
    this reflects real on-chain state regardless of whether a past buy/sell
    transaction actually confirmed. Returns 0.0 if the wallet has no token
    account for this mint (never held it, or the account was fully drained
    and closed).
    """
    payload = _post_with_retry(
        rpc_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                owner_address,
                {"mint": mint_address},
                {"encoding": "jsonParsed"},
            ],
        },
        timeout,
    )
    if "error" in payload:
        raise RuntimeError(f"RPC getTokenAccountsByOwner error: {payload['error']}")

    accounts = payload["result"]["value"]
    total = 0.0
    for acc in accounts:
        info = acc["account"]["data"]["parsed"]["info"]
        ui_amount = info["tokenAmount"]["uiAmount"]
        total += ui_amount or 0.0
    return total


def send_raw_transaction(rpc_url: str, raw_tx: bytes, timeout: float = 20.0) -> str:
    """Submit a fully-signed transaction via the sendTransaction RPC method.
    Returns the transaction signature. Raises on any RPC-level error.

    skipPreflight=True: without it, the RPC node runs its own local
    simulation before forwarding the transaction, using *its own* view of
    recent blockhashes — if that specific node is even slightly behind,
    it rejects with "Transaction simulation failed: BlockhashNotFound"
    even though the transaction (built by PumpPortal, against a different
    node) is actually valid and would land fine. Skipping preflight lets
    the actual network/leader decide instead of one RPC node's local
    (possibly stale) view. This is the standard fix for exactly this
    failure mode — see
    https://www.helius.dev/blog/how-to-deal-with-blockhash-errors-on-solana.
    The tradeoff: some other real errors (e.g. insufficient funds) that
    preflight would have caught early now only surface on-chain instead —
    acceptable here since nothing in this codebase relies on preflight's
    early rejection for correctness.
    """
    resp = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(raw_tx).decode("ascii"),
                {"encoding": "base64", "skipPreflight": True, "maxRetries": 3},
            ],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"RPC sendTransaction error: {payload['error']}")
    return str(payload["result"])
