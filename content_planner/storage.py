"""JSON-backed storage for YouTube video ideas.

Kept deliberately simple (a flat JSON file, no database) so the planner has
zero extra dependencies, matching the rest of this repo. Not safe for
concurrent multi-process writers, which is fine for a single-user local tool.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

# Stages a video idea moves through, in order.
STAGES = ["idea", "script", "record", "edit", "published"]

STAGE_LABELS = {
    "idea": "Ide",
    "script": "Riset & Skrip",
    "record": "Rekam",
    "edit": "Edit",
    "published": "Terbit",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContentPlanner:
    def __init__(self, path: str = "data/content_ideas.json"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            self._write([])

    def _read(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return []
        return json.loads(content)

    def _write(self, ideas: list[dict[str, Any]]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(ideas, f, indent=2, ensure_ascii=False)

    def list_ideas(self) -> list[dict[str, Any]]:
        return self._read()

    def add_idea(
        self,
        title: str,
        topic: str = "",
        notes: str = "",
        target_date: str = "",
    ) -> dict[str, Any]:
        if not title or not title.strip():
            raise ValueError("title tidak boleh kosong")

        ideas = self._read()
        next_id = (max((i["id"] for i in ideas), default=0)) + 1
        now = _now()
        idea = {
            "id": next_id,
            "title": title.strip(),
            "topic": topic.strip(),
            "notes": notes.strip(),
            "target_date": target_date.strip(),
            "status": "idea",
            "created_at": now,
            "updated_at": now,
        }
        ideas.append(idea)
        self._write(ideas)
        return idea

    def update_idea(self, idea_id: int, **fields: Any) -> dict[str, Any]:
        ideas = self._read()
        for idea in ideas:
            if idea["id"] == idea_id:
                if "status" in fields and fields["status"] not in STAGES:
                    raise ValueError(f"status tidak valid: {fields['status']}")
                for key in ("title", "topic", "notes", "target_date", "status"):
                    if key in fields and fields[key] is not None:
                        idea[key] = fields[key]
                idea["updated_at"] = _now()
                self._write(ideas)
                return idea
        raise KeyError(f"idea id {idea_id} tidak ditemukan")

    def delete_idea(self, idea_id: int) -> None:
        ideas = self._read()
        remaining = [i for i in ideas if i["id"] != idea_id]
        if len(remaining) == len(ideas):
            raise KeyError(f"idea id {idea_id} tidak ditemukan")
        self._write(remaining)

    def advance_idea(self, idea_id: int) -> dict[str, Any]:
        """Move an idea to the next stage in STAGES, if not already published."""
        ideas = self._read()
        for idea in ideas:
            if idea["id"] == idea_id:
                current = STAGES.index(idea["status"])
                if current < len(STAGES) - 1:
                    idea["status"] = STAGES[current + 1]
                    idea["updated_at"] = _now()
                    self._write(ideas)
                return idea
        raise KeyError(f"idea id {idea_id} tidak ditemukan")
