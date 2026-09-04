import time

from pumpbot.config import FilterConfig, RiskConfig
from pumpbot.market_data import TokenStats
from pumpbot.risk import RiskManager
from pumpbot.strategies.momentum import MomentumEntryStrategy


def make_strategy(**filter_overrides):
    fcfg = FilterConfig(
        min_token_age_seconds=20,
        max_token_age_seconds=180,
        min_unique_buyers=5,
        min_buy_volume_sol=1.0,
        max_creator_holding_pct=20.0,
        min_market_cap_sol=5.0,
        max_market_cap_sol=200.0,
        blacklist_mints=[],
        watch_window_seconds=300,
    )
    for k, v in filter_overrides.items():
        setattr(fcfg, k, v)
    rcfg = RiskConfig(
        max_position_sol=0.05,
        max_total_exposure_sol=0.25,
        max_concurrent_positions=5,
        max_daily_loss_sol=0.5,
        min_order_size_sol=0.01,
    )
    risk = RiskManager(rcfg)
    return MomentumEntryStrategy(fcfg, risk), risk


def qualifying_stats(age=30.0, buyers=6, buy_vol=2.0, mcap=10.0, price=0.0001) -> TokenStats:
    stats = TokenStats(mint="mintA", name="Foo", symbol="FOO")
    stats.first_seen = time.time() - age
    stats.unique_buyers = {f"buyer{i}" for i in range(buyers)}
    stats.buy_volume_sol = buy_vol
    stats.sell_volume_sol = 0.0
    stats.market_cap_sol = mcap
    stats.last_price_sol_per_token = price
    return stats


def test_too_young_returns_none_but_not_decided():
    strategy, _ = make_strategy()
    stats = qualifying_stats(age=5.0)
    assert strategy.evaluate(stats) is None
    assert stats.decided is False  # keep watching


def test_too_old_marks_decided_and_skips():
    strategy, _ = make_strategy()
    stats = qualifying_stats(age=999.0)
    assert strategy.evaluate(stats) is None
    assert stats.decided is True


def test_qualifying_token_produces_buy_signal():
    strategy, _ = make_strategy()
    stats = qualifying_stats()
    sig = strategy.evaluate(stats)
    assert sig is not None
    assert sig.side == "BUY"
    assert sig.mint == "mintA"
    assert stats.decided is True


def test_insufficient_unique_buyers_keeps_watching():
    strategy, _ = make_strategy(min_unique_buyers=10)
    stats = qualifying_stats(buyers=3)
    assert strategy.evaluate(stats) is None
    assert stats.decided is False


def test_insufficient_buy_volume_keeps_watching():
    strategy, _ = make_strategy(min_buy_volume_sol=5.0)
    stats = qualifying_stats(buy_vol=1.0)
    assert strategy.evaluate(stats) is None
    assert stats.decided is False


def test_net_sell_pressure_marks_decided_and_skips():
    strategy, _ = make_strategy()
    stats = qualifying_stats()
    stats.sell_volume_sol = 10.0  # more selling than buying
    assert strategy.evaluate(stats) is None
    assert stats.decided is True


def test_market_cap_outside_window_marks_decided_and_skips():
    strategy, _ = make_strategy()
    stats = qualifying_stats(mcap=1000.0)
    assert strategy.evaluate(stats) is None
    assert stats.decided is True


def test_creator_holding_too_high_marks_decided_and_skips():
    strategy, _ = make_strategy()
    stats = qualifying_stats()
    stats.creator_holding_pct = 50.0
    assert strategy.evaluate(stats) is None
    assert stats.decided is True


def test_unknown_creator_holding_does_not_block_entry():
    strategy, _ = make_strategy()
    stats = qualifying_stats()
    stats.creator_holding_pct = None  # unknown -- not a blocker
    sig = strategy.evaluate(stats)
    assert sig is not None


def test_blacklisted_mint_is_skipped_immediately():
    strategy, _ = make_strategy(blacklist_mints=["mintA"])
    stats = qualifying_stats(age=999.0)
    stats.mint = "mintA"
    assert strategy.evaluate(stats) is None
    assert stats.decided is True


def test_already_decided_is_not_re_evaluated():
    strategy, _ = make_strategy()
    stats = qualifying_stats()
    stats.decided = True
    assert strategy.evaluate(stats) is None


def test_no_signal_when_risk_budget_exhausted():
    strategy, risk = make_strategy()
    risk.record_open("otherMint", "BAR", token_amount=1.0, cost_sol=0.25)  # eats all exposure room
    stats = qualifying_stats()
    assert strategy.evaluate(stats) is None
    assert stats.decided is False  # filters passed; only budget was the blocker, so retry is allowed
