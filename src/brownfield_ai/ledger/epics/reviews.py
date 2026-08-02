"""PR review processing for epics.

Provides functions to check which epics are in review and to process
pre-fetched PR review states, transitioning epics according to the
review state machine (OPEN/MERGED/CHANGES_REQUESTED/CLOSED).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from typing import Any

from brownfield_ai.ledger.epics.lifecycle import update_status


def check_reviews(db: sqlite3.Connection) -> str:
    """Return JSON list of in_review epics with their current_prs.

    Args:
        db: SQLite database connection.

    Returns:
        JSON string: list of dicts with epic_id and current_prs.
    """
    rows = db.execute("SELECT epic_id, current_prs FROM epics WHERE status = 'in_review'").fetchall()
    return json.dumps([{"epic_id": r["epic_id"], "current_prs": r["current_prs"]} for r in rows])


def process_reviews(db: sqlite3.Connection, reviews_json: str) -> str:
    """Process pre-fetched PR review states and transition epics accordingly.

    Parses a JSON list of epic PR states and applies the review state machine:
    - OPEN PRs: skip entire epic.
    - All MERGED with valid mergeCommit: transition to completed.
    - CHANGES_REQUESTED (no OPEN): transition to backlog (beats CLOSED).
    - CLOSED (not merged, no OPEN, no CHANGES_REQUESTED): transition to abandoned.

    Args:
        db: SQLite database connection.
        reviews_json: JSON string with pre-fetched PR states per epic.

    Returns:
        JSON string with processed and skipped epic results.

    Raises:
        ValueError: If reviews_json is malformed JSON.
    """
    try:
        entries = json.loads(reviews_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed reviews_json: {exc}") from exc

    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for entry in entries:
        try:
            epic_id = entry["epic_id"]
            prs = entry.get("prs", [])

            # Priority 1: any OPEN PR -> skip
            if any(pr["state"] == "OPEN" for pr in prs):
                skipped.append({"epic_id": epic_id, "reason": "has_open_prs"})
                continue

            # Priority 1.5: any UNKNOWN PR -> skip (transient gh failure)
            unknown_refs = [pr["ref"] for pr in prs if pr.get("state") == "UNKNOWN"]
            if unknown_refs:
                for ref in unknown_refs:
                    print(
                        f"WARNING: PR {ref} returned UNKNOWN state -- possible transient gh failure",
                        file=sys.stderr,
                    )
                skipped.append({"epic_id": epic_id, "reason": "unknown_pr_state"})
                continue

            has_changes_requested = any(pr.get("reviewDecision") == "CHANGES_REQUESTED" for pr in prs)
            has_closed = any(pr["state"] == "CLOSED" for pr in prs)
            all_merged = all(pr["state"] == "MERGED" for pr in prs) if prs else False

            if all_merged:
                # Mid-merge guard: skip if any mergeCommit is None
                if any(pr.get("mergeCommit") is None for pr in prs):
                    skipped.append({"epic_id": epic_id, "reason": "mid_merge_processing"})
                    continue
                # Atomic clear + complete: write current_prs=NULL without
                # committing, then let update_status commit both changes together.
                # If update_status returns failure (e.g. open TODOs), rollback
                # the pending clear so the epic is not stranded with NULL prs.
                db.execute(
                    "UPDATE epics SET current_prs = NULL, last_updated_at = ? WHERE epic_id = ?",
                    (datetime.now().isoformat(), epic_id),
                )
                result = update_status(db, epic_id, "completed")
                if not result["success"]:
                    db.rollback()
                    skipped.append({"epic_id": epic_id, "reason": result.get("error", "update_failed")})
                    continue
                # update_status committed both the clear and the status change
                processed.append({"epic_id": epic_id, "new_status": "completed", "prs_to_close": []})
                continue

            # Priority 2: CHANGES_REQUESTED beats CLOSED
            # Note: update_status auto-clears current_prs for non-completed
            # transitions out of in_review (Req-011), so no explicit
            # clear_current_prs call is needed here.
            if has_changes_requested:
                non_merged_refs = [pr["ref"] for pr in prs if pr["state"] != "MERGED"]
                result = update_status(db, epic_id, "backlog")
                if not result["success"]:
                    skipped.append({"epic_id": epic_id, "reason": result.get("error", "update_failed")})
                    continue
                processed.append({"epic_id": epic_id, "new_status": "backlog", "prs_to_close": non_merged_refs})
                continue

            if has_closed:
                non_merged_refs = [pr["ref"] for pr in prs if pr["state"] != "MERGED"]
                result = update_status(db, epic_id, "abandoned", force=True)
                if not result["success"]:
                    skipped.append({"epic_id": epic_id, "reason": result.get("error", "update_failed")})
                    continue
                processed.append({"epic_id": epic_id, "new_status": "abandoned", "prs_to_close": non_merged_refs})
                continue

            # No actionable state -- skip
            skipped.append({"epic_id": epic_id, "reason": "no_terminal_state"})

        except (KeyError, TypeError):
            skipped.append({"epic_id": entry.get("epic_id", "<unknown>"), "reason": "malformed_entry"})
        except SystemExit:
            db.rollback()
            skipped.append({"epic_id": entry.get("epic_id", "<unknown>"), "reason": "invalid_transition"})

    return json.dumps({"processed": processed, "skipped": skipped})
