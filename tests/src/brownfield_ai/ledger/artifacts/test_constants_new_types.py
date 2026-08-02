"""Unit tests for the four dissent-lifecycle artifact types (RVW-002 Req-A01).

Each new artifact type registered in ``VALID_ARTIFACT_TYPES`` must
have a one-test-per-type guard so a future deletion is caught.
"""

from __future__ import annotations

from brownfield_ai.ledger.artifacts.constants import VALID_ARTIFACT_TYPES


def test_cross_family_dissent_registered_in_valid_artifact_types() -> None:
    assert "cross_family_dissent" in VALID_ARTIFACT_TYPES


def test_cross_family_dissent_resolved_registered_in_valid_artifact_types() -> None:
    assert "cross_family_dissent_resolved" in VALID_ARTIFACT_TYPES


def test_bridge_unavailable_registered_in_valid_artifact_types() -> None:
    assert "bridge_unavailable" in VALID_ARTIFACT_TYPES


def test_pre_pr_dissent_block_registered_in_valid_artifact_types() -> None:
    assert "pre_pr_dissent_block" in VALID_ARTIFACT_TYPES
