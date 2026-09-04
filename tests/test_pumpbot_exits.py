from pumpbot.config import RiskConfig
from pumpbot.exits import evaluate_exit
from pumpbot.risk import RiskManager


def make_risk_with_position(**risk_overrides) -> RiskManager:
    cfg = RiskConfig(
        max_position_sol=1.0,
        max_total_exposure_sol=1.0,
        max_concurrent_positions=5,
        max_daily_loss_sol=1.0,
        min_order_size_sol=0.001,
        take_profit_pct=0.5,
        stop_loss_pct=0.25,
        trailing_stop_pct=0.15,
        max_hold_seconds=900,
    )
    for k, v in risk_overrides.items():
        setattr(cfg, k, v)
    risk = RiskManager(cfg)
    # entry price 0.0001 SOL/token
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.1)
    return risk


def test_no_exit_when_flat():
    risk = make_risk_with_position()
    pos = risk.positions["mintA"]
    sig = evaluate_exit(risk, pos, current_price_sol=0.0001)
    assert sig is None


def test_take_profit_triggers():
    risk = make_risk_with_position(take_profit_pct=0.5)
    pos = risk.positions["mintA"]
    sig = evaluate_exit(risk, pos, current_price_sol=0.000151)  # +51%
    assert sig is not None
    assert sig.side == "SELL"
    assert "take_profit" in sig.reason


def test_stop_loss_triggers():
    risk = make_risk_with_position(stop_loss_pct=0.25)
    pos = risk.positions["mintA"]
    sig = evaluate_exit(risk, pos, current_price_sol=0.000074)  # -26%
    assert sig is not None
    assert "stop_loss" in sig.reason


def test_trailing_stop_only_arms_in_profit():
    risk = make_risk_with_position(trailing_stop_pct=0.1, stop_loss_pct=0.9)
    pos = risk.positions["mintA"]
    # price never went above entry, so no peak to trail from in profit
    sig = evaluate_exit(risk, pos, current_price_sol=0.00009)  # -10%, within stop_loss
    assert sig is None


def test_trailing_stop_triggers_after_peak_pullback():
    risk = make_risk_with_position(trailing_stop_pct=0.1, take_profit_pct=0.9, stop_loss_pct=0.9)
    pos = risk.positions["mintA"]
    # run up to +40%, arming/raising the peak
    assert evaluate_exit(risk, pos, current_price_sol=0.00014) is None
    assert pos.peak_price_sol == 0.00014
    # pull back >10% from that peak, but still above entry
    sig = evaluate_exit(risk, pos, current_price_sol=0.000123)
    assert sig is not None
    assert "trailing_stop" in sig.reason


def test_max_hold_seconds_forces_exit_even_at_flat_price():
    risk = make_risk_with_position(max_hold_seconds=0)
    pos = risk.positions["mintA"]
    sig = evaluate_exit(risk, pos, current_price_sol=0.0001)
    assert sig is not None
    assert "max_hold_seconds" in sig.reason


def test_max_hold_seconds_forces_exit_with_no_live_price():
    risk = make_risk_with_position(max_hold_seconds=0)
    pos = risk.positions["mintA"]
    sig = evaluate_exit(risk, pos, current_price_sol=None)
    assert sig is not None
    assert "max_hold_seconds" in sig.reason


def test_no_exit_within_bands_and_before_max_hold():
    risk = make_risk_with_position()
    pos = risk.positions["mintA"]
    sig = evaluate_exit(risk, pos, current_price_sol=0.000105)  # +5%, within bands
    assert sig is None
