"""Read-only query functions for the TODO subsystem.

Provides filtered, paginated listing and single-record fetch against
the SQLite ``todos`` table.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from brownfield_ai.ledger.todo.constants import _TODOS_BASE_SQL


def get_todo(db: sqlite3.Connection, todo_id: int) -> dict[str, Any] | None:
    """Fetch a single TODO by its integer ID.

    Args:
        db: SQLite database connection.
        todo_id: The integer TODO ID.

    Returns:
        The TODO row as a dictionary, or ``None`` if not found.
    """
    row = db.execute(_TODOS_BASE_SQL + " WHERE id = ?", (todo_id,)).fetchone()
    return dict(row) if row else None


def list_todos(
    db: sqlite3.Connection,
    statuses: list[str],
    *,
    category: str = "",
    epic_id: str = "",
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query TODOs from SQLite with optional filters and pagination.

    Supports multi-status filtering via SQL ``IN`` clause. Results are
    ordered by priority ascending (0 = highest priority first).

    Args:
        db: SQLite database connection.
        statuses: List of status values to filter on. Empty list returns
            all statuses.
        category: Optional category filter (exact match).
        epic_id: Optional epic ID filter (exact match).
        limit: Maximum number of results to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TODO row dictionaries.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        conditions.append(f"status IN ({placeholders})")
        params.extend(statuses)

    if category:
        conditions.append("category = ?")
        params.append(category)

    if epic_id:
        conditions.append("epic_id = ?")
        params.append(epic_id)

    base = _TODOS_BASE_SQL
    if conditions:
        base += " WHERE " + " AND ".join(conditions)
    base += " ORDER BY priority ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(base, params).fetchall()
    return [dict(row) for row in rows]


def fetch_categories(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all TODO categories from the database.

    Args:
        db: SQLite database connection.

    Returns:
        List of category row dictionaries with keys ``name``,
        ``description``, and ``created_at``.
    """
    rows = db.execute("SELECT name, description, created_at FROM todo_categories ORDER BY name").fetchall()
    return [dict(row) for row in rows]
