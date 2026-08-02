"""Tests for ``brownfield_ai.ledger.epics.queries``."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from brownfield_ai.ledger.epics.lifecycle import create_epic
from brownfield_ai.ledger.epics.queries import get_resume_context, list_epics
from tests.src.brownfield_ai.ledger.epics.helpers import insert_epic

# ---------------------------------------------------------------------------
# get_resume_context tests (migrated from Source A)
# ---------------------------------------------------------------------------


def test_get_resume_context_returns_dict_with_open_todos_key(make_db: sqlite3.Connection) -> None:
    """Resume context dict always contains 'open_todos' key."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    result = get_resume_context(mock_collection, make_db, "ACME-7001")
    assert "open_todos" in result


def test_get_resume_context_with_no_associated_todos_returns_empty_list(make_db: sqlite3.Connection) -> None:
    """When no TODOs are linked to the epic, open_todos is empty."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    result = get_resume_context(mock_collection, make_db, "ACME-7002")
    assert result["open_todos"] == []


def test_get_resume_context_surfaces_open_todos_for_epic(make_db: sqlite3.Connection) -> None:
    """Open TODOs linked to the epic appear in resume context."""
    now = "2026-01-01T00:00:00"
    make_db.execute(
        "INSERT INTO todos (title, priority, epic_id, status, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Open task for epic", 3, "ACME-7003", "open", now, now),
    )
    make_db.commit()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    result = get_resume_context(mock_collection, make_db, "ACME-7003")
    assert len(result["open_todos"]) == 1
    assert result["open_todos"][0]["title"] == "Open task for epic"


def test_get_resume_context_does_not_surface_done_todos(make_db: sqlite3.Connection) -> None:
    """Done TODOs linked to the epic do not appear in resume context."""
    now = "2026-01-01T00:00:00"
    make_db.execute(
        "INSERT INTO todos (title, priority, epic_id, status, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Done task for epic", 3, "ACME-7004", "done", now, now),
    )
    make_db.commit()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    result = get_resume_context(mock_collection, make_db, "ACME-7004")
    assert result["open_todos"] == []


@pytest.mark.parametrize(
    "artifact_type",
    [
        "cross_family_dissent",
        "cross_family_dissent_resolved",
        "bridge_unavailable",
        "pre_pr_dissent_block",
    ],
)
def test_get_resume_context_surfaces_dissent_lifecycle_artifacts(artifact_type: str, make_db: sqlite3.Connection) -> None:
    # RVW-002 dissent-lifecycle types must survive resume — codex-xhigh F1.
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": [f"ACME-7100|2026-05-05T01:02:03|{artifact_type}|claude-opus-4-7|1|step-x"],
        "documents": ["body"],
        "metadatas": [{"epic_id": "ACME-7100", "artifact_type": artifact_type, "artifact_status": "active"}],
    }
    result = get_resume_context(mock_collection, make_db, "ACME-7100")
    assert artifact_type in result, f"Resume context missing key {artifact_type!r}"
    assert len(result[artifact_type]) == 1, f"Resume context dropped {artifact_type!r} entry"


# ---------------------------------------------------------------------------
# list_epics tests (migrated from Source B)
# Uses make_db fixture (correct schema) instead of hand-rolled DB
# ---------------------------------------------------------------------------


def test_list_epics_returns_all_when_under_limit(make_db: sqlite3.Connection) -> None:
    """All epics returned when total count is under the limit."""
    insert_epic(make_db, "e1", status="pending", priority=1, title="t1")
    insert_epic(make_db, "e2", status="pending", priority=2, title="t2")
    insert_epic(make_db, "e3", status="pending", priority=3, title="t3")
    rows, has_more = list_epics(make_db)
    assert len(rows) == 3
    assert not has_more


def test_list_epics_pagination_limit(make_db: sqlite3.Connection) -> None:
    """Pagination correctly limits results and signals has_more."""
    for i in range(5):
        insert_epic(make_db, f"e{i}", status="pending", priority=i, title=f"t{i}")
    rows, has_more = list_epics(make_db, limit=2)
    assert len(rows) == 2
    assert has_more
    assert rows[0]["epic_id"] == "e0"
    assert rows[1]["epic_id"] == "e1"


def test_list_epics_pagination_offset(make_db: sqlite3.Connection) -> None:
    """Offset skips the correct number of rows in status-priority order."""
    statuses = ["in_progress", "approved", "pending", "completed", "abandoned"]
    for i, status in enumerate(statuses):
        insert_epic(make_db, f"e{i}", status=status, priority=5, title=f"t{i}")
    rows, has_more = list_epics(make_db, limit=2, offset=2)
    assert len(rows) == 2
    assert has_more
    assert rows[0]["status"] == "pending"
    assert rows[1]["status"] == "completed"


def test_list_epics_offset_beyond_total(make_db: sqlite3.Connection) -> None:
    """Offset beyond total rows returns empty list."""
    insert_epic(make_db, "e1", status="pending", priority=1, title="t1")
    rows, has_more = list_epics(make_db, offset=100)
    assert len(rows) == 0
    assert not has_more


def test_list_epics_status_filter(make_db: sqlite3.Connection) -> None:
    """Status filter returns only matching epics."""
    insert_epic(make_db, "e1", status="in_progress", priority=1, title="t1")
    insert_epic(make_db, "e2", status="pending", priority=1, title="t2")
    rows, has_more = list_epics(make_db, status_filter="in_progress")
    assert len(rows) == 1
    assert rows[0]["epic_id"] == "e1"


def test_list_epics_status_priority_order(make_db: sqlite3.Connection) -> None:
    """Epics are sorted by status lifecycle priority then numeric priority."""
    statuses = ["abandoned", "completed", "pending", "approved", "in_progress"]
    for s in statuses:
        insert_epic(make_db, s, status=s, priority=1, title="t")
    rows, _ = list_epics(make_db)
    assert len(rows) == 5
    assert rows[0]["status"] == "in_progress"
    assert rows[1]["status"] == "approved"
    assert rows[2]["status"] == "pending"
    assert rows[3]["status"] == "completed"
    assert rows[4]["status"] == "abandoned"


def test_list_epics_invalid_limit_raises(make_db: sqlite3.Connection) -> None:
    """limit=0 or negative raises ValueError."""
    with pytest.raises(ValueError, match="limit must be >= 1"):
        list_epics(make_db, limit=0)
    with pytest.raises(ValueError):
        list_epics(make_db, limit=-1)


def test_list_epics_invalid_offset_raises(make_db: sqlite3.Connection) -> None:
    """Negative offset raises ValueError."""
    with pytest.raises(ValueError, match="offset must be >= 0"):
        list_epics(make_db, offset=-1)


def test_list_epics_invalid_status_filter_raises(make_db: sqlite3.Connection) -> None:
    """Invalid status filter raises ValueError."""
    with pytest.raises(ValueError, match="status_filter must be one of"):
        list_epics(make_db, status_filter="garbage")


def test_list_epics_with_backlog_status_filter(make_db: sqlite3.Connection) -> None:
    """Backlog filter returns only backlog epics."""
    create_epic(make_db, "ACME-6001", "Backlog Epic One", status="backlog")
    create_epic(make_db, "ACME-6002", "Backlog Epic Two", status="backlog")
    create_epic(make_db, "ACME-6003", "Pending Epic", status="pending")
    epics, _ = list_epics(make_db, status_filter="backlog")
    assert len(epics) == 2
    assert all(e["status"] == "backlog" for e in epics)
