"""Docs-structure tests for the dissent-lifecycle artifact appendix (RVW-002 Req-A02 / Req-A04).

Asserts that ``docs/verification_protocol.md`` documents each of the four
new artifact types with both a body-schema table AND a parseable example
body JSON containing the required fields named in the table.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.orchestrator.envelope_parser import Finding

REPO_ROOT = Path(__file__).resolve().parents[2]
APPENDIX_PATH = REPO_ROOT / "docs" / "verification_protocol.md"

# (artifact_type_name, required_field_names_in_documented_order)
ARTIFACT_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cross_family_dissent", ("bridge_agent_ids", "findings", "gate_effort_tier", "step")),
    (
        "cross_family_dissent_resolved",
        ("parent_id", "resolution", "operator", "rationale"),
    ),
    (
        "bridge_unavailable",
        ("agent_id", "agent_family", "reason", "step", "gate_effort_tier"),
    ),
    (
        "pre_pr_dissent_block",
        ("parent_id", "gate_effort_tier", "pr_target_branch", "block_reason"),
    ),
)


def _appendix_text() -> str:
    """Read the verification_protocol.md file contents."""
    return APPENDIX_PATH.read_text(encoding="utf-8")


def _example_body_block(artifact_type: str, text: str) -> str:
    """Extract the first ```json fenced block under the artifact_type heading.

    Heading format is ``#### `artifact_type``` followed by prose then a
    ``json`` fenced code block. Returns the JSON body string.
    """
    heading_pattern = re.compile(
        rf"^####\s+`{re.escape(artifact_type)}`\s*$",
        re.MULTILINE,
    )
    heading_match = heading_pattern.search(text)
    if heading_match is None:
        pytest.fail(f"Heading for artifact type {artifact_type!r} not found in appendix")
    next_heading = re.search(r"^####\s+", text[heading_match.end() :], re.MULTILINE)
    section_end = heading_match.end() + next_heading.start() if next_heading else len(text)
    section = text[heading_match.end() : section_end]
    json_block = re.search(r"```json\s*\n(.*?)\n```", section, re.DOTALL)
    if json_block is None:
        pytest.fail(f"Example JSON block for {artifact_type!r} not found")
    return json_block.group(1)


@pytest.mark.parametrize(("artifact_type", "required_fields"), ARTIFACT_SPECS)
def test_body_schema_field_names_present_in_appendix(artifact_type: str, required_fields: tuple[str, ...]) -> None:
    text = _appendix_text()
    assert f"`{artifact_type}`" in text, f"Artifact type {artifact_type!r} not referenced in docs"
    for field in required_fields:
        assert f"`{field}`" in text, f"Field {field!r} not documented for artifact type {artifact_type!r}"


@pytest.mark.parametrize(("artifact_type", "required_fields"), ARTIFACT_SPECS)
def test_example_body_parses_and_carries_required_fields(artifact_type: str, required_fields: tuple[str, ...]) -> None:
    text = _appendix_text()
    body_json = _example_body_block(artifact_type, text)
    body = json.loads(body_json)
    assert isinstance(body, dict), f"Example body for {artifact_type!r} must be a JSON object"
    for field in required_fields:
        assert field in body, f"Example body for {artifact_type!r} missing required field {field!r}"


def test_cross_family_dissent_findings_round_trip_through_finding_dataclass() -> None:
    text = _appendix_text()
    body_json = _example_body_block("cross_family_dissent", text)
    body = json.loads(body_json)
    findings = body["findings"]
    assert findings, "cross_family_dissent example body must contain at least one finding"
    for finding_dict in findings:
        Finding(**finding_dict)
