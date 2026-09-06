"""Loads and validates screener configuration from .env (secrets/endpoints)
and YAML (screening thresholds).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv


@dataclass
class ApiConfig:
    """Connection details for gmgn.ai's public (unofficial) web API.

    gmgn.ai does not publish an official public API — these are the same
    JSON endpoints its own web frontend calls. They are undocumented, can
    change without notice, and sit behind Cloudflare bot-protection that may
    reject requests without browser-like headers. Verify with
    `scripts/gmgn_check_setup.py` before relying on this.
    """

    base_url: str = "https://gmgn.ai"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    cookie: str | None = None  # optional cf_clearance/session cookie, if Cloudflare blocks plain requests
    request_timeout_seconds: float = 10.0
    min_request_interval_seconds: float = 1.5  # simple client-side rate limit, be a good citizen
    max_retries: int = 3


@dataclass
class ScreenerConfig:
    lookback_minutes: int = 60  # only consider smart-money activity newer than this
    min_smart_wallets: int = 3  # distinct tagged wallets that must have bought
    min_net_buy_usd: float = 2000.0  # smart-money buy volume minus sell volume, in the window
    min_liquidity_usd: float = 5000.0
    min_holder_count: int = 50
    max_top_10_holder_pct: float = 40.0  # skip tokens with heavy holder concentration
    max_token_age_minutes: int = 1440  # ignore pairs older than this (default: 24h)
    min_market_cap_usd: float = 0.0
    max_market_cap_usd: float = 0.0  # 0 = no cap
    required_tags: list[str] = field(default_factory=lambda: ["smart_degen"])
    exclude_honeypot: bool = True


@dataclass
class NotifyConfig:
    console: bool = True
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    cooldown_minutes: int = 60  # don't re-alert the same token within this window


@dataclass
class Settings:
    api: ApiConfig
    screener: ScreenerConfig
    notify: NotifyConfig
    chain: str = "sol"
    new_pairs_limit: int = 50
    activities_limit: int = 100
    poll_interval_seconds: int = 60
    seen_cache_path: str = "data/gmgn_seen.json"
    signals_journal_path: str = "data/gmgn_signals.csv"


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: str | None = None, env_path: str | None = None) -> Settings:
    """Load configuration. Call once at startup.

    env_path defaults to a `.env` file in the current working directory (if present).
    config_path defaults to the GMGN_CONFIG_PATH env var, or config/gmgn_settings.yaml.
    """
    load_dotenv(dotenv_path=env_path, override=False)

    path = config_path or os.getenv("GMGN_CONFIG_PATH", "config/gmgn_settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    api_raw = raw.get("api", {}) or {}
    screener_raw = raw.get("screener", {}) or {}
    notify_raw = raw.get("notify", {}) or {}

    api = ApiConfig(
        base_url=os.getenv("GMGN_API_BASE_URL", api_raw.get("base_url", "https://gmgn.ai")),
        user_agent=os.getenv("GMGN_USER_AGENT") or api_raw.get("user_agent", ApiConfig.user_agent),
        cookie=os.getenv("GMGN_COOKIE") or api_raw.get("cookie") or None,
        request_timeout_seconds=float(api_raw.get("request_timeout_seconds", 10.0)),
        min_request_interval_seconds=float(api_raw.get("min_request_interval_seconds", 1.5)),
        max_retries=int(api_raw.get("max_retries", 3)),
    )

    screener = ScreenerConfig(
        lookback_minutes=int(screener_raw.get("lookback_minutes", 60)),
        min_smart_wallets=int(screener_raw.get("min_smart_wallets", 3)),
        min_net_buy_usd=float(screener_raw.get("min_net_buy_usd", 2000.0)),
        min_liquidity_usd=float(screener_raw.get("min_liquidity_usd", 5000.0)),
        min_holder_count=int(screener_raw.get("min_holder_count", 50)),
        max_top_10_holder_pct=float(screener_raw.get("max_top_10_holder_pct", 40.0)),
        max_token_age_minutes=int(screener_raw.get("max_token_age_minutes", 1440)),
        min_market_cap_usd=float(screener_raw.get("min_market_cap_usd", 0.0)),
        max_market_cap_usd=float(screener_raw.get("max_market_cap_usd", 0.0)),
        required_tags=list(screener_raw.get("required_tags", ["smart_degen"]) or []),
        exclude_honeypot=bool(screener_raw.get("exclude_honeypot", True)),
    )

    notify = NotifyConfig(
        console=bool(notify_raw.get("console", True)),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        cooldown_minutes=int(notify_raw.get("cooldown_minutes", 60)),
    )

    return Settings(
        api=api,
        screener=screener,
        notify=notify,
        chain=os.getenv("GMGN_CHAIN", raw.get("chain", "sol")),
        new_pairs_limit=int(raw.get("new_pairs_limit", 50)),
        activities_limit=int(raw.get("activities_limit", 100)),
        poll_interval_seconds=int(os.getenv("GMGN_POLL_INTERVAL_SECONDS", raw.get("poll_interval_seconds", 60))),
        seen_cache_path=raw.get("seen_cache_path", "data/gmgn_seen.json"),
        signals_journal_path=raw.get("signals_journal_path", "data/gmgn_signals.csv"),
    )
