"""Tests for brownfield_ai.ledger.todo.mutations — add, update, done, assign, duplicates, categories."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from brownfield_ai.ledger.todo.mutations import (
    add_todo,
    assign_todo,
    detect_duplicates,
    done_todo,
    insert_category,
    update_todo,
)
from brownfield_ai.ledger.todo.queries import fetch_categories, get_todo
from tests.src.brownfield_ai.ledger.todo.helpers import insert_todo

# ---------------------------------------------------------------------------
# add_todo
# ---------------------------------------------------------------------------


def test_add_todo_returns_autoincremented_id(make_db, make_collection) -> None:
    """add_todo returns an integer ID >= 1."""
    ctx: dict[str, Any] = {
        "schema_version": 1,
        "git_branch": None,
        "active_epic_id": None,
        "modified_files": [],
        "recent_commits": [],
        "notes": "",
    }

    todo_id = add_todo(
        make_db,
        make_collection,
        "Fix the thing",
        ctx,
        description="Some desc",
        category="tooling",
        priority=3,
        source_workspace="/ws",
    )

    assert isinstance(todo_id, int)
    assert todo_id >= 1


def test_add_todo_persists_row_in_sqlite(make_db, make_collection) -> None:
    """Row is retrievable from SQLite after add_todo."""
    db = make_db
    ctx: dict[str, Any] = {
        "schema_version": 1,
        "git_branch": None,
        "active_epic_id": None,
        "modified_files": [],
        "recent_commits": [],
        "notes": "",
    }

    todo_id = add_todo(db, make_collection, "Persist test", ctx)

    row = get_todo(db, todo_id)
    assert row is not None
    assert row["title"] == "Persist test"
    assert row["status"] == "open"


def test_add_todo_calls_chromadb_upsert(make_db, make_collection) -> None:
    """ChromaDB upsert is called with correct IDs and metadata."""
    ctx: dict[str, Any] = {
        "schema_version": 1,
        "git_branch": None,
        "active_epic_id": None,
        "modified_files": [],
        "recent_commits": [],
        "notes": "",
    }

    todo_id = add_todo(
        make_db,
        make_collection,
        "ChromaDB test",
        ctx,
        description="desc",
        category="agents",
        priority=2,
        source_workspace="/ws",
    )

    make_collection.upsert.assert_called_once()
    call_kwargs = make_collection.upsert.call_args
    assert call_kwargs.kwargs["ids"] == [str(todo_id)]
    assert call_kwargs.kwargs["metadatas"][0]["status"] == "open"
    assert call_kwargs.kwargs["metadatas"][0]["priority"] == 2


# ---------------------------------------------------------------------------
# detect_duplicates
# ---------------------------------------------------------------------------


def test_detect_duplicates_returns_matches_from_collection(make_collection) -> None:
    """Query results are returned as a list of match dicts."""
    make_collection.query.return_value = {
        "ids": [["1", "2"]],
        "documents": [["Fix login bug", "Token refresh fails"]],
        "metadatas": [[{"todo_id": 1, "status": "open"}, {"todo_id": 2, "status": "open"}]],
        "distances": [[0.12, 0.34]],
    }

    results = detect_duplicates(make_collection, "Fix auth token")

    assert len(results) == 2
    assert results[0]["id"] == "1"
    assert results[0]["distance"] == 0.12
    assert results[1]["id"] == "2"


def test_detect_duplicates_returns_empty_list_when_collection_raises(make_collection) -> None:
    """ChromaDB errors return an empty list rather than propagating."""
    make_collection.query.side_effect = RuntimeError("ChromaDB unavailable")

    results = detect_duplicates(make_collection, "some text")

    assert results == []


def test_detect_duplicates_respects_threshold(make_collection) -> None:
    """Threshold parameter is forwarded to ChromaDB query."""
    make_collection.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    detect_duplicates(make_collection, "query text", threshold=5)

    make_collection.query.assert_called_once_with(query_texts=["query text"], n_results=5)


# ---------------------------------------------------------------------------
# update_todo
# ---------------------------------------------------------------------------


def test_update_todo_updates_title_in_sqlite_and_chromadb(make_db, make_collection) -> None:
    """Title update persists in SQLite and triggers ChromaDB upsert."""
    db = make_db
    todo_id = insert_todo(db, title="Old Title")

    update_todo(db, make_collection, todo_id, title="New Title")

    updated = get_todo(db, todo_id)
    assert updated["title"] == "New Title"
    make_collection.upsert.assert_called_once()


def test_update_todo_rejects_epic_id_field(make_db, make_collection) -> None:
    """epic_id is rejected — use assign_todo() instead."""
    db = make_db
    todo_id = insert_todo(db)

    with pytest.raises(ValueError, match="epic_id"):
        update_todo(db, make_collection, todo_id, epic_id="ACME-9999")


def test_update_todo_rejects_status_field(make_db, make_collection) -> None:
    """status is rejected — use done_todo() instead."""
    db = make_db
    todo_id = insert_todo(db)

    with pytest.raises(ValueError, match="status"):
        update_todo(db, make_collection, todo_id, status="done")


def test_update_todo_raises_when_todo_not_found(make_db, make_collection) -> None:
    """Non-existent TODO ID raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        update_todo(make_db, make_collection, 99999, title="Ghost")


def test_update_todo_raises_when_no_valid_fields_provided(make_db, make_collection) -> None:
    """No valid fields raises ValueError."""
    db = make_db
    todo_id = insert_todo(db)

    with pytest.raises(ValueError, match="No valid fields"):
        update_todo(db, make_collection, todo_id, unknown_field="value")


