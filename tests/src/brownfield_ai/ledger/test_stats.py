"""Unit tests for brownfield_ai.ledger.stats aggregation functions.

Tests epic stats, TODO stats, and activity stats with in-memory SQLite
databases and mock ChromaDB collections to validate SQL aggregation
logic, time-windowed counts, category COALESCE, and client-side
timestamp filtering.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from brownfield_ai.ledger.stats import get_activity_stats, get_epic_stats, get_todo_stats


@pytest.fixture
def stats_db() -> sqlite3.Connection:
    """Create an in-memory SQLite database seeded with epic and TODO data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.execute("""CREATE TABLE epics (
        epic_id TEXT PRIMARY KEY,
        status TEXT,
        priority INTEGER,
        depends_on TEXT,
        claimed_by TEXT,
        claimed_at TEXT,
        title TEXT,
        created_at TEXT,
        last_updated_at TEXT,
        current_prs TEXT
    )""")

    now = datetime.now()
    recent = (now - timedelta(hours=2)).isoformat()
    old = (now - timedelta(days=5)).isoformat()

    conn.executemany(
        "INSERT INTO epics (epic_id, status, priority, depends_on, claimed_by, claimed_at, title, created_at, last_updated_at, current_prs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("E-001", "in_progress", 3, "[]", "agent", now.isoformat(), "Active epic", recent, recent, None),
            ("E-002", "in_progress", 2, "[]", "agent", now.isoformat(), "Another active", recent, recent, None),
            ("E-003", "completed", 5, "[]", "", "", "Recently completed", old, recent, None),
            ("E-004", "completed", 5, "[]", "", "", "Old completed", old, old, None),
            ("E-005", "backlog", 7, "[]", "", "", "Backlog epic", old, old, None),
            ("E-006", "blocked", 3, "[]", "", "", "Blocked epic", recent, recent, None),
            ("E-007", "in_review", 4, "[]", "agent", now.isoformat(), "In review", recent, recent, None),
            ("E-008", "approved", 3, "[]", "", "", "Recently created", recent, recent, None),
        ],
    )

    conn.execute("""CREATE TABLE todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        status TEXT DEFAULT 'open',
        priority INTEGER DEFAULT 5,
        category TEXT,
        epic_id TEXT,
        source_workspace TEXT,
        context_snapshot TEXT DEFAULT '{}',
        resolution TEXT,
        secondary_categories TEXT DEFAULT '',
        created_at TEXT,
        last_updated_at TEXT
    )""")

    conn.executemany(
        "INSERT INTO todos (title, status, priority, category, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("Open infra", "open", 2, "infra", old, old),
            ("Open infra 2", "open", 1, "infra", old, old),
            ("Open code", "open", 5, "code", old, old),
            ("Open null cat", "open", 4, None, old, old),
            ("Assigned", "assigned", 3, "code", old, old),
            ("Done task", "done", 5, "infra", old, old),
            ("Done task 2", "done", 2, "code", old, old),
        ],
    )

    conn.commit()
    return conn


def test_get_epic_stats_status_counts(stats_db: sqlite3.Connection) -> None:
    result = get_epic_stats(stats_db)
    assert result["by_status"]["in_progress"] == 2
    assert result["by_status"]["completed"] == 2
    assert result["by_status"]["backlog"] == 1
    assert result["by_status"]["blocked"] == 1
    assert result["by_status"]["in_review"] == 1
    assert result["by_status"]["approved"] == 1


def test_get_epic_stats_active_count(stats_db: sqlite3.Connection) -> None:
    result = get_epic_stats(stats_db)
    # active = in_progress(2) + in_review(1) = 3
    assert result["active"] == 3


def test_get_epic_stats_blocked_count(stats_db: sqlite3.Connection) -> None:
    result = get_epic_stats(stats_db)
    assert result["blocked"] == 1


def test_get_epic_stats_total(stats_db: sqlite3.Connection) -> None:
    result = get_epic_stats(stats_db)
    assert result["total"] == 8


def test_get_epic_stats_completed_24h(stats_db: sqlite3.Connection) -> None:
    result = get_epic_stats(stats_db)
    # E-003 has status=completed and last_updated_at within 24h (set to 2h ago)
    # E-004 has status=completed but last_updated_at is 5 days ago
    assert result["completed_24h"] == 1


