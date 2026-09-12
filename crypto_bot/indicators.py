"""Pure, dependency-free indicator functions over lists of `Bar`.

Every function returns a list the same length as its input, using `None`
for indices where there isn't enough history yet. Care is taken to avoid
lookahead: `donchian_high`/`donchian_low` at index `i` only look at bars
*strictly before* `i` (the channel a breakout at bar `i` is compared
against), matching how a live bot would evaluate it — it can't see bar
`i`'s high/low until after the breakout has already happened.
"""
from __future__ import annotations

from crypto_bot.models import Bar


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average. Seeded with a simple average of the
    first `period` values; `None` before that."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out

    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def true_range(bars: list[Bar], i: int) -> float:
    if i == 0:
        return bars[0].high - bars[0].low
    prev_close = bars[i - 1].close
    return max(
        bars[i].high - bars[i].low,
        abs(bars[i].high - prev_close),
        abs(bars[i].low - prev_close),
    )


def atr(bars: list[Bar], period: int) -> list[float | None]:
    """Average True Range, Wilder-smoothed. `atr[i]` reflects volatility up
    to and including bar `i` — usable for sizing a stop for a trade entered
    at bar `i`'s close / bar `i+1`'s open."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(bars)
    if len(bars) < period:
        return out

    trs = [true_range(bars, i) for i in range(len(bars))]
    seed = sum(trs[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(bars)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def donchian_high(bars: list[Bar], period: int) -> list[float | None]:
    """Highest high of the `period` bars *before* index i (excludes bar i)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(bars)
    for i in range(period, len(bars)):
        out[i] = max(b.high for b in bars[i - period : i])
    return out


def donchian_low(bars: list[Bar], period: int) -> list[float | None]:
    """Lowest low of the `period` bars *before* index i (excludes bar i)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(bars)
    for i in range(period, len(bars)):
        out[i] = min(b.low for b in bars[i - period : i])
    return out
