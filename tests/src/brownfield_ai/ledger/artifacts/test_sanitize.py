"""Unit tests for brownfield_ai.ledger.artifacts.sanitize."""

from __future__ import annotations

import json

from brownfield_ai.ledger.artifacts.sanitize import sanitize_content


def test_sanitize_content_redacts_aws_keys() -> None:
    """Verify AWS access key IDs are redacted in step_result content."""
    content = "Found key: AKIAIOSFODNN7EXAMPLEABCD in config"
    result = sanitize_content(content, "step_result")
    assert "[REDACTED]" in result
    assert "AKIAIOSFODNN7EXAMPLEABCD" not in result


def test_sanitize_content_redacts_email() -> None:
    """Verify email addresses are redacted in step_result content."""
    content = "Contact agent@example.com for details"
    result = sanitize_content(content, "step_result")
    assert "[REDACTED]" in result
    assert "agent@example.com" not in result


def test_sanitize_content_head_tail_truncation() -> None:
    """Verify long step_result content is truncated with head+tail."""
    long_content = "A" * 3000 + "B" * 3000
    result = sanitize_content(long_content, "step_result")
    assert "[TRUNCATED" in result
    assert result.startswith("A" * 100)
    assert result.endswith("B" * 100)


def test_sanitize_content_skips_non_sanitized_type() -> None:
    """Verify artifact types outside SANITIZED_ARTIFACT_TYPES pass through unchanged."""
    content = "User token: AKIAIOSFODNN7EXAMPLEABCD\nEmail: agent@example.com"
    result = sanitize_content(content, "plan_snapshot")
    assert result == content


def test_sanitize_content_redacts_cross_family_dissent_resolved_operator_email() -> None:
    """RVW-002 dissent-lifecycle types must redact operator PII."""
    content = '{"operator": "happyfaults@gmail.com", "resolution": "fixed"}'
    result = sanitize_content(content, "cross_family_dissent_resolved")
    assert "[REDACTED]" in result
    assert "happyfaults@gmail.com" not in result


def test_sanitize_content_redacts_cross_family_dissent_findings_email() -> None:
    """cross_family_dissent bodies pass through PII redaction."""
    content = "agent@example.com flagged the issue"
    result = sanitize_content(content, "cross_family_dissent")
    assert "[REDACTED]" in result
    assert "agent@example.com" not in result


def test_sanitize_content_redacts_bridge_unavailable_secrets() -> None:
    """bridge_unavailable bodies pass through secret redaction."""
    content = "Bridge failed: AKIAIOSFODNN7EXAMPLEABCD denied access"
    result = sanitize_content(content, "bridge_unavailable")
    assert "[REDACTED]" in result
    assert "AKIAIOSFODNN7EXAMPLEABCD" not in result


def test_sanitize_content_redacts_pre_pr_dissent_block_pii() -> None:
    """pre_pr_dissent_block bodies pass through PII redaction."""
    content = "Operator agent@example.com blocked PR"
    result = sanitize_content(content, "pre_pr_dissent_block")
    assert "[REDACTED]" in result
    assert "agent@example.com" not in result


def test_sanitize_content_preserves_json_for_oversized_dissent_body() -> None:
    # A cross_family_dissent body exceeding TRUNCATION_THRESHOLD must remain
    # parseable JSON — gemini-xhigh R2 F1 / codex-xhigh R2 F-R2-1: the
    # step_result head+tail truncation policy would corrupt the JSON, so it
    # must NOT fire for dissent-lifecycle artifact types.
    body = {
        "bridge_agent_ids": ["codex-reviewer-xhigh"],
        "findings": [
            {
                "severity": "significant",
                "description": "x" * 100,
                "rule_id": f"R{i:04d}",
                "file_path": f"f{i}.py",
                "line_range": "1-2",
            }
            for i in range(80)
        ],
        "gate_effort_tier": "xhigh",
        "step": "wave-1-quality-review",
    }
    raw = json.dumps(body)
    assert len(raw) > 5000  # exceeds TRUNCATION_THRESHOLD
    sanitized = sanitize_content(raw, "cross_family_dissent")
    parsed = json.loads(sanitized)  # must round-trip
    assert parsed["gate_effort_tier"] == "xhigh"
    assert len(parsed["findings"]) == 80


def test_sanitize_content_truncates_oversized_step_result_body() -> None:
    # step_result bodies retain the head+tail truncation policy because they
    # are free-form prose (no JSON-roundtrip contract).
    long_content = "A" * 3000 + "B" * 3000
    result = sanitize_content(long_content, "step_result")
    assert "[TRUNCATED" in result
