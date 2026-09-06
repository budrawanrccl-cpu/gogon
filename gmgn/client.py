"""Client for gmgn.ai's public (unofficial) web API.

gmgn.ai does not publish or support a public API — there is no ToS covering
programmatic access, and the endpoints below are the same JSON calls its own
web frontend makes. That means:

  * They are undocumented and can change or disappear without notice.
    `get_smart_money_tokens` targets `/defi/quotation/v1/rank/{chain}/swaps/
    {time_period}`, which is the most consistently community-documented
    gmgn.ai endpoint (used by several independent open-source gmgn.ai
    clients) — its query params and response field names below are based on
    that documentation, not guesswork. `get_smart_wallets`
    (`/rank/{chain}/wallets/{period}`) is less consistently documented;
    treat its field names as best-effort. Either can still drift — verify
    with `scripts/gmgn_check_setup.py --live` before trusting this.
  * gmgn.ai sits behind Cloudflare bot-protection. A plain `requests` call
    without a browser-like User-Agent (and sometimes a `cf_clearance`
    cookie captured from a real browser session, set via `GMGN_COOKIE`)
    will often get a 403 instead of data.
  * This client rate-limits itself (`min_request_interval_seconds`) and
    retries with backoff on 429/5xx — it is meant for light, personal
    screening use, not high-frequency scraping. Respect gmgn.ai's terms and
    robots.txt for whatever you build on top of this.

All parsing helpers (`parse_*`) take plain dicts and are pure/side-effect
free, so they're unit-testable without any network access.
"""
from __future__ import annotations

import logging
import time

import requests

from gmgn.config import ApiConfig
from gmgn.models import SmartWallet, TokenStats

logger = logging.getLogger("smartmoney.client")


class GmgnApiError(RuntimeError):
    """Raised when gmgn.ai returns an error, an unexpected shape, or is unreachable."""


def _num(raw: dict, *keys, default=None):
    for k in keys:
        v = raw.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _int(raw: dict, *keys, default: int | None = 0) -> int | None:
    v = _num(raw, *keys, default=None)
    return int(v) if v is not None else default


def parse_wallet(raw: dict, chain: str) -> SmartWallet | None:
    """Parse one row of a `/rank/{chain}/wallets/{period}` response."""
    address = raw.get("address") or raw.get("wallet_address")
    if not address:
        return None
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return SmartWallet(
        address=str(address),
        chain=chain,
        tags=[str(t) for t in tags],
        winrate=_num(raw, "winrate", "win_rate"),
        pnl_usd=_num(raw, "pnl_7d", "pnl", "realized_profit"),
        realized_profit_usd=_num(raw, "realized_profit_7d", "realized_profit"),
        buy_count=_int(raw, "buy", "buy_count"),
        sell_count=_int(raw, "sell", "sell_count"),
    )


def parse_token_stats(raw: dict, chain: str) -> TokenStats | None:
    """Parse one row of a `/rank/{chain}/swaps/{period}` response.

    Field names follow gmgn.ai's documented rank/swaps shape: address,
    symbol, price, market_cap, liquidity, volume, holder_count, buys/sells,
    smart_buy_24h/smart_sell_24h, sniper_count, bluechip_owner_percentage,
    buy_tax/sell_tax, is_honeypot/renounced, and a nested lockInfo.lockPercent.
    A few legacy/alternate field names are still accepted as fallbacks in
    case gmgn.ai returns a slightly different shape for a given chain/period.
    """
    address = raw.get("address") or raw.get("base_address") or raw.get("token_address")
    if not address:
        return None

    honeypot = raw.get("is_honeypot")
    renounced = raw.get("renounced") if raw.get("renounced") is not None else raw.get("is_renounced")
    lock_info = raw.get("lockInfo") or {}

    return TokenStats(
        chain=chain,
        address=str(address),
        symbol=str(raw.get("symbol", "")),
        name=str(raw.get("name", "")),
        price_usd=_num(raw, "price", "price_usd", default=0.0) or 0.0,
        price_change_pct=_num(raw, "price_change_percent", "change24h"),
        market_cap_usd=_num(raw, "market_cap", "market_cap_usd", "usd_market_cap", default=0.0) or 0.0,
        liquidity_usd=_num(raw, "liquidity", "liquidity_usd", default=0.0) or 0.0,
        volume_usd=_num(raw, "volume", "volume_usd", default=0.0) or 0.0,
        holder_count=_int(raw, "holder_count", "holders"),
        buys=_int(raw, "buys", "buy_count"),
        sells=_int(raw, "sells", "sell_count"),
        smart_buy_24h=_int(raw, "smart_buy_24h", "smart_buy"),
        smart_sell_24h=_int(raw, "smart_sell_24h", "smart_sell"),
        sniper_count=_int(raw, "sniper_count", default=None),
        bluechip_owner_pct=_num(raw, "bluechip_owner_percentage"),
        buy_tax_pct=_num(raw, "buy_tax"),
        sell_tax_pct=_num(raw, "sell_tax"),
        lock_pct=_num(lock_info, "lockPercent") if isinstance(lock_info, dict) else None,
        is_honeypot=bool(honeypot) if honeypot is not None else None,
        is_renounced=bool(renounced) if renounced is not None else None,
        top_10_holder_pct=_num(raw, "top_10_holder_rate", "top_10_holder_pct"),
        open_timestamp=_int(raw, "open_timestamp", "created_timestamp", default=0) or None,
    )


