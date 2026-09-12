"""Loads crypto bot configuration from .env (secrets) and YAML (strategy/risk)."""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv

from crypto_bot.risk import RiskConfig
from crypto_bot.strategy import DonchianConfig


@dataclass
class ExchangeConfig:
    exchange_id: str
    api_key: str | None
    api_secret: str | None
    testnet: bool
    live_trading: bool


@dataclass
class Settings:
    exchange: ExchangeConfig
    symbol: str
    timeframe: str
    polling_interval_seconds: int
    strategy: DonchianConfig
    risk: RiskConfig


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: str | None = None, env_path: str | None = None) -> Settings:
    """Load configuration. Call once at startup.

    env_path defaults to a `.env` file in the current working directory.
    config_path defaults to the CRYPTO_CONFIG_PATH env var, or
    config/crypto_settings.yaml.
    """
    load_dotenv(dotenv_path=env_path, override=False)

    path = config_path or os.getenv("CRYPTO_CONFIG_PATH", "config/crypto_settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    strategy_raw = raw.get("strategy", {}) or {}
    risk_raw = raw.get("risk", {}) or {}

    exchange = ExchangeConfig(
        exchange_id=raw.get("exchange", "binance"),
        api_key=os.getenv("BINANCE_API_KEY") or None,
        api_secret=os.getenv("BINANCE_API_SECRET") or None,
        testnet=_bool_env("BINANCE_TESTNET", True),
        live_trading=_bool_env("CRYPTO_LIVE_TRADING", False),
    )

    settings = Settings(
        exchange=exchange,
        symbol=raw.get("symbol", "BTC/USDT"),
        timeframe=raw.get("timeframe", "4h"),
        polling_interval_seconds=int(raw.get("polling_interval_seconds", 300)),
        strategy=DonchianConfig(
            entry_period=int(strategy_raw.get("donchian_entry_period", 20)),
            exit_period=int(strategy_raw.get("donchian_exit_period", 10)),
            atr_period=int(strategy_raw.get("atr_period", 14)),
            atr_stop_mult=float(strategy_raw.get("atr_stop_mult", 2.0)),
            trend_filter_ema_period=(
                int(strategy_raw["trend_filter_ema_period"])
                if strategy_raw.get("trend_filter_ema_period") not in (None, "", "null")
                else None
            ),
        ),
        risk=RiskConfig(
            starting_equity_usd=float(risk_raw.get("starting_equity_usd", 1000.0)),
            risk_per_trade_pct=float(risk_raw.get("risk_per_trade_pct", 0.01)),
            max_daily_loss_pct=float(risk_raw.get("max_daily_loss_pct", 0.03)),
            max_drawdown_pct=float(risk_raw.get("max_drawdown_pct", 0.20)),
            max_concurrent_positions=int(risk_raw.get("max_concurrent_positions", 1)),
            min_order_size_usd=float(risk_raw.get("min_order_size_usd", 10.0)),
            fee_pct=float(risk_raw.get("fee_pct", 0.001)),
        ),
    )

    if exchange.live_trading:
        missing = []
        if not exchange.api_key:
            missing.append("BINANCE_API_KEY")
        if not exchange.api_secret:
            missing.append("BINANCE_API_SECRET")
        if missing:
            raise ValueError(
                "CRYPTO_LIVE_TRADING=true but missing required env vars: "
                + ", ".join(missing)
                + ". Refusing to start in live mode without full API credentials."
            )

    return settings
