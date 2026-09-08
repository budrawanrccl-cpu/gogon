import json

from pumpbot.config import DataConfig
from pumpbot.market_data import PumpPortalFeed, RawEvent, TokenTracker


def make_feed() -> PumpPortalFeed:
    cfg = DataConfig(ws_url="wss://example.invalid/data", trade_api_url="https://example.invalid/trade", api_key=None)
    return PumpPortalFeed(cfg)


class FakeWs:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def test_sync_subscribes_new_mints_when_connected():
    feed = make_feed()
    feed._ws = FakeWs()
    feed.sync_trade_subscriptions(["A", "B"])

    sub_calls = [m for m in feed._ws.sent if m["method"] == "subscribeTokenTrade"]
    assert len(sub_calls) == 1
    assert set(sub_calls[0]["keys"]) == {"A", "B"}
    assert feed._known_tokens == {"A", "B"}


def test_sync_unsubscribes_mints_dropped_from_desired_set():
    feed = make_feed()
    feed._ws = FakeWs()
    feed.sync_trade_subscriptions(["A", "B"])
    feed._ws.sent.clear()

    feed.sync_trade_subscriptions(["B"])  # "A" no longer desired

    unsub_calls = [m for m in feed._ws.sent if m["method"] == "unsubscribeTokenTrade"]
    assert len(unsub_calls) == 1
    assert unsub_calls[0]["keys"] == ["A"]
    assert feed._known_tokens == {"B"}


def test_sync_is_noop_when_desired_set_unchanged():
    feed = make_feed()
    feed._ws = FakeWs()
    feed.sync_trade_subscriptions(["A", "B"])
    feed._ws.sent.clear()

    feed.sync_trade_subscriptions(["A", "B"])

    assert feed._ws.sent == []


def test_sync_updates_known_tokens_even_without_connected_socket():
    feed = make_feed()
    feed.sync_trade_subscriptions(["A", "B"])  # feed._ws is None — nothing to send yet
    assert feed._known_tokens == {"A", "B"}


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
