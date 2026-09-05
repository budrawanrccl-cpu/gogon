"""Heartbeat file the bot writes once per cycle so an external dashboard can
tell whether it's actually running (vs. crashed/stopped) without needing any
IPC beyond the filesystem.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

DEFAULT_PATH = "data/pumpfun_status.json"


def write_status(snapshot: dict, path: str = DEFAULT_PATH) -> None:
    payload = {**snapshot, "updated_at": datetime.now(timezone.utc).isoformat()}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp_path, path)


def read_status(path: str = DEFAULT_PATH) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
