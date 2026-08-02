"""Unit tests for brownfield_ai.ledger.epics.constants.

Validates the VALID_EPIC_STATUSES set, VALID_TRANSITIONS mapping, and
STATUS_PRIORITY_ORDER_SQL fragment for internal consistency and completeness.
"""

from __future__ import annotations

import re

from brownfield_ai.ledger.epics.constants import (
    STATUS_PRIORITY_ORDER_SQL,
    VALID_EPIC_STATUSES,
    VALID_TRANSITIONS,
)

# ---------------------------------------------------------------------------
# VALID_EPIC_STATUSES structural tests
# ---------------------------------------------------------------------------


def test_backlog_in_valid_epic_statuses() -> None:
    """backlog must be present in the set of valid statuses."""
    assert "backlog" in VALID_EPIC_STATUSES


def test_in_review_in_valid_epic_statuses() -> None:
    """in_review must be present in the set of valid statuses (Req-001)."""
    assert "in_review" in VALID_EPIC_STATUSES


def test_completed_in_valid_epic_statuses() -> None:
    """completed must be present as a terminal status."""
    assert "completed" in VALID_EPIC_STATUSES


def test_abandoned_in_valid_epic_statuses() -> None:
    """abandoned must be present as a terminal status."""
    assert "abandoned" in VALID_EPIC_STATUSES


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS structural tests
# ---------------------------------------------------------------------------


def test_valid_transitions_keys_are_valid_statuses() -> None:
    """Every key in VALID_TRANSITIONS must be a member of VALID_EPIC_STATUSES."""
    for status in VALID_TRANSITIONS:
        assert status in VALID_EPIC_STATUSES, f"Transition source '{status}' is not in VALID_EPIC_STATUSES"


def test_valid_transitions_values_are_valid_statuses() -> None:
    """Every target status listed in VALID_TRANSITIONS must be in VALID_EPIC_STATUSES."""
    for source, targets in VALID_TRANSITIONS.items():
        for target in targets:
            assert target in VALID_EPIC_STATUSES, f"Transition target '{target}' from '{source}' is not in VALID_EPIC_STATUSES"


def test_valid_transitions_no_self_transition() -> None:
    """No status should list itself as a valid transition target."""
    for status, targets in VALID_TRANSITIONS.items():
        assert status not in targets, f"Status '{status}' lists itself as a valid transition target"


def test_valid_transitions_completed_is_terminal() -> None:
    """completed must not appear as a key in VALID_TRANSITIONS (it is terminal)."""
    assert "completed" not in VALID_TRANSITIONS


def test_valid_transitions_abandoned_is_terminal() -> None:
    """abandoned must not appear as a key in VALID_TRANSITIONS (it is terminal)."""
    assert "abandoned" not in VALID_TRANSITIONS


def test_valid_transitions_completeness() -> None:
    """Core lifecycle transitions must be present for critical paths."""
    assert "pending" in VALID_TRANSITIONS
    assert "approved" in VALID_TRANSITIONS
    assert "in_progress" in VALID_TRANSITIONS
    assert "approved" in VALID_TRANSITIONS["pending"]
    assert "in_progress" in VALID_TRANSITIONS["approved"]
    assert "completed" in VALID_TRANSITIONS["in_progress"]
    assert "abandoned" in VALID_TRANSITIONS["in_progress"]


def test_backlog_to_pending_transition_is_allowed() -> None:
    """backlog -> pending must be a valid transition."""
    assert "pending" in VALID_TRANSITIONS["backlog"]


def test_backlog_to_approved_in_valid_transitions() -> None:
    """backlog -> approved must be present for the fast-path (Req-004)."""
    assert "approved" in VALID_TRANSITIONS["backlog"]


def test_no_existing_status_transitions_to_backlog_except_in_review() -> None:
    """Only in_review may transition back to backlog; all other statuses must not."""
    for status, targets in VALID_TRANSITIONS.items():
        if status == "in_review":
            continue
        assert "backlog" not in targets, f"Status '{status}' should not be able to transition to 'backlog'"


def test_in_progress_to_in_review_transition_is_valid() -> None:
    """in_progress -> in_review must be a valid transition (Req-001)."""
    assert "in_review" in VALID_TRANSITIONS["in_progress"]


def test_in_review_to_completed_transition_is_valid() -> None:
    """in_review -> completed must be a valid transition."""
    assert "completed" in VALID_TRANSITIONS["in_review"]


def test_in_review_to_backlog_transition_is_valid() -> None:
    """in_review -> backlog must be valid (revert / changes requested path)."""
    assert "backlog" in VALID_TRANSITIONS["in_review"]


def test_in_review_to_abandoned_transition_is_valid() -> None:
    """in_review -> abandoned must be a valid transition."""
    assert "abandoned" in VALID_TRANSITIONS["in_review"]


def test_in_review_self_transition_is_blocked() -> None:
    """in_review -> in_review must not be allowed (no self-transitions)."""
    assert "in_review" not in VALID_TRANSITIONS.get("in_review", [])


def test_in_review_to_in_progress_is_blocked() -> None:
    """in_review -> in_progress must not be allowed (cannot revert to in_progress)."""
    assert "in_progress" not in VALID_TRANSITIONS.get("in_review", [])


# ---------------------------------------------------------------------------
# STATUS_PRIORITY_ORDER_SQL structural tests
# ---------------------------------------------------------------------------


def test_status_priority_order_sql_includes_in_review() -> None:
    """STATUS_PRIORITY_ORDER_SQL must include a WHEN clause for 'in_review'."""
    assert "'in_review'" in STATUS_PRIORITY_ORDER_SQL


def test_status_priority_sql_covers_all_statuses() -> None:
    """Every status in VALID_EPIC_STATUSES must appear in STATUS_PRIORITY_ORDER_SQL.

    Guards the coupling between the SQL ordering fragment and the canonical
    status set so that new statuses are never silently assigned ELSE 8.
    """
    statuses_in_sql = set(re.findall(r"WHEN\s+'([^']+)'", STATUS_PRIORITY_ORDER_SQL))
    assert statuses_in_sql == VALID_EPIC_STATUSES, f"Mismatch: SQL has {statuses_in_sql}, VALID_EPIC_STATUSES has {VALID_EPIC_STATUSES}"
