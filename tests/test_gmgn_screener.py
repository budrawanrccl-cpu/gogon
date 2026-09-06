from gmgn.config import ScreenerConfig
from gmgn.models import TokenActivity, TokenStats
from gmgn.screener import SmartMoneyScreener

NOW = 1_700_000_000.0


def make_screener(**overrides) -> SmartMoneyScreener:
    cfg = ScreenerConfig(
        lookback_minutes=60,
        min_smart_wallets=3,
        min_net_buy_usd=2000.0,
        min_liquidity_usd=5000.0,
        min_holder_count=50,
        max_top_10_holder_pct=40.0,
        max_token_age_minutes=1440,
        min_market_cap_usd=0.0,
        max_market_cap_usd=0.0,
        required_tags=["smart_degen"],
        exclude_honeypot=True,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return SmartMoneyScreener(cfg)


def make_stats(**overrides) -> TokenStats:
    defaults = dict(
        chain="sol",
        address="tokenA",
        symbol="FOO",
        liquidity_usd=10000.0,
        market_cap_usd=100000.0,
        holder_count=200,
        top_10_holder_pct=20.0,
        open_timestamp=int(NOW) - 3600,
        is_honeypot=False,
    )
    defaults.update(overrides)
    return TokenStats(**defaults)


def make_activity(wallet: str, side: str, amount_usd: float, tags=("smart_degen",), ts_offset=0) -> TokenActivity:
    return TokenActivity(
        chain="sol",
        token_address="tokenA",
        wallet_address=wallet,
        wallet_tags=list(tags),
        side=side,
        amount_usd=amount_usd,
        price_usd=1.0,
        timestamp=int(NOW) - ts_offset,
    )


def three_buys(amount_usd=1000.0):
    return [make_activity(f"wallet{i}", "buy", amount_usd) for i in range(3)]


def test_passes_when_all_thresholds_met():
    screener = make_screener()
    signal = screener.evaluate(make_stats(), three_buys(1000.0), now=NOW)
    assert signal is not None
    assert signal.smart_wallet_count == 3
    assert signal.net_smart_buy_usd == 3000.0
    assert signal.address == "tokenA"
    assert signal.score > 0


def test_fails_below_min_smart_wallets():
    screener = make_screener()
    activities = [make_activity(f"wallet{i}", "buy", 1000.0) for i in range(2)]
    assert screener.evaluate(make_stats(), activities, now=NOW) is None


def test_fails_below_min_net_buy_usd():
    screener = make_screener(min_net_buy_usd=10000.0)
    assert screener.evaluate(make_stats(), three_buys(1000.0), now=NOW) is None


def test_sells_reduce_net_flow():
    screener = make_screener(min_net_buy_usd=100.0)
    activities = three_buys(1000.0) + [make_activity("wallet9", "sell", 2900.0)]
    signal = screener.evaluate(make_stats(), activities, now=NOW)
    assert signal is not None
    assert signal.net_smart_buy_usd == 100.0  # 3000 buy - 2900 sell


def test_excludes_honeypot():
    screener = make_screener()
    stats = make_stats(is_honeypot=True)
    assert screener.evaluate(stats, three_buys(), now=NOW) is None


def test_excludes_low_liquidity():
    screener = make_screener()
    stats = make_stats(liquidity_usd=1000.0)
    assert screener.evaluate(stats, three_buys(), now=NOW) is None


def test_excludes_high_holder_concentration():
    screener = make_screener()
    stats = make_stats(top_10_holder_pct=90.0)
    assert screener.evaluate(stats, three_buys(), now=NOW) is None


def test_excludes_stale_pairs():
    screener = make_screener(max_token_age_minutes=10)
    stats = make_stats(open_timestamp=int(NOW) - 3600)  # 60 minutes old
    assert screener.evaluate(stats, three_buys(), now=NOW) is None


def test_ignores_activity_outside_lookback_window():
    screener = make_screener(lookback_minutes=10)
    activities = [make_activity(f"wallet{i}", "buy", 1000.0, ts_offset=3600) for i in range(3)]
    assert screener.evaluate(make_stats(), activities, now=NOW) is None


def test_ignores_activity_without_required_tag():
    screener = make_screener()
    activities = [make_activity(f"wallet{i}", "buy", 1000.0, tags=("kol",)) for i in range(3)]
    assert screener.evaluate(make_stats(), activities, now=NOW) is None


def test_required_tags_empty_means_any_wallet_counts():
    screener = make_screener(required_tags=[])
    activities = [make_activity(f"wallet{i}", "buy", 1000.0, tags=()) for i in range(3)]
    signal = screener.evaluate(make_stats(), activities, now=NOW)
    assert signal is not None


def test_score_rewards_more_wallets_and_flow():
    screener = make_screener()
    stats = make_stats()
    small = screener.evaluate(stats, three_buys(700.0), now=NOW)
    bigger = screener.evaluate(
        stats, [make_activity(f"wallet{i}", "buy", 700.0) for i in range(6)], now=NOW
    )
    assert small is not None and bigger is not None
    assert bigger.score > small.score


def test_score_penalizes_holder_concentration():
    screener = make_screener()
    low_concentration = screener.evaluate(make_stats(top_10_holder_pct=5.0), three_buys(1000.0), now=NOW)
    high_concentration = screener.evaluate(make_stats(top_10_holder_pct=35.0), three_buys(1000.0), now=NOW)
    assert low_concentration is not None and high_concentration is not None
    assert low_concentration.score > high_concentration.score
