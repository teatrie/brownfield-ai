"""CLI wrappers (thin defopt handlers) for the epic subsystem.

Each function is a CLI subcommand that wires up infrastructure (DB, ChromaDB)
and delegates to the service-layer functions in ``lifecycle``, ``claims``,
``queries``, ``reviews``, and ``prs``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import defopt

from brownfield_ai.ledger.artifacts.constants import COLLECTION_NAME
from brownfield_ai.ledger.artifacts.queries import build_and_filter
from brownfield_ai.ledger.epics.claims import claim_next
from brownfield_ai.ledger.epics.constants import EPIC_LIST_DEFAULT_LIMIT
from brownfield_ai.ledger.epics.lifecycle import (
    create_epic,
    release_epic,
    touch_epic,
    update_status,
)
from brownfield_ai.ledger.epics.prs import set_current_prs
from brownfield_ai.ledger.epics.queries import get_resume_context, list_epics
from brownfield_ai.ledger.epics.reviews import check_reviews, process_reviews
from brownfield_ai.ledger.infra import get_client, get_db


def touch(epic_id: str) -> None:
    """Touch an epic's last_updated_at timestamp (heartbeat for claim refresh).

    Args:
        epic_id: The epic identifier to touch.
    """
    db = get_db()
    result = touch_epic(db, epic_id)
    db.close()
    if result:
        print(f"Touched {epic_id}")
    else:
        print(f"Epic '{epic_id}' not found.")
        sys.exit(1)


def create(
    epic_id: str,
    *,
    title: str,
    epic_status: str = "backlog",
    priority: int = 5,
    depends_on: str = "[]",
) -> None:
    """Create a new epic in the ledger registry.

    Uses INSERT-only semantics -- returns silently if the epic already
    exists.

    Args:
        epic_id: Unique epic identifier (e.g. ``ACME-1234``).
        title: Human-readable epic title.
        epic_status: Initial lifecycle status (default ``backlog``).
        priority: Numeric priority 0-9 where 0 is highest (default 5).
        depends_on: JSON array of dependency epic IDs (default ``[]``).
    """
    db = get_db()
    inserted = create_epic(db, epic_id, title, status=epic_status, priority=priority, depends_on=depends_on)
    db.close()
    if inserted:
        print(f"Created epic {epic_id} [{epic_status}]")
    else:
        print(f"Epic {epic_id} already exists (no changes made)")


def status(epic_id: str, *, new_status: str, fast_path: bool = False) -> None:
    """Update an epic's lifecycle status.

    Enforces TODO constraints for terminal statuses. When abandoning an
    epic with open TODOs, prompts for confirmation (auto-forces in
    headless ``CI=true`` mode).

    When ``fast_path=True`` and ``new_status == 'approved'``, validates that
    at least one ``pr_changes_required`` artifact exists for the epic in
    ChromaDB before allowing the transition. This ensures the fast-path
    backlog->approved shortcut is only used after a real PR review cycle.

    Args:
        epic_id: The epic identifier.
        new_status: The target status.
        fast_path: When ``True``, permits the ``backlog -> approved`` shortcut
            and validates that a ``pr_changes_required`` artifact exists.
    """
    if fast_path and new_status != "approved":
        print(f"Warning: --fast-path has no effect for transition to '{new_status}' (only applies to backlog -> approved).")
        fast_path = False

    db = get_db()
    try:
        if fast_path and new_status == "approved":
            client = get_client()
            collection = client.get_or_create_collection(name=COLLECTION_NAME)
            artifacts = build_and_filter(collection, epic_id, "pr_changes_required")
            if not artifacts.get("ids"):
                print(
                    f"Fast-path approval blocked: no 'pr_changes_required' artifact found for {epic_id}. "
                    "A PR review cycle must have occurred before using --fast-path."
                )
                sys.exit(1)

        result = update_status(db, epic_id, new_status, fast_path=fast_path)

        if not result["success"]:
            if result.get("action") == "confirm_orphan":
                todo_ids = result["todo_ids"]
                todo_labels = ", ".join(f"TODO-{tid:04d}" for tid in todo_ids)
                print(f"WARNING: Abandoning {epic_id} will orphan {len(todo_ids)} TODOs: {todo_labels}")

                if os.environ.get("CI") == "true":
                    print("Headless mode (CI=true): auto-forcing orphan of open TODOs.")
                    result = update_status(db, epic_id, new_status, force=True)
                else:
                    answer = input("Proceed and orphan these TODOs? [y/N] ")
                    if answer.strip().lower() == "y":
                        result = update_status(db, epic_id, new_status, force=True)
                    else:
                        print("Aborted.")
                        sys.exit(1)

            elif result.get("error"):
                print(result["error"])
                sys.exit(1)

        if result["success"]:
            print(f"Updated {epic_id} to {new_status}")
    finally:
        db.close()


def next_plan(
    *,
    claimed_by: str,
    stale_hours: int = 24,
) -> None:
    """Claim the next eligible plan for execution.

    Args:
        claimed_by: Identifier of the claiming agent.
        stale_hours: Hours after which a stale claim is auto-released.
    """
    db = get_db()
    result = claim_next(db, claimed_by, stale_hours)
    db.close()
    if result is None:
        print("No plans available.")
        return
    print(json.dumps(result, indent=2))


def release(epic_id: str) -> None:
    """Release a claimed plan back to available pool.

    Args:
        epic_id: The epic identifier to release.
    """
    db = get_db()
    success = release_epic(db, epic_id)
    db.close()
    if success:
        print(f"Released {epic_id}")
    else:
        print(f"Epic '{epic_id}' not found or not in_progress.")
        sys.exit(1)


def set_prs_cli(epic_id: str, *, pr_refs: str) -> None:
    """Set current PR refs for an epic.

    Args:
        epic_id: The epic identifier.
        pr_refs: Comma-separated PR refs (owner/repo#number).
    """
    db = get_db()
    set_current_prs(db, epic_id, pr_refs)
    db.close()
    print(f"Set current_prs for {epic_id}: {pr_refs}")


def check_reviews_cli() -> None:
    """List in_review epics and their PR refs."""
    db = get_db()
    result = check_reviews(db)
    db.close()
    print(result)


def process_reviews_cli(*, reviews_file: str) -> None:
    """Process pre-fetched PR review states from a JSON file.

    Args:
        reviews_file: Path to JSON file with pre-fetched PR states.
    """
    path = Path(reviews_file)
    if not path.exists():
        print(f"Reviews file not found: {reviews_file}")
        sys.exit(1)
    reviews_json = path.read_text()
    db = get_db()
    try:
        result = process_reviews(db, reviews_json)
        print(result)
    except ValueError as exc:
        print(f"Invalid reviews JSON: {exc}")
        sys.exit(1)
    finally:
        db.close()


def index_epics(
    *,
    status_filter: str | None = None,
    verbose: bool = False,
    limit: int = EPIC_LIST_DEFAULT_LIMIT,
    offset: int = 0,
) -> None:
    """List all epics from the SQLite registry.

    Args:
        status_filter: Filter by this status, or ``None`` for all.
        verbose: If True, show all fields.
        limit: Maximum number of epics to return (default 100).
        offset: Number of epics to skip before returning results (default 0).
    """
    db = get_db()
    rows, has_more = list_epics(db, status_filter, limit=limit, offset=offset)
    db.close()
    if not rows:
        print("No epics found.")
        return
    for row in rows:
        if verbose:
            print(json.dumps(row, indent=2))
        else:
            print(f"{row['epic_id']}  [{row['status']}]  p{row['priority']}  {row.get('title', '')}")
    if has_more:
        next_offset = offset + limit
        print(f"\nShowing {limit} epics from offset {offset} (--offset {next_offset} for next page)")


def resume(epic_id: str) -> None:
    """Resume an epic by fetching full execution context.

    Includes open TODOs associated with the epic in the output.

    Args:
        epic_id: The epic identifier.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    db = get_db()
    context = get_resume_context(collection, db, epic_id)
    db.close()
    print(json.dumps(context, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    defopt.run([
        touch,
        create,
        status,
        next_plan,
        release,
        set_prs_cli,
        check_reviews_cli,
        process_reviews_cli,
        index_epics,
        resume,
    ])
