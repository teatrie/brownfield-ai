"""Shared fixtures for dashboard route tests.

Provides ``dashboard_db`` (in-memory SQLite with seed data) and
``dashboard_overrides`` (FastAPI dependency overrides with mock
ChromaDB collections).  Both are non-autouse — test modules activate
them via a thin ``_override_dependencies`` wrapper.

Module-scope references to the dashboard ``app`` and dependency
functions are captured early so they survive the
``importlib.reload`` executed by ``test_health_route.py``.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

# Capture references at module scope BEFORE any test runs — this
# survives importlib.reload(services.dashboard.deps) in
# test_health_route.py.  Paths are already on sys.path via the
# root conftest's early setup block.
from services.dashboard.app import app as _dashboard_app
from services.dashboard.deps import (
    get_chromadb_client,
    get_chromadb_collection,
    get_epics_collection,
    get_kb_collection,
    get_sqlite_db,
    get_todos_collection,
)


@pytest.fixture
def dashboard_db():
    """Create an in-memory SQLite database seeded with dashboard test data."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
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
    conn.execute("""INSERT INTO epics VALUES (
        'TEST-001', 'in_progress', 3, '[]', 'agent-1', '2026-01-01',
        'Test Epic', '2026-01-01', '2026-01-02', NULL
    )""")
    conn.execute("""INSERT INTO epics VALUES (
        'TEST-002', 'backlog', 5, '[]', '', '', 'Backlog Epic',
        '2026-01-01', '2026-01-02', NULL
    )""")
    conn.execute("""CREATE TABLE todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        status TEXT DEFAULT 'open',
        priority INTEGER DEFAULT 5,
        category TEXT DEFAULT '',
        epic_id TEXT,
        source_workspace TEXT,
        context_snapshot TEXT DEFAULT '{}',
        resolution TEXT,
        secondary_categories TEXT DEFAULT '',
        created_at TEXT,
        last_updated_at TEXT
    )""")
    conn.execute("""INSERT INTO todos (
        id, title, status, priority, category, epic_id,
        created_at, last_updated_at
    ) VALUES (
        1, 'Test TODO', 'open', 5, 'infra', NULL,
        '2026-01-01', '2026-01-01'
    )""")
    conn.execute("""INSERT INTO todos (
        id, title, status, priority, category, epic_id,
        created_at, last_updated_at
    ) VALUES (
        2, 'Done TODO', 'done', 3, 'code', NULL,
        '2026-01-01', '2026-01-01'
    )""")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def dashboard_overrides(dashboard_db):
    """Override all FastAPI dashboard dependencies and return mock references.

    Sets ``app.dependency_overrides`` for SQLite and all four ChromaDB
    collections, then yields a dict with keys ``db``, ``collection``,
    ``todos_collection``, ``epics_collection``, and ``kb_collection``.
    Tests create their own ``httpx.AsyncClient`` with
    ``ASGITransport(app=app)``.
    """
    mock_collection = MagicMock()
    mock_todos_collection = MagicMock()
    mock_epics_collection = MagicMock()
    mock_kb_collection = MagicMock()
    mock_chromadb_client = MagicMock()

    def override_sqlite():
        yield dashboard_db

    def override_chromadb():
        return mock_collection

    def override_todos():
        return mock_todos_collection

    def override_epics():
        return mock_epics_collection

    def override_kb():
        return mock_kb_collection

    def override_chromadb_client():
        return mock_chromadb_client

    _dashboard_app.dependency_overrides[get_sqlite_db] = override_sqlite
    _dashboard_app.dependency_overrides[get_chromadb_collection] = override_chromadb
    _dashboard_app.dependency_overrides[get_todos_collection] = override_todos
    _dashboard_app.dependency_overrides[get_epics_collection] = override_epics
    _dashboard_app.dependency_overrides[get_kb_collection] = override_kb
    _dashboard_app.dependency_overrides[get_chromadb_client] = override_chromadb_client

    try:
        yield {
            "db": dashboard_db,
            "collection": mock_collection,
            "todos_collection": mock_todos_collection,
            "epics_collection": mock_epics_collection,
            "kb_collection": mock_kb_collection,
            "chromadb_client": mock_chromadb_client,
        }
    finally:
        _dashboard_app.dependency_overrides.clear()
