from gmgn.client import parse_activity, parse_token_stats, parse_wallet


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


def test_parse_token_stats_standard_fields():
    raw = {
        "address": "tokenA",
        "symbol": "FOO",
        "name": "Foo Coin",
        "price": 0.01,
        "market_cap": 500000,
        "liquidity": 20000,
        "holder_count": 300,
        "top_10_holder_rate": 25.5,
        "open_timestamp": 1700000000,
        "is_honeypot": False,
        "renounced": True,
    }
    stats = parse_token_stats(raw, "sol")
    assert stats is not None
    assert stats.address == "tokenA"
    assert stats.symbol == "FOO"
    assert stats.liquidity_usd == 20000
    assert stats.top_10_holder_pct == 25.5
    assert stats.is_honeypot is False
    assert stats.is_renounced is True


def test_parse_token_stats_alternate_address_field():
    raw = {"base_address": "tokenB", "usd_market_cap": 1000, "holders": 5}
    stats = parse_token_stats(raw, "sol")
    assert stats is not None
    assert stats.address == "tokenB"
    assert stats.market_cap_usd == 1000
    assert stats.holder_count == 5


def test_parse_token_stats_missing_address_returns_none():
    assert parse_token_stats({"symbol": "FOO"}, "sol") is None


def test_parse_activity_buy_event():
    raw = {
        "wallet_address": "walletA",
        "event_type": "BUY",
        "tags": ["smart_degen"],
        "amount_usd": 1234.5,
        "price": 0.02,
        "timestamp": 1700000000,
    }
    activity = parse_activity(raw, "sol", "tokenA")
    assert activity is not None
    assert activity.side == "buy"
    assert activity.wallet_address == "walletA"
    assert activity.amount_usd == 1234.5
    assert activity.token_address == "tokenA"


def test_parse_activity_invalid_side_returns_none():
    raw = {"wallet_address": "walletA", "event_type": "transfer"}
    assert parse_activity(raw, "sol", "tokenA") is None


def test_parse_activity_missing_wallet_returns_none():
    assert parse_activity({"event_type": "buy"}, "sol", "tokenA") is None
