"""Epic claim management with ACID safety.

Provides dependency-aware epic claiming (``claim_next``), stale-claim
auto-release, and dependency completion counting.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from brownfield_ai.ledger.epics.constants import _EPICS_CLAIM_SQL

logger = logging.getLogger(__name__)


def _count_completed_deps(db: sqlite3.Connection, dep_ids: list[str]) -> int:
    """Count how many of the given dependency epic IDs have status 'completed'."""
    placeholders = ",".join("?" for _ in dep_ids)
    sql = "".join(["SELECT COUNT(*) FROM epics WHERE epic_id IN (", placeholders, ") AND status = 'completed'"])
    count: int = db.execute(sql, dep_ids).fetchone()[0]
    return count


def _release_stale_claims(
    db: sqlite3.Connection,
    stale_cutoff: datetime,
    now: datetime,
) -> int:
    """Release all stale in_progress claims back to approved.

    Must be called within a ``BEGIN EXCLUSIVE`` transaction. Does NOT
    commit --- the caller is responsible for committing.

    Logs a WARNING for each released epic with its ``claimed_by``
    identity to aid split-brain diagnosis.

    Args:
        db: SQLite database connection (within active transaction).
        stale_cutoff: Cutoff timestamp; claims older than this are stale.
        now: Current timestamp for ``last_updated_at``.

    Returns:
        Number of stale claims released.
    """
    stale_rows = db.execute(
        "SELECT epic_id, claimed_by, last_updated_at FROM epics"
        " WHERE status = 'in_progress'"
        " AND last_updated_at < ?"
        " AND last_updated_at != ''",
        (stale_cutoff.isoformat(),),
    ).fetchall()

    for row in stale_rows:
        logger.warning(
            "Auto-releasing stale epic %s (claimed_by=%s, last_updated_at=%s, stale_cutoff=%s).",
            row["epic_id"],
            row["claimed_by"],
            row["last_updated_at"],
            stale_cutoff.isoformat(),
        )
        db.execute(
            "UPDATE epics"
            " SET status = 'approved', claimed_by = '',"
            " claimed_at = '', last_updated_at = ?"
            " WHERE epic_id = ? AND status = 'in_progress'",
            (now.isoformat(), row["epic_id"]),
        )

    return len(stale_rows)


def claim_next(
    db: sqlite3.Connection,
    claimed_by: str,
    stale_hours: int,
) -> dict[str, Any] | None:
    """Claim the next eligible epic for execution with ACID safety.

    Auto-releases stale claims before scanning. Uses ``BEGIN EXCLUSIVE``
    to prevent concurrent claims.

    Args:
        db: SQLite database connection.
        claimed_by: Identifier of the claiming agent.
        stale_hours: Hours after which an in-progress claim is stale.

    Returns:
        dict or None: The claimed epic row as a dictionary, or ``None``.
    """
    now = datetime.now()
    stale_cutoff = now - timedelta(hours=stale_hours)

    try:
        db.execute("BEGIN EXCLUSIVE")

        # Auto-release stale claims (with per-epic logging)
        _release_stale_claims(db, stale_cutoff, now)

        # Find eligible epics
        rows = db.execute(
            _EPICS_CLAIM_SQL,
        ).fetchall()

        for row in rows:
            # Check dependencies
            raw_deps = row["depends_on"] if row["depends_on"] else "[]"
            depends_on = json.loads(raw_deps)
            if depends_on:
                completed = _count_completed_deps(db, depends_on)
                if completed != len(depends_on):
                    continue

            # Claim this epic
            db.execute(
                "UPDATE epics SET status = 'in_progress', claimed_by = ?, claimed_at = ?, last_updated_at = ? WHERE epic_id = ?",
                (
                    claimed_by,
                    now.isoformat(),
                    now.isoformat(),
                    row["epic_id"],
                ),
            )
            db.commit()
            return dict(row)

        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
