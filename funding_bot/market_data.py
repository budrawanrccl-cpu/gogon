"""Funding-rate/price discovery for the spot+perp hedge.

Parsing here is deliberately defensive, like `bot/market_data.py`: ccxt's
unified funding-rate payload has field-naming variance across exchanges (and
Binance itself now supports non-8h funding intervals on some symbols), so
unknown/missing fields fall back to safe defaults rather than crashing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from funding_bot.config import SymbolsConfig

logger = logging.getLogger("fundingbot.market_data")

DEFAULT_FUNDING_INTERVAL_HOURS = 8.0


@dataclass
class FundingSnapshot:
    """One symbol's current funding-rate/price picture.

    `base` is the asset (e.g. "BTC"); `spot_symbol`/`perp_symbol` are the
    ccxt unified symbols used to place orders on each market.
    """

    base: str
    spot_symbol: str
    perp_symbol: str
    funding_rate: float  # fraction per funding interval, e.g. 0.0001 = 0.01%
    funding_interval_hours: float
    next_funding_time_ms: int | None
    mark_price: float
    spot_price: float

    @property
    def apr(self) -> float:
        """Funding rate annualized, assuming it stays constant (it won't —
        this is a snapshot estimate, not a forecast)."""
        if self.funding_interval_hours <= 0:
            return 0.0
        periods_per_year = (24.0 / self.funding_interval_hours) * 365.0
        return self.funding_rate * periods_per_year

    @property
    def basis_pct(self) -> float:
        if self.spot_price <= 0:
            return 0.0
        return (self.mark_price - self.spot_price) / self.spot_price


def _to_symbols(base: str, quote: str) -> tuple[str, str]:
    spot_symbol = f"{base}/{quote}"
    perp_symbol = f"{base}/{quote}:{quote}"
    return spot_symbol, perp_symbol


def discover_symbols(futures_client, cfg: SymbolsConfig) -> list[str]:
    """Return a list of base assets to scan.

    If `cfg.whitelist` is set, use it as-is. Otherwise rank all USDT-M perp
    symbols by |funding rate| and take the top N — the highest-funding
    symbols are where the arbitrage edge (if any) is largest.
    """
    if cfg.whitelist:
        return list(cfg.whitelist)

    try:
        rates = futures_client.fetch_funding_rates()
    except Exception:
        logger.exception("Failed to fetch funding rates for symbol discovery")
        return []

    candidates = []
    for symbol, info in (rates or {}).items():
        if not isinstance(info, dict):
            continue
        # Unified perpetual symbols look like "BTC/USDT:USDT".
        if ":" not in symbol or "/" not in symbol:
            continue
        base, _, rest = symbol.partition("/")
        quote = rest.split(":", 1)[0]
        if quote.upper() != cfg.quote_asset:
            continue
        rate = info.get("fundingRate")
        if rate is None:
            continue
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            continue
        candidates.append((base.upper(), rate))

    candidates.sort(key=lambda pair: abs(pair[1]), reverse=True)
    top = [base for base, _ in candidates[: cfg.auto_discover_top_n]]
    logger.info("Auto-discovered %d symbols by funding rate: %s", len(top), top)
    return top


def _num(d: dict, *keys, default=None):
    for k in keys:
        if d.get(k) is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                pass
    return default


def fetch_snapshot(spot_client, futures_client, base: str, quote: str) -> FundingSnapshot | None:
    """Fetch one symbol's funding rate + spot/mark price. Returns None on
    any failure (missing market, API error, unparseable payload) rather than
    raising — callers should just skip the symbol for this cycle."""
    spot_symbol, perp_symbol = _to_symbols(base, quote)

    try:
        funding = futures_client.fetch_funding_rate(perp_symbol)
    except Exception:
        logger.warning("Could not fetch funding rate for %s", perp_symbol, exc_info=True)
        return None

    funding_rate = _num(funding, "fundingRate")
    mark_price = _num(funding, "markPrice", "indexPrice")
    next_funding_ms = funding.get("nextFundingTimestamp") or funding.get("fundingTimestamp")

    raw_info = funding.get("info") or {}
    interval = _num(raw_info, "fundingIntervalHours", default=None)

    if funding_rate is None or mark_price is None:
        logger.warning("Incomplete funding payload for %s: %s", perp_symbol, funding)
        return None

    try:
        spot_ticker = spot_client.fetch_ticker(spot_symbol)
    except Exception:
        logger.warning("Could not fetch spot ticker for %s", spot_symbol, exc_info=True)
        return None

    spot_price = _num(spot_ticker, "last", "close", default=mark_price)

    return FundingSnapshot(
        base=base,
        spot_symbol=spot_symbol,
        perp_symbol=perp_symbol,
        funding_rate=funding_rate,
        funding_interval_hours=interval or DEFAULT_FUNDING_INTERVAL_HOURS,
        next_funding_time_ms=int(next_funding_ms) if next_funding_ms else None,
        mark_price=mark_price,
        spot_price=spot_price,
    )
