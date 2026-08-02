"""PR reference management for epics.

Provides functions to set, get, and clear the ``current_prs`` column
on the ``epics`` SQLite table.  PR refs follow the canonical
``owner/repo#number`` format validated by ``_PR_REF_PATTERN``.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from typing import Any

from brownfield_ai.ledger.epics.constants import _PR_REF_PATTERN


def set_current_prs(db: sqlite3.Connection, epic_id: str, pr_refs: str) -> None:
    """Validate and store PR refs for an epic.

    Each comma-separated entry must match ``{owner}/{repo}#{number}``.

    Passing an empty or whitespace-only string clears ``current_prs``
    (sets to NULL).

    Args:
        db: SQLite database connection.
        epic_id: The epic identifier.
        pr_refs: Comma-separated PR references in ``owner/repo#number`` format.

    Returns:
        None.

    Raises:
        SystemExit: If any PR ref does not match the expected format, or if the
            epic does not exist.
    """
    # Empty input clears current_prs (Req-011)
    if not pr_refs.strip():
        now = datetime.now().isoformat()
        cursor = db.execute(
            "UPDATE epics SET current_prs = NULL, last_updated_at = ? WHERE epic_id = ?",
            (now, epic_id),
        )
        db.commit()
        if cursor.rowcount == 0:
            print(f"Epic '{epic_id}' not found.")
            sys.exit(1)
        return
    entries = [e.strip() for e in pr_refs.split(",")]
    for entry in entries:
        if not _PR_REF_PATTERN.match(entry):
            print(f"Invalid PR ref format: '{entry}'. Expected: owner/repo#number")
            sys.exit(1)
    canonicalized = ", ".join(entries)
    now = datetime.now().isoformat()
    cursor = db.execute(
        "UPDATE epics SET current_prs = ?, last_updated_at = ? WHERE epic_id = ?",
        (canonicalized, now, epic_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        print(f"Epic '{epic_id}' not found.")
        sys.exit(1)


def get_current_prs(db: sqlite3.Connection, epic_id: str) -> str | None:
    """Read the current_prs column for an epic.

    Args:
        db: SQLite database connection.
        epic_id: The epic identifier.

    Returns:
        str or None: The current PR refs string, or ``None`` if not set.
    """
    row = db.execute("SELECT current_prs FROM epics WHERE epic_id = ?", (epic_id,)).fetchone()
    if row is None:
        return None
    val: Any = row["current_prs"]
    return val if isinstance(val, str) else None


def clear_current_prs(db: sqlite3.Connection, epic_id: str) -> None:
    """Set current_prs to NULL for an epic.

    Args:
        db: SQLite database connection.
        epic_id: The epic identifier.

    Returns:
        None.
    """
    now = datetime.now().isoformat()
    db.execute(
        "UPDATE epics SET current_prs = NULL, last_updated_at = ? WHERE epic_id = ?",
        (now, epic_id),
    )
    db.commit()
