"""Small, shared defensive-parsing helpers for third-party JSON payloads
(PumpPortal WebSocket/HTTP). Centralized here so market_data.py and
strategies/copytrade.py don't duplicate the same "try a few possible key
names, fall back to a safe default" logic.
"""
from __future__ import annotations


def num(d: dict, *keys: str, default=None):
    for k in keys:
        if d.get(k) is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                pass
    return default


def text(d: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        if d.get(k):
            return str(d[k])
    return default
