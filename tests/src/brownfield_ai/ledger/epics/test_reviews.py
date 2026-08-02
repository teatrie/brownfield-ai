"""Tests for ``brownfield_ai.ledger.epics.reviews``."""

from __future__ import annotations

import json
import sqlite3

import pytest

from brownfield_ai.ledger.epics.lifecycle import create_epic
from brownfield_ai.ledger.epics.prs import get_current_prs
from brownfield_ai.ledger.epics.reviews import check_reviews, process_reviews


def _setup_in_review_epic(
    db: sqlite3.Connection,
    epic_id: str,
    pr_refs: str,
) -> None:
    """Create an epic and transition it to in_review with given PR refs."""
    create_epic(db, epic_id, f"Epic {epic_id}", status="in_progress")
    db.execute(
        "UPDATE epics SET status = 'in_review', current_prs = ? WHERE epic_id = ?",
        (pr_refs, epic_id),
    )
    db.commit()


def test_check_reviews_returns_empty_list_when_no_in_review_epics(make_db: sqlite3.Connection) -> None:
    """No in_review epics: returns an empty JSON list."""
    create_epic(make_db, "ACME-1100", "Pending Epic", status="pending")
    create_epic(make_db, "ACME-1101", "Approved Epic", status="backlog")
    result = check_reviews(make_db)
    data = json.loads(result)
    assert data == []


def test_check_reviews_returns_in_review_epics_with_current_prs(make_db: sqlite3.Connection) -> None:
    """In_review epic with current_prs appears in output."""
    _setup_in_review_epic(make_db, "ACME-1102", "acme/analytics#245, acme/web#100")
    result = check_reviews(make_db)
    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["epic_id"] == "ACME-1102"
    assert data[0]["current_prs"] == "acme/analytics#245, acme/web#100"


def test_check_reviews_excludes_non_in_review_epics(make_db: sqlite3.Connection) -> None:
    """Only in_review epics appear; in_progress is excluded."""
    _setup_in_review_epic(make_db, "ACME-1103", "acme/analytics#300")
    create_epic(make_db, "ACME-1104", "In Progress Epic", status="in_progress")
    result = check_reviews(make_db)
    data = json.loads(result)
    epic_ids = [item["epic_id"] for item in data]
    assert "ACME-1103" in epic_ids
    assert "ACME-1104" not in epic_ids


def test_check_reviews_includes_epic_with_null_current_prs(make_db: sqlite3.Connection) -> None:
    """In_review epic with no current_prs appears with current_prs: null."""
    create_epic(make_db, "ACME-1105", "In Review No PRs", status="in_progress")
    make_db.execute(
        "UPDATE epics SET status = 'in_review', current_prs = NULL WHERE epic_id = ?",
        ("ACME-1105",),
    )
    make_db.commit()
    result = check_reviews(make_db)
    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["epic_id"] == "ACME-1105"
    assert data[0]["current_prs"] is None


def test_process_reviews_all_merged_transitions_to_completed(make_db: sqlite3.Connection) -> None:
    """All PRs MERGED with valid mergeCommit transitions to completed."""
    _setup_in_review_epic(make_db, "ACME-1200", "acme/analytics#245")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1200",
            "prs": [{"ref": "acme/analytics#245", "state": "MERGED", "reviewDecision": "APPROVED", "mergeCommit": {"oid": "abc123"}}],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1200'").fetchone()
    result = json.loads(result_str)
    assert any(item["epic_id"] == "ACME-1200" and item["new_status"] == "completed" for item in result["processed"])
    assert row["status"] == "completed"


def test_process_reviews_skips_epic_with_open_pr(make_db: sqlite3.Connection) -> None:
    """Any OPEN PR skips the entire epic."""
    _setup_in_review_epic(make_db, "ACME-1201", "acme/analytics#246")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1201",
            "prs": [{"ref": "acme/analytics#246", "state": "OPEN", "reviewDecision": None, "mergeCommit": None}],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1201'").fetchone()
    result = json.loads(result_str)
    assert any(item["epic_id"] == "ACME-1201" for item in result["skipped"])
    assert row["status"] == "in_review"


