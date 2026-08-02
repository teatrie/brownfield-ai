"""Unit tests for brownfield_ai.ledger.epics.lifecycle.

Covers create_epic, update_status (including TODO constraints, PR gate,
in_review transitions, fast_path guard), touch_epic, release_epic,
and update_epic_priority.
"""

from __future__ import annotations

import sqlite3

import pytest

from brownfield_ai.ledger.epics.lifecycle import (
    create_epic,
    release_epic,
    touch_epic,
    update_epic_priority,
    update_status,
)
from brownfield_ai.ledger.epics.prs import get_current_prs
from tests.src.brownfield_ai.ledger.epics.helpers import insert_epic

# ---------------------------------------------------------------------------
# create_epic tests
# ---------------------------------------------------------------------------


def test_create_epic_inserts_with_backlog_default_status(make_db: sqlite3.Connection) -> None:
    """create_epic must default to 'backlog' status."""
    result = create_epic(make_db, "ACME-9001", "Test Epic")
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-9001'").fetchone()
    assert result is True
    assert row["status"] == "backlog"


def test_create_epic_accepts_explicit_status_override(make_db: sqlite3.Connection) -> None:
    """create_epic must accept a non-default initial status."""
    result = create_epic(make_db, "ACME-9002", "Pending Epic", status="pending")
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-9002'").fetchone()
    assert result is True
    assert row["status"] == "pending"


def test_create_epic_returns_false_when_epic_already_exists(make_db: sqlite3.Connection) -> None:
    """create_epic must return False (not raise) when the epic_id already exists."""
    create_epic(make_db, "ACME-9003", "First Insert")
    result = create_epic(make_db, "ACME-9003", "Duplicate Insert")
    assert result is False


def test_create_epic_rejects_invalid_status(make_db: sqlite3.Connection) -> None:
    """create_epic must raise SystemExit for an unrecognised status value."""
    with pytest.raises(SystemExit):
        create_epic(make_db, "ACME-9004", "Bad Status Epic", status="invalid_status")


# ---------------------------------------------------------------------------
# update_status — basic transition tests
# ---------------------------------------------------------------------------


def test_update_status_backlog_to_approved_with_fast_path_succeeds(
    make_db: sqlite3.Connection,
) -> None:
    """backlog -> approved with fast_path=True must succeed (Req-004)."""
    create_epic(make_db, "ACME-5001", "Fast Path Epic", status="backlog")
    result = update_status(make_db, "ACME-5001", "approved", fast_path=True)
    assert result["success"] is True


def test_update_status_backlog_to_approved_without_fast_path_is_rejected(
    make_db: sqlite3.Connection,
) -> None:
    """backlog -> approved without fast_path must raise SystemExit (Req-004)."""
    create_epic(make_db, "ACME-5002", "No Fast Path Epic", status="backlog")
    with pytest.raises(SystemExit):
        update_status(make_db, "ACME-5002", "approved")


def test_update_status_backlog_to_approved_fast_path_trusts_caller(
    make_db: sqlite3.Connection,
) -> None:
    """update_status trusts the fast_path flag; artifact check lives in the CLI wrapper."""
    create_epic(make_db, "ACME-5003", "Fast Path Trust Caller", status="backlog")
    result = update_status(make_db, "ACME-5003", "approved", fast_path=True)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# update_status — TODO constraint tests
# ---------------------------------------------------------------------------


def test_update_status_blocks_completed_when_epic_has_open_todos(
    make_db: sqlite3.Connection,
) -> None:
    """update_status must block the completed transition when open TODOs exist."""
    insert_epic(make_db, "ACME-8001", status="in_progress")
    now = "2026-01-01T00:00:00"
    make_db.execute(
        "INSERT INTO todos (title, priority, epic_id, status, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Unresolved task", 5, "ACME-8001", "open", now, now),
    )
    make_db.commit()
    result = update_status(make_db, "ACME-8001", "completed")
    assert result["success"] is False
    assert "error" in result
    assert "open TODOs" in result["error"]


def test_update_status_allows_completed_when_all_todos_are_done(
    make_db: sqlite3.Connection,
) -> None:
    """update_status must allow the completed transition when all TODOs are done."""
    insert_epic(make_db, "ACME-8002", status="in_progress")
    now = "2026-01-01T00:00:00"
    make_db.execute(
        "INSERT INTO todos (title, priority, epic_id, status, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Completed task", 5, "ACME-8002", "done", now, now),
    )
    make_db.commit()
    result = update_status(make_db, "ACME-8002", "completed")
    assert result["success"] is True


def test_update_status_allows_completed_when_epic_has_no_todos(
    make_db: sqlite3.Connection,
) -> None:
    """update_status must allow the completed transition when no TODOs exist at all."""
    insert_epic(make_db, "ACME-8003", status="in_progress")
    result = update_status(make_db, "ACME-8003", "completed")
    assert result["success"] is True


