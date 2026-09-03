from bot.config import ArbitrageConfig, RiskConfig
from bot.market_data import BookLevel, MarketInfo, TokenInfo
from bot.risk import RiskManager
from bot.strategies.arbitrage import ArbitrageStrategy


def make_market():
    return MarketInfo(
        condition_id="mkt1",
        question="Will X happen?",
        tokens=[TokenInfo(token_id="tokYES", outcome="YES"), TokenInfo(token_id="tokNO", outcome="NO")],
        active=True,
        closed=False,
    )


def make_strategy(min_edge=0.015, fee_buffer=0.005, max_position_usd=100.0, max_total_exposure_usd=100.0):
    cfg = ArbitrageConfig(enabled=True, min_edge=min_edge, fee_buffer=fee_buffer)
    risk = RiskManager(
        RiskConfig(
            max_position_usd=max_position_usd,
            max_total_exposure_usd=max_total_exposure_usd,
            max_daily_loss_usd=1000.0,
            min_order_size_usd=1.0,
        )
    )
    return ArbitrageStrategy(cfg, risk), risk


def test_no_signal_when_no_edge():
    strat, _ = make_strategy()
    market = make_market()

    books = {
        "tokYES": BookLevel(best_bid=0.50, best_ask=0.51, best_bid_size=100, best_ask_size=100),
        "tokNO": BookLevel(best_bid=0.48, best_ask=0.50, best_bid_size=100, best_ask_size=100),
    }
    # combined ask = 1.01 -> no arbitrage
    signals = strat.generate_signals(market, lambda tid: books[tid])
    assert signals == []


def test_signal_when_combined_ask_below_one():
    strat, _ = make_strategy(min_edge=0.015, fee_buffer=0.005)
    market = make_market()

    # combined ask = 0.96 -> edge = 1 - 0.96 - 0.005 = 0.035 >= 0.015
    books = {
        "tokYES": BookLevel(best_bid=0.45, best_ask=0.47, best_bid_size=50, best_ask_size=50),
        "tokNO": BookLevel(best_bid=0.47, best_ask=0.49, best_bid_size=50, best_ask_size=50),
    }
    signals = strat.generate_signals(market, lambda tid: books[tid])
    assert len(signals) == 2

    yes_sig = next(s for s in signals if s.outcome == "YES")
    no_sig = next(s for s in signals if s.outcome == "NO")

    assert yes_sig.side == "BUY"
    assert no_sig.side == "BUY"
    assert yes_sig.group_id == no_sig.group_id
    # equal share counts on both legs (required for true arbitrage)
    assert abs(yes_sig.size_shares - no_sig.size_shares) < 1e-9


def test_size_limited_by_liquidity():
    strat, risk = make_strategy(max_position_usd=1000.0, max_total_exposure_usd=1000.0)
    market = make_market()

    books = {
        "tokYES": BookLevel(best_bid=0.45, best_ask=0.47, best_bid_size=3, best_ask_size=3),
        "tokNO": BookLevel(best_bid=0.47, best_ask=0.49, best_bid_size=500, best_ask_size=500),
    }
    signals = strat.generate_signals(market, lambda tid: books[tid])
    assert len(signals) == 2
    for s in signals:
        assert abs(s.size_shares - 3.0) < 1e-9  # capped by the thinner (YES) book


def test_size_limited_by_risk_budget():
    strat, risk = make_strategy(max_position_usd=5.0, max_total_exposure_usd=5.0)
    market = make_market()

    books = {
        "tokYES": BookLevel(best_bid=0.45, best_ask=0.47, best_bid_size=1000, best_ask_size=1000),
        "tokNO": BookLevel(best_bid=0.47, best_ask=0.49, best_bid_size=1000, best_ask_size=1000),
    }
    combined_ask = 0.47 + 0.49
    signals = strat.generate_signals(market, lambda tid: books[tid])
    assert len(signals) == 2
    total_cost = sum(s.size_usd for s in signals)
    assert total_cost <= 5.0 + 1e-6
    expected_shares = 5.0 / combined_ask
    assert abs(signals[0].size_shares - expected_shares) < 1e-6


def test_no_signal_for_non_binary_market():
    strat, _ = make_strategy()
    market = MarketInfo(
        condition_id="mkt2",
        question="Multi-outcome market",
        tokens=[TokenInfo(token_id="a", outcome="A")],
        active=True,
        closed=False,
    )
    signals = strat.generate_signals(market, lambda tid: BookLevel(0.5, 0.5, 10, 10))
    assert signals == []


def test_disabled_strategy_returns_nothing():
    cfg = ArbitrageConfig(enabled=False, min_edge=0.0, fee_buffer=0.0)
    risk = RiskManager(RiskConfig(max_position_usd=100, max_total_exposure_usd=100, max_daily_loss_usd=100, min_order_size_usd=1))
    strat = ArbitrageStrategy(cfg, risk)
    market = make_market()
    books = {
        "tokYES": BookLevel(0.1, 0.2, 100, 100),
        "tokNO": BookLevel(0.1, 0.2, 100, 100),
    }
    assert strat.generate_signals(market, lambda tid: books[tid]) == []
