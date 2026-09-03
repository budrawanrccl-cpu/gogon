"""Thin wrapper around py-clob-client's ClobClient.

In paper mode we never construct a signing client at all — market data
(order books, prices) is public/read-only, so we use an unauthenticated
client for that and never touch order placement.
"""
from __future__ import annotations

import logging

from py_clob_client.client import ClobClient

from bot.config import WalletConfig

logger = logging.getLogger("polybot.client")


def build_client(wallet: WalletConfig) -> ClobClient:
    """Build a ClobClient.

    - Live trading: fully authenticated client with signing key + derived API creds.
    - Paper trading: read-only client (no key) used only for public market-data
      endpoints (order books, prices). No order-signing capability is exercised.
    """
    if wallet.live_trading:
        client = ClobClient(
            wallet.clob_host,
            key=wallet.private_key,
            chain_id=wallet.chain_id,
            signature_type=wallet.signature_type,
            funder=wallet.funder_address,
        )
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        logger.info("Live ClobClient initialized with API credentials.")
        return client

    client = ClobClient(wallet.clob_host, chain_id=wallet.chain_id)
    logger.info("Read-only ClobClient initialized (paper trading mode).")
    return client