def test_process_reviews_merged_with_null_merge_commit_is_skipped(make_db: sqlite3.Connection) -> None:
    """MERGED PR with null mergeCommit is skipped (mid-merge guard)."""
    _setup_in_review_epic(make_db, "ACME-1202", "acme/analytics#247")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1202",
            "prs": [{"ref": "acme/analytics#247", "state": "MERGED", "reviewDecision": "APPROVED", "mergeCommit": None}],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1202'").fetchone()
    result = json.loads(result_str)
    assert any(item["epic_id"] == "ACME-1202" for item in result["skipped"])
    assert row["status"] == "in_review"


def test_process_reviews_changes_requested_transitions_to_backlog(make_db: sqlite3.Connection) -> None:
    """CHANGES_REQUESTED with no OPEN PRs transitions to backlog."""
    _setup_in_review_epic(make_db, "ACME-1203", "acme/analytics#248")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1203",
            "prs": [{"ref": "acme/analytics#248", "state": "CLOSED", "reviewDecision": "CHANGES_REQUESTED", "mergeCommit": None}],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1203'").fetchone()
    result = json.loads(result_str)
    assert any(item["epic_id"] == "ACME-1203" and item["new_status"] == "backlog" for item in result["processed"])
    assert row["status"] == "backlog"


def test_process_reviews_closed_pr_transitions_to_abandoned(make_db: sqlite3.Connection) -> None:
    """CLOSED PR (not merged, no OPEN) transitions to abandoned."""
    _setup_in_review_epic(make_db, "ACME-1204", "acme/analytics#249")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1204",
            "prs": [{"ref": "acme/analytics#249", "state": "CLOSED", "reviewDecision": None, "mergeCommit": None}],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1204'").fetchone()
    result = json.loads(result_str)
    assert any(item["epic_id"] == "ACME-1204" and item["new_status"] == "abandoned" for item in result["processed"])
    assert row["status"] == "abandoned"


def test_process_reviews_changes_requested_beats_closed(make_db: sqlite3.Connection) -> None:
    """CHANGES_REQUESTED + CLOSED (no OPEN) leads to backlog, not abandoned."""
    _setup_in_review_epic(make_db, "ACME-1205", "acme/analytics#250, acme/web#101")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1205",
            "prs": [
                {"ref": "acme/analytics#250", "state": "CLOSED", "reviewDecision": "CHANGES_REQUESTED", "mergeCommit": None},
                {"ref": "acme/web#101", "state": "CLOSED", "reviewDecision": None, "mergeCommit": None},
            ],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1205'").fetchone()
    result = json.loads(result_str)
    assert any(item["epic_id"] == "ACME-1205" and item["new_status"] == "backlog" for item in result["processed"])
    assert row["status"] == "backlog"


def test_process_reviews_clears_current_prs_on_completed(make_db: sqlite3.Connection) -> None:
    """current_prs is NULL after completed transition."""
    _setup_in_review_epic(make_db, "ACME-1206", "acme/analytics#251")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1206",
            "prs": [{"ref": "acme/analytics#251", "state": "MERGED", "reviewDecision": "APPROVED", "mergeCommit": {"oid": "def456"}}],
        }
    ])
    process_reviews(make_db, reviews_json)
    remaining_prs = get_current_prs(make_db, "ACME-1206")
    assert remaining_prs is None


def test_process_reviews_clears_current_prs_on_backlog(make_db: sqlite3.Connection) -> None:
    """current_prs is NULL after backlog transition."""
    _setup_in_review_epic(make_db, "ACME-1207", "acme/analytics#252")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1207",
            "prs": [{"ref": "acme/analytics#252", "state": "CLOSED", "reviewDecision": "CHANGES_REQUESTED", "mergeCommit": None}],
        }
    ])
    process_reviews(make_db, reviews_json)
    remaining_prs = get_current_prs(make_db, "ACME-1207")
    assert remaining_prs is None


def test_process_reviews_returns_prs_to_close_for_backlog(make_db: sqlite3.Connection) -> None:
    """Non-merged PRs returned in prs_to_close when transitioning to backlog."""
    _setup_in_review_epic(make_db, "ACME-1208", "acme/analytics#253")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1208",
            "prs": [{"ref": "acme/analytics#253", "state": "CLOSED", "reviewDecision": "CHANGES_REQUESTED", "mergeCommit": None}],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    result = json.loads(result_str)
    processed_item = next((item for item in result["processed"] if item["epic_id"] == "ACME-1208"), None)
    assert processed_item is not None
    assert "acme/analytics#253" in processed_item["prs_to_close"]


