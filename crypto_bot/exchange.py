"""Thin wrapper around ccxt: historical OHLCV fetching + order placement.

Kept separate from strategy/risk/backtest so those stay pure-Python and
testable without ccxt or a network connection.
"""
from __future__ import annotations

import logging
import time

import ccxt

from crypto_bot.config import ExchangeConfig
from crypto_bot.models import Bar

logger = logging.getLogger("cryptobot.exchange")


def build_exchange(cfg: ExchangeConfig) -> ccxt.Exchange:
    if not hasattr(ccxt, cfg.exchange_id):
        raise ValueError(f"unknown ccxt exchange id: {cfg.exchange_id!r}")
    exchange_class = getattr(ccxt, cfg.exchange_id)
    exchange: ccxt.Exchange = exchange_class(
        {
            "apiKey": cfg.api_key,
            "secret": cfg.api_secret,
            "enableRateLimit": True,
        }
    )
    if cfg.testnet:
        if not hasattr(exchange, "set_sandbox_mode"):
            raise ValueError(f"{cfg.exchange_id} has no ccxt sandbox/testnet support")
        exchange.set_sandbox_mode(True)
        logger.info("Exchange %s: sandbox/testnet mode ON", cfg.exchange_id)
    exchange.load_markets()
    return exchange


def _to_bars(raw: list[list[float]]) -> list[Bar]:
    return [
        Bar(timestamp=int(r[0]), open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4]), volume=float(r[5]))
        for r in raw
    ]


def fetch_recent_bars(exchange: ccxt.Exchange, symbol: str, timeframe: str, limit: int = 500) -> list[Bar]:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    return _to_bars(raw)


def fetch_ohlcv_history(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int | None = None,
    page_limit: int = 1000,
) -> list[Bar]:
    """Page through fetch_ohlcv to build a longer history for backtesting."""
    by_ts: dict[int, Bar] = {}
    cursor = since_ms
    tf_ms = int(exchange.parse_timeframe(timeframe) * 1000)

    while True:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=page_limit)
        if not raw:
            break
        batch = _to_bars(raw)
        for b in batch:
            by_ts[b.timestamp] = b
        last_ts = batch[-1].timestamp
        if until_ms is not None and last_ts >= until_ms:
            break
        if len(batch) < page_limit:
            break
        cursor = last_ts + tf_ms
        time.sleep(exchange.rateLimit / 1000.0)

    bars = [by_ts[k] for k in sorted(by_ts)]
    if until_ms is not None:
        bars = [b for b in bars if b.timestamp <= until_ms]
    return bars


def only_closed_bars(exchange: ccxt.Exchange, bars: list[Bar], timeframe: str) -> list[Bar]:
    """Drop a trailing bar that's still in progress (its window hasn't closed
    yet as of `exchange`'s clock) — acting on it would be lookahead."""
    if not bars:
        return bars
    tf_ms = int(exchange.parse_timeframe(timeframe) * 1000)
    now_ms = exchange.milliseconds()
    if bars[-1].timestamp + tf_ms > now_ms:
        return bars[:-1]
    return bars


def fetch_last_price(exchange: ccxt.Exchange, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    return float(ticker["last"])


def place_market_order(exchange: ccxt.Exchange, symbol: str, side: str, amount: float) -> dict:
    amount = float(exchange.amount_to_precision(symbol, amount))
    logger.info("Submitting LIVE market %s order: %s amount=%s", side.upper(), symbol, amount)
    return exchange.create_order(symbol, type="market", side=side, amount=amount)
