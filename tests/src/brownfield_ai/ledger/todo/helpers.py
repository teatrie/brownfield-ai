"""Test helper utilities for the brownfield_ai.ledger.todo test suite.

Plain functions (not pytest fixtures) used across multiple test modules.
"""

from __future__ import annotations

import json
import sqlite3


def insert_todo(
    db: sqlite3.Connection,
    *,
    title: str = "Test TODO",
    status: str = "open",
    priority: int = 5,
    category: str = "",
    epic_id: str = "",
) -> int:
    """Insert a TODO row directly into SQLite and return its ID.

    Args:
        db: SQLite connection with the ledger schema.
        title: TODO title.
        status: TODO status.
        priority: Numeric priority 0-9.
        category: Primary category.
        epic_id: Associated epic ID.

    Returns:
        The auto-incremented TODO ID.
    """
    now = "2026-01-01T00:00:00"
    ctx = json.dumps({"schema_version": 1})
    cursor = db.execute(
        """
        INSERT INTO todos (
            title, description, context_snapshot, category,
            secondary_categories, priority, source_workspace,
            status, created_at, last_updated_at, epic_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            "",
            ctx,
            category or None,
            None,
            priority,
            "/workspace",
            status,
            now,
            now,
            epic_id or None,
        ),
    )
    db.commit()
    assert cursor.lastrowid is not None, "INSERT failed to produce a row ID"
    return cursor.lastrowid
