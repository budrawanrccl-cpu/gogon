from bot.config import HedgingConfig, RiskConfig
from bot.market_data import BookLevel, MarketInfo, TokenInfo
from bot.risk import RiskManager
from bot.strategies.hedging import HedgingStrategy


def make_market():
    return MarketInfo(
        condition_id="mkt1",
        question="Will X happen?",
        tokens=[TokenInfo(token_id="tokYES", outcome="YES"), TokenInfo(token_id="tokNO", outcome="NO")],
        active=True,
        closed=False,
    )


def make_strategy(trigger_loss_pct=0.10, hedge_ratio=1.0, max_position_usd=100.0, max_total_exposure_usd=100.0):
    cfg = HedgingConfig(enabled=True, trigger_loss_pct=trigger_loss_pct, hedge_ratio=hedge_ratio)
    risk = RiskManager(
        RiskConfig(
            max_position_usd=max_position_usd,
            max_total_exposure_usd=max_total_exposure_usd,
            max_daily_loss_usd=100.0,
            min_order_size_usd=1.0,
        )
    )
    return HedgingStrategy(cfg, risk), risk


def test_no_signal_without_open_position():
    strat, _ = make_strategy()
    market = make_market()
    book = {"tokYES": BookLevel(0.50, 0.51, 100, 100), "tokNO": BookLevel(0.49, 0.50, 100, 100)}
    assert strat.generate_signals(market, lambda tid: book[tid]) == []


def test_no_signal_when_loss_below_trigger():
    strat, risk = make_strategy(trigger_loss_pct=0.10)
    market = make_market()
    # Bought YES at 0.60, now down only ~5% — below the 10% trigger.
    risk.record_open("mkt1", "tokYES", "YES", size=10.0, cost_usd=6.0)
    book = {"tokYES": BookLevel(0.56, 0.57, 100, 100), "tokNO": BookLevel(0.42, 0.43, 100, 100)}
    assert strat.generate_signals(market, lambda tid: book[tid]) == []


def test_hedge_signal_on_loss_past_trigger():
    strat, risk = make_strategy(trigger_loss_pct=0.10, hedge_ratio=1.0)
    market = make_market()
    # Bought 10 YES shares at avg 0.60; price has now dropped to a 0.40 mid (~33% loss).
    risk.record_open("mkt1", "tokYES", "YES", size=10.0, cost_usd=6.0)
    book = {"tokYES": BookLevel(0.39, 0.41, 100, 100), "tokNO": BookLevel(0.59, 0.61, 100, 100)}

    signals = strat.generate_signals(market, lambda tid: book[tid])

    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy == "hedging"
    assert sig.side == "BUY"
    assert sig.outcome == "NO"
    assert sig.token_id == "tokNO"
    assert sig.limit_price == 0.61
    assert sig.size_shares == 10.0  # fully hedge_ratio=1.0 -> match the 10 YES shares


def test_no_further_hedge_once_already_matched():
    strat, risk = make_strategy(trigger_loss_pct=0.10, hedge_ratio=1.0)
    market = make_market()
    risk.record_open("mkt1", "tokYES", "YES", size=10.0, cost_usd=6.0)
    risk.record_open("mkt1", "tokNO", "NO", size=10.0, cost_usd=6.0)  # already hedged 1:1
    book = {"tokYES": BookLevel(0.39, 0.41, 100, 100), "tokNO": BookLevel(0.59, 0.61, 100, 100)}

    assert strat.generate_signals(market, lambda tid: book[tid]) == []


def test_hedge_size_capped_by_liquidity():
    strat, risk = make_strategy(trigger_loss_pct=0.10, hedge_ratio=1.0)
    market = make_market()
    risk.record_open("mkt1", "tokYES", "YES", size=10.0, cost_usd=6.0)
    # Only 3 shares available on the opposite side's ask.
    book = {"tokYES": BookLevel(0.39, 0.41, 100, 100), "tokNO": BookLevel(0.59, 0.61, 3, 3)}

    signals = strat.generate_signals(market, lambda tid: book[tid])

    assert len(signals) == 1
    assert signals[0].size_shares == 3.0