class GmgnClient:
    def __init__(self, cfg: ApiConfig):
        self.cfg = cfg
        self.session = requests.Session()
        headers = {
            "User-Agent": cfg.user_agent,
            "Accept": "application/json",
        }
        if cfg.cookie:
            headers["Cookie"] = cfg.cookie
        self.session.headers.update(headers)
        self._last_request_at = 0.0

    # -- low-level ------------------------------------------------------
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.cfg.min_request_interval_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.cfg.base_url.rstrip('/')}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, self.cfg.max_retries + 1):
            self._throttle()
            self._last_request_at = time.monotonic()
            try:
                resp = self.session.get(url, params=params, timeout=self.cfg.request_timeout_seconds)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Request to %s failed (attempt %d/%d): %s", url, attempt, self.cfg.max_retries, exc)
                time.sleep(min(2 ** attempt, 10))
                continue

            if resp.status_code == 403:
                raise GmgnApiError(
                    f"gmgn.ai returned 403 for {url} — likely blocked by Cloudflare bot-protection. "
                    "Try setting GMGN_COOKIE to a valid cf_clearance/session cookie captured from a "
                    "real browser session, or a more current GMGN_USER_AGENT."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = GmgnApiError(f"HTTP {resp.status_code} from {url}")
                logger.warning(
                    "gmgn.ai returned %d for %s (attempt %d/%d), backing off",
                    resp.status_code, url, attempt, self.cfg.max_retries,
                )
                time.sleep(min(2 ** attempt, 10))
                continue

            try:
                resp.raise_for_status()
                data = resp.json()
            except (ValueError, requests.RequestException) as exc:
                raise GmgnApiError(f"Unexpected response from {url}: {exc}") from exc

            if isinstance(data, dict) and data.get("code") not in (0, None):
                raise GmgnApiError(f"gmgn.ai API error for {url}: {data.get('msg', data.get('code'))}")

            return data

        raise GmgnApiError(f"Giving up on {url} after {self.cfg.max_retries} attempts: {last_exc}")

    # -- endpoints --------------------------------------------------------
    def get_smart_wallets(
        self, chain: str, period: str = "7d", tag: str = "smart_degen", limit: int = 100
    ) -> list[SmartWallet]:
        """Smart-money wallet leaderboard for a chain/tag."""
        data = self._get(
            f"/defi/quotation/v1/rank/{chain}/wallets/{period}",
            params={"tag": tag, "orderby": "pnl_7d", "direction": "desc", "limit": limit},
        )
        rows = (data.get("data") or {}).get("rank", []) if isinstance(data, dict) else []
        wallets = [w for w in (parse_wallet(r, chain) for r in rows) if w is not None]
        return wallets

    def get_smart_money_tokens(
        self, chain: str, time_period: str = "24h", limit: int = 50
    ) -> list[TokenStats]:
        """Tokens ranked by smart-money buying activity, with trading stats and
        security flags all included in the same response — no follow-up
        per-token request needed.
        """
        data = self._get(
            f"/defi/quotation/v1/rank/{chain}/swaps/{time_period}",
            params={
                "orderby": "smartmoney",
                "direction": "desc",
                "limit": limit,
                "filters[]": "not_honeypot",
            },
        )
        rows = (data.get("data") or {}).get("rank", []) if isinstance(data, dict) else []
        if not rows and isinstance(data, dict):
            rows = data.get("data") or []  # some responses put the list directly under "data"
        return [t for t in (parse_token_stats(r, chain) for r in rows) if t is not None]
