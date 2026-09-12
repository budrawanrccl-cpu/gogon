"""Loads and validates bot configuration from .env (secrets) and YAML (strategy/risk)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv


@dataclass
class MarketFilterConfig:
    whitelist: list[str] = field(default_factory=list)
    min_volume_usd: float = 5000.0
    min_liquidity_usd: float = 200.0
    max_markets_per_cycle: int = 200


@dataclass
class RiskConfig:
    max_position_usd: float = 25.0
    max_total_exposure_usd: float = 200.0
    max_daily_loss_usd: float = 50.0
    min_order_size_usd: float = 1.0
    # Dollars of max_total_exposure_usd carved out exclusively for the hedging
    # strategy. Arbitrage/threshold never touch this slice (see
    # RiskManager.max_affordable_usd); hedging may use it, and may push a
    # single market's committed capital above max_position_usd by up to this
    # amount (see RiskManager.max_hedge_usd). 0.0 = no reserve (default),
    # which reproduces the old behavior where hedging only fires once some
    # other position frees up room.
    hedge_reserve_usd: float = 0.0


@dataclass
class ArbitrageConfig:
    enabled: bool = True
    min_edge: float = 0.015
    fee_buffer: float = 0.005


@dataclass
class ThresholdConfig:
    enabled: bool = False
    lookback_ticks: int = 20
    buy_drop_pct: float = 0.08
    sell_rise_pct: float = 0.08


@dataclass
class HedgingConfig:
    enabled: bool = False
    # Unrealized loss fraction on a held position that triggers a hedge.
    trigger_loss_pct: float = 0.10
    # Fraction of the original position size to match with the opposite
    # outcome once triggered. 1.0 = fully hedge (buy an equal number of
    # opposite-outcome shares, locking in the loss already taken instead of
    # letting it grow further).
    hedge_ratio: float = 1.0


@dataclass
class WalletConfig:
    private_key: str | None
    chain_id: int
    clob_host: str
    signature_type: int
    funder_address: str | None
    live_trading: bool


@dataclass
class Settings:
    wallet: WalletConfig
    markets: MarketFilterConfig
    risk: RiskConfig
    arbitrage: ArbitrageConfig
    threshold: ThresholdConfig
    hedging: HedgingConfig
    polling_interval_seconds: int = 15


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: str | None = None, env_path: str | None = None) -> Settings:
    """Load configuration. Call once at startup.

    env_path defaults to a `.env` file in the current working directory (if present).
    config_path defaults to the BOT_CONFIG_PATH env var, or config/settings.yaml.
    """
    load_dotenv(dotenv_path=env_path, override=False)

    path = config_path or os.getenv("BOT_CONFIG_PATH", "config/settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    markets_raw = raw.get("markets", {}) or {}
    risk_raw = raw.get("risk", {}) or {}
    strategies_raw = raw.get("strategies", {}) or {}
    arb_raw = strategies_raw.get("arbitrage", {}) or {}
    thr_raw = strategies_raw.get("threshold", {}) or {}
    hedge_raw = strategies_raw.get("hedging", {}) or {}

    wallet = WalletConfig(
        private_key=os.getenv("POLY_PRIVATE_KEY") or None,
        chain_id=int(os.getenv("POLY_CHAIN_ID", "137")),
        clob_host=os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com"),
        signature_type=int(os.getenv("POLY_SIGNATURE_TYPE", "0")),
        funder_address=os.getenv("POLY_FUNDER_ADDRESS") or None,
        live_trading=_bool_env("LIVE_TRADING", False),
    )

    settings = Settings(
        wallet=wallet,
        markets=MarketFilterConfig(
            whitelist=list(markets_raw.get("whitelist", []) or []),
            min_volume_usd=float(markets_raw.get("min_volume_usd", 5000.0)),
            min_liquidity_usd=float(markets_raw.get("min_liquidity_usd", 200.0)),
            max_markets_per_cycle=int(markets_raw.get("max_markets_per_cycle", 200)),
        ),
        risk=RiskConfig(
            max_position_usd=float(risk_raw.get("max_position_usd", 25.0)),
            max_total_exposure_usd=float(risk_raw.get("max_total_exposure_usd", 200.0)),
            max_daily_loss_usd=float(risk_raw.get("max_daily_loss_usd", 50.0)),
            min_order_size_usd=float(risk_raw.get("min_order_size_usd", 1.0)),
            hedge_reserve_usd=float(risk_raw.get("hedge_reserve_usd", 0.0)),
        ),
        arbitrage=ArbitrageConfig(
            enabled=bool(arb_raw.get("enabled", True)),
            min_edge=float(arb_raw.get("min_edge", 0.015)),
            fee_buffer=float(arb_raw.get("fee_buffer", 0.005)),
        ),
        threshold=ThresholdConfig(
            enabled=bool(thr_raw.get("enabled", False)),
            lookback_ticks=int(thr_raw.get("lookback_ticks", 20)),
            buy_drop_pct=float(thr_raw.get("buy_drop_pct", 0.08)),
            sell_rise_pct=float(thr_raw.get("sell_rise_pct", 0.08)),
        ),
        hedging=HedgingConfig(
            enabled=bool(hedge_raw.get("enabled", False)),
            trigger_loss_pct=float(hedge_raw.get("trigger_loss_pct", 0.10)),
            hedge_ratio=float(hedge_raw.get("hedge_ratio", 1.0)),
        ),
        polling_interval_seconds=int(raw.get("polling_interval_seconds", 15)),
    )

    if wallet.live_trading:
        missing = []
        if not wallet.private_key:
            missing.append("POLY_PRIVATE_KEY")
        if not wallet.funder_address:
            missing.append("POLY_FUNDER_ADDRESS")
        if missing:
            raise ValueError(
                "LIVE_TRADING=true but missing required env vars: "
                + ", ".join(missing)
                + ". Refusing to start in live mode without full wallet config."
            )

    return settings
