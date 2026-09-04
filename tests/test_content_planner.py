import pytest

from content_planner.storage import STAGES, ContentPlanner


@pytest.fixture
def planner(tmp_path):
    return ContentPlanner(path=str(tmp_path / "ideas.json"))


def test_new_planner_starts_empty(planner):
    assert planner.list_ideas() == []


def test_add_idea_sets_defaults(planner):
    idea = planner.add_idea(title="Cara Edit Video Cepat", topic="Tutorial")

    assert idea["id"] == 1
    assert idea["title"] == "Cara Edit Video Cepat"
    assert idea["topic"] == "Tutorial"
    assert idea["status"] == "idea"
    assert idea["created_at"] == idea["updated_at"]


def test_add_idea_requires_title(planner):
    with pytest.raises(ValueError):
        planner.add_idea(title="   ")


def test_ids_increment_and_persist(planner):
    planner.add_idea(title="Video 1")
    planner.add_idea(title="Video 2")

    reloaded = ContentPlanner(path=planner.path)
    ideas = reloaded.list_ideas()
    assert [i["id"] for i in ideas] == [1, 2]


def test_update_idea_changes_fields(planner):
    idea = planner.add_idea(title="Judul Lama")
    updated = planner.update_idea(idea["id"], title="Judul Baru", notes="catatan")

    assert updated["title"] == "Judul Baru"
    assert updated["notes"] == "catatan"
    assert updated["updated_at"] >= idea["updated_at"]


def test_update_idea_rejects_bad_status(planner):
    idea = planner.add_idea(title="Video")
    with pytest.raises(ValueError):
        planner.update_idea(idea["id"], status="not-a-stage")


def test_update_missing_idea_raises(planner):
    with pytest.raises(KeyError):
        planner.update_idea(999, title="x")


def test_advance_idea_moves_through_all_stages(planner):
    idea = planner.add_idea(title="Video")
    for expected in STAGES[1:]:
        idea = planner.advance_idea(idea["id"])
        assert idea["status"] == expected

    # Already at the last stage — advancing again is a no-op.
    final = planner.advance_idea(idea["id"])
    assert final["status"] == STAGES[-1]


def test_delete_idea_removes_it(planner):
    idea = planner.add_idea(title="Video")
    planner.delete_idea(idea["id"])

    assert planner.list_ideas() == []


def test_delete_missing_idea_raises(planner):
    with pytest.raises(KeyError):
        planner.delete_idea(999)
