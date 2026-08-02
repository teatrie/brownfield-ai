"""Unit tests for brownfield_ai.ledger.artifacts.builders."""

from __future__ import annotations

import pytest

from brownfield_ai.ledger.artifacts.builders import (
    build_metadata,
    generate_id,
    validate_artifact_type,
)
from brownfield_ai.ledger.artifacts.constants import VALID_ARTIFACT_TYPES


def test_generate_id_format() -> None:
    """Verify generate_id produces the expected pipe-delimited format."""
    fields = {
        "epic_id": "ACME-1234",
        "timestamp": "2026-01-01T00:00:00",
        "artifact_type": "plan_snapshot",
        "agent_model": "claude-opus-4",
        "wave": "1",
        "step": "design",
    }
    result = generate_id(fields)
    assert result == "ACME-1234|2026-01-01T00:00:00|plan_snapshot|claude-opus-4|1|design"


def test_generate_id_sanitizes_pipes() -> None:
    """Verify pipe characters in field values are replaced with hyphens."""
    fields = {
        "epic_id": "ACME|BAD",
        "timestamp": "2026-01-01T00:00:00",
        "artifact_type": "step_result",
        "agent_model": "gpt-4",
        "wave": "2",
        "step": "run",
    }
    result = generate_id(fields)
    parts = result.split("|")
    assert parts[0] == "ACME-BAD"


def test_validate_artifact_type_rejects_invalid() -> None:
    """Verify SystemExit is raised for unrecognized artifact types."""
    with pytest.raises(SystemExit):
        validate_artifact_type("not_a_valid_type")


def test_validate_artifact_type_accepts_valid() -> None:
    """Verify all members of VALID_ARTIFACT_TYPES are accepted."""
    for artifact_type in VALID_ARTIFACT_TYPES:
        validate_artifact_type(artifact_type)


def test_build_metadata_defaults_empty_strings() -> None:
    """Verify missing metadata fields default to empty strings."""
    result = build_metadata({"epic_id": "ACME-0001", "artifact_type": "gate_verdict"})
    assert result["epic_id"] == "ACME-0001"
    assert result["artifact_type"] == "gate_verdict"
    assert result["wave"] == ""
    assert result["domain"] == ""
    assert result["step"] == ""
    assert result["agent_role"] == ""
    assert result["agent_model"] == ""
    assert result["verdict"] == ""
    assert result["parent_id"] == ""
    assert result["epic_status"] == ""
    assert result["artifact_status"] == ""
    assert result["sub_plans"] == ""


def test_build_metadata_preserves_sub_plans_when_provided() -> None:
    """Verify sub_plans field is preserved when explicitly set."""
    result = build_metadata({
        "epic_id": "ACME-0001",
        "artifact_type": "plan_snapshot",
        "sub_plans": "A:0,1|B:2",
    })
    assert result["sub_plans"] == "A:0,1|B:2"
