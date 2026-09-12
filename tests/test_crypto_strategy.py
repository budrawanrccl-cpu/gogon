import pytest

from crypto_bot.models import Bar, Position
from crypto_bot.strategy import DonchianBreakoutStrategy, DonchianConfig, Indicators


def make_bar(ts, o, h, l, c, v=1.0):
    return Bar(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def make_strategy(**overrides) -> DonchianBreakoutStrategy:
    cfg = DonchianConfig(
        entry_period=20,
        exit_period=10,
        atr_period=14,
        atr_stop_mult=2.0,
        trend_filter_ema_period=None,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return DonchianBreakoutStrategy(cfg)


# -- precompute wiring --------------------------------------------------


def test_precompute_returns_arrays_same_length_as_bars():
    strat = make_strategy(entry_period=3, exit_period=2, atr_period=3, trend_filter_ema_period=3)
    bars = [make_bar(i, 100, 101, 99, 100) for i in range(6)]
    ind = strat.precompute(bars)
    assert len(ind.donchian_entry_high) == 6
    assert len(ind.donchian_exit_low) == 6
    assert len(ind.atr) == 6
    assert len(ind.trend_ema) == 6


def test_flat_history_never_breaks_out():
    # Close never exceeds the (flat) recent high, so no entry should fire.
    strat = make_strategy(entry_period=3, exit_period=2, atr_period=3, trend_filter_ema_period=None)
    bars = [make_bar(i, 100, 101, 99, 100) for i in range(10)]
    ind = strat.precompute(bars)
    for i in range(len(bars)):
        signal, _ = strat.evaluate(bars, ind, i, position=None)
        assert signal is None


# -- entries --------------------------------------------------------------


def test_enter_long_on_breakout_with_atr_stop():
    strat = make_strategy(trend_filter_ema_period=None)
    bar = make_bar(0, 100, 101, 99, 105)  # close breaks the channel high
    ind = Indicators(
        donchian_entry_high=[100.0],
        donchian_exit_low=[None],
        atr=[2.0],
        trend_ema=[None],
    )
    signal, new_stop = strat.evaluate([bar], ind, 0, position=None)
    assert signal is not None
    assert signal.action == "ENTER_LONG"
    assert signal.price == 105
    assert signal.stop_price == pytest.approx(105 - 2.0 * 2.0)  # atr_stop_mult=2.0
    assert new_stop is None


def test_no_entry_when_close_does_not_break_channel():
    strat = make_strategy(trend_filter_ema_period=None)
    bar = make_bar(0, 100, 101, 99, 100)  # close == channel high, not above it
    ind = Indicators(donchian_entry_high=[100.0], donchian_exit_low=[None], atr=[2.0], trend_ema=[None])
    signal, _ = strat.evaluate([bar], ind, 0, position=None)
    assert signal is None


def test_no_entry_without_enough_history():
    strat = make_strategy(trend_filter_ema_period=None)
    bar = make_bar(0, 100, 101, 99, 105)
    ind = Indicators(donchian_entry_high=[None], donchian_exit_low=[None], atr=[None], trend_ema=[None])
    signal, _ = strat.evaluate([bar], ind, 0, position=None)
    assert signal is None


def test_trend_filter_blocks_entry_below_ema():
    strat = make_strategy(trend_filter_ema_period=50)
    bar = make_bar(0, 100, 101, 99, 100)
    ind = Indicators(donchian_entry_high=[90.0], donchian_exit_low=[None], atr=[2.0], trend_ema=[105.0])
    signal, _ = strat.evaluate([bar], ind, 0, position=None)
    assert signal is None  # breakout is real, but price is still below the longer-term trend


def test_trend_filter_allows_entry_at_or_above_ema():
    strat = make_strategy(trend_filter_ema_period=50)
    bar = make_bar(0, 100, 101, 99, 100)
    ind = Indicators(donchian_entry_high=[90.0], donchian_exit_low=[None], atr=[2.0], trend_ema=[95.0])
    signal, _ = strat.evaluate([bar], ind, 0, position=None)
    assert signal is not None
    assert signal.action == "ENTER_LONG"


# -- exits ------------------------------------------------------------------


def test_exit_on_stop_hit_uses_bar_low_and_fills_at_stop():
    strat = make_strategy(trend_filter_ema_period=None)
    position = Position("BTC/USDT", "LONG", entry_price=100.0, size=1.0, stop_price=95.0, opened_at=0)
    bar = make_bar(1, 97, 98, 93, 96)  # low (93) pierces the stop (95)
    ind = Indicators(donchian_entry_high=[None, None], donchian_exit_low=[None, 80.0], atr=[None, 2.0], trend_ema=[None, None])
    signal, new_stop = strat.evaluate([make_bar(0, 100, 101, 99, 100), bar], ind, 1, position)
    assert signal is not None
    assert signal.action == "EXIT_LONG"
    assert signal.price == 95.0  # fills at the stop, not the bar's close
    assert new_stop is None


def test_exit_on_channel_break_when_stop_not_hit():
    strat = make_strategy(trend_filter_ema_period=None)
    position = Position("BTC/USDT", "LONG", entry_price=100.0, size=1.0, stop_price=50.0, opened_at=0)
    bar = make_bar(1, 94, 95, 90, 92)  # low (90) is well above the stop (50)
    ind = Indicators(donchian_entry_high=[None, None], donchian_exit_low=[None, 93.0], atr=[None, 2.0], trend_ema=[None, None])
    signal, new_stop = strat.evaluate([make_bar(0, 100, 101, 99, 100), bar], ind, 1, position)
    assert signal is not None
    assert signal.action == "EXIT_LONG"
    assert signal.price == 92  # fills at the close for a channel exit
    assert new_stop is None


def test_stop_hit_takes_priority_over_channel_exit():
    strat = make_strategy(trend_filter_ema_period=None)
    position = Position("BTC/USDT", "LONG", entry_price=100.0, size=1.0, stop_price=95.0, opened_at=0)
    bar = make_bar(1, 94, 95, 90, 92)  # both the stop (95) and the channel (93) are breached
    ind = Indicators(donchian_entry_high=[None, None], donchian_exit_low=[None, 93.0], atr=[None, 2.0], trend_ema=[None, None])
    signal, _ = strat.evaluate([make_bar(0, 100, 101, 99, 100), bar], ind, 1, position)
    assert signal.reason.startswith("stop hit")


# -- trailing stop ------------------------------------------------------------


def test_trailing_stop_moves_up_with_price():
    strat = make_strategy(atr_stop_mult=2.0, trend_filter_ema_period=None)
    position = Position("BTC/USDT", "LONG", entry_price=100.0, size=1.0, stop_price=95.0, opened_at=0)
    bar = make_bar(1, 108, 110, 107, 109)  # no stop hit, no channel exit
    ind = Indicators(donchian_entry_high=[None, None], donchian_exit_low=[None, 80.0], atr=[None, 3.0], trend_ema=[None, None])
    signal, new_stop = strat.evaluate([make_bar(0, 100, 101, 99, 100), bar], ind, 1, position)
    assert signal is None
    assert new_stop == pytest.approx(109 - 2.0 * 3.0)  # 103.0, higher than the old stop of 95


def test_trailing_stop_never_moves_down():
    strat = make_strategy(atr_stop_mult=2.0, trend_filter_ema_period=None)
    position = Position("BTC/USDT", "LONG", entry_price=100.0, size=1.0, stop_price=95.0, opened_at=0)
    # close=97 with atr=3 suggests a candidate stop of 97 - 2*3 = 91, below the
    # current stop of 95 — and the bar's low (96) stays above 95, so no exit.
    bar = make_bar(1, 97, 98, 96, 97)
    ind = Indicators(donchian_entry_high=[None, None], donchian_exit_low=[None, 80.0], atr=[None, 3.0], trend_ema=[None, None])
    signal, new_stop = strat.evaluate([make_bar(0, 100, 101, 99, 100), bar], ind, 1, position)
    assert signal is None
    assert new_stop == 95.0  # unchanged, not 97 - 6 = 91
