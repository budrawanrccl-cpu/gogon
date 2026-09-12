import pytest

from crypto_bot.indicators import atr, donchian_high, donchian_low, ema
from crypto_bot.models import Bar


def make_bar(ts, o, h, l, c, v=1.0):
    return Bar(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def test_ema_none_before_period():
    result = ema([1, 2, 3, 4, 5, 6], period=3)
    assert result[0] is None
    assert result[1] is None


def test_ema_seeds_with_simple_average_then_smooths():
    values = [1, 2, 3, 4, 5, 6]
    result = ema(values, period=3)
    assert result[2] == pytest.approx(2.0)  # simple avg of 1, 2, 3
    k = 2 / (3 + 1)
    expected_3 = values[3] * k + result[2] * (1 - k)
    assert result[3] == pytest.approx(expected_3)


def test_ema_rejects_bad_period():
    with pytest.raises(ValueError):
        ema([1, 2, 3], period=0)


def test_donchian_high_excludes_current_bar():
    # highs: 1, 2, 3, 4, 5 (index i has high i+1)
    bars = [make_bar(i, 0, i + 1, i, i + 0.5) for i in range(5)]
    out = donchian_high(bars, period=2)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == 2  # max(highs[0], highs[1]) = max(1, 2)
    assert out[3] == 3  # max(highs[1], highs[2]) = max(2, 3)
    assert out[4] == 4  # max(highs[2], highs[3]) = max(3, 4)


def test_donchian_low_excludes_current_bar():
    # lows: 0, 1, 2, 3, 4 (index i has low i)
    bars = [make_bar(i, 0, i + 5, i, i + 0.5) for i in range(5)]
    out = donchian_low(bars, period=2)
    assert out[2] == 0  # min(lows[0], lows[1]) = min(0, 1)
    assert out[3] == 1
    assert out[4] == 2


def test_atr_seeds_with_simple_average_true_range():
    bars = [
        make_bar(0, 10, 12, 8, 10),  # TR = 12-8 = 4 (no prior close)
        make_bar(1, 10, 13, 9, 11),  # TR = max(13-9, |13-10|, |9-10|) = 4
        make_bar(2, 11, 14, 10, 12),  # TR = max(14-10, |14-11|, |10-11|) = 4
    ]
    out = atr(bars, period=3)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx(4.0)


def test_atr_wilder_smooths_after_seed():
    bars = [
        make_bar(0, 10, 12, 8, 10),  # TR = 4
        make_bar(1, 10, 13, 9, 11),  # TR = 4
        make_bar(2, 11, 20, 10, 19),  # TR = max(10, |20-11|=9, |10-11|=1) = 10
    ]
    out = atr(bars, period=2)
    # seed at index 1: avg(TR[0], TR[1]) = avg(4, 4) = 4
    assert out[1] == pytest.approx(4.0)
    # index 2: Wilder smoothing: (prev*(n-1) + TR[2]) / n = (4*1 + 10) / 2 = 7
    assert out[2] == pytest.approx(7.0)
