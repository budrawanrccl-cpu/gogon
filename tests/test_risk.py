from bot.config import RiskConfig
from bot.risk import RiskManager


def make_risk(**overrides) -> RiskManager:
    cfg = RiskConfig(
        max_position_usd=25.0,
        max_total_exposure_usd=100.0,
        max_daily_loss_usd=50.0,
        min_order_size_usd=1.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return RiskManager(cfg)


def test_can_open_allows_within_limits():
    risk = make_risk()
    allowed, reason = risk.can_open("mkt1", 10.0)
    assert allowed
    assert reason == ""


def test_can_open_rejects_below_min_order_size():
    risk = make_risk()
    allowed, reason = risk.can_open("mkt1", 0.5)
    assert not allowed
    assert "minimum" in reason


def test_can_open_rejects_over_per_market_cap():
    risk = make_risk()
    risk.record_open("mkt1", "tokA", "YES", size=20.0, cost_usd=20.0)
    allowed, reason = risk.can_open("mkt1", 10.0)  # 20 + 10 > 25
    assert not allowed
    assert "max_position_usd" in reason


def test_can_open_rejects_over_total_exposure_cap():
    risk = make_risk(max_position_usd=1000.0, max_total_exposure_usd=30.0)
    risk.record_open("mkt1", "tokA", "YES", size=20.0, cost_usd=20.0)
    allowed, reason = risk.can_open("mkt2", 15.0)  # 20 + 15 > 30
    assert not allowed
    assert "max_total_exposure_usd" in reason


def test_daily_loss_limit_blocks_new_positions():
    risk = make_risk(max_daily_loss_usd=10.0)
    risk.record_open("mkt1", "tokA", "YES", size=10.0, cost_usd=10.0)
    pnl = risk.record_close("tokA", size=10.0, proceeds_usd=0.0)  # lose $10
    assert pnl == -10.0
    assert risk.daily_loss_limit_hit
    allowed, reason = risk.can_open("mkt2", 5.0)
    assert not allowed
    assert "daily loss limit" in reason


def test_record_open_accumulates_and_avg_price():
    risk = make_risk()
    risk.record_open("mkt1", "tokA", "YES", size=10.0, cost_usd=5.0)  # 0.50 each
    risk.record_open("mkt1", "tokA", "YES", size=10.0, cost_usd=6.0)  # 0.60 each
    pos = risk.positions["tokA"]
    assert pos.size == 20.0
    assert pos.cost_usd == 11.0
    assert abs(pos.avg_price - 0.55) < 1e-9


def test_record_close_partial_realizes_correct_pnl():
    risk = make_risk()
    risk.record_open("mkt1", "tokA", "YES", size=10.0, cost_usd=5.0)  # avg 0.50
    pnl = risk.record_close("tokA", size=4.0, proceeds_usd=3.0)  # sold 4 @ 0.75, cost basis 2.0
    assert abs(pnl - 1.0) < 1e-9
    assert risk.positions["tokA"].size == 6.0
    assert abs(risk.positions["tokA"].cost_usd - 3.0) < 1e-9


def test_record_close_full_removes_position():
    risk = make_risk()
    risk.record_open("mkt1", "tokA", "YES", size=10.0, cost_usd=5.0)
    risk.record_close("tokA", size=10.0, proceeds_usd=8.0)
    assert "tokA" not in risk.positions


def test_max_affordable_usd_respects_both_caps():
    risk = make_risk(max_position_usd=25.0, max_total_exposure_usd=30.0)
    risk.record_open("mkt1", "tokA", "YES", size=20.0, cost_usd=20.0)
    # per-market room = 5, total room = 10 -> min is 5
    assert risk.max_affordable_usd("mkt1") == 5.0


def test_max_affordable_usd_zero_when_daily_loss_hit():
    risk = make_risk(max_daily_loss_usd=5.0)
    risk.record_open("mkt1", "tokA", "YES", size=10.0, cost_usd=10.0)
    risk.record_close("tokA", size=10.0, proceeds_usd=0.0)  # -$10 loss
    assert risk.max_affordable_usd("mkt2") == 0.0
