"""Read-only query functions for the epic subsystem.

Provides paginated epic listing (``list_epics``) and full resume
context assembly (``get_resume_context``) that combines ChromaDB
artifact data with SQLite TODO state.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from brownfield_ai.ledger.epics.constants import (
    _EPICS_FILTERED_SQL,
    _EPICS_UNFILTERED_SQL,
    EPIC_LIST_DEFAULT_LIMIT,
    VALID_EPIC_STATUSES,
)


def get_resume_context(
    collection: Any,
    db: sqlite3.Connection,
    epic_id: str,
) -> dict[str, Any]:
    """Build a full resume context for an epic.

    Fetches the latest ``plan_snapshot``, all ``design_decision`` entries,
    all ``step_result`` entries, all ``wave_summary`` entries, the
    latest ``gate_verdict`` per wave, the latest ``requirement_map``,
    all ``pr_created``, ``pr_merged``, ``session_exit`` entries, all
    dissent-lifecycle entries (``cross_family_dissent``,
    ``cross_family_dissent_resolved``, ``bridge_unavailable``,
    ``pre_pr_dissent_block``), and any open TODOs associated with the
    epic. Filters ChromaDB results on ``artifact_status: active``.

    Args:
        collection: The ChromaDB collection.
        db: SQLite database connection for querying associated TODOs.
        epic_id: The epic identifier.

    Returns:
        dict: Resume context with keys for each artifact type plus
        ``open_todos`` (list of TODO dicts, empty if none).
    """
    all_results = collection.get(where={"epic_id": epic_id})

    categorized: dict[str, list[dict[str, Any]]] = {
        "plan_snapshot": [],
        "design_decision": [],
        "step_result": [],
        "wave_summary": [],
        "gate_verdict": [],
        "requirement_map": [],
        "pr_created": [],
        "pr_merged": [],
        "session_exit": [],
        "cross_family_dissent": [],
        "cross_family_dissent_resolved": [],
        "bridge_unavailable": [],
        "pre_pr_dissent_block": [],
    }

    for i, doc_id in enumerate(all_results.get("ids", [])):
        meta = all_results["metadatas"][i]
        if meta.get("artifact_status") != "active":
            continue
        atype = meta.get("artifact_type", "")
        if atype in categorized:
            categorized[atype].append({
                "id": doc_id,
                "document": all_results["documents"][i],
                "metadata": meta,
            })

    # Sort each category by ID (chronological)
    for key in categorized:
        categorized[key].sort(key=lambda x: x["id"])

    # Latest plan_snapshot only
    plan = categorized["plan_snapshot"][-1] if categorized["plan_snapshot"] else None

    # Latest gate_verdict per wave (group by wave segment in ID)
    wave_verdicts: dict[str, dict[str, Any]] = {}
    for item in categorized["gate_verdict"]:
        # ID: epic_id|timestamp|artifact_type|agent_model|wave|step
        parts = item["id"].split("|")
        wave_key = f"{parts[4]}|{parts[3]}" if len(parts) > 4 else ""
        wave_verdicts[wave_key] = item
    latest_verdicts = list(wave_verdicts.values())

    # Latest requirement_map only (supersedes previous snapshots)
    req_map = categorized["requirement_map"][-1] if categorized["requirement_map"] else None

    # Query open TODOs associated with this epic
    todo_rows = db.execute(
        "SELECT id, title, status, priority FROM todos WHERE epic_id = ? AND status != 'done' ORDER BY priority ASC",
        (epic_id,),
    ).fetchall()
    open_todos: list[dict[str, Any]] = [
        {"id": row["id"], "title": row["title"], "status": row["status"], "priority": row["priority"]} for row in todo_rows
    ]

    return {
        "plan_snapshot": plan,
        "design_decisions": categorized["design_decision"],
        "step_results": categorized["step_result"],
        "wave_summaries": categorized["wave_summary"],
        "gate_verdicts": latest_verdicts,
        "requirement_map": req_map,
        "pr_created": categorized["pr_created"],
        "pr_merged": categorized["pr_merged"],
        "session_exit": categorized["session_exit"],
        "cross_family_dissent": categorized["cross_family_dissent"],
        "cross_family_dissent_resolved": categorized["cross_family_dissent_resolved"],
        "bridge_unavailable": categorized["bridge_unavailable"],
        "pre_pr_dissent_block": categorized["pre_pr_dissent_block"],
        "open_todos": open_todos,
    }


def list_epics(
    db: sqlite3.Connection,
    status_filter: str | None = None,
    *,
    limit: int = EPIC_LIST_DEFAULT_LIMIT,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    """List all epics from the SQLite registry.

    Results are sorted by status lifecycle priority (``in_progress`` first,
    terminal states last), then by numeric ``priority ASC``.  The CASE
    expression in the filtered branch is structurally redundant (all rows
    share the same status) but kept for query-symmetry with the unfiltered
    branch.

    The ``ELSE 8`` fallback in the CASE expression is a defensive SQL
    safety net.  Invalid statuses cannot enter the table because
    ``update_epic_status`` validates against ``VALID_EPIC_STATUSES`` at
    write time; the ELSE clause guards only against hypothetical data
    corruption, not silent acceptance of unknown values.

    Args:
        db: SQLite database connection.
        status_filter: Filter by this status, or ``None`` for all.
        limit: Maximum number of epics to return (default 100).
        offset: Number of epics to skip before returning results (default 0).

    Returns:
        tuple: (list of epic row dictionaries, boolean has_more)
    """
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if status_filter is not None and status_filter not in VALID_EPIC_STATUSES:
        raise ValueError(f"status_filter must be one of {sorted(VALID_EPIC_STATUSES)}, got '{status_filter}'")

    # Fetch one extra row to detect whether more pages exist.
    fetch_limit = limit + 1

    if status_filter is not None:
        rows = db.execute(
            _EPICS_FILTERED_SQL,
            (status_filter, fetch_limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            _EPICS_UNFILTERED_SQL,
            (fetch_limit, offset),
        ).fetchall()

    has_more = len(rows) > limit
    return [dict(r) for r in rows[:limit]], has_more
