"""Shared infrastructure helpers for the execution ledger.

Provides the SQLite database connection factory (``get_db``), the
ChromaDB client factory (``get_client``), seed data for TODO
categories, and the canonical database path constant.  All other
ledger subpackages import their DB/client plumbing from here.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime

import chromadb

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SQLITE_DB_PATH: str = "/brownfield-ai/ledger_index.db"

_SEED_CATEGORIES: list[tuple[str, str]] = [
    ("infra", "Infrastructure, CI/CD, Docker, and deployment tooling"),
    ("datalake", "Data lake pipelines, ETL, and Spark jobs"),
    ("tooling", "Developer tools, CLI utilities, and task automation"),
    ("agents", "AI agent orchestration, skills, and prompts"),
    ("docs", "Documentation, READMEs, and architecture guides"),
    ("testing", "Test coverage, fixtures, and QA improvements"),
    ("security", "Security hardening, secrets management, and access control"),
    ("data-quality", "Data validation, schema enforcement, and quality checks"),
]


# ---------------------------------------------------------------------------
# Connection factories
# ---------------------------------------------------------------------------


def get_client() -> chromadb.api.ClientAPI:
    """Initialize and return a ChromaDB HTTP client.

    Reads ``CHROMADB_HOST`` and ``CHROMADB_PORT`` from environment variables,
    falling back to ``localhost:8000``.

    Returns:
        chromadb.api.ClientAPI: The instantiated client.
    """
    host = os.environ.get("CHROMADB_HOST", "localhost")
    port = int(os.environ.get("CHROMADB_PORT", "8000"))
    try:
        return chromadb.HttpClient(host=host, port=port)
    except (chromadb.errors.ChromaError, ConnectionError, ValueError, OSError) as exc:
        print(f"Failed to connect to ChromaDB at {host}:{port}: {exc}")
        sys.exit(1)


def get_db() -> sqlite3.Connection:
    """Open (and auto-create) the SQLite ledger index database.

    Creates the ``epics``, ``todo_categories``, and ``todos`` tables
    along with their composite indexes if they do not already exist.
    Seeds ``todo_categories`` with the default category set using
    ``INSERT OR IGNORE`` for idempotency.

    Returns:
        sqlite3.Connection: An open database connection.
    """
    db_path = os.environ.get("LEDGER_DB_PATH", SQLITE_DB_PATH)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS epics (
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_epics_status ON epics(status, priority)")

        # Migrate: add current_prs column if absent
        cols = {row[1] for row in conn.execute("PRAGMA table_info(epics)").fetchall()}
        if "current_prs" not in cols:
            conn.execute("ALTER TABLE epics ADD COLUMN current_prs TEXT DEFAULT NULL")
            conn.commit()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS todo_categories (
                name        TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                title                TEXT    NOT NULL,
                description          TEXT,
                context_snapshot     TEXT,
                category             TEXT    REFERENCES todo_categories(name),
                secondary_categories TEXT,
                priority             INTEGER NOT NULL DEFAULT 5,
                epic_id              TEXT,
                source_workspace     TEXT,
                status               TEXT    NOT NULL DEFAULT 'open',
                resolution           TEXT,
                created_at           TEXT    NOT NULL,
                last_updated_at      TEXT    NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_status_priority ON todos (status, priority)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_epic ON todos (epic_id)")

        now = datetime.now().isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO todo_categories (name, description, created_at) VALUES (?, ?, ?)",
            [(name, desc, now) for name, desc in _SEED_CATEGORIES],
        )

        conn.commit()
        return conn
    except (sqlite3.Error, OSError) as exc:
        print(f"Failed to open SQLite database at {db_path}: {exc}")
        sys.exit(1)
