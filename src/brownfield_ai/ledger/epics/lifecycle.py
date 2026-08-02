"""Epic lifecycle state management.

Provides functions for creating epics, updating their status through
the state machine, touching timestamps, updating priorities, releasing
claims, and upserting the SQLite index during plan-snapshot saves.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from typing import Any

from brownfield_ai.ledger.epics.constants import VALID_EPIC_STATUSES, VALID_TRANSITIONS
from brownfield_ai.ledger.epics.prs import get_current_prs


def upsert_epic_index(db: sqlite3.Connection, params: dict[str, Any], now: str) -> None:
    """Upsert an epic's index entry in SQLite during plan_snapshot saves.

    Args:
        db: SQLite database connection.
        params: Dictionary with keys ``epic_id``, ``epic_status``,
            ``priority``, ``depends_on``, ``title``.
        now: ISO-8601 timestamp string.
    """
    eid = params["epic_id"]
    est = params.get("epic_status", "pending")
    pri = params.get("priority", 5)
    dep = params.get("depends_on", "[]")
    ttl = params.get("title", "")
    db.execute(
        """
        INSERT INTO epics (
            epic_id, status, priority, depends_on, title,
            created_at, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(epic_id) DO UPDATE SET
            status = COALESCE(NULLIF(?, ''), epics.status),
            priority = ?,
            depends_on = ?,
            title = COALESCE(NULLIF(?, ''), epics.title),
            last_updated_at = ?
        """,
        (eid, est, pri, dep, ttl, now, now, est, pri, dep, ttl, now),
    )
    db.commit()


def create_epic(
    db: sqlite3.Connection,
    epic_id: str,
    title: str,
    *,
    status: str = "backlog",
    priority: int = 5,
    depends_on: str = "[]",
) -> bool:
    """Create a new epic in the SQLite registry (INSERT-only, not upsert).

    Uses ``INSERT OR IGNORE`` so that duplicate calls for the same
    ``epic_id`` are silently ignored rather than raising an error.
    This function coexists with ``upsert_epic_index()`` which handles
    plan-snapshot-driven upserts with ``ON CONFLICT DO UPDATE`` semantics.

    Args:
        db: SQLite database connection.
        epic_id: Unique epic identifier (e.g. ``ACME-1234``).
        title: Human-readable epic title.
        status: Initial lifecycle status (default ``backlog``).
        priority: Numeric priority 0-9 where 0 is highest (default 5).
        depends_on: JSON array of dependency epic IDs (default ``[]``).

    Returns:
        bool: ``True`` if the epic was inserted, ``False`` if it already
        exists.
    """
    if status not in VALID_EPIC_STATUSES:
        print(f"Invalid status '{status}'. Must be one of: {sorted(VALID_EPIC_STATUSES)}")
        sys.exit(1)

    now = datetime.now().isoformat()
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO epics (
            epic_id, status, priority, depends_on, title,
            created_at, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (epic_id, status, priority, depends_on, title, now, now),
    )
    db.commit()
    return cursor.rowcount > 0


def release_epic(db: sqlite3.Connection, epic_id: str) -> bool:
    """Release a claimed epic back to ``approved`` status.

    Args:
        db: SQLite database connection.
        epic_id: The epic identifier to release.

    Returns:
        bool: ``True`` if the epic was released, ``False`` if not found
        or not claimed.
    """
    now = datetime.now().isoformat()
    cursor = db.execute(
        "UPDATE epics"
        " SET status = 'approved', claimed_by = '',"
        " claimed_at = '', last_updated_at = ?"
        " WHERE epic_id = ? AND status = 'in_progress'",
        (now, epic_id),
    )
    db.commit()
    return cursor.rowcount > 0


def _query_open_todos(db: sqlite3.Connection, epic_id: str) -> list[dict[str, Any]]:
    """Query non-done TODOs associated with an epic.

    Args:
        db: SQLite database connection.
        epic_id: The epic identifier.

    Returns:
        list: List of dicts with ``id`` and ``title`` for each open TODO.
    """
    rows = db.execute(
        "SELECT id, title FROM todos WHERE epic_id = ? AND status != 'done'",
        (epic_id,),
    ).fetchall()
    return [{"id": row["id"], "title": row["title"]} for row in rows]


def update_status(
    db: sqlite3.Connection,
    epic_id: str,
    new_status: str,
    *,
    force: bool = False,
    fast_path: bool = False,
) -> dict[str, Any]:
    """Update an epic's lifecycle status with transition validation.

    Validates allowed transitions per the state machine. Updates
    ``last_updated_at`` on every transition. Enforces TODO constraints
    for terminal statuses:

    - **completed**: Hard-blocked if the epic has non-done TODOs or if
      ``current_prs`` is non-NULL (unmerged PRs exist).
    - **abandoned**: Returns a warning payload when non-done TODOs exist
      and ``force`` is ``False``. When ``force`` is ``True``, orphans
      those TODOs (sets ``epic_id=NULL``, ``status='open'``) before
      proceeding. ``done`` TODOs retain their ``epic_id`` for audit.

    Callers may stage uncommitted writes (e.g., ``current_prs = NULL``)
    before invocation; ``db.commit()`` inside this function commits both
    changes atomically.

    The ``backlog -> approved`` transition requires ``fast_path=True``.
    The artifact check for ``pr_changes_required`` lives in the ``status()``
    CLI wrapper, not here; ``update_status()`` trusts the ``fast_path`` flag.

    Args:
        db: SQLite database connection.
        epic_id: The epic identifier.
        new_status: The target status.
        force: When ``True``, auto-orphan non-done TODOs on ``abandoned``
            transitions instead of returning a warning.
        fast_path: When ``True``, permits the ``backlog -> approved``
            shortcut transition without requiring the normal planning steps.

    Returns:
        dict: ``{"success": True}`` on normal completion,
        ``{"success": False, "error": "..."}`` on validation failure,
        ``{"success": False, "action": "confirm_orphan", "todo_ids": [...]}``
        when ``abandoned`` with ``force=False`` and orphan-eligible TODOs exist.

    Raises:
        SystemExit: If the transition is invalid or epic not found.
    """
    if new_status not in VALID_EPIC_STATUSES:
        print(f"Invalid status '{new_status}'. Must be one of: {sorted(VALID_EPIC_STATUSES)}")
        sys.exit(1)

    row = db.execute("SELECT status FROM epics WHERE epic_id = ?", (epic_id,)).fetchone()
    if row is None:
        print(f"Epic '{epic_id}' not found.")
        sys.exit(1)

    current = row["status"]
    allowed = VALID_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        print(f"Invalid transition: '{current}' -> '{new_status}'. Allowed: {allowed}")
        sys.exit(1)

    # Fast-path guard: backlog -> approved requires explicit fast_path flag
    if current == "backlog" and new_status == "approved" and not fast_path:
        print("Transition backlog -> approved requires fast_path=True. Use the status CLI with --fast-path.")
        sys.exit(1)

    # Completion gate: block if current_prs is set (Req-005)
    if new_status == "completed":
        prs = get_current_prs(db, epic_id)
        if prs:
            return {
                "success": False,
                "error": f"Cannot complete epic {epic_id}: unmerged PRs exist (current_prs: {prs}). Merge or close them first.",
            }

    # TODO constraints for terminal statuses
    if new_status == "completed":
        open_todos = _query_open_todos(db, epic_id)
        if open_todos:
            todo_labels = ", ".join(f"TODO-{t['id']:04d}" for t in open_todos)
            return {
                "success": False,
                "error": (
                    f"Cannot complete epic {epic_id}: {len(open_todos)} open TODOs remain ({todo_labels}). Resolve or reassign them first."
                ),
            }

    if new_status == "abandoned":
        open_todos = _query_open_todos(db, epic_id)
        if open_todos and not force:
            return {
                "success": False,
                "action": "confirm_orphan",
                "todo_ids": [t["id"] for t in open_todos],
            }
        if open_todos and force:
            now_orphan = datetime.now().isoformat()
            for todo in open_todos:
                db.execute(
                    "UPDATE todos SET epic_id = NULL, status = 'open', last_updated_at = ? WHERE id = ?",
                    (now_orphan, todo["id"]),
                )

    # Clear current_prs on transitions out of in_review (Req-011).
    # Placed AFTER all early-return guards (completion gate, TODO
    # constraints, confirm_orphan) to avoid dirty uncommitted writes
    # on early-return paths. This UPDATE participates in the same
    # implicit SQLite transaction as the status UPDATE below and
    # commits atomically at db.commit().
    if current == "in_review" and new_status != "completed":
        db.execute(
            "UPDATE epics SET current_prs = NULL, last_updated_at = ? WHERE epic_id = ?",
            (datetime.now().isoformat(), epic_id),
        )

    now = datetime.now().isoformat()
    if new_status in ("approved", "pending", "blocked"):
        db.execute(
            "UPDATE epics SET status = ?, claimed_by = '', claimed_at = '', last_updated_at = ? WHERE epic_id = ?",
            (new_status, now, epic_id),
        )
    else:
        db.execute(
            "UPDATE epics SET status = ?, last_updated_at = ? WHERE epic_id = ?",
            (new_status, now, epic_id),
        )
    db.commit()
    return {"success": True}


def touch_epic(db: sqlite3.Connection, epic_id: str) -> bool:
    """Update last_updated_at for an epic without changing status or creating artifacts.

    Args:
        db: SQLite database connection.
        epic_id: Epic identifier to touch.

    Returns:
        True if the epic was found and updated, False otherwise.
    """
    now = datetime.now().isoformat()
    cursor = db.execute(
        "UPDATE epics SET last_updated_at = ? WHERE epic_id = ?",
        (now, epic_id),
    )
    db.commit()
    return cursor.rowcount > 0


def update_epic_priority(db: sqlite3.Connection, epic_id: str, *, priority: int) -> None:
    """Update the priority of an existing epic.

    Args:
        db: SQLite database connection.
        epic_id: Epic identifier to update.
        priority: New priority value (0-9, lower is higher priority).

    Raises:
        SystemExit: If priority is out of range or epic not found.
    """
    if not 0 <= priority <= 9:
        print(f"Priority must be 0-9, got {priority}")
        sys.exit(1)
    now = datetime.now().isoformat()
    cursor = db.execute(
        "UPDATE epics SET priority = ?, last_updated_at = ? WHERE epic_id = ?",
        (priority, now, epic_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        print(f"Epic not found: {epic_id}")
        sys.exit(1)
