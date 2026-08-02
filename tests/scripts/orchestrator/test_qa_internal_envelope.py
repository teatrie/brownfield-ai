"""Envelope-shape contract tests for the qa-internal agent family (W3).

Epic: REVIEWER-ENVELOPE-001 (Wave 3 RED phase).

The qa-* agents (`qa-standards`, `qa-standards-{high,xhigh,max}`,
`qa-lint`, `qa-test`) are NOT bridges — they emit envelopes from their
own native verdicts, like the W1 claude-native code-review* family.
The schema enum already covers ``agent_family="qa-internal"`` (W1
schema), and ``MIGRATED_AGENT_FAMILIES["W3"]`` already includes
``"qa-internal"`` (parser allowlist seeded in W1). These tests pin the
fixture-driven shape for the three load-bearing scenarios listed in the
W3 resume prompt:

1. **qa-standards** APPROVED + APPROVE — clean architectural-compliance
   pass.
2. **qa-lint** REJECTED + RETURN_TO_WORKER — typical lint-failure verdict
   with a blocking finding pointing at the staged file.
3. **qa-test** BLOCKED + HALT_FOR_OPERATOR with
   ``halt_trigger="operator_auth_boundary"`` — exercises the
   operator-auth boundary path (e.g., a staged test exercising a
   destructive task whose execution would require user confirmation).

The tests also pin two parser invariants for the qa-internal family
that W4 will start to consume:

- ``_normalize_recommended_tier`` is a no-op for qa-internal (its
  ceiling is ``max``, the comparison short-circuits).
- ``_reroute_at_ceiling`` is a no-op for qa-internal (qa-internal is
  not in ``_PER_FAMILY_CEILING_REROUTE``).

Each test docstring cites at least one Requirement ID per the TDD
traceability mandate (CLAUDE.md §13).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.orchestrator import envelope_parser
from scripts.orchestrator.envelope_parser import (
    Envelope,
    Finding,
    ParseResult,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "envelopes"


@dataclass(frozen=True)
class _CBStateStub:
    """Minimal stand-in for the GREEN-phase ``CircuitBreakerState``.

    The parser only consumes ``cb_legacy_fallback_families`` (a set of
    agent-family strings); these tests never exercise the CB path so
    the stub stays empty.
    """

    cb_legacy_fallback_families: frozenset[str] = frozenset()


def _parse_fixture(name: str, *, agent_id: str) -> ParseResult:
    """Read a fixture file and route it through ``parse_or_fallback``.

    Centralizes the fixture-load + parse boilerplate so each test body
    asserts only the shape invariants for the scenario under test.
    """
    body = (_FIXTURES_DIR / name).read_text(encoding="utf-8")
    return envelope_parser.parse_or_fallback(
        body,
        agent_id=agent_id,
        agent_family="qa-internal",
        cb_state=_CBStateStub(),
        current_wave="W3",
    )


# ---------------------------------------------------------------------------
# Fixture-driven shape tests — qa-internal scenarios
# ---------------------------------------------------------------------------


def test_qa_standards_approved_envelope_parses_clean() -> None:
    """[Req-001] [Req-002] [Req-018] qa-standards APPROVED + APPROVE round-trips through the parser.

    Mirrors the W1 valid_envelope.md shape but with
    ``agent_family="qa-internal"`` and ``agent_id="qa-standards"``.
    Asserts the family is preserved end-to-end (the parser does NOT
    reroute qa-internal — see ``test_qa_internal_reroute_is_noop``).
    """
    result = _parse_fixture(
        "qa_internal_standards_approved.md",
        agent_id="qa-standards",
    )
    assert not result.degraded
    envelope = result.envelope
    assert envelope is not None
    assert envelope.agent_family == "qa-internal"
    assert envelope.agent_id == "qa-standards"
    assert envelope.status == "APPROVED"
    assert envelope.next_action == "APPROVE"
    assert envelope.feedback_to_forward == ()
    assert envelope.recommended_next_tier is None
    assert envelope.halt_trigger is None
    assert result.audit_annotations is None


def test_qa_lint_rejected_envelope_carries_blocking_finding() -> None:
    """[Req-002] [Req-007] [Req-018] qa-lint REJECTED + RETURN_TO_WORKER carries a blocking finding.

    A typical lint failure: the staged file has an unresolved ruff
    violation. The envelope MUST emit a ``feedback_to_forward`` entry
    (the schema's allOf clause requires ``minItems: 1`` for
    RETURN_TO_WORKER) with ``blocking=true`` (B-2 R2 default).
    """
    result = _parse_fixture(
        "qa_internal_lint_rejected.md",
        agent_id="qa-lint",
    )
    assert not result.degraded
    envelope = result.envelope
    assert envelope is not None
    assert envelope.agent_family == "qa-internal"
    assert envelope.agent_id == "qa-lint"
    assert envelope.status == "REJECTED"
    assert envelope.next_action == "RETURN_TO_WORKER"
    assert len(envelope.feedback_to_forward) == 1
    finding = envelope.feedback_to_forward[0]
    assert isinstance(finding, Finding)
    assert finding.severity == "significant"
    assert finding.blocking is True
    assert finding.file_path is not None


def test_qa_test_halt_for_operator_auth_boundary() -> None:
    """[Req-006] [Req-018] [B-5 R2] qa-test BLOCKED + HALT_FOR_OPERATOR carries operator_auth_boundary halt_trigger.

    Exercises the operator-authorization boundary path (CLAUDE.md §17 +
    §9). A staged test that would invoke a destructive task outside the
    production allow list (e.g., ``task repos:reset``, which CLAUDE.md
    §9 explicitly requires "PROCEED WITH RESET" user confirmation)
    requires user confirmation before execution; qa-test surfaces that
    as a HALT instead of running it autonomously. Schema allOf clause
    requires ``halt_trigger`` to be a non-null string when
    ``next_action="HALT_FOR_OPERATOR"``.
    """
    result = _parse_fixture(
        "qa_internal_test_halt_operator_auth.md",
        agent_id="qa-test",
    )
    assert not result.degraded
    envelope = result.envelope
    assert envelope is not None
    assert envelope.agent_family == "qa-internal"
    assert envelope.agent_id == "qa-test"
    assert envelope.status == "BLOCKED"
    assert envelope.next_action == "HALT_FOR_OPERATOR"
    assert envelope.halt_trigger == "operator_auth_boundary"
    assert envelope.recommended_next_tier is None


# ---------------------------------------------------------------------------
# Parser invariants — qa-internal is NOT a bridge
# ---------------------------------------------------------------------------


def test_qa_internal_normalize_recommended_tier_is_noop() -> None:
    """[Req-005] [S-1 R2] _normalize_recommended_tier never lowers a qa-internal tier.

    qa-internal's per-family ceiling is ``max`` (table-completeness
    only — there is no real cap). Any ``recommended_next_tier`` value
    in the schema enum (``medium``, ``high``, ``xhigh``, ``max``) is at
    or below the ceiling, so the function returns the envelope
    unchanged. Pinning this here protects against a future widening of
    the ceiling table that accidentally narrows qa-internal.
    """
    base = Envelope(
        envelope_version="1",
        agent_id="qa-standards-max",
        agent_family="qa-internal",
        agent_effort_tier="max",
        round=1,
        status="ESCALATE",
        next_action="ESCALATE_REVIEWER_TIER",
        recommended_next_tier="max",
        halt_trigger=None,
    )
    for tier in ("medium", "high", "xhigh", "max"):
        envelope = base.replace(recommended_next_tier=tier)
        result = envelope_parser._normalize_recommended_tier(envelope)
        assert result.recommended_next_tier == tier
        assert result.agent_family == "qa-internal"


def test_qa_internal_reroute_at_ceiling_is_noop() -> None:
    """[G-1 R2] _reroute_at_ceiling never reroutes a qa-internal envelope.

    qa-internal is intentionally absent from
    ``_PER_FAMILY_CEILING_REROUTE`` — the reroute mechanism is for
    bridge families that hit their upstream-CLI ceiling and need a
    family swap to claude-native to gain real tier headroom. qa-internal
    is itself the headroom family and never needs a reroute.
    """
    envelope = Envelope(
        envelope_version="1",
        agent_id="qa-standards-xhigh",
        agent_family="qa-internal",
        agent_effort_tier="xhigh",
        round=1,
        status="ESCALATE",
        next_action="ESCALATE_REVIEWER_TIER",
        recommended_next_tier="max",
        halt_trigger=None,
    )
    rerouted, audit = envelope_parser._reroute_at_ceiling(envelope)
    assert rerouted is envelope or rerouted == envelope
    assert rerouted.agent_family == "qa-internal"
    assert audit is None


def test_qa_internal_is_in_w3_migrated_allowlist() -> None:
    """[Req-015] [G-2 R2] qa-internal is in MIGRATED_AGENT_FAMILIES["W3"] so absent envelopes hard-fail.

    W3 starts requiring qa-internal envelopes; the allowlist entry was
    pre-staged in W1 (the parser was scaffolded ahead of agent-body
    rollout so each wave only ships the agent updates plus tests). This
    test pins the invariant against accidental removal — an absent
    envelope from a qa-* agent during W3 must raise
    ``EnvelopeParseError`` rather than degrade to prose extraction.
    """
    assert "qa-internal" in envelope_parser.MIGRATED_AGENT_FAMILIES["W3"]
    assert "qa-internal" in envelope_parser.MIGRATED_AGENT_FAMILIES["W4"]
