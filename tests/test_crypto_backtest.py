import pytest

from crypto_bot.backtest import run_backtest
from crypto_bot.models import Bar
from crypto_bot.risk import RiskConfig
from crypto_bot.strategy import DonchianBreakoutStrategy, DonchianConfig


def build_bars() -> list[Bar]:
    bars = []
    ts = 0

    def add(close, spread=2.0, vol=10.0):
        nonlocal ts
        bars.append(Bar(timestamp=ts, open=close, high=close + spread, low=close - spread, close=close, volume=vol))
        ts += 1

    for _ in range(6):
        add(100)  # flat base, seeds the indicators
    for p in (106, 112, 118, 124, 122, 130, 136):  # breakout + uptrend
        add(p)
    for p in (115, 100, 90, 82):  # sharp reversal -> should stop the long out
        add(p)
    for _ in range(6):
        add(85)  # flat again, no new signal

    return bars


def make_strategy() -> DonchianBreakoutStrategy:
    return DonchianBreakoutStrategy(
        DonchianConfig(entry_period=5, exit_period=3, atr_period=5, atr_stop_mult=2.0, trend_filter_ema_period=None)
    )


def make_risk_cfg(**overrides) -> RiskConfig:
    cfg = RiskConfig(
        starting_equity_usd=1000.0,
        risk_per_trade_pct=0.02,
        max_daily_loss_pct=1.0,  # effectively disabled for this test
        max_drawdown_pct=1.0,  # effectively disabled for this test
        max_concurrent_positions=1,
        min_order_size_usd=1.0,
        fee_pct=0.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_backtest_produces_at_least_one_trade_and_consistent_equity():
    bars = build_bars()
    result = run_backtest("BTC/USDT", bars, make_strategy(), make_risk_cfg())

    assert result.num_trades >= 1
    assert len(result.equity_curve) == len(bars)

    total_pnl = sum(t.pnl_usd for t in result.trades)
    assert result.final_equity == pytest.approx(result.starting_equity + total_pnl)
    assert result.total_return_pct == pytest.approx(total_pnl / result.starting_equity)


def test_backtest_max_drawdown_is_nonnegative_and_bounded():
    result = run_backtest("BTC/USDT", build_bars(), make_strategy(), make_risk_cfg())
    assert 0.0 <= result.max_drawdown_pct <= 1.0


def test_backtest_summary_does_not_raise():
    result = run_backtest("BTC/USDT", build_bars(), make_strategy(), make_risk_cfg())
    text = result.summary()
    assert "BTC/USDT" in text
    assert str(result.num_trades) in text


def test_fees_reduce_final_equity_versus_zero_fee_baseline():
    bars = build_bars()
    strat = make_strategy()
    no_fee = run_backtest("BTC/USDT", bars, strat, make_risk_cfg(fee_pct=0.0))
    with_fee = run_backtest("BTC/USDT", bars, make_strategy(), make_risk_cfg(fee_pct=0.01))
    assert no_fee.num_trades == with_fee.num_trades
    assert with_fee.final_equity < no_fee.final_equity


def test_open_position_is_force_closed_at_end_of_data():
    # A pure uptrend that never triggers the exit/stop should still end with
    # zero open positions in the result — the backtest force-closes at the end.
    bars = []
    ts = 0
    for _ in range(6):
        bars.append(Bar(ts, 100, 101, 99, 100, 10))
        ts += 1
    price = 100
    for _ in range(15):
        price += 5
        bars.append(Bar(ts, price - 1, price + 1, price - 2, price, 10))
        ts += 1

    result = run_backtest("BTC/USDT", bars, make_strategy(), make_risk_cfg())
    assert result.num_trades >= 1
    assert result.trades[-1].exit_reason == "backtest end (forced close)"


def test_too_few_bars_raises():
    with pytest.raises(ValueError):
        run_backtest("BTC/USDT", [Bar(0, 100, 101, 99, 100, 1)], make_strategy(), make_risk_cfg())
