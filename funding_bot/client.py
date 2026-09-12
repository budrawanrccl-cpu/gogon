"""Thin wrapper around ccxt for Binance spot + USDT-M perpetual futures.

In paper mode we never pass API credentials at all — funding rates, mark
prices, and spot tickers are all public/read-only endpoints, so an
unauthenticated client is enough and order-placement is never exercised.
"""
from __future__ import annotations

import logging

import ccxt

from funding_bot.config import ExchangeConfig

logger = logging.getLogger("fundingbot.client")


def build_clients(cfg: ExchangeConfig) -> tuple[ccxt.Exchange, ccxt.Exchange]:
    """Build (spot_client, futures_client).

    - Live trading: both clients carry API key/secret so orders can be signed.
    - Paper trading: unauthenticated clients used only for public market-data
      endpoints (tickers, funding rates). No order-signing capability needed
      or exercised.
    """
    creds = {}
    if cfg.live_trading:
        creds = {"apiKey": cfg.api_key, "secret": cfg.api_secret}

    spot = ccxt.binance({**creds, "options": {"defaultType": "spot"}, "enableRateLimit": True})
    futures = ccxt.binanceusdm({**creds, "enableRateLimit": True})

    if cfg.testnet:
        spot.set_sandbox_mode(True)
        futures.set_sandbox_mode(True)

    spot.load_markets()
    futures.load_markets()

    mode = "LIVE" if cfg.live_trading else "paper (read-only)"
    logger.info(
        "Binance clients initialized: mode=%s testnet=%s",
        mode,
        cfg.testnet,
    )
    return spot, futures
