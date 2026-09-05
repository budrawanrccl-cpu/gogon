"""Loads and validates pump.fun bot configuration from .env (secrets) and YAML
(watch list / sizing / risk parameters).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv


@dataclass
class WalletWatchConfig:
    watch: list[str] = field(default_factory=list)
    signatures_per_poll: int = 20


@dataclass
class CopyConfig:
    size_ratio: float = 0.1
    max_sol_per_trade: float = 0.5
    min_target_trade_sol: float = 0.05
    mirror_sells: bool = True
    skip_if_already_holding: bool = True


@dataclass
class RiskConfig:
    max_position_sol: float = 0.5
    max_total_exposure_sol: float = 2.0
    max_daily_loss_sol: float = 1.0
    min_virtual_sol_reserves: float = 5.0


@dataclass
class ExecutionConfig:
    slippage_bps: int = 500
    priority_fee_microlamports: int = 20_000


@dataclass
class MintFilterConfig:
    whitelist: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)


@dataclass
class SolanaWalletConfig:
    private_key: str | None
    rpc_url: str
    live_trading: bool


@dataclass
class Settings:
    wallet: SolanaWalletConfig
    wallets_to_watch: WalletWatchConfig
    copy: CopyConfig
    risk: RiskConfig
    execution: ExecutionConfig
    mints: MintFilterConfig
    polling_interval_seconds: int = 5


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: str | None = None, env_path: str | None = None) -> Settings:
    """Load configuration. Call once at startup.

    env_path defaults to a `.env` file in the current working directory (if present).
    config_path defaults to the PF_CONFIG_PATH env var, or config/pumpfun_settings.yaml.
    """
    load_dotenv(dotenv_path=env_path, override=False)

    path = config_path or os.getenv("PF_CONFIG_PATH", "config/pumpfun_settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    wallets_raw = raw.get("wallets", {}) or {}
    copy_raw = raw.get("copy", {}) or {}
    risk_raw = raw.get("risk", {}) or {}
    exec_raw = raw.get("execution", {}) or {}
    mints_raw = raw.get("mints", {}) or {}

    wallet = SolanaWalletConfig(
        private_key=os.getenv("SOLANA_PRIVATE_KEY") or None,
        rpc_url=os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
        live_trading=_bool_env("PF_LIVE_TRADING", False),
    )

    watch_list = [w.strip() for w in (wallets_raw.get("watch", []) or []) if w and w.strip()]

    settings = Settings(
        wallet=wallet,
        wallets_to_watch=WalletWatchConfig(
            watch=watch_list,
            signatures_per_poll=int(wallets_raw.get("signatures_per_poll", 20)),
        ),
        copy=CopyConfig(
            size_ratio=float(copy_raw.get("size_ratio", 0.1)),
            max_sol_per_trade=float(copy_raw.get("max_sol_per_trade", 0.5)),
            min_target_trade_sol=float(copy_raw.get("min_target_trade_sol", 0.05)),
            mirror_sells=bool(copy_raw.get("mirror_sells", True)),
            skip_if_already_holding=bool(copy_raw.get("skip_if_already_holding", True)),
        ),
        risk=RiskConfig(
            max_position_sol=float(risk_raw.get("max_position_sol", 0.5)),
            max_total_exposure_sol=float(risk_raw.get("max_total_exposure_sol", 2.0)),
            max_daily_loss_sol=float(risk_raw.get("max_daily_loss_sol", 1.0)),
            min_virtual_sol_reserves=float(risk_raw.get("min_virtual_sol_reserves", 5.0)),
        ),
        execution=ExecutionConfig(
            slippage_bps=int(exec_raw.get("slippage_bps", 500)),
            priority_fee_microlamports=int(exec_raw.get("priority_fee_microlamports", 20_000)),
        ),
        mints=MintFilterConfig(
            whitelist=list(mints_raw.get("whitelist", []) or []),
            blacklist=list(mints_raw.get("blacklist", []) or []),
        ),
        polling_interval_seconds=int(raw.get("polling_interval_seconds", 5)),
    )

    if wallet.live_trading and not wallet.private_key:
        raise ValueError(
            "PF_LIVE_TRADING=true but SOLANA_PRIVATE_KEY is not set. Refusing to start "
            "in live mode without a signing key."
        )
    if not settings.wallets_to_watch.watch:
        raise ValueError(
            "No wallets configured under `wallets.watch` in "
            f"{path} — add at least one Solana address to copy trades from."
        )

    return settings