def test_process_reviews_multi_repo_mixed_states(make_db: sqlite3.Connection) -> None:
    """2 merged + 1 CHANGES_REQUESTED (no OPEN) goes to backlog."""
    _setup_in_review_epic(make_db, "ACME-1209", "acme/analytics#254, acme/web#102, acme/service-b#10")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-1209",
            "prs": [
                {"ref": "acme/analytics#254", "state": "MERGED", "reviewDecision": "APPROVED", "mergeCommit": {"oid": "aaa111"}},
                {"ref": "acme/web#102", "state": "MERGED", "reviewDecision": "APPROVED", "mergeCommit": {"oid": "bbb222"}},
                {"ref": "acme/service-b#10", "state": "CLOSED", "reviewDecision": "CHANGES_REQUESTED", "mergeCommit": None},
            ],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1209'").fetchone()
    result = json.loads(result_str)
    assert any(item["epic_id"] == "ACME-1209" and item["new_status"] == "backlog" for item in result["processed"])
    assert row["status"] == "backlog"


def test_process_reviews_no_in_review_epics_returns_empty(make_db: sqlite3.Connection) -> None:
    """Empty input JSON list returns empty processed and skipped."""
    result_str = process_reviews(make_db, json.dumps([]))
    result = json.loads(result_str)
    assert result["processed"] == []
    assert result["skipped"] == []


def test_process_reviews_malformed_json_raises_error(make_db: sqlite3.Connection) -> None:
    """Malformed JSON input raises ValueError."""
    _setup_in_review_epic(make_db, "ACME-1210", "acme/analytics#255")
    with pytest.raises((ValueError, SystemExit)):
        process_reviews(make_db, "not valid json {{{")
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-1210'").fetchone()
    assert row["status"] == "in_review"


def test_process_reviews_unknown_state_skips_with_unknown_reason(make_db: sqlite3.Connection) -> None:
    """UNKNOWN PR state skips with reason 'unknown_pr_state'."""
    _setup_in_review_epic(make_db, "ACME-5101", "acme/analytics#300")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-5101",
            "prs": [{"ref": "acme/analytics#300", "state": "UNKNOWN", "reviewDecision": None, "mergeCommit": None}],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-5101'").fetchone()
    result = json.loads(result_str)
    skipped_item = next((item for item in result["skipped"] if item["epic_id"] == "ACME-5101"), None)
    assert skipped_item is not None
    assert skipped_item["reason"] == "unknown_pr_state"
    assert row["status"] == "in_review"


def test_process_reviews_mixed_unknown_and_merged_skips(make_db: sqlite3.Connection) -> None:
    """UNKNOWN alongside MERGED still skips (fail-closed)."""
    _setup_in_review_epic(make_db, "ACME-5102", "acme/analytics#301, acme/web#200")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-5102",
            "prs": [
                {"ref": "acme/analytics#301", "state": "MERGED", "reviewDecision": "APPROVED", "mergeCommit": {"oid": "aaa001"}},
                {"ref": "acme/web#200", "state": "UNKNOWN", "reviewDecision": None, "mergeCommit": None},
            ],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-5102'").fetchone()
    result = json.loads(result_str)
    skipped_item = next((item for item in result["skipped"] if item["epic_id"] == "ACME-5102"), None)
    assert skipped_item is not None
    assert skipped_item["reason"] == "unknown_pr_state"
    assert row["status"] == "in_review"


def test_process_reviews_open_beats_unknown(make_db: sqlite3.Connection) -> None:
    """OPEN beats UNKNOWN — skipped with 'has_open_prs'."""
    _setup_in_review_epic(make_db, "ACME-5103", "acme/analytics#302, acme/web#201")
    reviews_json = json.dumps([
        {
            "epic_id": "ACME-5103",
            "prs": [
                {"ref": "acme/analytics#302", "state": "OPEN", "reviewDecision": None, "mergeCommit": None},
                {"ref": "acme/web#201", "state": "UNKNOWN", "reviewDecision": None, "mergeCommit": None},
            ],
        }
    ])
    result_str = process_reviews(make_db, reviews_json)
    row = make_db.execute("SELECT status FROM epics WHERE epic_id = 'ACME-5103'").fetchone()
    result = json.loads(result_str)
    skipped_item = next((item for item in result["skipped"] if item["epic_id"] == "ACME-5103"), None)
    assert skipped_item is not None
    assert skipped_item["reason"] == "has_open_prs"
    assert row["status"] == "in_review"
