from funding_bot.config import FundingArbitrageConfig, RiskConfig
from funding_bot.market_data import FundingSnapshot
from funding_bot.risk import RiskManager
from funding_bot.strategies.base import Leg
from funding_bot.strategies.funding_arbitrage import FundingArbitrageStrategy


def make_snapshot(funding_rate=0.0003, mark_price=100.0, spot_price=100.0, base="BTC"):
    return FundingSnapshot(
        base=base,
        spot_symbol=f"{base}/USDT",
        perp_symbol=f"{base}/USDT:USDT",
        funding_rate=funding_rate,
        funding_interval_hours=8.0,
        next_funding_time_ms=1000,
        mark_price=mark_price,
        spot_price=spot_price,
    )


def make_strategy(**cfg_overrides):
    cfg = FundingArbitrageConfig(
        enabled=True,
        min_funding_rate_apr=0.15,
        exit_funding_rate_apr=0.03,
        fee_buffer_apr=0.02,
        max_basis_pct=0.005,
        allow_negative_funding=False,
    )
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    risk = RiskManager(
        RiskConfig(max_position_usd=1000.0, max_total_exposure_usd=1000.0, max_daily_loss_usd=1000.0, min_order_size_usd=10.0)
    )
    return FundingArbitrageStrategy(cfg, risk), risk


def test_no_signal_when_funding_apr_below_threshold():
    # rate 0.0003 * (24/8)*365 = ~32.9% APR, still test a genuinely low one:
    strat, _ = make_strategy(min_funding_rate_apr=0.5)
    snapshot = make_snapshot(funding_rate=0.0003)
    assert strat.generate_signals(snapshot) == []


def test_no_signal_for_non_positive_funding_rate():
    strat, _ = make_strategy()
    snapshot = make_snapshot(funding_rate=-0.0005)
    assert strat.generate_signals(snapshot) == []


def test_no_signal_when_basis_too_wide():
    strat, _ = make_strategy(max_basis_pct=0.001)
    snapshot = make_snapshot(funding_rate=0.0003, mark_price=101.0, spot_price=100.0)  # 1% basis
    assert strat.generate_signals(snapshot) == []


def test_opens_hedge_when_funding_apr_clears_threshold():
    strat, risk = make_strategy(min_funding_rate_apr=0.15, fee_buffer_apr=0.02)
    # apr = 0.0003 * 3 * 365 = 32.85%, net of 2% buffer = ~30.85% >= 15%
    snapshot = make_snapshot(funding_rate=0.0003, spot_price=100.0, mark_price=100.0)

    signals = strat.generate_signals(snapshot)
    assert len(signals) == 2

    spot_sig = next(s for s in signals if s.leg == Leg.SPOT)
    perp_sig = next(s for s in signals if s.leg == Leg.PERP)

    assert spot_sig.action == "OPEN"
    assert spot_sig.side == "BUY"
    assert perp_sig.side == "SELL"
    assert spot_sig.group_id == perp_sig.group_id
    assert abs(spot_sig.qty - perp_sig.qty) < 1e-9  # equal-notional delta-neutral hedge


def test_no_new_signal_when_symbol_already_has_open_position_and_edge_holds():
    strat, risk = make_strategy()
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=100.0, perp_price=100.0,
        notional_usd=100.0, entry_funding_apr=0.3, funding_rate=0.0003, funding_time_ms=1000,
    )
    snapshot = make_snapshot(funding_rate=0.0003)  # edge still well above exit threshold
    assert strat.generate_signals(snapshot) == []


def test_closes_hedge_when_funding_apr_drops_below_exit_threshold():
    strat, risk = make_strategy(exit_funding_rate_apr=0.10)
    risk.record_open(
        "BTC", spot_qty=2.0, perp_qty=2.0, spot_price=100.0, perp_price=100.0,
        notional_usd=200.0, entry_funding_apr=0.3, funding_rate=0.0005, funding_time_ms=1000,
    )
    # apr now near zero -> should trigger a close
    snapshot = make_snapshot(funding_rate=0.00001, spot_price=105.0, mark_price=105.0)
    signals = strat.generate_signals(snapshot)
    assert len(signals) == 2
    spot_sig = next(s for s in signals if s.leg == Leg.SPOT)
    perp_sig = next(s for s in signals if s.leg == Leg.PERP)
    assert spot_sig.action == "CLOSE"
    assert spot_sig.side == "SELL"
    assert perp_sig.side == "BUY"
    assert spot_sig.qty == 2.0
    assert perp_sig.qty == 2.0


def test_closes_hedge_when_basis_blows_out():
    strat, risk = make_strategy(max_basis_pct=0.005)
    risk.record_open(
        "BTC", spot_qty=1.0, perp_qty=1.0, spot_price=100.0, perp_price=100.0,
        notional_usd=100.0, entry_funding_apr=0.3, funding_rate=0.0005, funding_time_ms=1000,
    )
    # basis 2% >> 2x max_basis_pct (1%) -> forced unwind even if funding still good
    snapshot = make_snapshot(funding_rate=0.0005, spot_price=100.0, mark_price=102.0)
    signals = strat.generate_signals(snapshot)
    assert len(signals) == 2
    assert all(s.action == "CLOSE" for s in signals)


def test_disabled_strategy_returns_nothing():
    strat, _ = make_strategy(enabled=False)
    snapshot = make_snapshot(funding_rate=0.001)
    assert strat.generate_signals(snapshot) == []
