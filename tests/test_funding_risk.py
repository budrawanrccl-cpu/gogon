from funding_bot.config import RiskConfig
from funding_bot.risk import RiskManager


def make_risk(**overrides) -> RiskManager:
    cfg = RiskConfig(
        max_position_usd=100.0,
        max_total_exposure_usd=300.0,
        max_daily_loss_usd=50.0,
        min_order_size_usd=10.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return RiskManager(cfg)


def test_can_open_allows_within_limits():
    risk = make_risk()
    allowed, reason = risk.can_open("BTC", 50.0)
    assert allowed
    assert reason == ""


def test_can_open_rejects_below_min_order_size():
    risk = make_risk()
    allowed, reason = risk.can_open("BTC", 5.0)
    assert not allowed
    assert "minimum" in reason


def test_can_open_rejects_second_position_in_same_symbol():
    risk = make_risk()
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=100.0, perp_price=100.0,
        notional_usd=100.0, entry_funding_apr=0.2, funding_rate=0.0002, funding_time_ms=1000,
    )
    allowed, reason = risk.can_open("BTC", 10.0)
    assert not allowed
    assert "already has an open" in reason


def test_can_open_rejects_over_per_symbol_cap():
    risk = make_risk(max_position_usd=25.0)
    allowed, reason = risk.can_open("BTC", 30.0)
    assert not allowed
    assert "max_position_usd" in reason


def test_can_open_rejects_over_total_exposure_cap():
    risk = make_risk(max_position_usd=1000.0, max_total_exposure_usd=30.0)
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=20.0, perp_price=20.0,
        notional_usd=20.0, entry_funding_apr=0.2, funding_rate=0.0002, funding_time_ms=1000,
    )
    allowed, reason = risk.can_open("ETH", 15.0)  # 20 + 15 > 30
    assert not allowed
    assert "max_total_exposure_usd" in reason


def test_daily_loss_limit_blocks_new_positions():
    risk = make_risk(max_daily_loss_usd=10.0)
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=100.0, perp_price=100.0,
        notional_usd=100.0, entry_funding_apr=0.2, funding_rate=0.0002, funding_time_ms=1000,
    )
    pnl = risk.record_close("BTC", spot_proceeds_usd=90.0, perp_proceeds_usd=100.0)  # -$10 price P&L
    assert pnl == -10.0
    assert risk.daily_loss_limit_hit
    allowed, reason = risk.can_open("ETH", 20.0)
    assert not allowed
    assert "daily loss limit" in reason


def test_record_close_computes_price_pnl_for_short_perp_hedge():
    risk = make_risk()
    # Open: buy 1 BTC spot @ 100, sell 1 BTC perp @ 100 (short).
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=100.0, perp_price=100.0,
        notional_usd=100.0, entry_funding_apr=0.2, funding_rate=0.0002, funding_time_ms=1000,
    )
    # Close: sell spot @ 110 (+10), buy back perp @ 110 (perp leg loses 10 since
    # it was short) -> net price P&L should be ~0 (delta-neutral hedge).
    pnl = risk.record_close("BTC", spot_proceeds_usd=110.0, perp_proceeds_usd=110.0)
    assert abs(pnl - 0.0) < 1e-9
    assert "BTC" not in risk.positions


def test_accrue_funding_credits_pending_rate_once_per_settlement():
    risk = make_risk()
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=2.0, spot_price=100.0, perp_price=100.0,
        notional_usd=100.0, entry_funding_apr=0.2, funding_rate=0.0005, funding_time_ms=1000,
    )
    # Same funding_time_ms as entry -> nothing has settled yet.
    credited = risk.accrue_funding("BTC", funding_rate=0.0006, mark_price=100.0, funding_time_ms=1000)
    assert credited == 0.0
    assert risk.positions["BTC"].funding_collected_usd == 0.0

    # Timestamp advanced -> the *previously pending* rate (0.0005) settles now.
    credited = risk.accrue_funding("BTC", funding_rate=0.0006, mark_price=100.0, funding_time_ms=2000)
    assert abs(credited - (2.0 * 100.0 * 0.0005)) < 1e-9
    assert abs(risk.positions["BTC"].funding_collected_usd - credited) < 1e-9
    assert abs(risk.realized_pnl_today - credited) < 1e-9

    # No new settlement this call -> no double-credit.
    credited_again = risk.accrue_funding("BTC", funding_rate=0.0006, mark_price=100.0, funding_time_ms=2000)
    assert credited_again == 0.0


def test_max_affordable_usd_respects_both_caps():
    risk = make_risk(max_position_usd=25.0, max_total_exposure_usd=30.0)
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=20.0, perp_price=20.0,
        notional_usd=20.0, entry_funding_apr=0.2, funding_rate=0.0002, funding_time_ms=1000,
    )
    # per-symbol room = 25 (BTC already has a position so ETH room unaffected),
    # total room = 30 - 20 = 10 -> min is 10
    assert risk.max_affordable_usd("ETH") == 10.0


def test_max_affordable_usd_zero_for_symbol_with_open_position():
    risk = make_risk()
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=20.0, perp_price=20.0,
        notional_usd=20.0, entry_funding_apr=0.2, funding_rate=0.0002, funding_time_ms=1000,
    )
    assert risk.max_affordable_usd("BTC") == 0.0
