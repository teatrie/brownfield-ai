"""Shared helpers for the brownfield_ai.ledger.epics test suite.

Provides low-level insert utilities for setting up test data without
going through the public API, enabling targeted unit test isolation.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


def insert_epic(
    db: sqlite3.Connection,
    epic_id: str,
    *,
    status: str = "pending",
    priority: int = 5,
    depends_on: str = "[]",
    title: str = "",
    claimed_by: str = "",
    claimed_at: str = "",
    current_prs: str | None = None,
) -> None:
    """Insert a test epic directly into the database.

    Bypasses public API validation so individual unit tests can exercise
    specific database states without going through the full lifecycle.

    Args:
        db: SQLite database connection.
        epic_id: Unique epic identifier (e.g. ``TEST-001``).
        status: Epic lifecycle status (default ``pending``).
        priority: Numeric priority 0-9 where 0 is highest (default 5).
        depends_on: JSON array of dependency epic IDs (default ``[]``).
        title: Human-readable epic title (default ``""``).
        claimed_by: Identifier of the agent that claimed this epic (default ``""``).
        claimed_at: ISO-8601 timestamp of when the epic was claimed (default ``""``).
        current_prs: Comma-separated PR refs in ``owner/repo#number`` format,
            or ``None`` to leave unset (default ``None``).
    """
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO epics"
        " (epic_id, status, priority, depends_on, title,"
        " claimed_by, claimed_at, current_prs, created_at, last_updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            epic_id,
            status,
            priority,
            depends_on,
            title,
            claimed_by,
            claimed_at,
            current_prs,
            now,
            now,
        ),
    )
    db.commit()