def test_update_status_abandoned_without_force_returns_confirm_orphan_action(
    make_db: sqlite3.Connection,
) -> None:
    """update_status must return confirm_orphan action when force=False and TODOs exist."""
    insert_epic(make_db, "ACME-8004", status="in_progress")
    now = "2026-01-01T00:00:00"
    make_db.execute(
        "INSERT INTO todos (title, priority, epic_id, status, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Open task", 5, "ACME-8004", "open", now, now),
    )
    make_db.commit()
    result = update_status(make_db, "ACME-8004", "abandoned", force=False)
    assert result["success"] is False
    assert result["action"] == "confirm_orphan"
    assert len(result["todo_ids"]) == 1


def test_update_status_abandoned_with_force_orphans_nondone_todos_and_retains_done(
    make_db: sqlite3.Connection,
) -> None:
    """With force=True, abandoned must orphan open TODOs but retain done TODOs' epic_id."""
    insert_epic(make_db, "ACME-8005", status="in_progress")
    now = "2026-01-01T00:00:00"
    make_db.execute(
        "INSERT INTO todos (title, priority, epic_id, status, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Open task", 5, "ACME-8005", "open", now, now),
    )
    make_db.execute(
        "INSERT INTO todos (title, priority, epic_id, status, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Done task", 5, "ACME-8005", "done", now, now),
    )
    make_db.commit()
    result = update_status(make_db, "ACME-8005", "abandoned", force=True)
    open_todo = make_db.execute("SELECT epic_id, status FROM todos WHERE title = 'Open task'").fetchone()
    done_todo = make_db.execute("SELECT epic_id, status FROM todos WHERE title = 'Done task'").fetchone()
    assert result["success"] is True
    assert open_todo["epic_id"] is None
    assert open_todo["status"] == "open"
    assert done_todo["epic_id"] == "ACME-8005"


# ---------------------------------------------------------------------------
# update_status — PR completion gate tests (Req-005)
# ---------------------------------------------------------------------------


def test_update_status_blocks_completed_when_current_prs_is_non_null(
    make_db: sqlite3.Connection,
) -> None:
    """update_status must block completed when current_prs is set (Req-005)."""
    insert_epic(make_db, "ACME-3001", status="in_progress")
    make_db.execute(
        "UPDATE epics SET current_prs = ? WHERE epic_id = ?",
        ("acme/analytics#245", "ACME-3001"),
    )
    make_db.commit()
    result = update_status(make_db, "ACME-3001", "completed")
    assert result["success"] is False
    assert "current_prs" in result.get("error", "")


def test_update_status_allows_completed_when_current_prs_is_null(
    make_db: sqlite3.Connection,
) -> None:
    """update_status must allow completed when current_prs is NULL (Req-005)."""
    insert_epic(make_db, "ACME-3002", status="in_progress")
    result = update_status(make_db, "ACME-3002", "completed")
    assert result["success"] is True


# ---------------------------------------------------------------------------
# update_status — in_review transition tests (Req-001, Req-011)
# ---------------------------------------------------------------------------


def test_update_status_clears_current_prs_on_completed_from_in_review(
    make_db: sqlite3.Connection,
) -> None:
    """Transitioning in_review -> completed after clearing PRs must leave current_prs NULL."""
    insert_epic(make_db, "ACME-2001", status="in_review", current_prs="acme/analytics#245")
    # Simulate merge: clear current_prs before completing
    make_db.execute("UPDATE epics SET current_prs = NULL WHERE epic_id = ?", ("ACME-2001",))
    make_db.commit()
    result = update_status(make_db, "ACME-2001", "completed")
    remaining_prs = get_current_prs(make_db, "ACME-2001")
    assert result["success"] is True
    assert remaining_prs is None


def test_update_status_clears_current_prs_on_backlog_from_in_review(
    make_db: sqlite3.Connection,
) -> None:
    """Transitioning in_review -> backlog must automatically clear current_prs (Req-011)."""
    insert_epic(make_db, "ACME-2002", status="in_review", current_prs="acme/analytics#999")
    result = update_status(make_db, "ACME-2002", "backlog")
    remaining_prs = get_current_prs(make_db, "ACME-2002")
    assert result["success"] is True
    assert remaining_prs is None


def test_update_status_clears_current_prs_on_abandoned_from_in_review(
    make_db: sqlite3.Connection,
) -> None:
    """Transitioning in_review -> abandoned must automatically clear current_prs (Req-011)."""
    insert_epic(make_db, "ACME-2003", status="in_review", current_prs="acme/analytics#777")
    result = update_status(make_db, "ACME-2003", "abandoned", force=True)
    remaining_prs = get_current_prs(make_db, "ACME-2003")
    assert result["success"] is True
    assert remaining_prs is None


