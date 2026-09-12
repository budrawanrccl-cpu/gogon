"""Donchian channel breakout with an ATR trailing stop — a classic, long-only
trend-following system (the same family as the "Turtle Trading" rules).

Honest framing, please read before trusting this with money:

- **What it is**: buy when price breaks above its N-bar high (a new trend
  may be starting), exit on a stop that trails up with price, or when price
  breaks back below a shorter M-bar low (the trend looks over). It never
  tries to predict direction from news, sentiment, or "signals" — only from
  price itself.
- **Why this family of strategy, and not something claiming a bigger edge**:
  trend-following breakout systems are one of the few rule sets with a long
  public track record (decades, multiple asset classes, including the
  original Turtle traders) of positive expectancy *over many trades*,
  precisely because the rules are simple and the edge doesn't get arbitraged
  away completely — but "positive expectancy over many trades" is very
  different from "profitable every week". See the win-rate note below.
- **What it is NOT**: a way to win most trades. Typical live/backtested
  behavior is a low win rate (often well under 50%) with a few big trending
  winners paying for many small stopped-out losers. If you can't tolerate a
  string of small losses while waiting for a trend, this strategy will feel
  bad to run even when it's working as designed.
- **When it loses money**: sideways/choppy markets, where price keeps
  breaking out and immediately reversing ("whipsaw"). The optional EMA trend
  filter (`trend_filter_ema_period`) cuts some of this by only taking
  breakouts in the direction of the longer-term trend, at the cost of
  missing some early moves.
- **Always backtest a symbol/timeframe/parameter combination on real
  historical data (`scripts/run_crypto_backtest.py`) and paper-trade it
  before risking real money.** Past performance still doesn't guarantee
  future results — markets change regime.
"""
from __future__ import annotations

from dataclasses import dataclass

from crypto_bot import indicators
from crypto_bot.models import Bar, Position, Signal


@dataclass
class DonchianConfig:
    entry_period: int = 20  # breakout lookback for entries
    exit_period: int = 10  # breakout lookback for channel exits
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    # Optional regime filter: only take long entries when close >= this EMA.
    # Set to None to disable.
    trend_filter_ema_period: int | None = 100


@dataclass
class Indicators:
    donchian_entry_high: list[float | None]
    donchian_exit_low: list[float | None]
    atr: list[float | None]
    trend_ema: list[float | None]


class DonchianBreakoutStrategy:
    name = "donchian_breakout"

    def __init__(self, cfg: DonchianConfig):
        self.cfg = cfg

    def precompute(self, bars: list[Bar]) -> Indicators:
        closes = [b.close for b in bars]
        trend_ema: list[float | None] = [None] * len(bars)
        if self.cfg.trend_filter_ema_period:
            trend_ema = indicators.ema(closes, self.cfg.trend_filter_ema_period)
        return Indicators(
            donchian_entry_high=indicators.donchian_high(bars, self.cfg.entry_period),
            donchian_exit_low=indicators.donchian_low(bars, self.cfg.exit_period),
            atr=indicators.atr(bars, self.cfg.atr_period),
            trend_ema=trend_ema,
        )

    def initial_stop(self, entry_price: float, atr_val: float) -> float:
        return entry_price - self.cfg.atr_stop_mult * atr_val

    def evaluate(
        self, bars: list[Bar], ind: Indicators, i: int, position: Position | None
    ) -> tuple[Signal | None, float | None]:
        """Decide what to do at bar `i`.

        Returns (signal, new_stop_price):
          - signal is None when there's nothing to do this bar.
          - new_stop_price is the trailing stop to apply to an open position
            that is NOT being exited this bar (ignored otherwise).
        """
        bar = bars[i]
        atr_val = ind.atr[i]

        if position is not None:
            # 1. Protective stop: a resting stop order can be hit intrabar,
            #    so check against the bar's low, not just its close.
            if bar.low <= position.stop_price:
                return (
                    Signal(
                        action="EXIT_LONG",
                        price=position.stop_price,
                        stop_price=None,
                        reason=f"stop hit at {position.stop_price:.6g}",
                    ),
                    None,
                )
            # 2. Trend-exhaustion exit: close breaks the shorter Donchian low.
            exit_level = ind.donchian_exit_low[i]
            if exit_level is not None and bar.close <= exit_level:
                return (
                    Signal(
                        action="EXIT_LONG",
                        price=bar.close,
                        stop_price=None,
                        reason=f"close {bar.close:.6g} <= {self.cfg.exit_period}-bar low {exit_level:.6g}",
                    ),
                    None,
                )
            # 3. No exit: trail the stop up (never down).
            new_stop = position.stop_price
            if atr_val is not None:
                new_stop = max(new_stop, bar.close - self.cfg.atr_stop_mult * atr_val)
            return None, new_stop

        # Flat: look for a new breakout entry.
        entry_level = ind.donchian_entry_high[i]
        if entry_level is None or atr_val is None or atr_val <= 0:
            return None, None
        if bar.close <= entry_level:
            return None, None
        if self.cfg.trend_filter_ema_period:
            trend = ind.trend_ema[i]
            if trend is None or bar.close < trend:
                return None, None

        stop = self.initial_stop(bar.close, atr_val)
        if stop <= 0:
            return None, None
        return (
            Signal(
                action="ENTER_LONG",
                price=bar.close,
                stop_price=stop,
                reason=(
                    f"close {bar.close:.6g} broke {self.cfg.entry_period}-bar high "
                    f"{entry_level:.6g}; stop {stop:.6g} ({self.cfg.atr_stop_mult}x ATR)"
                ),
            ),
            None,
        )
