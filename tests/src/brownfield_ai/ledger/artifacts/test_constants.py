"""Unit tests for brownfield_ai.ledger.artifacts.constants."""

from __future__ import annotations

from brownfield_ai.ledger.artifacts.constants import VALID_ARTIFACT_TYPES


def test_todo_linked_in_valid_artifact_types() -> None:
    """Verify todo_linked is a recognized artifact type."""
    assert "todo_linked" in VALID_ARTIFACT_TYPES


def test_ci_resolution_in_valid_artifact_types() -> None:
    """Verify ci_resolution is a recognized artifact type."""
    assert "ci_resolution" in VALID_ARTIFACT_TYPES


def test_pr_changes_required_in_valid_artifact_types() -> None:
    """Verify pr_changes_required is a recognized artifact type."""
    assert "pr_changes_required" in VALID_ARTIFACT_TYPES