def test_get_epic_stats_created_24h(stats_db: sqlite3.Connection) -> None:
    result = get_epic_stats(stats_db)
    # E-001, E-002 have created_at=recent. E-003-E-005 have old.
    # E-006, E-007, E-008 have created_at=recent
    assert result["created_24h"] == 5


def test_get_todo_stats_status_counts(stats_db: sqlite3.Connection) -> None:
    result = get_todo_stats(stats_db)
    assert result["open"] == 4
    assert result["assigned"] == 1
    assert result["done"] == 2
    assert result["total"] == 7


def test_get_todo_stats_by_category(stats_db: sqlite3.Connection) -> None:
    result = get_todo_stats(stats_db)
    categories = {c["category"]: c["count"] for c in result["by_category"]}
    assert categories["infra"] == 2
    assert categories["code"] == 1
    assert categories["uncategorized"] == 1


def test_get_todo_stats_by_category_order(stats_db: sqlite3.Connection) -> None:
    result = get_todo_stats(stats_db)
    counts = [c["count"] for c in result["by_category"]]
    assert counts == sorted(counts, reverse=True)


def test_get_todo_stats_high_priority_open(stats_db: sqlite3.Connection) -> None:
    result = get_todo_stats(stats_db)
    # Open TODOs with priority <= 3: "Open infra" (p2), "Open infra 2" (p1)
    assert result["high_priority_open"] == 2


def test_get_activity_stats_artifact_counts() -> None:
    now = datetime.now()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["a1", "a2", "a3", "a4"],
        "metadatas": [
            {"timestamp": (now - timedelta(minutes=30)).isoformat(), "artifact_type": "step_result"},
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "artifact_type": "wave_summary"},
            {"timestamp": (now - timedelta(hours=25)).isoformat(), "artifact_type": "step_result"},
            {"timestamp": (now - timedelta(days=3)).isoformat(), "artifact_type": "plan_snapshot"},
        ],
    }

    result = get_activity_stats(mock_collection)
    assert result["artifacts_1h"] == 1
    assert result["artifacts_24h"] == 2
    mock_collection.get.assert_called_once_with(include=["metadatas"])


def test_get_activity_stats_gate_verdicts() -> None:
    now = datetime.now()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["g1", "g2", "g3"],
        "metadatas": [
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "artifact_type": "gate_verdict", "verdict": "GREEN"},
            {"timestamp": (now - timedelta(hours=3)).isoformat(), "artifact_type": "gate_verdict", "verdict": "FAIL"},
            {"timestamp": (now - timedelta(hours=25)).isoformat(), "artifact_type": "gate_verdict", "verdict": "GREEN"},
        ],
    }

    result = get_activity_stats(mock_collection)
    assert result["gates_24h"]["pass"] == 1
    assert result["gates_24h"]["fail"] == 1


def test_get_activity_stats_pr_counts() -> None:
    now = datetime.now()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["p1", "p2", "p3"],
        "metadatas": [
            {"timestamp": (now - timedelta(days=2)).isoformat(), "artifact_type": "pr_created"},
            {"timestamp": (now - timedelta(days=3)).isoformat(), "artifact_type": "pr_merged"},
            {"timestamp": (now - timedelta(days=10)).isoformat(), "artifact_type": "pr_created"},
        ],
    }

    result = get_activity_stats(mock_collection)
    assert result["prs_created_7d"] == 1
    assert result["prs_merged_7d"] == 1


def test_get_activity_stats_empty_collection() -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}

    result = get_activity_stats(mock_collection)
    assert result["artifacts_1h"] == 0
    assert result["artifacts_24h"] == 0
    assert result["gates_24h"] == {"pass": 0, "fail": 0}
    assert result["prs_created_7d"] == 0
    assert result["prs_merged_7d"] == 0


def test_get_activity_stats_skips_missing_timestamp() -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["x1"],
        "metadatas": [{"artifact_type": "step_result"}],
    }

    result = get_activity_stats(mock_collection)
    assert result["artifacts_1h"] == 0
    assert result["artifacts_24h"] == 0
