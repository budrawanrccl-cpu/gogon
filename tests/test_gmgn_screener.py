from gmgn.config import ScreenerConfig
from gmgn.models import TokenStats
from gmgn.screener import SmartMoneyScreener

NOW = 1_700_000_000.0


def make_screener(**overrides) -> SmartMoneyScreener:
    cfg = ScreenerConfig(
        min_smart_buy_24h=3,
        min_net_smart_buys=2,
        min_liquidity_usd=5000.0,
        min_holder_count=50,
        min_market_cap_usd=0.0,
        max_market_cap_usd=0.0,
        max_buy_tax_pct=0.0,
        max_sell_tax_pct=0.0,
        max_sniper_count=0,
        min_bluechip_owner_pct=0.0,
        exclude_honeypot=True,
        require_renounced=False,
        max_top_10_holder_pct=40.0,
        max_token_age_minutes=1440,
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
        smart_buy_24h=5,
        smart_sell_24h=1,
        is_honeypot=False,
    )
    defaults.update(overrides)
    return TokenStats(**defaults)


def test_passes_when_all_thresholds_met():
    screener = make_screener()
    signal = screener.evaluate(make_stats(), now=NOW)
    assert signal is not None
    assert signal.smart_buy_24h == 5
    assert signal.smart_sell_24h == 1
    assert signal.net_smart_buys == 4
    assert signal.address == "tokenA"
    assert signal.score > 0


def test_fails_below_min_smart_buy_24h():
    screener = make_screener(min_smart_buy_24h=10)
    assert screener.evaluate(make_stats(), now=NOW) is None


def test_fails_below_min_net_smart_buys():
    screener = make_screener(min_net_smart_buys=10)
    assert screener.evaluate(make_stats(smart_buy_24h=5, smart_sell_24h=4), now=NOW) is None


def test_sells_reduce_net_flow():
    screener = make_screener(min_net_smart_buys=1)
    signal = screener.evaluate(make_stats(smart_buy_24h=10, smart_sell_24h=9), now=NOW)
    assert signal is not None
    assert signal.net_smart_buys == 1


def test_excludes_honeypot():
    screener = make_screener()
    assert screener.evaluate(make_stats(is_honeypot=True), now=NOW) is None


def test_excludes_low_liquidity():
    screener = make_screener()
    assert screener.evaluate(make_stats(liquidity_usd=1000.0), now=NOW) is None


def test_excludes_low_holder_count():
    screener = make_screener()
    assert screener.evaluate(make_stats(holder_count=5), now=NOW) is None


def test_requires_renounced_when_configured():
    screener = make_screener(require_renounced=True)
    assert screener.evaluate(make_stats(is_renounced=False), now=NOW) is None
    assert screener.evaluate(make_stats(is_renounced=True), now=NOW) is not None


def test_max_buy_tax_filter():
    screener = make_screener(max_buy_tax_pct=5.0)
    assert screener.evaluate(make_stats(buy_tax_pct=10.0), now=NOW) is None
    assert screener.evaluate(make_stats(buy_tax_pct=3.0), now=NOW) is not None


def test_max_sniper_count_filter():
    screener = make_screener(max_sniper_count=5)
    assert screener.evaluate(make_stats(sniper_count=20), now=NOW) is None
    assert screener.evaluate(make_stats(sniper_count=2), now=NOW) is not None


def test_min_bluechip_owner_pct_filter():
    screener = make_screener(min_bluechip_owner_pct=50.0)
    assert screener.evaluate(make_stats(bluechip_owner_pct=10.0), now=NOW) is None
    assert screener.evaluate(make_stats(bluechip_owner_pct=60.0), now=NOW) is not None


def test_optional_fields_left_none_never_block_a_signal():
    # sniper_count/bluechip_owner_pct/buy_tax_pct default to None on TokenStats;
    # filters configured but the field absent should never trigger a rejection.
    screener = make_screener(max_sniper_count=5, min_bluechip_owner_pct=50.0, max_buy_tax_pct=5.0)
    assert screener.evaluate(make_stats(), now=NOW) is not None


def test_excludes_stale_pairs_when_open_timestamp_present():
    screener = make_screener(max_token_age_minutes=10)
    stats = make_stats(open_timestamp=int(NOW) - 3600)  # 60 minutes old
    assert screener.evaluate(stats, now=NOW) is None


def test_score_rewards_more_net_buys():
    screener = make_screener()
    stats = make_stats()
    small = screener.evaluate(stats, now=NOW)
    bigger = screener.evaluate(make_stats(smart_buy_24h=20, smart_sell_24h=1), now=NOW)
    assert small is not None and bigger is not None
    assert bigger.score > small.score


def test_score_penalizes_sniper_count():
    screener = make_screener()
    low_snipe = screener.evaluate(make_stats(sniper_count=1), now=NOW)
    high_snipe = screener.evaluate(make_stats(sniper_count=40), now=NOW)
    assert low_snipe is not None and high_snipe is not None
    assert low_snipe.score > high_snipe.score
