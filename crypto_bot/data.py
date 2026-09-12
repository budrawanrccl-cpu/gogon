"""Cache historical OHLCV bars to CSV so repeated backtests don't re-hit the
exchange, and so a backtest is reproducible even if the exchange's history
window moves on."""
from __future__ import annotations

import csv
import os

from crypto_bot.models import Bar

FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]


def cache_path(symbol: str, timeframe: str, data_dir: str = "data/ohlcv") -> str:
    safe_symbol = symbol.replace("/", "-")
    return os.path.join(data_dir, f"{safe_symbol}_{timeframe}.csv")


def save_bars(bars: list[Bar], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        for b in bars:
            writer.writerow([b.timestamp, b.open, b.high, b.low, b.close, b.volume])


def load_bars(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(
                Bar(
                    timestamp=int(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return bars
