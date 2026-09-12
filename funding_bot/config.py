"""Loads and validates funding-bot configuration from .env (secrets) and YAML
(strategy/risk), mirroring the layout of `bot/config.py`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv


@dataclass
class ExchangeConfig:
    api_key: str | None
    api_secret: str | None
    testnet: bool
    live_trading: bool


@dataclass
class SymbolsConfig:
    # Base assets, e.g. ["BTC", "ETH"]. Empty -> auto-discover by funding rate.
    whitelist: list[str] = field(default_factory=list)
    # Used only when whitelist is empty: scan the top N symbols by |funding rate|.
    auto_discover_top_n: int = 10
    quote_asset: str = "USDT"
    # How often (in cycles) to refresh the auto-discovered symbol list.
    rediscover_every_cycles: int = 30


@dataclass
class RiskConfig:
    max_position_usd: float = 100.0
    max_total_exposure_usd: float = 500.0
    max_daily_loss_usd: float = 50.0
    min_order_size_usd: float = 10.0


@dataclass
class FundingArbitrageConfig:
    enabled: bool = True
    # Annualized funding rate (APR) required to open a position, net of fee_buffer_apr.
    min_funding_rate_apr: float = 0.15
    # Exit once net APR falls below this (hysteresis so we don't flip-flop
    # in/out of a position right around the entry threshold).
    exit_funding_rate_apr: float = 0.03
    # Estimated round-trip trading-fee/slippage drag, expressed as an APR,
    # subtracted from the observed funding APR before comparing to thresholds.
    fee_buffer_apr: float = 0.02
    # Skip/exit if |mark_price - spot_price| / spot_price exceeds this —
    # a wide basis means the hedge is imprecise and execution risk is higher.
    max_basis_pct: float = 0.005
    # Negative funding rate (shorts pay longs) can only be collected by
    # holding the position in reverse (short spot via margin + long perp).
    # This bot does not implement spot margin borrowing, so this flag is a
    # placeholder that currently just enables a one-time warning — it is
    # NOT a way to actually trade the negative-funding side yet.
    allow_negative_funding: bool = False


@dataclass
class Settings:
    exchange: ExchangeConfig
    symbols: SymbolsConfig
    risk: RiskConfig
    funding_arbitrage: FundingArbitrageConfig
    polling_interval_seconds: int = 60


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: str | None = None, env_path: str | None = None) -> Settings:
    """Load configuration. Call once at startup.

    env_path defaults to a `.env` file in the current working directory (if present).
    config_path defaults to the FUNDING_BOT_CONFIG_PATH env var, or
    config/funding_settings.yaml.
    """
    load_dotenv(dotenv_path=env_path, override=False)

    path = config_path or os.getenv("FUNDING_BOT_CONFIG_PATH", "config/funding_settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    symbols_raw = raw.get("symbols", {}) or {}
    risk_raw = raw.get("risk", {}) or {}
    arb_raw = raw.get("funding_arbitrage", {}) or {}

    exchange = ExchangeConfig(
        api_key=os.getenv("BINANCE_API_KEY") or None,
        api_secret=os.getenv("BINANCE_API_SECRET") or None,
        testnet=_bool_env("BINANCE_TESTNET", False),
        live_trading=_bool_env("FUNDING_LIVE_TRADING", False),
    )

    settings = Settings(
        exchange=exchange,
        symbols=SymbolsConfig(
            whitelist=[str(s).upper() for s in (symbols_raw.get("whitelist", []) or [])],
            auto_discover_top_n=int(symbols_raw.get("auto_discover_top_n", 10)),
            quote_asset=str(symbols_raw.get("quote_asset", "USDT")).upper(),
            rediscover_every_cycles=int(symbols_raw.get("rediscover_every_cycles", 30)),
        ),
        risk=RiskConfig(
            max_position_usd=float(risk_raw.get("max_position_usd", 100.0)),
            max_total_exposure_usd=float(risk_raw.get("max_total_exposure_usd", 500.0)),
            max_daily_loss_usd=float(risk_raw.get("max_daily_loss_usd", 50.0)),
            min_order_size_usd=float(risk_raw.get("min_order_size_usd", 10.0)),
        ),
        funding_arbitrage=FundingArbitrageConfig(
            enabled=bool(arb_raw.get("enabled", True)),
            min_funding_rate_apr=float(arb_raw.get("min_funding_rate_apr", 0.15)),
            exit_funding_rate_apr=float(arb_raw.get("exit_funding_rate_apr", 0.03)),
            fee_buffer_apr=float(arb_raw.get("fee_buffer_apr", 0.02)),
            max_basis_pct=float(arb_raw.get("max_basis_pct", 0.005)),
            allow_negative_funding=bool(arb_raw.get("allow_negative_funding", False)),
        ),
        polling_interval_seconds=int(raw.get("polling_interval_seconds", 60)),
    )

    if exchange.live_trading:
        missing = []
        if not exchange.api_key:
            missing.append("BINANCE_API_KEY")
        if not exchange.api_secret:
            missing.append("BINANCE_API_SECRET")
        if missing:
            raise ValueError(
                "FUNDING_LIVE_TRADING=true but missing required env vars: "
                + ", ".join(missing)
                + ". Refusing to start in live mode without full API credentials."
            )

    return settings
