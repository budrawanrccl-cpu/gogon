from pumpbot.market_data import RawEvent, TokenTracker


def test_snapshot_reflects_create_and_buy_events():
    tracker = TokenTracker()
    mint = "MintAAAA1111111111111111111111111111111"

    tracker.apply(RawEvent(kind="create", payload={
        "txType": "create", "mint": mint, "name": "Test Coin", "symbol": "TEST",
        "traderPublicKey": "CreatorXXX",
    }))
    tracker.apply(RawEvent(kind="trade", payload={
        "txType": "buy", "mint": mint, "traderPublicKey": "BuyerYYY", "solAmount": 1.5,
        "vTokensInBondingCurve": 1_000_000, "vSolInBondingCurve": 50, "marketCapSol": 12.3,
    }))

    snap = tracker.snapshot()
    assert len(snap) == 1
    row = snap[0]
    assert row["mint"] == mint
    assert row["symbol"] == "TEST"
    assert row["name"] == "Test Coin"
    assert row["unique_buyers"] == 1
    assert abs(row["buy_volume_sol"] - 1.5) < 1e-9
    assert row["sell_volume_sol"] == 0.0
    assert row["market_cap_sol"] == 12.3
    assert abs(row["last_price_sol_per_token"] - 0.00005) < 1e-12
    assert row["decided"] is False
    assert "first_seen" in row and "age_seconds" in row


def test_snapshot_is_json_serializable():
    import json

    tracker = TokenTracker()
    tracker.apply(RawEvent(kind="create", payload={"txType": "create", "mint": "M1", "symbol": "A"}))
    json.dumps(tracker.snapshot())  # must not raise


def test_snapshot_sorted_newest_first():
    tracker = TokenTracker()
    tracker.apply(RawEvent(kind="create", payload={"txType": "create", "mint": "OLD", "symbol": "OLD"}))
    tracker.tokens["OLD"].first_seen -= 100  # simulate it being seen earlier
    tracker.apply(RawEvent(kind="create", payload={"txType": "create", "mint": "NEW", "symbol": "NEW"}))

    snap = tracker.snapshot()
    assert [r["mint"] for r in snap] == ["NEW", "OLD"]


def test_snapshot_empty_tracker_returns_empty_list():
    assert TokenTracker().snapshot() == []
