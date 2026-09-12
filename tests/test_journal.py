import csv
import os

from bot.journal import FIELDS, TradeJournal, load_fills


def write_rows(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def base_row(**overrides):
    row = dict(
        timestamp="2026-01-01T00:00:00+00:00",
        mode="paper",
        strategy="threshold",
        market_id="mkt1",
        token_id="tokA",
        outcome="YES",
        side="BUY",
        price="0.5000",
        size_shares="10.0000",
        size_usd="5.0000",
        filled="True",
        group_id="",
        reason="",
    )
    row.update(overrides)
    return row


def test_load_fills_returns_empty_list_when_journal_missing(tmp_path):
    assert load_fills(str(tmp_path / "does_not_exist.csv")) == []


def test_load_fills_filters_out_unfilled_rows(tmp_path):
    path = str(tmp_path / "trades.csv")
    write_rows(path, [base_row(filled="True"), base_row(filled="False")])
    fills = load_fills(path)
    assert len(fills) == 1
    assert fills[0]["filled"] == "True"


def test_load_fills_sorts_chronologically(tmp_path):
    path = str(tmp_path / "trades.csv")
    write_rows(
        path,
        [
            base_row(timestamp="2026-01-01T00:02:00+00:00", token_id="second"),
            base_row(timestamp="2026-01-01T00:01:00+00:00", token_id="first"),
        ],
    )
    fills = load_fills(path)
    assert [f["token_id"] for f in fills] == ["first", "second"]


def test_journal_created_file_has_no_fills_yet(tmp_path):
    path = str(tmp_path / "trades.csv")
    TradeJournal(path=path)  # creates the file with just a header
    assert load_fills(path) == []