def test_hedge_uses_reserve_when_entry_strategy_exhausted_the_market_cap():
    # Simulates threshold having just spent its entire per-market budget —
    # without a hedge reserve, hedging would have $0 room (see
    # test_no_signal_without_open_position-style scenarios / max_affordable_usd).
    strat, risk = make_strategy(
        trigger_loss_pct=0.10, hedge_ratio=1.0, max_position_usd=25.0, max_total_exposure_usd=100.0
    )
    risk.cfg.hedge_reserve_usd = 20.0
    market = make_market()
    risk.record_open("mkt1", "tokYES", "YES", size=50.0, cost_usd=25.0)  # avg 0.50, at the cap
    book = {"tokYES": BookLevel(0.39, 0.41, 100, 100), "tokNO": BookLevel(0.59, 0.61, 100, 100)}

    signals = strat.generate_signals(market, lambda tid: book[tid])

    assert len(signals) == 1
    assert signals[0].outcome == "NO"
    assert signals[0].size_usd <= 20.0 + 1e-9


def test_orphaned_hedge_gets_closed_when_protected_position_is_gone():
    # The YES position hedging was protecting has since been closed
    # (e.g. threshold sold it); NO -- opened by hedging -- is now orphaned
    # and should be sold at market rather than left open indefinitely.
    strat, risk = make_strategy()
    market = make_market()
    risk.record_open("mkt1", "tokNO", "NO", size=40.0, cost_usd=24.0, opened_by="hedging")
    book = {"tokYES": BookLevel(0.69, 0.71, 100, 100), "tokNO": BookLevel(0.29, 0.31, 100, 100)}

    signals = strat.generate_signals(market, lambda tid: book[tid])

    assert len(signals) == 1
    sig = signals[0]
    assert sig.side == "SELL"
    assert sig.outcome == "NO"
    assert sig.size_shares == 40.0
    assert sig.limit_price == 0.29


def test_hedge_not_closed_while_still_protecting_an_active_position():
    strat, risk = make_strategy(trigger_loss_pct=0.10, hedge_ratio=1.0)
    market = make_market()
    risk.record_open("mkt1", "tokYES", "YES", size=10.0, cost_usd=6.0, opened_by="threshold")
    risk.record_open("mkt1", "tokNO", "NO", size=10.0, cost_usd=6.0, opened_by="hedging")
    # Stable book: no new hedge needed (already matched) and nothing orphaned.
    book = {"tokYES": BookLevel(0.59, 0.61, 100, 100), "tokNO": BookLevel(0.39, 0.41, 100, 100)}

    signals = strat.generate_signals(market, lambda tid: book[tid])

    assert signals == []


def test_never_hedges_a_position_that_is_itself_a_hedge():
    # Regression: a hedge that has itself moved against its own avg price
    # must not be treated as a fresh directional position worth protecting
    # -- that would ping-pong capital between both outcomes. Unlike the
    # orphaned-hedge case, the position it's protecting (YES) is still
    # active here, so the only question is whether NO gets "hedged" too.
    strat, risk = make_strategy(trigger_loss_pct=0.10, hedge_ratio=1.0)
    market = make_market()
    risk.record_open("mkt1", "tokYES", "YES", size=10.0, cost_usd=6.0, opened_by="threshold")  # avg 0.60, not down
    risk.record_open("mkt1", "tokNO", "NO", size=40.0, cost_usd=24.0, opened_by="hedging")  # avg 0.60, down hard
    book = {"tokYES": BookLevel(0.59, 0.61, 100, 100), "tokNO": BookLevel(0.29, 0.31, 100, 100)}

    signals = strat.generate_signals(market, lambda tid: book[tid])

    assert signals == []


def test_disabled_strategy_returns_nothing():
    cfg = HedgingConfig(enabled=False, trigger_loss_pct=0.10, hedge_ratio=1.0)
    risk = RiskManager(RiskConfig(max_position_usd=100, max_total_exposure_usd=100, max_daily_loss_usd=100, min_order_size_usd=1))
    strat = HedgingStrategy(cfg, risk)
    market = make_market()
    risk.record_open("mkt1", "tokYES", "YES", size=10.0, cost_usd=6.0)
    book = {"tokYES": BookLevel(0.39, 0.41, 100, 100), "tokNO": BookLevel(0.59, 0.61, 100, 100)}
    assert strat.generate_signals(market, lambda tid: book[tid]) == []
