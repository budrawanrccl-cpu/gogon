import os

from pumpfun_bot.status import read_status, write_status


def test_read_status_none_when_missing(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    assert read_status(path) is None


def test_write_then_read_round_trips_and_stamps_updated_at(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    write_status({"mode": "paper", "open_positions": 2}, path)
    status = read_status(path)
    assert status is not None
    assert status["mode"] == "paper"
    assert status["open_positions"] == 2
    assert "updated_at" in status


def test_read_status_recovers_from_corrupt_file(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert read_status(path) is None
