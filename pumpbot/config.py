"""Loads and validates pumpbot configuration from .env (secrets) and YAML
(strategy/risk), mirroring bot/config.py's pattern for the Polymarket bot.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv


@dataclass
class WalletConfig:
    private_key: str | None  # base58-encoded Solana secret key. Never logged.
    rpc_url: str
    live_trading: bool


@dataclass
class DataConfig:
    ws_url: str
    trade_api_url: str
    api_key: str | None  # optional; only some PumpPortal endpoints require it


@dataclass
class FilterConfig:
    """Entry filters applied to newly observed tokens before any buy signal
    is generated. Defaults are deliberately conservative and skip a token
    outright when a required signal is missing rather than assuming it's
    safe — see the None checks in strategies/momentum.py.
    """

    min_token_age_seconds: int = 20
    max_token_age_seconds: int = 180
    min_unique_buyers: int = 8
    min_buy_volume_sol: float = 3.0
    max_creator_holding_pct: float = 20.0
    min_market_cap_sol: float = 5.0
    max_market_cap_sol: float = 200.0
    blacklist_mints: list[str] = field(default_factory=list)
    watch_window_seconds: int = 300  # give up tracking a mint after this long


@dataclass
class RiskConfig:
    max_position_sol: float = 0.05
    max_total_exposure_sol: float = 0.25
    max_concurrent_positions: int = 5
    max_daily_loss_sol: float = 0.5
    min_order_size_sol: float = 0.01
    take_profit_pct: float = 0.5
    stop_loss_pct: float = 0.25
    trailing_stop_pct: float = 0.15
    max_hold_seconds: int = 900


@dataclass
class TradingConfig:
    slippage_pct: float = 10.0
    priority_fee_sol: float = 0.0005
    pool: str = "pump"


@dataclass
class Settings:
    wallet: WalletConfig
    data: DataConfig
    filters: FilterConfig
    risk: RiskConfig
    trading: TradingConfig
    polling_interval_seconds: float = 2.0


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: str | None = None, env_path: str | None = None) -> Settings:
    """Load configuration. Call once at startup.

    env_path defaults to a `.env` file in the current working directory (if present).
    config_path defaults to the PUMPBOT_CONFIG_PATH env var, or config/pumpbot_settings.yaml.
    """
    load_dotenv(dotenv_path=env_path, override=False)

    path = config_path or os.getenv("PUMPBOT_CONFIG_PATH", "config/pumpbot_settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    filters_raw = raw.get("filters", {}) or {}
    risk_raw = raw.get("risk", {}) or {}
    trading_raw = raw.get("trading", {}) or {}

    wallet = WalletConfig(
        private_key=os.getenv("SOLANA_PRIVATE_KEY") or None,
        rpc_url=os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
        live_trading=_bool_env("LIVE_TRADING", False),
    )

    data = DataConfig(
        ws_url=os.getenv("PUMPPORTAL_WS_URL", "wss://pumpportal.fun/api/data"),
        trade_api_url=os.getenv("PUMPPORTAL_TRADE_API", "https://pumpportal.fun/api/trade-local"),
        api_key=os.getenv("PUMPPORTAL_API_KEY") or None,
    )

    settings = Settings(
        wallet=wallet,
        data=data,
        filters=FilterConfig(
            min_token_age_seconds=int(filters_raw.get("min_token_age_seconds", 20)),
            max_token_age_seconds=int(filters_raw.get("max_token_age_seconds", 180)),
            min_unique_buyers=int(filters_raw.get("min_unique_buyers", 8)),
            min_buy_volume_sol=float(filters_raw.get("min_buy_volume_sol", 3.0)),
            max_creator_holding_pct=float(filters_raw.get("max_creator_holding_pct", 20.0)),
            min_market_cap_sol=float(filters_raw.get("min_market_cap_sol", 5.0)),
            max_market_cap_sol=float(filters_raw.get("max_market_cap_sol", 200.0)),
            blacklist_mints=list(filters_raw.get("blacklist_mints", []) or []),
            watch_window_seconds=int(filters_raw.get("watch_window_seconds", 300)),
        ),
        risk=RiskConfig(
            max_position_sol=float(risk_raw.get("max_position_sol", 0.05)),
            max_total_exposure_sol=float(risk_raw.get("max_total_exposure_sol", 0.25)),
            max_concurrent_positions=int(risk_raw.get("max_concurrent_positions", 5)),
            max_daily_loss_sol=float(risk_raw.get("max_daily_loss_sol", 0.5)),
            min_order_size_sol=float(risk_raw.get("min_order_size_sol", 0.01)),
            take_profit_pct=float(risk_raw.get("take_profit_pct", 0.5)),
            stop_loss_pct=float(risk_raw.get("stop_loss_pct", 0.25)),
            trailing_stop_pct=float(risk_raw.get("trailing_stop_pct", 0.15)),
            max_hold_seconds=int(risk_raw.get("max_hold_seconds", 900)),
        ),
        trading=TradingConfig(
            slippage_pct=float(trading_raw.get("slippage_pct", 10.0)),
            priority_fee_sol=float(trading_raw.get("priority_fee_sol", 0.0005)),
            pool=str(trading_raw.get("pool", "pump")),
        ),
        polling_interval_seconds=float(raw.get("polling_interval_seconds", 2.0)),
    )

    if wallet.live_trading and not wallet.private_key:
        raise ValueError(
            "LIVE_TRADING=true but SOLANA_PRIVATE_KEY is not set. Refusing to start "
            "in live mode without a signing wallet."
        )

    return settings
