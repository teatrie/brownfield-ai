"""Tests for brownfield_ai.ledger.todo.queries — get_todo, list_todos, fetch_categories."""

from __future__ import annotations

from brownfield_ai.ledger.todo.queries import fetch_categories, get_todo, list_todos
from tests.src.brownfield_ai.ledger.todo.helpers import insert_todo

# ---------------------------------------------------------------------------
# get_todo
# ---------------------------------------------------------------------------


def test_get_todo_returns_dict_for_existing_id(make_db) -> None:
    """Existing TODO returns a full row dict."""
    db = make_db
    inserted_id = insert_todo(db, title="Find Me")

    result = get_todo(db, inserted_id)

    assert result is not None
    assert result["title"] == "Find Me"
    assert result["id"] == inserted_id


def test_get_todo_returns_none_for_missing_id(make_db) -> None:
    """Missing TODO returns None."""
    result = get_todo(make_db, 99999)
    assert result is None


# ---------------------------------------------------------------------------
# list_todos
# ---------------------------------------------------------------------------


def test_list_todos_returns_only_open_by_default(make_db) -> None:
    """Single-status filter returns only matching rows."""
    db = make_db
    insert_todo(db, title="Open TODO", status="open")
    insert_todo(db, title="Done TODO", status="done")

    results = list_todos(db, statuses=["open"])

    titles = [r["title"] for r in results]
    assert "Open TODO" in titles
    assert "Done TODO" not in titles


def test_list_todos_multi_status_returns_open_and_assigned(make_db) -> None:
    """Multi-status filter returns union of matching rows."""
    db = make_db
    insert_todo(db, title="Open TODO", status="open")
    insert_todo(db, title="Assigned TODO", status="assigned")
    insert_todo(db, title="Done TODO", status="done")

    results = list_todos(db, statuses=["open", "assigned"])

    titles = [r["title"] for r in results]
    assert "Open TODO" in titles
    assert "Assigned TODO" in titles
    assert "Done TODO" not in titles


def test_list_todos_empty_statuses_returns_all(make_db) -> None:
    """Empty statuses list returns all rows regardless of status."""
    db = make_db
    insert_todo(db, title="Open TODO", status="open")
    insert_todo(db, title="Done TODO", status="done")

    results = list_todos(db, statuses=[])

    assert len(results) == 2


def test_list_todos_pagination_limit_and_offset(make_db) -> None:
    """Limit and offset correctly paginate results."""
    db = make_db
    for i in range(5):
        insert_todo(db, title=f"TODO {i}", status="open")

    page1 = list_todos(db, statuses=["open"], limit=2, offset=0)
    page2 = list_todos(db, statuses=["open"], limit=2, offset=2)

    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["title"] != page2[0]["title"]


def test_list_todos_category_filter(make_db) -> None:
    """Category filter returns only matching rows."""
    db = make_db
    insert_todo(db, title="Infra TODO", status="open", category="infra")
    insert_todo(db, title="Agents TODO", status="open", category="agents")

    results = list_todos(db, statuses=["open"], category="infra")

    assert len(results) == 1
    assert results[0]["title"] == "Infra TODO"


def test_list_todos_epic_id_filter(make_db) -> None:
    """Epic ID filter returns only matching rows."""
    db = make_db
    insert_todo(db, title="Epic TODO", status="assigned", epic_id="ACME-1234")
    insert_todo(db, title="No Epic TODO", status="open")

    results = list_todos(db, statuses=[], epic_id="ACME-1234")

    assert len(results) == 1
    assert results[0]["title"] == "Epic TODO"


def test_list_todos_ordered_by_priority_ascending(make_db) -> None:
    """Results are sorted by priority ascending."""
    db = make_db
    insert_todo(db, title="Low Priority", status="open", priority=8)
    insert_todo(db, title="High Priority", status="open", priority=1)
    insert_todo(db, title="Medium Priority", status="open", priority=4)

    results = list_todos(db, statuses=["open"])

    priorities = [r["priority"] for r in results]
    assert priorities == sorted(priorities)


# ---------------------------------------------------------------------------
# fetch_categories
# ---------------------------------------------------------------------------


def test_fetch_categories_returns_seeded_defaults(make_db) -> None:
    """Seeded categories are present in a fresh database."""
    categories = fetch_categories(make_db)

    names = [c["name"] for c in categories]
    assert "infra" in names
    assert "agents" in names
    assert "testing" in names


def test_fetch_categories_returns_list_of_dicts_with_required_keys(make_db) -> None:
    """Each category has name, description, and created_at keys."""
    categories = fetch_categories(make_db)

    assert len(categories) > 0
    for cat in categories:
        assert "name" in cat
        assert "description" in cat
        assert "created_at" in cat
