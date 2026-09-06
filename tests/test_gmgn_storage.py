import csv
import os

from gmgn.models import TokenStats, TokenSignal
from gmgn.storage import SeenCache, SignalJournal

NOW = 1_700_000_000.0


def make_signal() -> TokenSignal:
    stats = TokenStats(
        chain="sol",
        address="tokenA",
        symbol="FOO",
        liquidity_usd=10000.0,
        market_cap_usd=100000.0,
        holder_count=200,
        top_10_holder_pct=20.0,
    )
    return TokenSignal(
        chain="sol",
        address="tokenA",
        symbol="FOO",
        score=12.5,
        smart_wallet_count=3,
        net_smart_buy_usd=3000.0,
        buy_wallets=["w1", "w2", "w3"],
        reasons=["3 wallets bought"],
        stats=stats,
    )


def test_seen_cache_allows_first_alert(tmp_path):
    cache = SeenCache(str(tmp_path / "seen.json"))
    assert cache.should_alert("tokenA", cooldown_minutes=60, now=NOW)


def test_seen_cache_blocks_within_cooldown(tmp_path):
    cache = SeenCache(str(tmp_path / "seen.json"))
    cache.mark("tokenA", now=NOW)
    assert not cache.should_alert("tokenA", cooldown_minutes=60, now=NOW + 60)


def test_seen_cache_allows_after_cooldown_expires(tmp_path):
    cache = SeenCache(str(tmp_path / "seen.json"))
    cache.mark("tokenA", now=NOW)
    assert cache.should_alert("tokenA", cooldown_minutes=60, now=NOW + 3601)


def test_seen_cache_persists_across_instances(tmp_path):
    path = str(tmp_path / "seen.json")
    cache1 = SeenCache(path)
    cache1.mark("tokenA", now=NOW)

    cache2 = SeenCache(path)
    assert not cache2.should_alert("tokenA", cooldown_minutes=60, now=NOW + 60)


def test_signal_journal_writes_header_and_row(tmp_path):
    path = str(tmp_path / "signals.csv")
    journal = SignalJournal(path)
    journal.record(make_signal())

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert rows[0][0] == "timestamp"
    assert rows[1][2] == "tokenA"
    assert rows[1][3] == "FOO"
    assert "w1" in rows[1][10]


def test_signal_journal_creates_parent_dir(tmp_path):
    path = str(tmp_path / "nested" / "signals.csv")
    SignalJournal(path)
    assert os.path.exists(path)
