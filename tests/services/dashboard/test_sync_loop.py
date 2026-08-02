"""Tests for the background sync loop change detection logic.

Validates the ``_detect_changes`` function directly using mocked
SQLite and ChromaDB backends to ensure correct event emission
for epic timestamp changes and new artifact detection.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

from services.dashboard.sync import _detect_changes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_sqlite_rows(
    rows: list[dict[str, Any]],
) -> MagicMock:
    """Create a mock SQLite connection returning the given rows.

    Args:
        rows: List of dicts, each with ``epic_id``, ``last_updated_at``,
              and ``status`` keys.

    Returns:
        A MagicMock that behaves like ``sqlite3.connect()`` returning a
        connection with Row-style results.
    """
    mock_row_objects = []
    for row in rows:
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key, r=row: r[key]
        mock_row_objects.append(mock_row)

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_row_objects
    mock_connect = MagicMock(return_value=mock_conn)
    return mock_connect


def _make_mock_chromadb(
    epic_results: dict[str, dict[str, list[Any]]],
) -> MagicMock:
    """Create a mock ChromaDB client returning the given results per epic.

    Args:
        epic_results: Mapping of epic_id to a dict with ``ids``,
                      ``documents``, and ``metadatas`` lists.

    Returns:
        A MagicMock that behaves like ``chromadb.HttpClient()``.
    """
    mock_collection = MagicMock()

    def mock_get(where: dict[str, str] | None = None) -> dict[str, list[Any]]:
        """Return test results filtered by epic_id."""
        eid = where.get("epic_id", "") if where else ""
        return epic_results.get(eid, {"ids": [], "documents": [], "metadatas": []})

    mock_collection.get.side_effect = mock_get

    mock_epics_collection = MagicMock()

    mock_client = MagicMock()

    def _get_or_create(name: str) -> MagicMock:
        """Route collection creation to the correct mock."""
        if name == "epics":
            return mock_epics_collection
        return mock_collection

    mock_client.get_or_create_collection.side_effect = _get_or_create
    mock_http_client = MagicMock(return_value=mock_client)
    return mock_http_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_first_poll_seeds_without_events() -> None:
    epic_timestamps: dict[str, str] = {}
    epic_artifact_counts: dict[str, int] = {}
    epic_chromadb_timestamps: dict[str, str] = {}

    rows = [
        {"epic_id": "E-001", "last_updated_at": "2026-01-01T00:00:00", "status": "in_progress", "title": "Test Epic", "depends_on": "[]"},
    ]
    epic_results: dict[str, dict[str, list[Any]]] = {
        "E-001": {
            "ids": ["a1", "a2"],
            "documents": ["doc1", "doc2"],
            "metadatas": [{"epic_id": "E-001"}, {"epic_id": "E-001"}],
        },
    }

    with (
        patch("services.dashboard.sync.sqlite3.connect", _make_mock_sqlite_rows(rows)),
        patch("services.dashboard.sync.chromadb.HttpClient", _make_mock_chromadb(epic_results)),
    ):
        events = _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    assert events == []
    assert epic_timestamps["E-001"] == "2026-01-01T00:00:00"
    assert epic_artifact_counts["E-001"] == 2


def test_epic_timestamp_change_emits_event() -> None:
    epic_timestamps: dict[str, str] = {"E-001": "2026-01-01T00:00:00"}
    epic_artifact_counts: dict[str, int] = {"E-001": 2}
    epic_chromadb_timestamps: dict[str, str] = {}

    rows = [
        {"epic_id": "E-001", "last_updated_at": "2026-01-02T00:00:00", "status": "completed", "title": "Test Epic", "depends_on": "[]"},
    ]
    epic_results: dict[str, dict[str, list[Any]]] = {
        "E-001": {
            "ids": ["a1", "a2"],
            "documents": ["doc1", "doc2"],
            "metadatas": [{"epic_id": "E-001"}, {"epic_id": "E-001"}],
        },
    }

    with (
        patch("services.dashboard.sync.sqlite3.connect", _make_mock_sqlite_rows(rows)),
        patch("services.dashboard.sync.chromadb.HttpClient", _make_mock_chromadb(epic_results)),
    ):
        events = _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    assert len(events) == 1
    assert events[0]["type"] == "epic_change"
    assert events[0]["epic_id"] == "E-001"
    assert events[0]["data"]["status"] == "completed"
    assert events[0]["data"]["last_updated_at"] == "2026-01-02T00:00:00"


def test_new_artifacts_detected() -> None:
    epic_timestamps: dict[str, str] = {"E-001": "2026-01-01T00:00:00"}
    epic_artifact_counts: dict[str, int] = {"E-001": 2}
    epic_chromadb_timestamps: dict[str, str] = {}

    rows = [
        {"epic_id": "E-001", "last_updated_at": "2026-01-01T00:00:00", "status": "in_progress", "title": "Test Epic", "depends_on": "[]"},
    ]
    epic_results: dict[str, dict[str, list[Any]]] = {
        "E-001": {
            "ids": ["a1", "a2", "a3"],
            "documents": ["doc1", "doc2", "doc3"],
            "metadatas": [
                {"epic_id": "E-001"},
                {"epic_id": "E-001"},
                {"epic_id": "E-001", "artifact_type": "step_result"},
            ],
        },
    }

    with (
        patch("services.dashboard.sync.sqlite3.connect", _make_mock_sqlite_rows(rows)),
        patch("services.dashboard.sync.chromadb.HttpClient", _make_mock_chromadb(epic_results)),
    ):
        events = _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    assert len(events) == 1
    assert events[0]["type"] == "artifact_new"
    assert events[0]["epic_id"] == "E-001"
    assert events[0]["data"]["id"] == "a3"
    assert events[0]["data"]["document"] == "doc3"
    assert epic_artifact_counts["E-001"] == 3


def test_sqlite_error_does_not_crash() -> None:
    epic_timestamps: dict[str, str] = {}
    epic_artifact_counts: dict[str, int] = {}
    epic_chromadb_timestamps: dict[str, str] = {}

    mock_connect = MagicMock(side_effect=sqlite3.Error("db locked"))
    epic_results: dict[str, dict[str, list[Any]]] = {}

    with (
        patch("services.dashboard.sync.sqlite3.connect", mock_connect),
        patch("services.dashboard.sync.chromadb.HttpClient", _make_mock_chromadb(epic_results)),
    ):
        events = _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    # No events because SQLite failed and no epics were seeded
    assert events == []
    assert len(epic_timestamps) == 0


def test_chromadb_error_does_not_crash() -> None:
    epic_timestamps: dict[str, str] = {"E-001": "2026-01-01T00:00:00"}
    epic_artifact_counts: dict[str, int] = {"E-001": 1}
    epic_chromadb_timestamps: dict[str, str] = {}

    rows = [
        {"epic_id": "E-001", "last_updated_at": "2026-01-02T00:00:00", "status": "completed", "title": "Test Epic", "depends_on": "[]"},
    ]
    mock_chromadb = MagicMock(side_effect=ConnectionError("unreachable"))

    with (
        patch("services.dashboard.sync.sqlite3.connect", _make_mock_sqlite_rows(rows)),
        patch("services.dashboard.sync.chromadb.HttpClient", mock_chromadb),
    ):
        events = _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    # Should still get the epic_change event from SQLite
    assert len(events) == 1
    assert events[0]["type"] == "epic_change"
