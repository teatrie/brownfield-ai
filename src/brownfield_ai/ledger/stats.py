"""Home page statistics aggregation for the ledger dashboard.

Provides SQLite-backed epic and TODO aggregate queries plus ChromaDB-backed
activity stats with client-side timestamp filtering.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import chromadb


def get_epic_stats(db: sqlite3.Connection) -> dict[str, Any]:
    """Compute epic aggregate statistics from the SQLite registry.

    Queries:
    - Status counts: SELECT status, COUNT(status) AS cnt FROM epics GROUP BY status
    - completed_24h: SELECT COUNT(epic_id) FROM epics WHERE status = 'completed' AND last_updated_at >= ?
    - created_24h: SELECT COUNT(epic_id) FROM epics WHERE created_at >= ?
    - active = in_progress + in_review count
    - total = sum of all status counts

    Args:
        db: Open SQLite connection with row_factory = sqlite3.Row.

    Returns:
        Dict with keys: by_status, active, blocked, completed_24h, created_24h, total.
    """
    cutoff_24h = (datetime.now() - timedelta(hours=24)).isoformat()

    # Status counts
    rows = db.execute("SELECT status, COUNT(status) AS cnt FROM epics GROUP BY status").fetchall()
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = row["cnt"]

    # Completed in last 24h
    completed_24h: int = db.execute(
        "SELECT COUNT(epic_id) FROM epics WHERE status = 'completed' AND last_updated_at >= ?",
        (cutoff_24h,),
    ).fetchone()[0]

    # Created in last 24h
    created_24h: int = db.execute(
        "SELECT COUNT(epic_id) FROM epics WHERE created_at >= ?",
        (cutoff_24h,),
    ).fetchone()[0]

    active = by_status.get("in_progress", 0) + by_status.get("in_review", 0)
    total = sum(by_status.values())

    return {
        "by_status": by_status,
        "active": active,
        "blocked": by_status.get("blocked", 0),
        "completed_24h": completed_24h,
        "created_24h": created_24h,
        "total": total,
    }


def get_todo_stats(db: sqlite3.Connection) -> dict[str, Any]:
    """Compute TODO aggregate statistics from the SQLite todos table.

    Queries:
    - Status counts: SELECT status, COUNT(id) AS cnt FROM todos GROUP BY status
    - by_category: SELECT COALESCE(category, 'uncategorized') AS cat, COUNT(id) AS cnt
      FROM todos WHERE status = 'open' GROUP BY cat ORDER BY cnt DESC
    - high_priority_open: SELECT COUNT(id) FROM todos WHERE status = 'open' AND priority <= 3

    Args:
        db: Open SQLite connection with row_factory = sqlite3.Row.

    Returns:
        Dict with keys: open, assigned, done, total, high_priority_open, by_category.
    """
    # Status counts
    rows = db.execute("SELECT status, COUNT(id) AS cnt FROM todos GROUP BY status").fetchall()
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = row["cnt"]

    # Open by category
    cat_rows = db.execute(
        "SELECT COALESCE(category, 'uncategorized') AS cat, COUNT(id) AS cnt "
        "FROM todos WHERE status = 'open' GROUP BY cat ORDER BY cnt DESC"
    ).fetchall()
    by_category = [{"category": row["cat"], "count": row["cnt"]} for row in cat_rows]

    # High priority open
    high_priority_open: int = db.execute("SELECT COUNT(id) FROM todos WHERE status = 'open' AND priority <= 3").fetchone()[0]

    total = sum(status_counts.values())

    return {
        "open": status_counts.get("open", 0),
        "assigned": status_counts.get("assigned", 0),
        "done": status_counts.get("done", 0),
        "total": total,
        "high_priority_open": high_priority_open,
        "by_category": by_category,
    }


def get_sqlite_stats(db: sqlite3.Connection) -> dict[str, Any]:
    """Run both SQLite stat queries sequentially on the same connection.

    Combines epic and TODO statistics in a single call to avoid
    concurrent SQLite access from separate threads (DD-4).

    Args:
        db: Open SQLite connection with row_factory = sqlite3.Row.

    Returns:
        Dict with ``epics`` and ``todos`` keys containing their
        respective aggregate statistics.
    """
    return {
        "epics": get_epic_stats(db),
        "todos": get_todo_stats(db),
    }


def get_activity_stats(collection: chromadb.Collection) -> dict[str, Any]:
    """Compute activity statistics from ChromaDB execution_ledger artifacts.

    Fetches ALL artifacts with include=["metadatas"] (no documents/embeddings)
    and performs client-side timestamp filtering using Python string comparison
    on ISO-8601 timestamp metadata. ChromaDB $gte/$lte does NOT work on strings.

    Computes: artifacts_1h, artifacts_24h, gates_24h (pass/fail counts),
    prs_created_7d, prs_merged_7d.

    Args:
        collection: The execution_ledger ChromaDB collection.

    Returns:
        Dict with activity metric keys.
    """
    now = datetime.now()
    cutoff_1h = (now - timedelta(hours=1)).isoformat()
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_7d = (now - timedelta(days=7)).isoformat()

    result = collection.get(include=["metadatas"])
    metadatas: list[Any] = result.get("metadatas") or []

    artifacts_1h = 0
    artifacts_24h = 0
    gates_pass = 0
    gates_fail = 0
    prs_created_7d = 0
    prs_merged_7d = 0

    for meta in metadatas:
        ts = meta.get("timestamp", "")
        if not ts:
            continue

        if ts >= cutoff_1h:
            artifacts_1h += 1
        if ts >= cutoff_24h:
            artifacts_24h += 1
            if meta.get("artifact_type") == "gate_verdict":
                verdict = str(meta.get("verdict", "")).lower()
                if verdict in ("green", "pass"):
                    gates_pass += 1
                elif verdict in ("fail", "red"):
                    gates_fail += 1
        if ts >= cutoff_7d:
            artifact_type = meta.get("artifact_type", "")
            if artifact_type == "pr_created":
                prs_created_7d += 1
            elif artifact_type == "pr_merged":
                prs_merged_7d += 1

    return {
        "artifacts_1h": artifacts_1h,
        "artifacts_24h": artifacts_24h,
        "gates_24h": {"pass": gates_pass, "fail": gates_fail},
        "prs_created_7d": prs_created_7d,
        "prs_merged_7d": prs_merged_7d,
    }
