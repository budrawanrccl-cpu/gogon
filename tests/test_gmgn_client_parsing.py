from gmgn.client import parse_token_stats, parse_wallet


def test_parse_wallet_standard_fields():
    raw = {
        "address": "abc123",
        "tags": ["smart_degen"],
        "winrate": 0.62,
        "pnl_7d": 15000.5,
        "realized_profit_7d": 12000.0,
        "buy": 10,
        "sell": 4,
    }
    wallet = parse_wallet(raw, "sol")
    assert wallet is not None
    assert wallet.address == "abc123"
    assert wallet.chain == "sol"
    assert wallet.tags == ["smart_degen"]
    assert wallet.winrate == 0.62
    assert wallet.pnl_usd == 15000.5
    assert wallet.buy_count == 10
    assert wallet.sell_count == 4


def test_parse_wallet_handles_alternate_field_names_and_string_tag():
    raw = {"wallet_address": "abc123", "tags": "kol", "win_rate": 0.5}
    wallet = parse_wallet(raw, "sol")
    assert wallet is not None
    assert wallet.address == "abc123"
    assert wallet.tags == ["kol"]
    assert wallet.winrate == 0.5


def test_parse_wallet_missing_address_returns_none():
    assert parse_wallet({"tags": ["kol"]}, "sol") is None


def test_parse_token_stats_documented_rank_swaps_fields():
    """Fields as documented for gmgn.ai's /rank/{chain}/swaps/{period} endpoint."""
    raw = {
        "address": "tokenA",
        "symbol": "FOO",
        "price": 0.01,
        "price_change_percent": 12.5,
        "market_cap": 500000,
        "liquidity": 20000,
        "volume": 80000,
        "holder_count": 300,
        "buys": 120,
        "sells": 40,
        "smart_buy_24h": 5,
        "smart_sell_24h": 1,
        "sniper_count": 3,
        "bluechip_owner_percentage": 45.0,
        "buy_tax": 0.0,
        "sell_tax": 5.0,
        "is_honeypot": False,
        "renounced": True,
        "lockInfo": {"isLock": True, "lockPercent": 80.0},
    }
    stats = parse_token_stats(raw, "sol")
    assert stats is not None
    assert stats.address == "tokenA"
    assert stats.symbol == "FOO"
    assert stats.liquidity_usd == 20000
    assert stats.volume_usd == 80000
    assert stats.holder_count == 300
    assert stats.buys == 120
    assert stats.sells == 40
    assert stats.smart_buy_24h == 5
    assert stats.smart_sell_24h == 1
    assert stats.sniper_count == 3
    assert stats.bluechip_owner_pct == 45.0
    assert stats.buy_tax_pct == 0.0
    assert stats.sell_tax_pct == 5.0
    assert stats.is_honeypot is False
    assert stats.is_renounced is True
    assert stats.lock_pct == 80.0


def test_parse_token_stats_alternate_address_field():
    raw = {"base_address": "tokenB", "usd_market_cap": 1000, "holders": 5}
    stats = parse_token_stats(raw, "sol")
    assert stats is not None
    assert stats.address == "tokenB"
    assert stats.market_cap_usd == 1000
    assert stats.holder_count == 5


def test_parse_token_stats_missing_optional_fields_default_to_none():
    stats = parse_token_stats({"address": "tokenC"}, "sol")
    assert stats is not None
    assert stats.sniper_count is None
    assert stats.bluechip_owner_pct is None
    assert stats.buy_tax_pct is None
    assert stats.lock_pct is None
    assert stats.smart_buy_24h == 0
    assert stats.smart_sell_24h == 0


def test_parse_token_stats_missing_address_returns_none():
    assert parse_token_stats({"symbol": "FOO"}, "sol") is None
