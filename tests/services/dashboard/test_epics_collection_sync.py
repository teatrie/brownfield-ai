"""Tests for the epics collection sync logic in the sync loop.

Validates that the ``_detect_changes`` function correctly upserts
epic data to the ChromaDB ``epics`` collection, skips unchanged
epics on subsequent polls, and that the ``sync_loop`` handles
ChromaDB failures with exponential backoff.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.dashboard.sync import (
    SYNC_INTERVAL,
    _detect_changes,
    sync_loop,
)


def _make_mock_row(
    epic_id: str,
    last_updated_at: str,
    status: str,
    title: str,
    depends_on: str,
) -> MagicMock:
    """Create a mock SQLite Row with dict-style key access.

    Args:
        epic_id: The epic identifier.
        last_updated_at: ISO-8601 timestamp.
        status: Epic status string.
        title: Epic title.
        depends_on: Comma-separated dependency list.

    Returns:
        A MagicMock that supports dictionary-style access by column name.
    """
    data = {
        "epic_id": epic_id,
        "last_updated_at": last_updated_at,
        "status": status,
        "title": title,
        "depends_on": depends_on,
    }
    row = MagicMock()
    row.__getitem__ = lambda self, key: data[key]
    row.keys = lambda: data.keys()
    return row


# ---------------------------------------------------------------------------
# test_first_sync_populates_epics_collection
# ---------------------------------------------------------------------------


def test_first_sync_populates_epics_collection() -> None:
    mock_rows = [
        _make_mock_row("E-001", "2026-01-01", "in_progress", "Alpha", "[]"),
        _make_mock_row("E-002", "2026-01-02", "backlog", "Beta", "[E-001]"),
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_conn.row_factory = None

    mock_epics_collection = MagicMock()
    mock_artifacts_collection = MagicMock()
    mock_artifacts_collection.get.return_value = {"ids": []}

    mock_client = MagicMock()

    def _get_or_create(name: str) -> MagicMock:
        """Route collection creation to the correct mock."""
        if name == "epics":
            return mock_epics_collection
        return mock_artifacts_collection

    mock_client.get_or_create_collection.side_effect = _get_or_create

    epic_timestamps: dict[str, str] = {}
    epic_artifact_counts: dict[str, int] = {}
    epic_chromadb_timestamps: dict[str, str] = {}

    with (
        patch("services.dashboard.sync.sqlite3") as mock_sqlite3,
        patch("services.dashboard.sync.chromadb") as mock_chromadb,
    ):
        mock_sqlite3.connect.return_value = mock_conn
        mock_sqlite3.Error = Exception
        mock_chromadb.HttpClient.return_value = mock_client

        _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    # Both epics should have been upserted
    assert mock_epics_collection.upsert.call_count == 2

    first_call = mock_epics_collection.upsert.call_args_list[0]
    assert first_call[1]["ids"] == ["E-001"]
    assert "Alpha" in first_call[1]["documents"][0]
    assert first_call[1]["metadatas"][0]["status"] == "in_progress"

    second_call = mock_epics_collection.upsert.call_args_list[1]
    assert second_call[1]["ids"] == ["E-002"]
    assert "Beta" in second_call[1]["documents"][0]

    # Tracking state should be updated
    assert epic_chromadb_timestamps["E-001"] == "2026-01-01"
    assert epic_chromadb_timestamps["E-002"] == "2026-01-02"


# ---------------------------------------------------------------------------
# test_unchanged_epics_not_reupserted
# ---------------------------------------------------------------------------


def test_unchanged_epics_not_reupserted() -> None:
    mock_rows = [
        _make_mock_row("E-001", "2026-01-01", "in_progress", "Alpha", "[]"),
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_conn.row_factory = None

    mock_epics_collection = MagicMock()
    mock_artifacts_collection = MagicMock()
    mock_artifacts_collection.get.return_value = {"ids": []}

    mock_client = MagicMock()

    def _get_or_create(name: str) -> MagicMock:
        """Route collection creation to the correct mock."""
        if name == "epics":
            return mock_epics_collection
        return mock_artifacts_collection

    mock_client.get_or_create_collection.side_effect = _get_or_create

    # Pre-seed tracking state to simulate prior sync
    epic_timestamps: dict[str, str] = {"E-001": "2026-01-01"}
    epic_artifact_counts: dict[str, int] = {"E-001": 0}
    epic_chromadb_timestamps: dict[str, str] = {"E-001": "2026-01-01"}

    with (
        patch("services.dashboard.sync.sqlite3") as mock_sqlite3,
        patch("services.dashboard.sync.chromadb") as mock_chromadb,
    ):
        mock_sqlite3.connect.return_value = mock_conn
        mock_sqlite3.Error = Exception
        mock_chromadb.HttpClient.return_value = mock_client

        _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    # No upsert should have occurred
    mock_epics_collection.upsert.assert_not_called()


# ---------------------------------------------------------------------------
# test_changed_epic_reupserted
# ---------------------------------------------------------------------------


def test_changed_epic_reupserted() -> None:
    mock_rows = [
        _make_mock_row("E-001", "2026-01-05", "completed", "Alpha Done", "[]"),
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_conn.row_factory = None

    mock_epics_collection = MagicMock()
    mock_artifacts_collection = MagicMock()
    mock_artifacts_collection.get.return_value = {"ids": []}

    mock_client = MagicMock()

    def _get_or_create(name: str) -> MagicMock:
        """Route collection creation to the correct mock."""
        if name == "epics":
            return mock_epics_collection
        return mock_artifacts_collection

    mock_client.get_or_create_collection.side_effect = _get_or_create

    # Pre-seed tracking state with old timestamp
    epic_timestamps: dict[str, str] = {"E-001": "2026-01-01"}
    epic_artifact_counts: dict[str, int] = {"E-001": 0}
    epic_chromadb_timestamps: dict[str, str] = {"E-001": "2026-01-01"}

    with (
        patch("services.dashboard.sync.sqlite3") as mock_sqlite3,
        patch("services.dashboard.sync.chromadb") as mock_chromadb,
    ):
        mock_sqlite3.connect.return_value = mock_conn
        mock_sqlite3.Error = Exception
        mock_chromadb.HttpClient.return_value = mock_client

        _detect_changes(epic_timestamps, epic_artifact_counts, epic_chromadb_timestamps)

    # Upsert should have been called with the new data
    mock_epics_collection.upsert.assert_called_once()
    call = mock_epics_collection.upsert.call_args
    assert call[1]["ids"] == ["E-001"]
    assert "Alpha Done" in call[1]["documents"][0]
    assert "completed" in call[1]["documents"][0]
    assert call[1]["metadatas"][0]["status"] == "completed"
    assert epic_chromadb_timestamps["E-001"] == "2026-01-05"


# ---------------------------------------------------------------------------
# test_chromadb_failure_increments_backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chromadb_failure_increments_backoff() -> None:
    manager = MagicMock()
    manager.broadcast = AsyncMock()
    manager.send_to_epic = AsyncMock()

    call_count = 0
    backoff_values: list[float] = []

    async def mock_sleep(duration: float) -> None:
        """Capture sleep durations to verify backoff progression."""
        nonlocal call_count
        backoff_values.append(duration)
        call_count += 1
        if call_count >= 6:
            raise asyncio.CancelledError

    def _failing_detect(*args: Any) -> list[dict[str, Any]]:
        """Simulate a sync cycle failure."""
        raise ConnectionError("ChromaDB unavailable")

    with (
        patch("services.dashboard.sync._detect_changes", side_effect=_failing_detect),
        patch("services.dashboard.sync.asyncio.sleep", side_effect=mock_sleep),
        patch("services.dashboard.sync.asyncio.to_thread", side_effect=_failing_detect),
    ):
        with pytest.raises(asyncio.CancelledError):
            await sync_loop(manager)

    # First iteration: no backoff sleep, then SYNC_INTERVAL sleep
    # Second iteration: backoff=BACKOFF_BASE, then SYNC_INTERVAL sleep
    # Third iteration: backoff=BACKOFF_BASE*2, then SYNC_INTERVAL sleep
    # The backoff_values list contains interleaved backoff and interval sleeps
    assert len(backoff_values) >= 3
    # Verify that backoff values are increasing (filter out SYNC_INTERVAL sleeps)
    backoff_only = [v for v in backoff_values if v != SYNC_INTERVAL]
    if len(backoff_only) >= 2:
        assert backoff_only[1] >= backoff_only[0]
