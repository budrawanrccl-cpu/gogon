"""Tiny file-based control channel between the dashboard (a separate
process) and the running bot.

The bot re-reads this file once per polling cycle; the dashboard writes to
it when someone clicks Pause/Resume. Written atomically (temp file + os
.replace) so a concurrent read never sees a half-written file — no locking
needed for something this small.
"""
from __future__ import annotations

import json
import os

DEFAULT_PATH = "data/pumpfun_control.json"

_DEFAULTS = {"paused": False}


def read_control(path: str = DEFAULT_PATH) -> dict:
    if not os.path.exists(path):
        return dict(_DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**_DEFAULTS, **data}
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULTS)


def write_control(updates: dict, path: str = DEFAULT_PATH) -> dict:
    current = read_control(path)
    current.update(updates)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(current, f)
    os.replace(tmp_path, path)
    return current