# ---------------------------------------------------------------------------
# touch_epic tests
# ---------------------------------------------------------------------------


def test_touch_epic_returns_true_for_existing_epic(make_db: sqlite3.Connection) -> None:
    """touch_epic must return True when the epic exists."""
    insert_epic(make_db, "ACME-T001", status="in_progress")
    result = touch_epic(make_db, "ACME-T001")
    assert result is True


def test_touch_epic_returns_false_for_nonexistent_epic(make_db: sqlite3.Connection) -> None:
    """touch_epic must return False when the epic does not exist."""
    result = touch_epic(make_db, "NONEXISTENT-001")
    assert result is False


def test_touch_epic_updates_last_updated_at(make_db: sqlite3.Connection) -> None:
    """touch_epic must update last_updated_at without changing status."""
    insert_epic(make_db, "ACME-T002", status="pending")
    before = make_db.execute("SELECT last_updated_at, status FROM epics WHERE epic_id = 'ACME-T002'").fetchone()
    touch_epic(make_db, "ACME-T002")
    after = make_db.execute("SELECT last_updated_at, status FROM epics WHERE epic_id = 'ACME-T002'").fetchone()
    assert after["last_updated_at"] >= before["last_updated_at"]
    assert after["status"] == "pending"


# ---------------------------------------------------------------------------
# release_epic tests
# ---------------------------------------------------------------------------


def test_release_epic_returns_true_for_in_progress_epic(make_db: sqlite3.Connection) -> None:
    """release_epic must return True when the epic is in_progress."""
    insert_epic(
        make_db,
        "ACME-R001",
        status="in_progress",
        claimed_by="agent-1",
        claimed_at="2026-01-01T00:00:00",
    )
    result = release_epic(make_db, "ACME-R001")
    assert result is True


def test_release_epic_transitions_to_approved(make_db: sqlite3.Connection) -> None:
    """release_epic must set the status back to 'approved'."""
    insert_epic(
        make_db,
        "ACME-R002",
        status="in_progress",
        claimed_by="agent-1",
        claimed_at="2026-01-01T00:00:00",
    )
    release_epic(make_db, "ACME-R002")
    row = make_db.execute("SELECT status, claimed_by, claimed_at FROM epics WHERE epic_id = 'ACME-R002'").fetchone()
    assert row["status"] == "approved"
    assert row["claimed_by"] == ""
    assert row["claimed_at"] == ""


def test_release_epic_returns_false_for_non_in_progress_epic(
    make_db: sqlite3.Connection,
) -> None:
    """release_epic must return False when the epic is not in_progress."""
    insert_epic(make_db, "ACME-R003", status="approved")
    result = release_epic(make_db, "ACME-R003")
    assert result is False


def test_release_epic_returns_false_for_nonexistent_epic(make_db: sqlite3.Connection) -> None:
    """release_epic must return False when the epic does not exist."""
    result = release_epic(make_db, "NONEXISTENT-999")
    assert result is False


# ---------------------------------------------------------------------------
# update_epic_priority tests (migrated from Source C)
# ---------------------------------------------------------------------------


def test_valid_priority_updates_value_and_timestamp(make_db: sqlite3.Connection) -> None:
    """A valid priority update must change the stored priority and update last_updated_at."""
    insert_epic(make_db, "TEST-001", status="in_progress", priority=5)
    before = make_db.execute("SELECT last_updated_at FROM epics WHERE epic_id = 'TEST-001'").fetchone()
    before_ts = before["last_updated_at"]

    update_epic_priority(make_db, "TEST-001", priority=3)

    row = make_db.execute("SELECT priority, last_updated_at FROM epics WHERE epic_id = 'TEST-001'").fetchone()
    assert row["priority"] == 3
    assert row["last_updated_at"] >= before_ts


def test_out_of_range_priority_above_raises_system_exit(make_db: sqlite3.Connection) -> None:
    """Priority 10 is outside the 0-9 range and must trigger SystemExit."""
    insert_epic(make_db, "TEST-002", status="in_progress")
    with pytest.raises(SystemExit):
        update_epic_priority(make_db, "TEST-002", priority=10)


def test_out_of_range_priority_below_raises_system_exit(make_db: sqlite3.Connection) -> None:
    """Priority -1 is outside the 0-9 range and must trigger SystemExit."""
    insert_epic(make_db, "TEST-003", status="in_progress")
    with pytest.raises(SystemExit):
        update_epic_priority(make_db, "TEST-003", priority=-1)


def test_nonexistent_epic_raises_system_exit(make_db: sqlite3.Connection) -> None:
    """Updating priority for an epic that does not exist must trigger SystemExit."""
    with pytest.raises(SystemExit):
        update_epic_priority(make_db, "DOES-NOT-EXIST", priority=3)