# ---------------------------------------------------------------------------
# done_todo
# ---------------------------------------------------------------------------


def test_done_todo_sets_status_to_done_and_stores_resolution(make_db, make_collection) -> None:
    """done_todo transitions status and stores the resolution."""
    db = make_db
    todo_id = insert_todo(db, status="open")

    done_todo(db, make_collection, todo_id, resolution="Fixed in PR #42")

    result = get_todo(db, todo_id)
    assert result["status"] == "done"
    assert result["resolution"] == "Fixed in PR #42"


def test_done_todo_updates_chromadb_metadata_to_done(make_db, make_collection) -> None:
    """ChromaDB metadata is updated to status=done."""
    db = make_db
    todo_id = insert_todo(db, status="open")

    done_todo(db, make_collection, todo_id, resolution="Resolved")

    make_collection.upsert.assert_called_once()
    metadata = make_collection.upsert.call_args.kwargs["metadatas"][0]
    assert metadata["status"] == "done"


def test_done_todo_raises_if_already_done(make_db, make_collection) -> None:
    """Already-done TODO raises ValueError."""
    db = make_db
    todo_id = insert_todo(db, status="done")

    with pytest.raises(ValueError, match="already done"):
        done_todo(db, make_collection, todo_id, resolution="Redundant")


def test_done_todo_raises_if_todo_not_found(make_db, make_collection) -> None:
    """Non-existent TODO ID raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        done_todo(make_db, make_collection, 99999, resolution="Ghost resolution")


# ---------------------------------------------------------------------------
# assign_todo
# ---------------------------------------------------------------------------


def test_assign_todo_sets_status_to_assigned_and_epic_id(make_db, make_collection) -> None:
    """assign_todo transitions status to assigned and sets epic_id."""
    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    todo_id = insert_todo(db, title="Assign Me", status="open")

    with patch("brownfield_ai.ledger.todo.mutations.save_artifact"):
        assign_todo(db, todos_col, ledger_col, todo_id, "ACME-5000")

    result = get_todo(db, todo_id)
    assert result["status"] == "assigned"
    assert result["epic_id"] == "ACME-5000"


def test_assign_todo_auto_creates_backlog_epic(make_db, make_collection) -> None:
    """Target epic is auto-created in backlog if it doesn't exist."""
    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    todo_id = insert_todo(db, title="New Epic Test", status="open")

    with patch("brownfield_ai.ledger.todo.mutations.save_artifact"):
        assign_todo(db, todos_col, ledger_col, todo_id, "ACME-NEWEPIC")

    epic = db.execute("SELECT epic_id, status FROM epics WHERE epic_id = ?", ("ACME-NEWEPIC",)).fetchone()
    assert epic is not None
    assert epic["status"] == "backlog"


def test_assign_todo_does_not_duplicate_existing_epic(make_db, make_collection) -> None:
    """Pre-existing epic is not overwritten to backlog."""
    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()

    db.execute(
        "INSERT INTO epics (epic_id, status, priority, depends_on, title, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("ACME-EXISTING", "in_progress", 3, "[]", "Pre-existing", "2026-01-01", "2026-01-01"),
    )
    db.commit()

    todo_id = insert_todo(db, title="Pre-existing Epic Test", status="open")

    with patch("brownfield_ai.ledger.todo.mutations.save_artifact"):
        assign_todo(db, todos_col, ledger_col, todo_id, "ACME-EXISTING")

    epic = db.execute("SELECT status FROM epics WHERE epic_id = ?", ("ACME-EXISTING",)).fetchone()
    assert epic["status"] == "in_progress"


def test_assign_todo_checkpoints_todo_linked_artifact(make_db, make_collection) -> None:
    """save_artifact is called with artifact_type=todo_linked."""
    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    todo_id = insert_todo(db, title="Checkpoint Test", status="open")

    with patch("brownfield_ai.ledger.todo.mutations.save_artifact") as mock_save:
        assign_todo(db, todos_col, ledger_col, todo_id, "ACME-7000")

    mock_save.assert_called_once()
    save_call = mock_save.call_args
    assert save_call.kwargs["params"]["artifact_type"] == "todo_linked"
    assert save_call.kwargs["params"]["epic_id"] == "ACME-7000"


def test_assign_todo_raises_if_todo_not_found(make_db, make_collection) -> None:
    """Non-existent TODO ID raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        assign_todo(make_db, make_collection, make_collection, 99999, "ACME-0001")


# ---------------------------------------------------------------------------
# insert_category / fetch_categories
# ---------------------------------------------------------------------------


def test_insert_category_stores_row_retrievable_by_fetch(make_db) -> None:
    """Inserted category is retrievable via fetch_categories."""
    db = make_db
    insert_category(db, "my-custom-cat", "A custom category")
    categories = fetch_categories(db)

    names = [c["name"] for c in categories]
    assert "my-custom-cat" in names


def test_insert_category_rejects_name_with_spaces(make_db) -> None:
    """Spaces in category name raise ValueError."""
    with pytest.raises(ValueError, match="must match"):
        insert_category(make_db, "bad name", "Has a space")


def test_insert_category_rejects_uppercase_name(make_db) -> None:
    """Uppercase letters in category name raise ValueError."""
    with pytest.raises(ValueError, match="must match"):
        insert_category(make_db, "BadName", "Has uppercase")


def test_insert_category_rejects_special_characters(make_db) -> None:
    """Special characters in category name raise ValueError."""
    with pytest.raises(ValueError, match="must match"):
        insert_category(make_db, "bad@name!", "Has special chars")
