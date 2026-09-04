"""Real-time token/trade feed via PumpPortal's public WebSocket API
(wss://pumpportal.fun/api/data — subscribeNewToken / subscribeTokenTrade).

PumpPortal is a third-party (unofficial) data/trading API for pump.fun's
on-chain bonding curve program; it is not operated by pump.fun itself.
Payload field names are not a versioned, guaranteed-stable contract, so —
same pattern as bot/market_data.py for Polymarket — parsing here is
defensive: unknown/missing fields fall back to safe defaults (or None,
which strategies must treat as "skip, don't assume") rather than crashing
the bot. Verify the exact payload shape against a live connection before
depending on any single field for money-moving decisions.

This module only *reads* public trade/token-creation data. No wallet or
private key is involved anywhere in this file.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from pumpbot.config import DataConfig

logger = logging.getLogger("pumpbot.market_data")


@dataclass
class RawEvent:
    kind: str  # "create" | "trade"
    payload: dict
    received_at: float = field(default_factory=time.time)


@dataclass
class TokenStats:
    """Running, best-effort stats for one mint since it was first observed."""

    mint: str
    name: str = ""
    symbol: str = ""
    creator: str | None = None
    first_seen: float = field(default_factory=time.time)
    unique_buyers: set = field(default_factory=set)
    buy_volume_sol: float = 0.0
    sell_volume_sol: float = 0.0
    trade_count: int = 0
    market_cap_sol: float | None = None
    last_price_sol_per_token: float | None = None
    creator_holding_pct: float | None = None
    decided: bool = False  # True once the strategy has acted (bought or passed)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.first_seen

    @property
    def net_buy_volume_sol(self) -> float:
        return self.buy_volume_sol - self.sell_volume_sol


def _num(d: dict, *keys, default=None):
    for k in keys:
        if d.get(k) is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                pass
    return default


def _str(d: dict, *keys, default=""):
    for k in keys:
        if d.get(k):
            return str(d[k])
    return default


class TokenTracker:
    """Applies incoming RawEvents to a dict of mint -> TokenStats."""

    def __init__(self):
        self.tokens: dict[str, TokenStats] = {}

    def apply(self, event: RawEvent) -> TokenStats | None:
        p = event.payload
        mint = _str(p, "mint", "mintAddress")
        if not mint:
            return None

        stats = self.tokens.get(mint)
        if stats is None:
            stats = TokenStats(
                mint=mint,
                name=_str(p, "name"),
                symbol=_str(p, "symbol"),
                creator=_str(p, "traderPublicKey", "creator") or None,
            )
            self.tokens[mint] = stats

        tx_type = _str(p, "txType", "type").lower()
        trader = _str(p, "traderPublicKey", "trader") or None
        sol_amount = _num(p, "solAmount", default=0.0) or 0.0
        market_cap = _num(p, "marketCapSol", "marketCap")
        v_tokens = _num(p, "vTokensInBondingCurve")
        v_sol = _num(p, "vSolInBondingCurve")

        if market_cap is not None:
            stats.market_cap_sol = market_cap
        if v_tokens and v_sol and v_tokens > 0:
            stats.last_price_sol_per_token = v_sol / v_tokens

        if tx_type in ("create",):
            if stats.creator is None:
                stats.creator = trader
        elif tx_type in ("buy",):
            stats.trade_count += 1
            stats.buy_volume_sol += sol_amount
            if trader:
                stats.unique_buyers.add(trader)
        elif tx_type in ("sell",):
            stats.trade_count += 1
            stats.sell_volume_sol += sol_amount

        # Best-effort: PumpPortal's create event usually includes the
        # creator's own initial buy. If a later buy's trader == creator and
        # we can see their resulting token balance vs. total supply, we
        # could estimate holding % here — but total supply isn't reliably
        # present on every event, so leave creator_holding_pct as None
        # (== "unknown") unless a field explicitly provides it.
        holding_pct = _num(p, "creatorHoldingPct")
        if holding_pct is not None:
            stats.creator_holding_pct = holding_pct

        return stats

    def prune(self, max_age_seconds: float) -> None:
        stale = [m for m, s in self.tokens.items() if s.age_seconds > max_age_seconds]
        for m in stale:
            del self.tokens[m]


class PumpPortalFeed:
    """Background WebSocket listener. Pushes RawEvents onto a thread-safe
    queue that the main loop drains synchronously — keeps the rest of the
    bot single-threaded and easy to reason about, matching the rest of the
    codebase's synchronous style.
    """

    def __init__(self, cfg: DataConfig):
        self.cfg = cfg
        self.events: "queue.Queue[RawEvent]" = queue.Queue()
        self._ws = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        import websocket  # websocket-client

        def on_open(ws):
            logger.info("Connected to PumpPortal data feed (%s)", self.cfg.ws_url)
            sub = {"method": "subscribeNewToken"}
            ws.send(json.dumps(sub))

        def on_message(ws, message):
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                logger.debug("Non-JSON message from feed, ignoring: %.200s", message)
                return
            if not isinstance(payload, dict):
                return
            tx_type = str(payload.get("txType", "")).lower()
            kind = "create" if tx_type == "create" else "trade"
            self.events.put(RawEvent(kind=kind, payload=payload))

        def on_error(ws, error):
            logger.warning("PumpPortal feed error: %s", error)

        def on_close(ws, status, msg):
            logger.warning("PumpPortal feed closed (status=%s msg=%s)", status, msg)

        def run():
            backoff = 2
            while not self._stop.is_set():
                try:
                    self._ws = websocket.WebSocketApp(
                        self.cfg.ws_url,
                        on_open=on_open,
                        on_message=on_message,
                        on_error=on_error,
                        on_close=on_close,
                    )
                    self._ws.run_forever(ping_interval=30, ping_timeout=10)
                except Exception:
                    logger.exception("PumpPortal feed crashed; reconnecting")
                if self._stop.is_set():
                    break
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

        self._thread = threading.Thread(target=run, name="pumpportal-feed", daemon=True)
        self._thread.start()

    def subscribe_trades(self, mints: list[str]) -> None:
        """Ask the feed to also stream trade events for specific mints
        (needed to track a candidate token's buyer count / volume after
        its creation event, and to mark price while a position is open).
        """
        if not mints or self._ws is None:
            return
        try:
            self._ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": mints[:100]}))
        except Exception:
            logger.exception("Failed to send subscribeTokenTrade for %s", mints)

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    def drain(self) -> list[RawEvent]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                break
        return out
