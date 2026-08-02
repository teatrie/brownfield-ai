"""Unit tests for brownfield_ai.ledger.infra connection factories.

Tests get_client (ChromaDB HTTP client) and get_db (SQLite schema
bootstrap, migration idempotency, and category seeding).
"""

from __future__ import annotations

import os
import pathlib
import sqlite3 as _sqlite3
from unittest.mock import MagicMock, patch

from brownfield_ai.ledger.infra import get_client, get_db

# ---------------------------------------------------------------------------
# get_client() tests
# ---------------------------------------------------------------------------


@patch("brownfield_ai.ledger.infra.chromadb.HttpClient")
@patch.dict(os.environ, {}, clear=True)
def test_get_client_defaults_to_localhost(mock_client: MagicMock) -> None:
    """Verify get_client defaults to localhost:8000 when env vars are unset."""
    get_client()
    mock_client.assert_called_once_with(host="localhost", port=8000)


@patch("brownfield_ai.ledger.infra.chromadb.HttpClient")
@patch.dict(os.environ, {"CHROMADB_HOST": "remote-host", "CHROMADB_PORT": "9000"}, clear=True)
def test_get_client_respects_env_vars(mock_client: MagicMock) -> None:
    """Verify get_client reads CHROMADB_HOST and CHROMADB_PORT from env."""
    get_client()
    mock_client.assert_called_once_with(host="remote-host", port=9000)


# ---------------------------------------------------------------------------
# get_db() schema tests
# ---------------------------------------------------------------------------


def test_get_db_creates_table(tmp_path: pathlib.Path) -> None:
    """Verify get_db creates the epics table."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn = get_db()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='epics'")
        row = cursor.fetchone()
        conn.close()
    assert row is not None
    assert row[0] == "epics"


def test_get_db_creates_todos_table(tmp_path: pathlib.Path) -> None:
    """Verify get_db creates the todos table."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn = get_db()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='todos'")
        row = cursor.fetchone()
        conn.close()
    assert row is not None
    assert row[0] == "todos"


def test_get_db_creates_todo_categories_table(tmp_path: pathlib.Path) -> None:
    """Verify get_db creates the todo_categories table."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn = get_db()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='todo_categories'")
        row = cursor.fetchone()
        conn.close()
    assert row is not None
    assert row[0] == "todo_categories"


def test_get_db_seeds_eight_categories(tmp_path: pathlib.Path) -> None:
    """Verify get_db seeds exactly 8 default categories."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM todo_categories").fetchone()[0]
        conn.close()
    assert count == 8


def test_get_db_seed_is_idempotent(tmp_path: pathlib.Path) -> None:
    """Verify calling get_db twice does not duplicate seed categories."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn1 = get_db()
        conn1.close()
        conn2 = get_db()
        count = conn2.execute("SELECT COUNT(*) FROM todo_categories").fetchone()[0]
        conn2.close()
    assert count == 8


def test_get_db_creates_current_prs_column(tmp_path: pathlib.Path) -> None:
    """Verify get_db includes current_prs column in epics table."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn = get_db()
        columns = [row[1] for row in conn.execute("PRAGMA table_info(epics)").fetchall()]
        conn.close()
    assert "current_prs" in columns


def test_get_db_idempotent_second_call_on_same_file(tmp_path: pathlib.Path) -> None:
    """Verify second get_db call on same file does not raise."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn1 = get_db()
        conn1.close()
        conn2 = get_db()
        columns = [row[1] for row in conn2.execute("PRAGMA table_info(epics)").fetchall()]
        conn2.close()
    assert "current_prs" in columns


def test_get_db_adds_current_prs_via_alter_table_on_existing_db(tmp_path: pathlib.Path) -> None:
    """Verify get_db adds current_prs column to a legacy DB via ALTER TABLE.

    Bootstraps a minimal DB without the current_prs column, then calls
    get_db() which must add it via ALTER TABLE migration.
    """
    db_path = str(tmp_path / "legacy.db")
    legacy_conn = _sqlite3.connect(db_path)
    legacy_conn.execute(
        """
        CREATE TABLE epics (
            epic_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 5,
            depends_on TEXT DEFAULT '[]',
            claimed_by TEXT DEFAULT '',
            claimed_at TEXT DEFAULT '',
            title TEXT DEFAULT '',
            created_at TEXT,
            last_updated_at TEXT
        )
        """
    )
    legacy_conn.commit()
    legacy_conn.close()

    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        conn = get_db()
        columns = [row[1] for row in conn.execute("PRAGMA table_info(epics)").fetchall()]
        conn.close()
    assert "current_prs" in columns
