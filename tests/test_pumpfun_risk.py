from pumpfun_bot.config import RiskConfig
from pumpfun_bot.risk import RiskManager


def make_risk(**overrides) -> RiskManager:
    cfg = RiskConfig(
        max_position_sol=0.5,
        max_total_exposure_sol=2.0,
        max_daily_loss_sol=1.0,
        min_virtual_sol_reserves=5.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return RiskManager(cfg)


def test_can_open_allows_within_limits():
    risk = make_risk()
    allowed, reason = risk.can_open("mintA", 0.1)
    assert allowed
    assert reason == ""


def test_can_open_rejects_zero_or_negative():
    risk = make_risk()
    allowed, reason = risk.can_open("mintA", 0.0)
    assert not allowed
    assert "zero or negative" in reason


def test_can_open_rejects_over_per_mint_cap():
    risk = make_risk()
    risk.record_open("mintA", token_amount=1000.0, cost_sol=0.4)
    allowed, reason = risk.can_open("mintA", 0.2)  # 0.4 + 0.2 > 0.5
    assert not allowed
    assert "max_position_sol" in reason


def test_can_open_rejects_over_total_exposure_cap():
    risk = make_risk(max_position_sol=1000.0, max_total_exposure_sol=0.3)
    risk.record_open("mintA", token_amount=1000.0, cost_sol=0.2)
    allowed, reason = risk.can_open("mintB", 0.2)  # 0.2 + 0.2 > 0.3
    assert not allowed
    assert "max_total_exposure_sol" in reason


def test_daily_loss_limit_blocks_new_positions():
    risk = make_risk(max_daily_loss_sol=0.1)
    risk.record_open("mintA", token_amount=1000.0, cost_sol=0.1)
    pnl = risk.record_close("mintA", token_amount=1000.0, proceeds_sol=0.0)  # lose 0.1 SOL
    assert pnl == -0.1
    assert risk.daily_loss_limit_hit
    allowed, reason = risk.can_open("mintB", 0.05)
    assert not allowed
    assert "daily loss limit" in reason


def test_record_open_accumulates_and_avg_price():
    risk = make_risk()
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.05)  # 0.0005 each
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.06)  # 0.0006 each
    pos = risk.positions["mintA"]
    assert pos.token_amount == 200.0
    assert abs(pos.cost_sol - 0.11) < 1e-9
    assert abs(pos.avg_price_sol - 0.00055) < 1e-9


def test_record_close_partial_realizes_correct_pnl():
    risk = make_risk()
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.05)  # avg 0.0005/token
    pnl = risk.record_close("mintA", token_amount=40.0, proceeds_sol=0.03)  # cost basis 0.02
    assert abs(pnl - 0.01) < 1e-9
    assert risk.positions["mintA"].token_amount == 60.0
    assert abs(risk.positions["mintA"].cost_sol - 0.03) < 1e-9


def test_record_close_full_removes_position():
    risk = make_risk()
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.05)
    risk.record_close("mintA", token_amount=100.0, proceeds_sol=0.08)
    assert "mintA" not in risk.positions


def test_max_affordable_sol_respects_both_caps():
    risk = make_risk(max_position_sol=0.5, max_total_exposure_sol=0.6)
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.4)
    # per-mint room = 0.1, total room = 0.2 -> min is 0.1
    assert abs(risk.max_affordable_sol("mintA") - 0.1) < 1e-9


def test_max_affordable_sol_zero_when_daily_loss_hit():
    risk = make_risk(max_daily_loss_sol=0.1)
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.1)
    risk.record_close("mintA", token_amount=100.0, proceeds_sol=0.0)  # -0.1 SOL loss
    assert risk.max_affordable_sol("mintB") == 0.0
