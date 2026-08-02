"""Unit tests for the Reviewer Output Envelope circuit-breaker.

Epic: REVIEWER-ENVELOPE-001 (Wave 4 RED phase).

The circuit-breaker under test lives at
``scripts/orchestrator/envelope_circuit_breaker.py``. The W4 RED
phase ships only the dataclass + function stubs; bodies raise
NotImplementedError until the GREEN phase lands the lifecycle
logic per plan §7 (lines 934-1032).

Every test docstring cites at least one Req-ID or resolution
marker per the W1/W2/W3 RED-phase precedent (CLAUDE.md §13
traceability mandate).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.orchestrator.envelope_circuit_breaker import (
    CircuitBreakerState,
    from_ledger_artifact,
    record_parse_failure,
    record_parse_success,
    redact_output_excerpt,
    to_ledger_artifact,
)

# ---------------------------------------------------------------------------
# Counter / trip semantics
# ---------------------------------------------------------------------------


def test_two_consecutive_failures_trips() -> None:
    """[Req-016] N=2 consecutive parse failures on the same agent_family trips the breaker.

    Post-trip:
    - codex-bridge appears in tripped_families.
    - codex-bridge appears in cb_legacy_fallback_families (G-3 R2).
    - orchestrator_tier promoted to high (sticky per Req-017).
    """
    state = CircuitBreakerState(epic_id="EPIC-CB-001")
    after_first = record_parse_failure(state, "codex-bridge")
    assert "codex-bridge" not in after_first.tripped_families
    assert after_first.orchestrator_tier == "medium"
    after_second = record_parse_failure(after_first, "codex-bridge")
    assert "codex-bridge" in after_second.tripped_families
    assert "codex-bridge" in after_second.cb_legacy_fallback_families
    assert after_second.orchestrator_tier == "high"


def test_state_round_trips_through_ledger() -> None:
    """[Req-016 / §7.2] Serializing and parsing a state through the ledger artifact preserves shape.

    The ledger artifact body shape is the §7.2 schema_version=2
    contract (lines 960-973). A JSON round-trip through
    to_ledger_artifact / from_ledger_artifact must be lossless for
    every field used by the lifecycle logic.
    """
    state = CircuitBreakerState(
        epic_id="EPIC-CB-002",
        failure_counts={"codex-bridge": 1, "gemini-bridge": 0},
        tripped_families=frozenset({"codex-bridge"}),
        cb_legacy_fallback_families=frozenset({"codex-bridge"}),
        orchestrator_tier="high",
        last_updated_at="2026-04-30T12:00:00Z",
        schema_version=2,
    )
    artifact = to_ledger_artifact(state)
    # Body must be JSON-serializable for the ledger writer.
    json_text = json.dumps(artifact)
    parsed = json.loads(json_text)
    restored = from_ledger_artifact(parsed)
    assert restored == state
    assert parsed["schema_version"] == 2


def test_tripped_family_added_to_legacy_fallback() -> None:
    """[G-3 R2] On N=2 trip, the family is added to cb_legacy_fallback_families.

    This is the spin-loop guard: subsequent envelope-absence on
    that family no longer increments the CB counter (the parser
    treats it as legacy fallback per envelope_parser._current_migrated_families).
    """
    state = CircuitBreakerState(epic_id="EPIC-CB-003")
    state = record_parse_failure(state, "gemini-bridge")
    state = record_parse_failure(state, "gemini-bridge")
    assert "gemini-bridge" in state.cb_legacy_fallback_families


def test_post_trip_envelope_absence_no_further_increment() -> None:
    """[G-3 R2] After a family is in cb_legacy_fallback_families, the parser falls back without incrementing.

    The parser side already verifies this in W1 tests; this CB
    side verifies that if the orchestrator nevertheless calls
    record_parse_failure again on a tripped family, the failure
    counter does NOT continue to grow indefinitely. Either the
    counter caps at N (no further increment past the trip
    threshold) or it stays reset - GREEN selects the policy. The
    assertion here pins the high-level invariant: a third
    consecutive call on a tripped family does NOT promote the
    state into a new degenerate regime (e.g., counter=1000 with
    runaway tier).
    """
    state = CircuitBreakerState(epic_id="EPIC-CB-004")
    state = record_parse_failure(state, "codex-bridge")
    state = record_parse_failure(state, "codex-bridge")
    third = record_parse_failure(state, "codex-bridge")
    # tier is sticky high
    assert third.orchestrator_tier == "high"
    # tripped_families is monotonic; codex-bridge stays present
    assert "codex-bridge" in third.tripped_families
    # counter does not run away to absurd values; cap at N=2 (or below)
    assert third.failure_counts.get("codex-bridge", 0) <= 2


def test_recovery_resets_counter_not_tier() -> None:
    """[Req-017] A successful parse resets failure_counts but orchestrator_tier stays high once tripped."""
    state = CircuitBreakerState(epic_id="EPIC-CB-005")
    state = record_parse_failure(state, "codex-bridge")
    state = record_parse_failure(state, "codex-bridge")
    assert state.orchestrator_tier == "high"
    recovered = record_parse_success(state, "codex-bridge")
    assert recovered.failure_counts.get("codex-bridge", 0) == 0
    assert recovered.orchestrator_tier == "high"


def test_per_family_scoping() -> None:
    """[Req-016] Failures on codex-bridge do NOT increment the gemini-bridge counter."""
    state = CircuitBreakerState(epic_id="EPIC-CB-006")
    state = record_parse_failure(state, "codex-bridge")
    state = record_parse_failure(state, "codex-bridge")
    assert state.failure_counts.get("gemini-bridge", 0) == 0
    assert "gemini-bridge" not in state.tripped_families
    assert "gemini-bridge" not in state.cb_legacy_fallback_families


# ---------------------------------------------------------------------------
# Redaction (S-5)
# ---------------------------------------------------------------------------


def test_redaction_applied_on_secret_pattern() -> None:
    """[S-5] redact_output_excerpt strips api_key=<long-value> patterns and sets redaction_applied=True."""
    raw = "the cli output mentioned api_key=AAAAAAAAAAAAAAAAAAAA in passing"
    redacted, applied = redact_output_excerpt(raw)
    assert applied is True
    assert "AAAAAAAAAAAAAAAAAAAA" not in redacted
    assert "REDACTED" in redacted.upper()


def test_redaction_applied_on_bearer_token() -> None:
    """[S-5] redact_output_excerpt strips bearer-token-shaped substrings."""
    raw = "Authorization: Bearer SK_abcdefghijklmnopqrstuvwxyz0123"
    redacted, applied = redact_output_excerpt(raw)
    assert applied is True
    assert "abcdefghijklmnopqrstuvwxyz0123" not in redacted


def test_redaction_truncates_to_max_chars() -> None:
    """[S-5] Output is truncated to first max_chars characters before redaction."""
    raw = "x" * 5000
    redacted, _applied = redact_output_excerpt(raw, max_chars=1000)
    assert len(redacted) <= 1000


def test_redaction_failure_drops_excerpt_failclosed() -> None:
    """[S-5 fail-closed] On any redaction-failure path, the excerpt is dropped entirely.

    The implementation may simulate failure by passing None or
    by mocking the regex compile - this test pins the behavioral
    contract that the failure path returns ('', True).
    """
    redacted, applied = redact_output_excerpt(None)
    assert applied is True
    assert redacted == ""


# ---------------------------------------------------------------------------
# Schema-version invariants
# ---------------------------------------------------------------------------


def test_schema_version_below_2_rejected() -> None:
    """[§7.2 migration note] CircuitBreakerState rejects schema_version < 2 (introductory release)."""
    with pytest.raises(ValueError):
        CircuitBreakerState(epic_id="EPIC-CB-007", schema_version=1)


def test_default_schema_version_is_2() -> None:
    """[§7.2 migration note] CircuitBreakerState defaults to schema_version=2."""
    state = CircuitBreakerState(epic_id="EPIC-CB-008")
    assert state.schema_version == 2


# ---------------------------------------------------------------------------
# to_ledger_artifact shape
# ---------------------------------------------------------------------------


def test_to_ledger_artifact_shape() -> None:
    """[§7.2 lines 960-973] to_ledger_artifact produces the documented schema_version=2 shape."""
    state = CircuitBreakerState(
        epic_id="EPIC-CB-009",
        failure_counts={"codex-bridge": 1, "claude-native": 0},
        tripped_families=frozenset({"codex-bridge"}),
        cb_legacy_fallback_families=frozenset({"codex-bridge"}),
        orchestrator_tier="high",
        last_updated_at="2026-04-30T12:00:00Z",
        schema_version=2,
    )
    artifact: Any = to_ledger_artifact(state)
    assert artifact["artifact_type"] == "circuit_breaker_state"
    assert artifact["epic_id"] == "EPIC-CB-009"
    assert artifact["schema_version"] == 2
    body = artifact["body"]
    assert body["failure_counts"] == {"codex-bridge": 1, "claude-native": 0}
    assert body["orchestrator_tier"] == "high"
    assert body["last_updated_at"] == "2026-04-30T12:00:00Z"
    # Sets serialize as sorted lists for deterministic ordering.
    assert body["tripped_families"] == ["codex-bridge"]
    assert body["cb_legacy_fallback_families"] == ["codex-bridge"]
