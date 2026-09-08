from pumpbot.config import RiskConfig
from pumpbot.risk import RiskManager


def make_risk(**overrides) -> RiskManager:
    cfg = RiskConfig(
        max_position_sol=0.05,
        max_total_exposure_sol=0.2,
        max_concurrent_positions=3,
        max_daily_loss_sol=0.1,
        min_order_size_sol=0.01,
        take_profit_pct=0.5,
        stop_loss_pct=0.25,
        trailing_stop_pct=0.15,
        max_hold_seconds=900,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return RiskManager(cfg)


def test_can_open_allows_within_limits():
    risk = make_risk()
    allowed, reason = risk.can_open("mintA", 0.03)
    assert allowed
    assert reason == ""


def test_can_open_rejects_below_min_order_size():
    risk = make_risk()
    allowed, reason = risk.can_open("mintA", 0.001)
    assert not allowed
    assert "minimum" in reason


def test_can_open_rejects_duplicate_mint():
    risk = make_risk()
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.02)
    allowed, reason = risk.can_open("mintA", 0.01)
    assert not allowed
    assert "already holding" in reason


def test_can_open_rejects_over_position_cap():
    risk = make_risk(max_position_sol=0.05)
    allowed, reason = risk.can_open("mintA", 0.06)
    assert not allowed
    assert "max_position_sol" in reason


def test_can_open_rejects_over_total_exposure_cap():
    risk = make_risk(max_position_sol=1.0, max_total_exposure_sol=0.05)
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.04)
    allowed, reason = risk.can_open("mintB", 0.03)  # 0.04 + 0.03 > 0.05
    assert not allowed
    assert "max_total_exposure_sol" in reason


def test_can_open_rejects_over_max_concurrent_positions():
    risk = make_risk(max_position_sol=1.0, max_total_exposure_sol=1.0, max_concurrent_positions=1)
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)
    allowed, reason = risk.can_open("mintB", 0.01)
    assert not allowed
    assert "max_concurrent_positions" in reason


def test_daily_loss_limit_blocks_new_positions():
    risk = make_risk(max_daily_loss_sol=0.01)
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.02)
    pnl = risk.record_close("mintA", token_amount=1000.0, proceeds_sol=0.0)  # lose 0.02 SOL
    assert pnl == -0.02
    assert risk.daily_loss_limit_hit
    allowed, reason = risk.can_open("mintB", 0.01)
    assert not allowed
    assert "daily loss limit" in reason


def test_record_open_accumulates_and_avg_price():
    risk = make_risk()
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)  # 0.00001/token
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.02)  # 0.00002/token
    pos = risk.positions["mintA"]
    assert pos.token_amount == 2000.0
    assert abs(pos.cost_sol - 0.03) < 1e-12
    assert abs(pos.avg_price_sol - 0.000015) < 1e-12


def test_record_close_partial_realizes_correct_pnl():
    risk = make_risk()
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)  # avg 0.00001/token
    pnl = risk.record_close("mintA", token_amount=400.0, proceeds_sol=0.006)  # cost basis 0.004
    assert abs(pnl - 0.002) < 1e-12
    assert risk.positions["mintA"].token_amount == 600.0
    assert abs(risk.positions["mintA"].cost_sol - 0.006) < 1e-12


def test_record_close_full_removes_position():
    risk = make_risk()
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)
    risk.record_close("mintA", token_amount=1000.0, proceeds_sol=0.015)
    assert "mintA" not in risk.positions


def test_max_affordable_sol_respects_caps():
    risk = make_risk(max_position_sol=0.05, max_total_exposure_sol=0.06)
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.04)
    # position room = 0.05 (fresh cap, per-mint not accumulated across mints),
    # total room = 0.06 - 0.04 = 0.02 -> min is 0.02
    assert abs(risk.max_affordable_sol() - 0.02) < 1e-12


def test_max_affordable_sol_zero_when_daily_loss_hit():
    risk = make_risk(max_daily_loss_sol=0.005)
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)
    risk.record_close("mintA", token_amount=1000.0, proceeds_sol=0.0)  # -0.01 SOL loss
    assert risk.max_affordable_sol() == 0.0


def test_max_affordable_sol_zero_when_at_max_positions():
    risk = make_risk(max_concurrent_positions=1, max_position_sol=1.0, max_total_exposure_sol=1.0)
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)
    assert risk.max_affordable_sol() == 0.0


# -- persistence across restarts (state_path) --------------------------
# Without this, a bot restart (e.g. to pick up a config change) silently
# "forgot" every open position while the SOL spent on them stayed gone
# from the wallet — the exact bug that left tokens stuck unsellable.

def test_open_position_survives_a_simulated_restart(tmp_path):
    from pumpbot.config import RiskConfig
    from pumpbot.risk import RiskManager

    state_path = str(tmp_path / "risk_state.json")
    cfg = RiskConfig()

    risk1 = RiskManager(cfg, state_path=state_path)
    risk1.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.05)

    # A fresh RiskManager, as a new bot process would construct on startup.
    risk2 = RiskManager(cfg, state_path=state_path)
    assert "mintA" in risk2.positions
    assert risk2.positions["mintA"].symbol == "FOO"
    assert risk2.positions["mintA"].token_amount == 1000.0
    assert abs(risk2.positions["mintA"].cost_sol - 0.05) < 1e-12


def test_closed_position_and_realized_pnl_persist(tmp_path):
    from pumpbot.config import RiskConfig
    from pumpbot.risk import RiskManager

    state_path = str(tmp_path / "risk_state.json")
    cfg = RiskConfig()

    risk1 = RiskManager(cfg, state_path=state_path)
    risk1.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)
    risk1.record_close("mintA", token_amount=1000.0, proceeds_sol=0.015)  # +0.005 SOL

    risk2 = RiskManager(cfg, state_path=state_path)
    assert "mintA" not in risk2.positions  # fully closed — nothing left to restore
    assert abs(risk2.realized_pnl_today_sol - 0.005) < 1e-12


def test_without_state_path_nothing_is_written(tmp_path):
    """Default behavior (state_path=None) stays pure in-memory — no file
    is created, matching every existing caller/test that doesn't pass it.
    """
    risk = make_risk()
    risk.record_open("mintA", "FOO", token_amount=1000.0, cost_sol=0.01)
    assert list(tmp_path.iterdir()) == []


def test_corrupt_state_file_is_ignored_not_fatal(tmp_path):
    from pumpbot.config import RiskConfig
    from pumpbot.risk import RiskManager

    state_path = tmp_path / "risk_state.json"
    state_path.write_text("not valid json{{{")

    risk = RiskManager(RiskConfig(), state_path=str(state_path))  # must not raise
    assert risk.positions == {}
