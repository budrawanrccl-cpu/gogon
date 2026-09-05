import os

from pumpfun_bot.control import read_control, write_control


def test_read_control_defaults_when_missing(tmp_path):
    path = os.path.join(tmp_path, "control.json")
    assert read_control(path) == {"paused": False}


def test_write_then_read_round_trips(tmp_path):
    path = os.path.join(tmp_path, "control.json")
    result = write_control({"paused": True}, path)
    assert result == {"paused": True}
    assert read_control(path) == {"paused": True}


def test_write_control_merges_with_existing(tmp_path):
    path = os.path.join(tmp_path, "control.json")
    write_control({"paused": True}, path)
    write_control({"note": "test"}, path)
    state = read_control(path)
    assert state["paused"] is True
    assert state["note"] == "test"


def test_read_control_recovers_from_corrupt_file(tmp_path):
    path = os.path.join(tmp_path, "control.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert read_control(path) == {"paused": False}
