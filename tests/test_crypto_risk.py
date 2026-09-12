import pytest

from crypto_bot.models import Position
from crypto_bot.risk import RiskConfig, RiskManager


def make_risk(**overrides) -> RiskManager:
    cfg = RiskConfig(
        starting_equity_usd=1000.0,
        risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.20,
        max_concurrent_positions=1,
        min_order_size_usd=10.0,
        fee_pct=0.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return RiskManager(cfg)


def test_position_size_risks_exactly_the_configured_fraction():
    risk = make_risk(risk_per_trade_pct=0.01)  # risk $10 on $1000 equity
    size = risk.position_size(entry_price=100.0, stop_price=90.0)  # $10 stop distance/share
    assert size == pytest.approx(1.0)  # $10 risk / $10 per share = 1 share


def test_position_size_zero_for_invalid_stop():
    risk = make_risk()
    assert risk.position_size(entry_price=100.0, stop_price=100.0) == 0.0
    assert risk.position_size(entry_price=100.0, stop_price=110.0) == 0.0  # stop above entry (long)


def test_position_size_capped_by_available_equity():
    risk = make_risk(risk_per_trade_pct=0.5)  # would want $500 risk
    # stop distance tiny -> naive size huge, but capped to equity / price
    size = risk.position_size(entry_price=100.0, stop_price=99.99)
    assert size == pytest.approx(1000.0 / 100.0)


def test_can_open_allows_when_flat():
    risk = make_risk()
    allowed, reason = risk.can_open("BTC/USDT")
    assert allowed
    assert reason == ""


def test_can_open_rejects_when_already_holding_symbol():
    risk = make_risk()
    risk.record_open("BTC/USDT", Position("BTC/USDT", "LONG", 100.0, 1.0, 90.0, opened_at=0))
    allowed, reason = risk.can_open("BTC/USDT")
    assert not allowed
    assert "already holding" in reason


def test_can_open_rejects_over_max_concurrent_positions():
    risk = make_risk(max_concurrent_positions=1)
    risk.record_open("BTC/USDT", Position("BTC/USDT", "LONG", 100.0, 1.0, 90.0, opened_at=0))
    allowed, reason = risk.can_open("ETH/USDT")
    assert not allowed
    assert "max_concurrent_positions" in reason


def test_daily_loss_limit_blocks_new_positions():
    risk = make_risk(max_daily_loss_pct=0.01)  # $10 on $1000 equity
    risk.record_open("BTC/USDT", Position("BTC/USDT", "LONG", 100.0, 1.0, 90.0, opened_at=0))
    trade = risk.record_close("BTC/USDT", exit_price=88.0, closed_at=1, reason="stop hit")  # -$12
    assert trade.pnl_usd == pytest.approx(-12.0)
    assert risk.daily_loss_limit_hit
    allowed, reason = risk.can_open("ETH/USDT")
    assert not allowed
    assert "daily loss limit" in reason


def test_max_drawdown_halts_new_positions_but_not_existing():
    risk = make_risk(max_drawdown_pct=0.05)  # halt at 5% drawdown
    risk.mark_unrealized(-60.0)  # -6% on $1000 equity
    assert risk.halted_for_drawdown
    allowed, reason = risk.can_open("BTC/USDT")
    assert not allowed
    assert "drawdown" in reason


def test_record_close_removes_position_and_computes_fees():
    risk = make_risk(fee_pct=0.01)
    risk.record_open("BTC/USDT", Position("BTC/USDT", "LONG", 100.0, 2.0, 90.0, opened_at=0))
    trade = risk.record_close("BTC/USDT", exit_price=110.0, closed_at=1, reason="channel exit")
    # gross pnl = (110-100)*2 = 20; fees = (100*2 + 110*2)*0.01 = 4.2
    assert trade.pnl_usd == pytest.approx(20.0 - 4.2)
    assert "BTC/USDT" not in risk.open_positions
    assert risk.realized_equity == pytest.approx(1000.0 + (20.0 - 4.2))


def test_record_close_unknown_symbol_returns_none():
    risk = make_risk()
    assert risk.record_close("BTC/USDT", exit_price=100.0, closed_at=0, reason="n/a") is None
