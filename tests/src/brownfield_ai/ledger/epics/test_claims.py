"""Tests for ``brownfield_ai.ledger.epics.claims``."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

import pytest

from brownfield_ai.ledger.epics.claims import _release_stale_claims, claim_next
from brownfield_ai.ledger.epics.lifecycle import create_epic


def test_release_stale_claims_releases_old_epic(make_db: sqlite3.Connection) -> None:
    """Stale in_progress epic is released back to approved."""
    create_epic(make_db, "ACME-5000", "Stale Epic", status="in_progress")
    stale_ts = (datetime.now() - timedelta(hours=25)).isoformat()
    make_db.execute(
        "UPDATE epics SET claimed_by = ?, claimed_at = ?, last_updated_at = ? WHERE epic_id = ?",
        ("ralph-1", stale_ts, stale_ts, "ACME-5000"),
    )
    make_db.commit()

    now = datetime.now()
    stale_cutoff = now - timedelta(hours=24)
    make_db.execute("BEGIN EXCLUSIVE")
    released = _release_stale_claims(make_db, stale_cutoff, now)
    make_db.commit()

    row = make_db.execute(
        "SELECT epic_id, status, claimed_by, claimed_at FROM epics WHERE epic_id = ?",
        ("ACME-5000",),
    ).fetchone()
    assert released == 1
    assert row["status"] == "approved"
    assert row["claimed_by"] == ""
    assert row["claimed_at"] == ""


def test_release_stale_claims_preserves_fresh_epic(make_db: sqlite3.Connection) -> None:
    """Fresh in_progress epic is not released."""
    create_epic(make_db, "ACME-5001", "Fresh Epic", status="in_progress")
    fresh_ts = (datetime.now() - timedelta(hours=1)).isoformat()
    make_db.execute(
        "UPDATE epics SET claimed_by = ?, claimed_at = ?, last_updated_at = ? WHERE epic_id = ?",
        ("ralph-1", fresh_ts, fresh_ts, "ACME-5001"),
    )
    make_db.commit()

    now = datetime.now()
    stale_cutoff = now - timedelta(hours=24)
    make_db.execute("BEGIN EXCLUSIVE")
    released = _release_stale_claims(make_db, stale_cutoff, now)
    make_db.commit()

    row = make_db.execute(
        "SELECT epic_id, status, claimed_by FROM epics WHERE epic_id = ?",
        ("ACME-5001",),
    ).fetchone()
    assert released == 0
    assert row["status"] == "in_progress"
    assert row["claimed_by"] == "ralph-1"


def test_release_stale_claims_logs_identity(
    make_db: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stale claim release logs the claimed_by identity for diagnosis."""
    create_epic(make_db, "ACME-5002", "Stale Logged Epic", status="in_progress")
    stale_ts = (datetime.now() - timedelta(hours=25)).isoformat()
    make_db.execute(
        "UPDATE epics SET claimed_by = ?, claimed_at = ?, last_updated_at = ? WHERE epic_id = ?",
        ("ralph-1", stale_ts, stale_ts, "ACME-5002"),
    )
    make_db.commit()

    now = datetime.now()
    stale_cutoff = now - timedelta(hours=24)
    make_db.execute("BEGIN EXCLUSIVE")
    with caplog.at_level(logging.WARNING):
        _release_stale_claims(make_db, stale_cutoff, now)
    make_db.commit()

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("ralph-1" in msg and "ACME-5002" in msg for msg in warning_messages)


def test_claim_next_auto_releases_then_claims(make_db: sqlite3.Connection) -> None:
    """claim_next auto-releases stale claims then claims the next approved epic."""
    create_epic(make_db, "ACME-5010", "Stale Claimed Epic", status="in_progress")
    stale_ts = (datetime.now() - timedelta(hours=25)).isoformat()
    make_db.execute(
        "UPDATE epics SET claimed_by = ?, claimed_at = ?, last_updated_at = ? WHERE epic_id = ?",
        ("ralph-old", stale_ts, stale_ts, "ACME-5010"),
    )
    make_db.commit()

    create_epic(make_db, "ACME-5011", "Ready Epic", status="approved")

    result = claim_next(make_db, "ralph-new", stale_hours=24)

    stale_row = make_db.execute(
        "SELECT epic_id, status, claimed_by FROM epics WHERE epic_id = ?",
        ("ACME-5010",),
    ).fetchone()
    claimed_row = make_db.execute(
        "SELECT epic_id, status FROM epics WHERE epic_id = ?",
        ("ACME-5011",),
    ).fetchone()

    assert result is not None
    assert result["epic_id"] == "ACME-5010"
    assert stale_row["status"] == "in_progress"
    assert stale_row["claimed_by"] == "ralph-new"
    assert claimed_row["status"] == "approved"


def test_release_stale_claims_handles_multiple(make_db: sqlite3.Connection) -> None:
    """Multiple stale claims are all released in a single pass."""
    stale_ts = (datetime.now() - timedelta(hours=25)).isoformat()

    create_epic(make_db, "ACME-5020", "Stale A", status="in_progress")
    make_db.execute(
        "UPDATE epics SET claimed_by = ?, claimed_at = ?, last_updated_at = ? WHERE epic_id = ?",
        ("agent-alpha", stale_ts, stale_ts, "ACME-5020"),
    )

    create_epic(make_db, "ACME-5021", "Stale B", status="in_progress")
    make_db.execute(
        "UPDATE epics SET claimed_by = ?, claimed_at = ?, last_updated_at = ? WHERE epic_id = ?",
        ("agent-beta", stale_ts, stale_ts, "ACME-5021"),
    )

    create_epic(make_db, "ACME-5022", "Approved C", status="approved")
    make_db.commit()

    now = datetime.now()
    stale_cutoff = now - timedelta(hours=24)
    make_db.execute("BEGIN EXCLUSIVE")
    released = _release_stale_claims(make_db, stale_cutoff, now)
    make_db.commit()

    row_a = make_db.execute(
        "SELECT epic_id, status, claimed_by FROM epics WHERE epic_id = ?",
        ("ACME-5020",),
    ).fetchone()
    row_b = make_db.execute(
        "SELECT epic_id, status, claimed_by FROM epics WHERE epic_id = ?",
        ("ACME-5021",),
    ).fetchone()

    assert released == 2
    assert row_a["status"] == "approved"
    assert row_a["claimed_by"] == ""
    assert row_b["status"] == "approved"
    assert row_b["claimed_by"] == ""
