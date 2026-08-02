"""Unit tests for brownfield_ai.ledger.epics.prs.

Covers set_current_prs, get_current_prs, and clear_current_prs including
format validation, canonical storage, empty-string clearing, and
multi-ref handling.
"""

from __future__ import annotations

import sqlite3

import pytest

from brownfield_ai.ledger.epics.prs import clear_current_prs, get_current_prs, set_current_prs
from tests.src.brownfield_ai.ledger.epics.helpers import insert_epic

# ---------------------------------------------------------------------------
# set_current_prs tests
# ---------------------------------------------------------------------------


def test_set_current_prs_stores_value(make_db: sqlite3.Connection) -> None:
    """set_current_prs must persist a valid single PR ref."""
    insert_epic(make_db, "ACME-4001", status="in_progress")
    set_current_prs(make_db, "ACME-4001", "acme/analytics#245")
    value = get_current_prs(make_db, "ACME-4001")
    assert value == "acme/analytics#245"


def test_set_current_prs_accepts_valid_multi_ref(make_db: sqlite3.Connection) -> None:
    """set_current_prs must store a comma-separated list of valid PR refs."""
    insert_epic(make_db, "ACME-4007", status="in_progress")
    set_current_prs(make_db, "ACME-4007", "acme/analytics#245, acme/web#100")
    value = get_current_prs(make_db, "ACME-4007")
    assert value == "acme/analytics#245, acme/web#100"


def test_set_current_prs_rejects_malformed_ref_no_slash(make_db: sqlite3.Connection) -> None:
    """A PR ref with no slash must trigger SystemExit."""
    insert_epic(make_db, "ACME-4004", status="in_progress")
    with pytest.raises(SystemExit):
        set_current_prs(make_db, "ACME-4004", "bad-ref")


def test_set_current_prs_rejects_malformed_ref_no_hash(make_db: sqlite3.Connection) -> None:
    """A PR ref with a slash but no '#' must trigger SystemExit."""
    insert_epic(make_db, "ACME-4005", status="in_progress")
    with pytest.raises(SystemExit):
        set_current_prs(make_db, "ACME-4005", "no/hash")


def test_set_current_prs_rejects_malformed_ref_no_pr_number(make_db: sqlite3.Connection) -> None:
    """A PR ref with owner/repo but no number must trigger SystemExit."""
    insert_epic(make_db, "ACME-4006", status="in_progress")
    with pytest.raises(SystemExit):
        set_current_prs(make_db, "ACME-4006", "acme/repo")


def test_set_current_prs_stores_canonicalized_form(make_db: sqlite3.Connection) -> None:
    """Input without space after comma must be stored with canonical ', ' separator (Req-009)."""
    insert_epic(make_db, "ACME-5201", status="in_progress")
    set_current_prs(make_db, "ACME-5201", "acme/analytics#245,acme/web#100")
    value = get_current_prs(make_db, "ACME-5201")
    assert value == "acme/analytics#245, acme/web#100", f"Expected canonicalized form with ', ' separator, got '{value}'"


def test_set_current_prs_canonicalizes_extra_spaces(make_db: sqlite3.Connection) -> None:
    """Input with extra whitespace around commas must be stored canonically (Req-009)."""
    insert_epic(make_db, "ACME-5202", status="in_progress")
    set_current_prs(make_db, "ACME-5202", "acme/analytics#245 ,  acme/web#100")
    value = get_current_prs(make_db, "ACME-5202")
    assert value == "acme/analytics#245, acme/web#100", f"Expected canonicalized form with ', ' separator, got '{value}'"


def test_set_current_prs_empty_string_clears_prs(make_db: sqlite3.Connection) -> None:
    """Passing an empty string to set_current_prs must set current_prs to NULL (Req-011)."""
    insert_epic(make_db, "ACME-5301", status="in_progress")
    set_current_prs(make_db, "ACME-5301", "acme/analytics#245")
    set_current_prs(make_db, "ACME-5301", "")
    value = get_current_prs(make_db, "ACME-5301")
    assert value is None, f"Expected None after set_current_prs with empty string, got '{value}'"


def test_set_current_prs_whitespace_only_clears_prs(make_db: sqlite3.Connection) -> None:
    """Passing a whitespace-only string to set_current_prs must set current_prs to NULL (Req-011)."""
    insert_epic(make_db, "ACME-5302", status="in_progress")
    set_current_prs(make_db, "ACME-5302", "   ")
    value = get_current_prs(make_db, "ACME-5302")
    assert value is None, f"Expected None after set_current_prs with whitespace-only string, got '{value}'"


# ---------------------------------------------------------------------------
# get_current_prs tests
# ---------------------------------------------------------------------------


def test_get_current_prs_retrieves_stored_value(make_db: sqlite3.Connection) -> None:
    """get_current_prs must return the exact value stored by set_current_prs."""
    insert_epic(make_db, "ACME-4002", status="in_progress")
    set_current_prs(make_db, "ACME-4002", "acme/web#100")
    result = get_current_prs(make_db, "ACME-4002")
    assert result == "acme/web#100"


def test_get_current_prs_returns_none_when_not_set(make_db: sqlite3.Connection) -> None:
    """get_current_prs must return None for an epic where current_prs was never set."""
    insert_epic(make_db, "ACME-4010", status="in_progress")
    result = get_current_prs(make_db, "ACME-4010")
    assert result is None


def test_get_current_prs_returns_none_for_missing_epic(make_db: sqlite3.Connection) -> None:
    """get_current_prs must return None when the epic does not exist."""
    result = get_current_prs(make_db, "NONEXISTENT-999")
    assert result is None


# ---------------------------------------------------------------------------
# clear_current_prs tests
# ---------------------------------------------------------------------------


def test_clear_current_prs_sets_value_to_null(make_db: sqlite3.Connection) -> None:
    """clear_current_prs must set current_prs to NULL."""
    insert_epic(make_db, "ACME-4003", status="in_progress")
    set_current_prs(make_db, "ACME-4003", "acme/analytics#245")
    clear_current_prs(make_db, "ACME-4003")
    value = get_current_prs(make_db, "ACME-4003")
    assert value is None


def test_clear_current_prs_on_already_null_is_idempotent(make_db: sqlite3.Connection) -> None:
    """clear_current_prs on an epic with no PRs must not raise and leave current_prs NULL."""
    insert_epic(make_db, "ACME-4011", status="in_progress")
    clear_current_prs(make_db, "ACME-4011")
    value = get_current_prs(make_db, "ACME-4011")
    assert value is None
