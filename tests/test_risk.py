from datetime import datetime, timedelta, timezone

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


def test_can_open_tolerates_floating_point_rounding_at_the_cap():
    # A proposed_usd a few ULPs over the cap (as can happen from a
    # shares = usd / price; usd2 = shares * price round-trip) should still
    # be allowed rather than rejected for an insignificant fraction of a cent.
    risk = make_risk(max_position_usd=25.0)
    allowed, _ = risk.can_open("mkt1", 25.0 + 1e-9)
    assert allowed


def test_can_open_still_rejects_meaningfully_over_the_cap():
    risk = make_risk(max_position_usd=25.0)
    allowed, reason = risk.can_open("mkt1", 25.01)
    assert not allowed
    assert "max_position_usd" in reason


def test_max_affordable_usd_leaves_hedge_reserve_untouched():
    risk = make_risk(max_position_usd=1000.0, max_total_exposure_usd=100.0, hedge_reserve_usd=20.0)
    # Entry strategies (arbitrage/threshold) should only ever see 100-20=80 of
    # total room, leaving the reserve for hedging.
    assert risk.max_affordable_usd("mkt1") == 80.0


def test_max_hedge_usd_can_use_the_reserve_and_exceed_max_position_usd():
    risk = make_risk(max_position_usd=25.0, max_total_exposure_usd=100.0, hedge_reserve_usd=20.0)
    # threshold spends its entire per-market budget (25) on entry.
    risk.record_open("mkt1", "tokA", "YES", size=50.0, cost_usd=25.0)
    assert risk.max_affordable_usd("mkt1") == 0.0  # entry strategies: no room left
    # hedging can still act, using the 20 reserved for it.
    assert risk.max_hedge_usd("mkt1") == 20.0


def test_max_hedge_usd_still_bounded_by_total_exposure_cap():
    risk = make_risk(max_position_usd=25.0, max_total_exposure_usd=30.0, hedge_reserve_usd=20.0)
    risk.record_open("mkt1", "tokA", "YES", size=50.0, cost_usd=25.0)
    # total room = 30 - 25 = 5, smaller than the 20 reserve -> capped at 5.
    assert risk.max_hedge_usd("mkt1") == 5.0


def _fill(**overrides):
    row = dict(
        timestamp="2026-01-01T00:00:00+00:00",
        strategy="threshold",
        market_id="mkt1",
        token_id="tokA",
        outcome="YES",
        side="BUY",
        size_shares="10.0",
        size_usd="5.0",
    )
    row.update(overrides)
    return row


def test_restore_from_fills_rebuilds_an_open_position():
    risk = make_risk()
    risk.restore_from_fills([_fill()])
    pos = risk.positions["tokA"]
    assert pos.size == 10.0
    assert pos.cost_usd == 5.0
    assert pos.opened_by == "threshold"


def test_restore_from_fills_replays_a_partial_close():
    risk = make_risk()
    risk.restore_from_fills(
        [
            _fill(side="BUY", size_shares="10.0", size_usd="5.0"),  # avg 0.50
            _fill(side="SELL", size_shares="4.0", size_usd="3.0"),  # sold 4 @ 0.75
        ]
    )
    pos = risk.positions["tokA"]
    assert pos.size == 6.0
    assert abs(pos.cost_usd - 3.0) < 1e-9


def test_restore_from_fills_drops_a_fully_closed_position():
    risk = make_risk()
    risk.restore_from_fills(
        [
            _fill(side="BUY", size_shares="10.0", size_usd="5.0"),
            _fill(side="SELL", size_shares="10.0", size_usd="8.0"),
        ]
    )
    assert "tokA" not in risk.positions


def test_restore_from_fills_only_counts_todays_closes_toward_realized_pnl_today():
    risk = make_risk()
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    risk.restore_from_fills(
        [
            # Opened and fully closed yesterday for a $3 profit -- must NOT
            # count against today's daily-loss kill switch.
            _fill(side="BUY", timestamp=yesterday.isoformat(), token_id="tokOld", size_shares="10.0", size_usd="5.0"),
            _fill(side="SELL", timestamp=yesterday.isoformat(), token_id="tokOld", size_shares="10.0", size_usd="8.0"),
            # Opened yesterday, partially closed today for a $1 profit --
            # this one DOES count.
            _fill(side="BUY", timestamp=yesterday.isoformat(), token_id="tokB", size_shares="10.0", size_usd="5.0"),
            _fill(side="SELL", timestamp=today.isoformat(), token_id="tokB", size_shares="2.0", size_usd="2.0"),
        ]
    )
    assert "tokOld" not in risk.positions
    assert risk.positions["tokB"].size == 8.0
    assert abs(risk.realized_pnl_today - 1.0) < 1e-9


def test_restore_from_fills_ignores_a_sell_with_no_matching_position():
    risk = make_risk()
    risk.restore_from_fills([_fill(side="SELL", size_shares="5.0", size_usd="3.0")])
    assert risk.positions == {}
    assert risk.realized_pnl_today == 0.0
