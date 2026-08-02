"""Unit tests for the Reviewer Output Envelope parser.

Epic: REVIEWER-ENVELOPE-001 (Wave 1 RED phase).

The parser under test lives at ``scripts/orchestrator/envelope_parser.py``
(GREEN phase will create it). These tests intentionally fail at import-time
during the RED phase — that is the load-bearing failing signal.

Every test docstring cites at least one Requirement ID from the plan
(``tmp/plan-reviewer-output-envelope.md`` §3) per the TDD traceability
mandate (CLAUDE.md §13, ``docs/tdd-protocol.md`` step 2.1).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import pytest

# RED-phase import: this module does not exist yet. Importing it raises
# ModuleNotFoundError at collection time, which is the correct failing
# signal for the RED phase. GREEN phase will create the module.
from scripts.orchestrator import envelope_parser

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = _REPO_ROOT / "docs" / "schemas" / "reviewer_envelope.schema.json"
_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "envelopes"


@dataclass(frozen=True)
class _CBStateStub:
    """Minimal stand-in for the GREEN-phase ``CircuitBreakerState``.

    The parser only consumes ``cb_legacy_fallback_families`` (a set of
    agent-family strings). GREEN may broaden the dataclass; tests pin the
    minimum surface needed to drive ``parse_or_fallback``.
    """

    cb_legacy_fallback_families: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    """Load and return the JSON Schema for the reviewer envelope."""
    loaded: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def validator(schema: dict[str, Any]) -> jsonschema.Draft202012Validator:
    """Return a Draft 2020-12 validator bound to the envelope schema."""
    return jsonschema.Draft202012Validator(schema)


@pytest.fixture(scope="module")
def fixtures_dir() -> Path:
    """Return the absolute path to the envelope fixtures directory."""
    return _FIXTURES_DIR


@pytest.fixture
def example_a() -> dict[str, Any]:
    """Return Worked Example A (unanimous APPROVE) from plan §4.2."""
    return {
        "envelope_version": "1",
        "agent_id": "code-review-high",
        "agent_family": "claude-native",
        "agent_effort_tier": "high",
        "round": 1,
        "status": "APPROVED",
        "next_action": "APPROVE",
        "feedback_to_forward": [],
        "recommended_next_tier": None,
        "halt_trigger": None,
    }


@pytest.fixture
def example_b() -> dict[str, Any]:
    """Return Worked Example B (RETURN_TO_WORKER with feedback) from plan §4.2."""
    return {
        "envelope_version": "1",
        "agent_id": "code-review-high",
        "agent_family": "claude-native",
        "agent_effort_tier": "high",
        "round": 2,
        "status": "APPROVED_WITH_NOTES",
        "next_action": "RETURN_TO_WORKER",
        "feedback_to_forward": [
            {
                "severity": "significant",
                "file_path": "scripts/orchestrator/envelope_parser.py",
                "line_range": "42-58",
                "description": (
                    "Parser silently catches JSONDecodeError and returns None — "
                    "violates Req-N05. Must raise EnvelopeParseError so the "
                    "circuit-breaker counter increments."
                ),
                "suggested_fix": ("Replace the bare except with: raise EnvelopeParseError(...) from exc"),
                "rule_id": "Req-N05",
            },
        ],
        "recommended_next_tier": None,
        "halt_trigger": None,
    }


@pytest.fixture
def example_d() -> dict[str, Any]:
    """Return Worked Example D (HALT_FOR_OPERATOR) from plan §4.2."""
    return {
        "envelope_version": "1",
        "agent_id": "code-review-xhigh",
        "agent_family": "claude-native",
        "agent_effort_tier": "xhigh",
        "round": 1,
        "status": "BLOCKED",
        "next_action": "HALT_FOR_OPERATOR",
        "feedback_to_forward": [
            {
                "severity": "critical",
                "file_path": ".claude/settings.json",
                "line_range": "12-18",
                "description": (
                    "Plan adds Bash(task aws:*) to the production allowlist. "
                    "CLAUDE.md §17 requires this be operator-authorized via PR "
                    "review, not orchestrator-applied."
                ),
                "rule_id": "CLAUDE.md::§17::OPERATOR_AUTHORIZED_DESTRUCTIVE",
            },
        ],
        "recommended_next_tier": None,
        "halt_trigger": "operator_auth_boundary",
    }


# ---------------------------------------------------------------------------
# Schema validation tests (Req-002, Req-N01, B-2 R2, S-3 R2)
# ---------------------------------------------------------------------------


def test_schema_validates_canonical_envelope(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[Req-002] The canonical APPROVE envelope (Example A) round-trips through jsonschema."""
    validator.validate(example_a)


def test_missing_required_field_rejected(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[Req-002] Dropping a top-level required field causes ValidationError."""
    broken = dict(example_a)
    del broken["status"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(broken)


def test_unknown_top_level_key_rejected(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[Req-N01] additionalProperties:false rejects free-form top-level keys (e.g. 'notes')."""
    broken = dict(example_a)
    broken["notes"] = "trojan-horse reasoning would live here"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(broken)


def test_blocking_field_default_true_when_absent(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[B-2 R2] [Req-007] Finding without 'blocking' validates; default semantics live in code, not the schema."""
    # Example B's first finding has no 'blocking' key — it must validate.
    assert "blocking" not in example_b["feedback_to_forward"][0]
    validator.validate(example_b)


def test_blocking_field_explicit_false_preserved(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[B-2 R2] [Req-007] Explicit blocking=false validates."""
    envelope = json.loads(json.dumps(example_b))
    envelope["feedback_to_forward"][0]["blocking"] = False
    validator.validate(envelope)


def test_blocking_field_explicit_true_preserved(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[B-2 R2] [Req-007] Explicit blocking=true validates."""
    envelope = json.loads(json.dumps(example_b))
    envelope["feedback_to_forward"][0]["blocking"] = True
    validator.validate(envelope)


# ---------------------------------------------------------------------------
# Discriminated-fence detection tests (Req-001, B-3 R2, B-4 R2 / Req-N08, Req-N05)
# ---------------------------------------------------------------------------


def test_plain_json_fence_ignored(fixtures_dir: Path) -> None:
    """[B-3 R2] [Req-001] Plain ```json fences MUST NOT be promoted as envelopes.

    The fixture has a prose-cited plain ```json block (with envelope-shaped
    content) followed by the real ```json envelope`` block. The parser must
    select the discriminated block, never the plain one.
    """
    output = (fixtures_dir / "prose_cited_json.md").read_text(encoding="utf-8")
    body = envelope_parser.find_envelope_block(output)
    assert body is not None
    parsed = json.loads(body)
    assert parsed["agent_id"] == "code-review-high"
    # Sanity: the prose-cited ILLUSTRATIVE block must NOT have leaked through.
    assert parsed["agent_id"] != "EXAMPLE-FROM-PROSE"


def test_suggested_fix_json_snippet_does_not_confuse_parser(
    fixtures_dir: Path,
) -> None:
    """[Req-001] A JSON snippet rendered in plain ```json inside the prose body must be ignored.

    The discriminated final fence is the only envelope, even when other JSON
    appears earlier in the output (e.g. as a `suggested_fix` illustration).
    """
    output = (fixtures_dir / "suggested_fix_json_snippet.md").read_text(encoding="utf-8")
    body = envelope_parser.find_envelope_block(output)
    assert body is not None
    parsed = json.loads(body)
    assert parsed["round"] == 2
    assert parsed["status"] == "APPROVED_WITH_NOTES"


def test_multiple_envelope_fences_raises(fixtures_dir: Path) -> None:
    """[Req-N08] [B-4 R2] Two ``json envelope`` fences MUST raise — no last-wins fallback."""
    output = (fixtures_dir / "multiple_envelope_fences.md").read_text(encoding="utf-8")
    with pytest.raises(envelope_parser.EnvelopeParseError) as excinfo:
        envelope_parser.find_envelope_block(output)
    assert getattr(excinfo.value, "reason", None) == "multiple_envelope_fences"


def test_empty_fence_raises(fixtures_dir: Path) -> None:
    """[Req-N05] An envelope fence with empty body MUST raise EnvelopeParseError."""
    output = (fixtures_dir / "empty_fence.md").read_text(encoding="utf-8")
    with pytest.raises(envelope_parser.EnvelopeParseError):
        envelope_parser.parse_or_fallback(
            output,
            agent_id="code-review-high",
            agent_family="claude-native",
            cb_state=_CBStateStub(),
            current_wave="W1",
        )


def test_whitespace_only_fence_raises(fixtures_dir: Path) -> None:
    """[Req-N05] An envelope fence with whitespace-only body MUST raise EnvelopeParseError."""
    output = (fixtures_dir / "whitespace_only_fence.md").read_text(encoding="utf-8")
    with pytest.raises(envelope_parser.EnvelopeParseError):
        envelope_parser.parse_or_fallback(
            output,
            agent_id="code-review-high",
            agent_family="claude-native",
            cb_state=_CBStateStub(),
            current_wave="W1",
        )


def test_malformed_envelope_raises_envelope_parse_error(
    fixtures_dir: Path,
) -> None:
    """[Req-N05] Schema-violating envelope MUST raise EnvelopeParseError, not silently fall back.

    The fixture pairs ``status=APPROVED`` with ``next_action=RETURN_TO_WORKER``
    which is forbidden by the §4.1.1 status × next_action validity matrix.
    """
    output = (fixtures_dir / "malformed_envelope.md").read_text(encoding="utf-8")
    with pytest.raises(envelope_parser.EnvelopeParseError):
        envelope_parser.parse_or_fallback(
            output,
            agent_id="code-review-high",
            agent_family="claude-native",
            cb_state=_CBStateStub(),
            current_wave="W1",
        )


def test_literal_empty_fence_raises_malformed_envelope_fence(
    fixtures_dir: Path,
) -> None:
    """[Req-N05] [TODO-0152] An opener line followed immediately by a closer line (no body line at all) raises ``reason="malformed_envelope_fence"``.

    The shape ``\\`\\`\\`json envelope\\n\\`\\`\\`\\n`` cannot match the
    full :data:`ENVELOPE_FENCE_RE` because the regex requires
    ``\\n(.*?)\\n\\`\\`\\``` between opener and closer (two newlines
    minimum). The pre-scan guard added in TODO-0152 detects the
    discriminated opener line in isolation and raises
    ``EnvelopeParseError(reason="malformed_envelope_fence")`` so the
    failure does not get conflated with the envelope-absent path.
    """
    output = (fixtures_dir / "literal_empty_fence.md").read_text(encoding="utf-8")
    with pytest.raises(envelope_parser.EnvelopeParseError) as excinfo:
        envelope_parser.find_envelope_block(output)
    assert getattr(excinfo.value, "reason", None) == "malformed_envelope_fence"


def test_closer_attached_to_body_line_raises_malformed_envelope_fence() -> None:
    """[Req-N05] [TODO-0152] An opener followed by a body line whose closer is not preceded by a newline raises ``reason="malformed_envelope_fence"``.

    The shape ``\\`\\`\\`json envelope\\n{}\\`\\`\\``` (closer attached
    to the body line, no preceding newline before the trailing
    backticks) cannot match :data:`ENVELOPE_FENCE_RE` because the regex
    requires ``\\n\\`\\`\\``` after the body capture. The pre-scan guard
    classifies it as ``malformed_envelope_fence`` rather than letting
    it route through the envelope-absent path.
    """
    output = "```json envelope\n{}```\n"
    with pytest.raises(envelope_parser.EnvelopeParseError) as excinfo:
        envelope_parser.find_envelope_block(output)
    assert getattr(excinfo.value, "reason", None) == "malformed_envelope_fence"


def test_prose_only_output_routes_through_envelope_absent_path(
    fixtures_dir: Path,
) -> None:
    """[Req-015] [TODO-0152] Prose-only reviewer output (no opener line whatsoever) returns None from ``find_envelope_block``, NOT a malformed-fence raise.

    The pre-scan guard for ``malformed_envelope_fence`` must fire only
    when the reviewer emitted a literal ``\\`\\`\\`json envelope`` opener
    line. Prose that merely mentions the discriminator inline (e.g. as
    inline code with single backticks) MUST still route through the
    envelope-absent branch so non-migrated families fall back to the
    legacy verdict ladder rather than tripping the circuit-breaker.
    """
    output = (fixtures_dir / "no_envelope_legacy.md").read_text(encoding="utf-8")
    body = envelope_parser.find_envelope_block(output)
    assert body is None


def test_literal_empty_fence_through_parse_or_fallback_for_migrated_family(
    fixtures_dir: Path,
) -> None:
    """[Req-N05] [TODO-0152] A literal-empty-fence emitted by a migrated family raises ``reason="malformed_envelope_fence"`` via ``parse_or_fallback`` — distinct from ``"envelope_absent_for_migrated_family"``.

    Before TODO-0152 this shape routed through ``find_envelope_block``
    returning ``None``, which then raised
    ``reason="envelope_absent_for_migrated_family"`` for migrated
    families. The pre-scan guard distinguishes "the agent attempted an
    envelope and the bytes came out malformed" from "the agent emitted
    prose only" so the orchestrator's circuit-breaker classifier can
    route the malformed case through RETRY_REVIEWER with a
    distinguishable reason tag.
    """
    output = (fixtures_dir / "literal_empty_fence.md").read_text(encoding="utf-8")
    with pytest.raises(envelope_parser.EnvelopeParseError) as excinfo:
        envelope_parser.parse_or_fallback(
            output,
            agent_id="code-review-high",
            agent_family="claude-native",
            cb_state=_CBStateStub(),
            current_wave="W1",
        )
    assert getattr(excinfo.value, "reason", None) == "malformed_envelope_fence"


def test_agent_id_exceeding_maxlength_rejected_by_schema(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[TODO-0137] agent_id at length 257 MUST violate schema maxLength=256.

    The W1 schema accepted unbounded strings on agent_id; an adversarial
    reviewer could emit a multi-megabyte agent_id that the parser would
    pass through to the orchestrator's logging / ledger writer. The
    DoS guard caps agent_id at 256 bytes — generous for the longest
    real agent name (e.g. "gemini-reviewer-xhigh" = 21 chars) but
    bounded enough to defeat resource exhaustion.
    """
    payload = dict(example_a)
    payload["agent_id"] = "a" * 257
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_spillover_findings_path_exceeding_maxlength_rejected_by_schema(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[TODO-0137] spillover_findings_path at length 1025 MUST violate schema maxLength=1024.

    The schema guards against an adversarial reviewer emitting a
    pathological spillover path string. 1024 bytes accommodates any
    realistic ``tmp/findings-overflow-<round>-<epic>.json`` form
    while bounding the DoS surface.
    """
    payload = dict(example_a)
    payload["spillover_findings_path"] = "tmp/" + ("x" * 1021)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_feedback_exceeding_50_items_rejected_by_schema(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[Req-N07] feedback_to_forward with 51 items MUST violate schema maxItems=50.

    Plan §3 Req-N07 caps the array at 50 finding objects per envelope;
    reviewers exceeding the cap MUST emit a single summary finding plus
    a non-null ``spillover_findings_path``. The schema enforces the cap
    structurally so the parser never hands a runaway-array envelope to
    the merge function. Without this test, a future schema relaxation
    (e.g. removing maxItems) could silently re-open the DoS surface
    that Req-N07 closes.
    """
    payload = dict(example_b)
    base_finding = payload["feedback_to_forward"][0]
    payload["feedback_to_forward"] = [dict(base_finding) for _ in range(51)]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_feedback_exactly_50_items_accepted_by_schema(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[Req-N07] feedback_to_forward with 50 items MUST validate.

    Boundary check on the cap — exactly the documented maximum is
    permitted; the rejection above triggers only when a reviewer
    crosses the cap. Together the two tests pin the inequality
    direction (``> 50`` rejected, ``<= 50`` accepted).
    """
    payload = dict(example_b)
    base_finding = payload["feedback_to_forward"][0]
    payload["feedback_to_forward"] = [dict(base_finding) for _ in range(50)]
    validator.validate(payload)


def test_spillover_findings_path_propagates_through_parser() -> None:
    """[Req-N07] A non-null ``spillover_findings_path`` round-trips into the parsed Envelope.

    Plan §3 Req-N07 documents the spillover-artifact convention: when
    the 50-finding cap is hit, the reviewer emits a summary finding
    pointing at ``tmp/findings-overflow-<round>.json`` via the
    optional ``spillover_findings_path`` field. The parser must
    surface this field on the resulting :class:`Envelope` so the
    orchestrator can locate the overflow artifact during finding
    aggregation. Test fingerprint: a discriminated-fence envelope
    carrying a non-null path validates AND parses to an Envelope
    whose ``spillover_findings_path`` is the same path.
    """
    fixture_body = json.dumps(
        {
            "envelope_version": "1",
            "agent_id": "code-review-high",
            "agent_family": "claude-native",
            "agent_effort_tier": "high",
            "round": 1,
            "status": "APPROVED_WITH_NOTES",
            "next_action": "RETURN_TO_WORKER",
            "feedback_to_forward": [
                {
                    "severity": "informational",
                    "description": "50+ findings exceeded; see spillover artifact for full set.",
                    "rule_id": "Req-N07::spillover-summary",
                },
            ],
            "recommended_next_tier": None,
            "halt_trigger": None,
            "spillover_findings_path": "tmp/findings-overflow-r3.json",
        },
    )
    output = "# Review with spillover\n\n```json envelope\n" + fixture_body + "\n```\n"
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="code-review-high",
        agent_family="claude-native",
        cb_state=_CBStateStub(),
        current_wave="W1",
    )
    assert result.envelope is not None
    assert result.envelope.spillover_findings_path == "tmp/findings-overflow-r3.json"


def test_oversized_envelope_body_raises_before_json_loads_runs() -> None:
    """[TODO-0137] Body > 256_000 bytes MUST raise EnvelopeParseError(reason='envelope_too_large') BEFORE json.loads runs.

    The guard is positioned upstream of ``json.loads`` so adversarial
    payloads engineered to OOM or trigger pathological allocator
    behavior never reach the parser. Test fingerprint: feed a
    300_000-byte body that is NOT valid JSON. Without the guard,
    ``json.loads`` would raise ``JSONDecodeError`` wrapped as a
    generic ``EnvelopeParseError(agent_id=..., cause=exc)`` (no ``reason``).
    With the guard, the error carries ``reason='envelope_too_large'``
    — the distinguishable signal asserts the guard fired first.
    """
    body = "x" * 300_000
    output = "# Adversarial review\n\n```json envelope\n" + body + "\n```\n"
    with pytest.raises(envelope_parser.EnvelopeParseError) as excinfo:
        envelope_parser.parse_or_fallback(
            output,
            agent_id="code-review-high",
            agent_family="claude-native",
            cb_state=_CBStateStub(),
            current_wave="W1",
        )
    assert excinfo.value.reason == "envelope_too_large"


def test_deeply_nested_envelope_does_not_escape_circuit_breaker() -> None:
    """[Req-N05] Deeply-nested JSON MUST raise EnvelopeParseError, not escape as RecursionError.

    Adversarial reviewer output containing JSON nested deeper than
    ``sys.getrecursionlimit()`` causes ``json.loads`` to raise
    ``RecursionError`` on some CPython builds. Without an explicit guard
    the exception escapes ``parse_or_fallback`` uncaught, the
    circuit-breaker counter never increments, and the orchestrator does
    not route as RETRY_REVIEWER — bypassing the Req-N05 contract that
    every parse failure must trip the CB. (Codex F2 audit, 2026-04-30.)
    """
    depth = sys.getrecursionlimit() * 4
    body = ("[" * depth) + ("]" * depth)
    output = "# Adversarial review\n\n```json envelope\n" + body + "\n```\n"
    with pytest.raises(envelope_parser.EnvelopeParseError):
        envelope_parser.parse_or_fallback(
            output,
            agent_id="code-review-high",
            agent_family="claude-native",
            cb_state=_CBStateStub(),
            current_wave="W1",
        )


# ---------------------------------------------------------------------------
# Per-family ceiling normalization (_normalize_recommended_tier) — Req-005, S-1 R2
# ---------------------------------------------------------------------------


def _envelope_with(**overrides: Any) -> Any:
    """Build a minimally-valid Envelope via the parser's constructor.

    The factory delegates to ``envelope_parser.Envelope`` so GREEN can choose
    the concrete shape (dataclass, NamedTuple, pydantic model). Tests only
    rely on attribute access and ``replace``-style updates.
    """
    base: dict[str, Any] = {
        "envelope_version": "1",
        "agent_id": "test-agent",
        "agent_family": "claude-native",
        "agent_effort_tier": "high",
        "round": 1,
        "status": "ESCALATE",
        "next_action": "ESCALATE_REVIEWER_TIER",
        "feedback_to_forward": [],
        "recommended_next_tier": "high",
        "halt_trigger": None,
    }
    base.update(overrides)
    return envelope_parser.Envelope(**base)


def test_codex_max_normalized_to_xhigh() -> None:
    """[Req-005] [S-1 R2] codex-bridge requesting 'max' normalizes to 'xhigh'."""
    env = _envelope_with(
        agent_family="codex-bridge",
        agent_id="codex-reviewer-xhigh",
        recommended_next_tier="max",
    )
    out = envelope_parser._normalize_recommended_tier(env)
    assert out.recommended_next_tier == "xhigh"


def test_gemini_xhigh_normalized_to_high() -> None:
    """[Req-005] [S-1 R2] gemini-bridge requesting 'xhigh' normalizes to 'high'."""
    env = _envelope_with(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer-high",
        recommended_next_tier="xhigh",
    )
    out = envelope_parser._normalize_recommended_tier(env)
    assert out.recommended_next_tier == "high"


def test_gemini_max_normalized_to_high() -> None:
    """[Req-005] [S-1 R2] gemini-bridge requesting 'max' normalizes to 'high'."""
    env = _envelope_with(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer-high",
        recommended_next_tier="max",
    )
    out = envelope_parser._normalize_recommended_tier(env)
    assert out.recommended_next_tier == "high"


def test_claude_max_preserved_no_cap() -> None:
    """[Req-005] [S-1 R2] claude-native has no ceiling — 'max' is preserved."""
    env = _envelope_with(
        agent_family="claude-native",
        agent_id="code-review-max",
        recommended_next_tier="max",
    )
    out = envelope_parser._normalize_recommended_tier(env)
    assert out.recommended_next_tier == "max"


def test_recommended_next_tier_null_passthrough() -> None:
    """[Req-005] When recommended_next_tier is None, normalization is a no-op."""
    env = _envelope_with(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer",
        next_action="APPROVE",
        status="APPROVED",
        recommended_next_tier=None,
    )
    out = envelope_parser._normalize_recommended_tier(env)
    assert out.recommended_next_tier is None


# ---------------------------------------------------------------------------
# Reroute at ceiling (_reroute_at_ceiling) — Req-005, G-1 R2, Round 3 V3-N01
# ---------------------------------------------------------------------------


def test_reroute_at_ceiling_gemini_high() -> None:
    """[G-1 R2] [Round 3 V3-N01] Gemini ESCALATE→high reroutes to claude-native; audit captured out-of-band."""
    env = _envelope_with(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer-high",
        recommended_next_tier="high",
    )
    rerouted, audit = envelope_parser._reroute_at_ceiling(env)
    assert rerouted.agent_family == "claude-native"
    assert audit is not None
    assert audit.original_family == "gemini-bridge"
    assert audit.agent_id == "gemini-reviewer-high"
    assert audit.reroute_reason == "ceiling_collision"


def test_reroute_at_ceiling_codex_xhigh() -> None:
    """[G-1 R2] Codex ESCALATE→xhigh (its binding ceiling) reroutes to claude-native."""
    env = _envelope_with(
        agent_family="codex-bridge",
        agent_id="codex-reviewer-xhigh",
        recommended_next_tier="xhigh",
    )
    rerouted, audit = envelope_parser._reroute_at_ceiling(env)
    assert rerouted.agent_family == "claude-native"
    assert audit is not None
    assert audit.original_family == "codex-bridge"


def test_no_reroute_when_below_ceiling() -> None:
    """[G-1 R2] Gemini ESCALATE→medium does NOT reroute — only ceiling collisions trigger reroute."""
    env = _envelope_with(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer",
        recommended_next_tier="medium",
    )
    rerouted, audit = envelope_parser._reroute_at_ceiling(env)
    assert rerouted.agent_family == "gemini-bridge"
    assert audit is None


def test_no_reroute_when_not_escalate() -> None:
    """[G-1 R2] Gemini RETURN_TO_WORKER (even at ceiling tier) does NOT reroute.

    The reroute rule fires only for ``next_action == ESCALATE_REVIEWER_TIER``.
    """
    env = _envelope_with(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer-high",
        status="REJECTED",
        next_action="RETURN_TO_WORKER",
        recommended_next_tier="high",
        feedback_to_forward=[
            {
                "severity": "critical",
                "description": "blocker that has nothing to do with tier escalation",
            },
        ],
    )
    rerouted, audit = envelope_parser._reroute_at_ceiling(env)
    assert rerouted.agent_family == "gemini-bridge"
    assert audit is None


def test_reroute_audit_carried_out_of_band_on_parse_result(
    fixtures_dir: Path,
) -> None:
    """[Round 3 V3-N01 / MINOR-3 / N3-1] RerouteAudit lives on ParseResult.audit_annotations, NEVER on the envelope.

    The envelope schema declares ``additionalProperties: false``, so any
    ``_audit`` key written onto the envelope JSON would fail downstream
    re-validation. This test verifies the audit is delivered out-of-band.
    """
    # Synthesize a Gemini ESCALATE→high output (ceiling collision) inline.
    output = (
        "# Gemini Review\n\n"
        "Diff is deep; recommend Claude-native re-review at high.\n\n"
        "```json envelope\n"
        + json.dumps(
            {
                "envelope_version": "1",
                "agent_id": "gemini-reviewer-high",
                "agent_family": "gemini-bridge",
                "agent_effort_tier": "high",
                "round": 1,
                "status": "ESCALATE",
                "next_action": "ESCALATE_REVIEWER_TIER",
                "feedback_to_forward": [],
                "recommended_next_tier": "high",
                "halt_trigger": None,
            },
            indent=2,
        )
        + "\n```\n"
    )
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="gemini-reviewer-high",
        agent_family="gemini-bridge",
        cb_state=_CBStateStub(),
        current_wave="W2",
    )
    # Envelope must remain schema-conformant — no `_audit` key.
    #
    # The Round 3 V3-N01 / MINOR-3 / N3-1 invariant has THREE failure modes
    # that this test must independently catch (Codex F2 audit, 2026-04-30):
    #
    #   (a) `_audit` declared as an Envelope dataclass field — caught by the
    #       `dataclasses.fields()` check below. Asserting on `to_dict()` keys
    #       alone is insufficient because asdict() only enumerates declared
    #       fields, so it would tautologically pass even if a bug existed.
    #
    #   (b) `_audit` written via `object.__setattr__` (the same frozen-dataclass
    #       bypass `__post_init__` uses). Caught by the JSON-serialization check
    #       — `json.dumps(asdict(envelope))` projects through declared fields
    #       only, so an instance attribute set via __setattr__ would not appear
    #       in the JSON. We therefore also serialize `vars(envelope)` to catch
    #       the instance-dict path.
    #
    #   (c) `_audit` re-validation against the schema — `additionalProperties:
    #       false` would reject any extra key, so we round-trip through the
    #       Draft202012Validator as a third defense.
    assert result.envelope is not None
    declared_field_names = {f.name for f in dataclasses.fields(envelope_parser.Envelope)}
    assert "_audit" not in declared_field_names, (
        f"Envelope dataclass MUST NOT declare an `_audit` field "
        f"(Round 3 V3-N01: schema has additionalProperties:false). "
        f"Found fields: {sorted(declared_field_names)}"
    )
    envelope_dict = result.envelope.to_dict()
    assert "_audit" not in envelope_dict
    serialized = json.dumps(envelope_dict, default=str)
    assert "_audit" not in serialized, f"Envelope JSON serialization MUST NOT contain `_audit`. Got: {serialized}"
    instance_attrs = vars(result.envelope) if hasattr(result.envelope, "__dict__") else {}
    assert "_audit" not in instance_attrs, (
        f"Envelope instance MUST NOT carry `_audit` via object.__setattr__ bypass. Found instance attrs: {sorted(instance_attrs)}"
    )
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(envelope_dict)
    # Audit metadata is on the ParseResult instead.
    assert result.audit_annotations is not None
    assert len(result.audit_annotations) == 1
    assert result.audit_annotations[0].original_family == "gemini-bridge"


# ---------------------------------------------------------------------------
# Status × next_action validity matrix (S-3 R2 / Req-003 / Req-004 / Req-006 / Req-N04)
#
# Citation map for the qa-standards-xhigh Spec Verification Gate
# (W4 closeout, TODO-0151): the parametrized cases below pin the §4.1.1
# allOf if/then matrix. Each pairing test simultaneously exercises the
# status enum (Req-003), the next_action enum (Req-004), and — when a
# BLOCKED / HALT_FOR_OPERATOR row is involved — the halt_trigger enum
# (Req-006). Req-N04 is satisfied structurally: the matrix is encoded
# as a single ``enum`` per field plus an allOf if/then chain, NOT as
# oneOf/anyOf disjunctions, so there is no ambiguous overlap to game.
# ---------------------------------------------------------------------------


def _assert_invalid(
    validator: jsonschema.Draft202012Validator,
    envelope: dict[str, Any],
) -> None:
    """Assert the given envelope payload fails schema validation."""
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(envelope)


def test_abstain_with_non_retry_rejected(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[S-3 R2] status=ABSTAIN paired with anything other than RETRY_REVIEWER must fail."""
    envelope = dict(example_a)
    envelope["status"] = "ABSTAIN"
    envelope["next_action"] = "APPROVE"
    _assert_invalid(validator, envelope)


def test_approved_with_non_approve_rejected(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[S-3 R2] status=APPROVED paired with non-APPROVE next_action must fail."""
    envelope = dict(example_a)
    envelope["next_action"] = "RETURN_TO_WORKER"
    envelope["feedback_to_forward"] = [
        {"severity": "minor", "description": "x"},
    ]
    _assert_invalid(validator, envelope)


def test_approved_with_notes_with_escalate_rejected(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[S-3 R2] status=APPROVED_WITH_NOTES paired with ESCALATE_REVIEWER_TIER must fail."""
    envelope = json.loads(json.dumps(example_b))
    envelope["next_action"] = "ESCALATE_REVIEWER_TIER"
    envelope["recommended_next_tier"] = "xhigh"
    _assert_invalid(validator, envelope)


def test_rejected_with_non_return_rejected(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[S-3 R2] status=REJECTED paired with non-RETURN_TO_WORKER next_action must fail."""
    envelope = json.loads(json.dumps(example_b))
    envelope["status"] = "REJECTED"
    envelope["next_action"] = "APPROVE"
    _assert_invalid(validator, envelope)


def test_blocked_with_non_halt_rejected(
    validator: jsonschema.Draft202012Validator,
    example_d: dict[str, Any],
) -> None:
    """[S-3 R2] status=BLOCKED paired with non-HALT_FOR_OPERATOR next_action must fail."""
    envelope = json.loads(json.dumps(example_d))
    envelope["next_action"] = "RETURN_TO_WORKER"
    envelope["halt_trigger"] = None
    _assert_invalid(validator, envelope)


def test_escalate_with_non_escalate_action_rejected(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[S-3 R2] status=ESCALATE paired with non-ESCALATE_REVIEWER_TIER next_action must fail."""
    envelope = dict(example_a)
    envelope["status"] = "ESCALATE"
    envelope["next_action"] = "APPROVE"
    _assert_invalid(validator, envelope)


def test_return_to_worker_requires_minitems_1(
    validator: jsonschema.Draft202012Validator,
    example_b: dict[str, Any],
) -> None:
    """[S-3 R2] next_action=RETURN_TO_WORKER requires feedback_to_forward minItems: 1."""
    envelope = json.loads(json.dumps(example_b))
    envelope["feedback_to_forward"] = []
    _assert_invalid(validator, envelope)


def test_return_to_worker_advisory_requires_minitems_1(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[S-3 R2] next_action=RETURN_TO_WORKER_ADVISORY requires feedback_to_forward minItems: 1."""
    envelope = dict(example_a)
    envelope["status"] = "APPROVED_WITH_NOTES"
    envelope["next_action"] = "RETURN_TO_WORKER_ADVISORY"
    envelope["feedback_to_forward"] = []
    _assert_invalid(validator, envelope)


def test_halt_for_operator_requires_halt_trigger(
    validator: jsonschema.Draft202012Validator,
    example_d: dict[str, Any],
) -> None:
    """[S-3 R2] next_action=HALT_FOR_OPERATOR requires non-null halt_trigger string."""
    envelope = json.loads(json.dumps(example_d))
    envelope["halt_trigger"] = None
    _assert_invalid(validator, envelope)


def test_escalate_reviewer_tier_requires_recommended_next_tier(
    validator: jsonschema.Draft202012Validator,
    example_a: dict[str, Any],
) -> None:
    """[S-3 R2] next_action=ESCALATE_REVIEWER_TIER requires non-null recommended_next_tier string."""
    envelope = dict(example_a)
    envelope["status"] = "ESCALATE"
    envelope["next_action"] = "ESCALATE_REVIEWER_TIER"
    envelope["recommended_next_tier"] = None
    _assert_invalid(validator, envelope)


# ---------------------------------------------------------------------------
# Allowlist gating — Req-015, G-2 R2, G-3 R2
# ---------------------------------------------------------------------------


def test_envelope_absent_in_allowlist_raises(fixtures_dir: Path) -> None:
    """[Req-015] [G-2 R2] Migrated family (claude-native @ W1) missing envelope MUST raise.

    No silent fallback for migrated families — the absence is a hard error
    that increments the circuit-breaker counter.
    """
    output = (fixtures_dir / "no_envelope_legacy.md").read_text(encoding="utf-8")
    with pytest.raises(envelope_parser.EnvelopeParseError) as excinfo:
        envelope_parser.parse_or_fallback(
            output,
            agent_id="code-review-high",
            agent_family="claude-native",
            cb_state=_CBStateStub(),
            current_wave="W1",
        )
    assert getattr(excinfo.value, "envelope_required", False) is True


def test_envelope_absent_off_allowlist_falls_back(fixtures_dir: Path) -> None:
    """[Req-015] [G-2 R2] Non-migrated family (codex-bridge @ W1) missing envelope falls back to legacy.

    The W1 allowlist contains only ``claude-native``; ``codex-bridge`` is
    legacy/future-external until W2.
    """
    output = (fixtures_dir / "no_envelope_legacy.md").read_text(encoding="utf-8")
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="codex-reviewer-high",
        agent_family="codex-bridge",
        cb_state=_CBStateStub(),
        current_wave="W1",
    )
    assert result.envelope is None
    assert result.degraded is True
    assert result.legacy_verdict is not None


def test_cb_tripped_family_added_to_legacy_fallback(
    fixtures_dir: Path,
) -> None:
    """[Req-015] [G-3 R2] Once a family is in cb_legacy_fallback_families, envelope-absence falls back.

    Even though claude-native IS in the W1 MIGRATED_AGENT_FAMILIES allowlist,
    a CB trip moves it to ``cb_legacy_fallback_families`` for the rest of the
    epic — subsequent envelope-absence is treated as legacy fallback (no
    further CB increment, no exception).
    """
    output = (fixtures_dir / "no_envelope_legacy.md").read_text(encoding="utf-8")
    cb_state = _CBStateStub(
        cb_legacy_fallback_families=frozenset({"claude-native"}),
    )
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="code-review-high",
        agent_family="claude-native",
        cb_state=cb_state,
        current_wave="W1",
    )
    assert result.envelope is None
    assert result.degraded is True
    assert result.legacy_verdict is not None


# ---------------------------------------------------------------------------
# Legacy prose verdict ladder — TODO-0136 (priority-branch coverage +
# word-boundary regression guards)
# ---------------------------------------------------------------------------


def test_legacy_verdict_halt_priority_wins_over_lower_rungs() -> None:
    """[Req-015] HALT outranks RETURN_TO_WORKER / APPROVE_WITH_NOTES / APPROVE.

    Co-occurring sentinels MUST resolve to the highest-priority verdict on
    the ladder. The fixture intentionally embeds every rung's marker so a
    naive last-match implementation would regress.
    """
    output = (
        "HALT_FOR_OPERATOR — operator authorization required.\n"
        "REJECTED prior round; APPROVED_WITH_NOTES on the previous attempt;\n"
        "APPROVED in round 1.\n"
    )
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "HALT"
    assert verdict.parse_failure is False


def test_legacy_verdict_return_to_worker_priority_wins_over_approve_branches() -> None:
    """[Req-015] RETURN_TO_WORKER outranks APPROVE_WITH_NOTES / APPROVE when no HALT marker is present."""
    output = "REJECTED — APPROVED_WITH_NOTES from a prior round does not override\nthe current rejection. APPROVED in round 1.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "RETURN_TO_WORKER"
    assert verdict.parse_failure is False


def test_legacy_verdict_approve_with_notes_priority_wins_over_bare_approve() -> None:
    """[Req-015] APPROVE_WITH_NOTES outranks bare APPROVED when both are present.

    The ``\\bAPPROVED\\b`` pattern would not match inside ``APPROVED_WITH_NOTES``
    (underscore is a word character), but the bare ``APPROVED`` token also
    appears in the prose — the priority order resolves the ambiguity.
    """
    output = "APPROVED_WITH_NOTES — see findings list.\nAPPROVED overall.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "APPROVE_WITH_NOTES"
    assert verdict.parse_failure is False


def test_legacy_verdict_approve_branch_matches_bare_token_only() -> None:
    """[Req-015] [TODO-0136] Bare APPROVED matches; DISAPPROVED MUST NOT match. Bare BLOCKED matches; UNBLOCKED MUST NOT match.

    Word-boundary anchoring is the load-bearing change. The previous
    ``"APPROVED" in haystack`` substring scan would falsely promote
    ``DISAPPROVED`` to the APPROVE rung; the parallel ``"BLOCKED" in
    haystack`` scan would falsely promote ``UNBLOCKED`` to the
    RETURN_TO_WORKER rung. Both regression cases are pinned here so a
    future "simplification" back to ``in`` would fail the suite.
    """
    output_bare_approve = "APPROVED — looks good, ship it.\n"
    output_disapproved = "DISAPPROVED — the change introduces regressions.\n"
    output_bare_blocked = "BLOCKED — release stalled on QA sign-off.\n"
    output_unblocked = "UNBLOCKED — proceed with the merge.\n"
    assert envelope_parser._legacy_prose_verdict_extractor(output_bare_approve).verdict == "APPROVE"
    assert envelope_parser._legacy_prose_verdict_extractor(output_disapproved).verdict == "ABSTAIN"
    assert envelope_parser._legacy_prose_verdict_extractor(output_bare_blocked).verdict == "RETURN_TO_WORKER"
    assert envelope_parser._legacy_prose_verdict_extractor(output_unblocked).verdict == "ABSTAIN"


def test_legacy_verdict_abstain_when_no_marker_present() -> None:
    """[Req-015] Default verdict is ABSTAIN with parse_failure=True when no marker matches.

    Empty input and prose lacking any priority sentinel both fall through
    to the ABSTAIN rung, marking ``parse_failure=True`` so the orchestrator
    can flag the envelope-absent path for circuit-breaker accounting.
    """
    for output in ("", "Some neutral commentary with no verdict markers.\n"):
        verdict = envelope_parser._legacy_prose_verdict_extractor(output)
        assert verdict.verdict == "ABSTAIN"
        assert verdict.parse_failure is True


def test_legacy_verdict_negation_short_circuits_blocked_to_abstain() -> None:
    """[Req-015] [TODO-0153] [TODO-0153-followup] Lowercase ``not blocked`` falls through to default-rung ABSTAIN under the sentinel-only ladder.

    Sentinel-only refactor (TODO-0153-followup): the legacy fallback
    ladder no longer has informal-phrase positive matchers. Only verbatim
    UPPER_SNAKE_CASE sentinels promote a verdict; everything else falls
    through to ABSTAIN(parse_failure=True). The case-sensitive sentinel
    half of the negation rung covers verbatim sentinel-form negations
    only (``not BLOCKED`` / ``never APPROVED``) — exercised by
    ``test_legacy_verdict_sentinel_negation_short_circuits_to_abstain``.
    Lowercase ``not blocked`` matches no rung (the bare ``\\bBLOCKED\\b``
    pattern is case-sensitive) and falls through to the default ABSTAIN
    rung, which is exactly what this test pins so the orchestrator's
    circuit-breaker still flags ambiguous prose as un-trustable via
    ``parse_failure=True``.
    """
    output = "Review complete: not blocked, proceed with the merge.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "ABSTAIN"
    assert verdict.parse_failure is True


def test_legacy_verdict_negation_short_circuits_approved_to_abstain() -> None:
    """[Req-015] [TODO-0153] [TODO-0153-followup] Lowercase ``not approved`` falls through to default-rung ABSTAIN under the sentinel-only ladder.

    Sentinel-only refactor (TODO-0153-followup): the bare
    ``\\bAPPROVED\\b`` pattern is case-sensitive and does not match
    lowercase ``approved``, so ``not approved — needs revision``
    matches no rung and falls through to default-rung ABSTAIN. This
    pins the default-fallthrough path so the orchestrator's
    circuit-breaker still flags ambiguous prose as un-trustable via
    ``parse_failure=True``. Verbatim sentinel-form negations like
    ``not APPROVED`` are exercised by
    ``test_legacy_verdict_sentinel_negation_short_circuits_to_abstain``;
    case-mixed prefixes (``NOT APPROVED``) are exercised by
    ``test_legacy_verdict_sentinel_negation_handles_mixed_case_prefix``.
    """
    output = "not approved — needs revision before merge.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "ABSTAIN"
    assert verdict.parse_failure is True


def test_legacy_verdict_no_halt_required_short_circuits_to_abstain() -> None:
    """[Req-015] [TODO-0153] [TODO-0153-followup] Informal HALT-adjacent prose falls through to default-rung ABSTAIN under the sentinel-only ladder.

    Sentinel-only refactor (TODO-0153-followup): the HALT rung has
    exactly one pattern (``\\bHALT_FOR_OPERATOR\\b``) — the prior
    ``\\boperator authorization required\\b`` pattern was removed
    because informal-prose matchers create unbounded negation-coverage
    surface. ``no halt required, no merge needed`` matches no rung
    and falls through to default-rung ABSTAIN(parse_failure=True),
    which is the conservative response the legacy fallback path
    promises for ambiguous prose without a verbatim sentinel.
    """
    output = "Review summary: no halt required, no merge needed yet either.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "ABSTAIN"
    assert verdict.parse_failure is True


def test_legacy_verdict_negation_short_circuits_rejected_to_abstain() -> None:
    """[Req-015] [TODO-0153] [TODO-0153-followup] Lowercase ``not rejected`` falls through to default-rung ABSTAIN under the sentinel-only ladder.

    Sentinel-only refactor (TODO-0153-followup): the bare
    ``\\bREJECTED\\b`` pattern is case-sensitive and does not match
    lowercase ``rejected``, so ``not rejected outright`` matches no
    rung and falls through to default-rung ABSTAIN(parse_failure=True).
    Verbatim sentinel-form negations like ``not REJECTED`` are exercised
    by ``test_legacy_verdict_sentinel_negation_short_circuits_to_abstain``.
    """
    output = "Round 2 outcome: not rejected outright — pending follow-up review.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "ABSTAIN"
    assert verdict.parse_failure is True


def test_legacy_verdict_negation_rung_outranks_explicit_halt_marker() -> None:
    """[Req-015] [TODO-0153] [TODO-0153-followup] When a verbatim sentinel-form negation co-occurs with a later positive sentinel, the sentinel-negation rung wins.

    Sentinel-only ladder (TODO-0153-followup): the negation rung
    matches only verbatim UPPER_SNAKE_CASE sentinel negations
    (``not BLOCKED`` / ``never APPROVED`` / etc.). When prose mixes
    a sentinel-form negation with a later positive sentinel, the
    top rung short-circuits before the positive rung fires — the
    conservative-fallback path treats deliberate sentinel-negation
    + sentinel-positive ambiguity as un-trustable and abstains. The
    orchestrator's circuit-breaker handles repeated abstains via
    tier escalation, which is the safer response than picking one
    sentinel over another at this layer.
    """
    output = "Initial pass: not BLOCKED, no critical findings.\nOn reflection — HALT_FOR_OPERATOR — operator escalated.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "ABSTAIN"
    assert verdict.parse_failure is True


def test_legacy_verdict_sentinel_negation_short_circuits_to_abstain() -> None:
    """[Req-015] [TODO-0153-followup] Verbatim sentinel-form negation (``not BLOCKED`` / ``never APPROVED``) routes to ABSTAIN.

    Direct unit on the sentinel-only negation rung. The rung's regex
    is ``\\b(?i:not|never)\\s+(?:HALT_FOR_OPERATOR|REJECTED|BLOCKED|APPROVED_WITH_NOTES|APPROVED)\\b``
    — the ``(?i:...)`` inline flag scopes IGNORECASE to the negation
    prefix only, so ``not``/``Not``/``NOT``/``never``/``Never``/``NEVER``
    all match while the sentinel alternation remains case-sensitive
    (lowercase ``approved``/``blocked`` still fall through to
    default-rung ABSTAIN). This test exercises the lowercase-prefix
    variants only; mixed-case prefixes are exercised by
    ``test_legacy_verdict_sentinel_negation_handles_mixed_case_prefix``.
    Each input deliberately uses the verbatim sentinel; the rung
    short-circuits before any positive rung fires.
    """
    cases = [
        "Result: this is not BLOCKED — proceed.",
        "Result: never APPROVED in this round.",
        "Result: not REJECTED outright; pending follow-up.",
        "Result: never HALT_FOR_OPERATOR before round 3.",
    ]
    for output in cases:
        verdict = envelope_parser._legacy_prose_verdict_extractor(output)
        assert verdict.verdict == "ABSTAIN", f"input: {output!r}"
        assert verdict.parse_failure is True, f"input: {output!r}"


def test_legacy_verdict_sentinel_negation_handles_mixed_case_prefix() -> None:
    """[Req-015] [TODO-0153-followup] [F1] Uppercase / title-case negation prefix MUST short-circuit verbatim sentinels via the sentinel-negation rung.

    Formal review summaries commonly use all-caps verdict prefixes
    (``NOT APPROVED:``, ``NOT BLOCKED:``) to mirror the verbatim
    sentinel style. The sentinel-negation rung uses an inline
    ``(?i:not|never)`` flag scoped to the negation prefix only, so
    case-mixed prefixes match while the sentinel half remains
    case-sensitive (lowercase ``approved`` / ``blocked`` still fall
    through to default-rung ABSTAIN as the docstring promises).
    """
    cases = [
        "Summary: NOT APPROVED — needs revision before merge.",
        "Summary: Not APPROVED — needs revision.",
        "Summary: NOT BLOCKED — proceed.",
        "Summary: Never REJECTED — pending follow-up.",
        "Summary: NOT APPROVED_WITH_NOTES — strict APPROVE only.",
        "Summary: NEVER HALT_FOR_OPERATOR — operator escalation deferred.",
    ]
    for output in cases:
        verdict = envelope_parser._legacy_prose_verdict_extractor(output)
        assert verdict.verdict == "ABSTAIN", f"input: {output!r}"
        assert verdict.parse_failure is True, f"input: {output!r}"


def test_legacy_verdict_negation_short_circuits_looks_good_to_abstain() -> None:
    """[Req-015] [TODO-0153] [gemini-followup] [TODO-0153-followup] ``does not look good`` falls through to default-rung ABSTAIN under the sentinel-only ladder.

    Sentinel-only refactor (TODO-0153-followup): the APPROVE rung's
    informal ``\\blooks good\\b`` matcher was removed entirely. With
    no positive matcher for the phrase, ``does not look good`` matches
    no rung and falls through to default-rung ABSTAIN(parse_failure=True).
    The strict-whitelist design eliminates the unbounded negation-
    coverage class — there is no longer a positive informal-prose
    matcher for negation to leak through.
    """
    output = "Round 2 review: this does not look good — needs more iteration.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "ABSTAIN"
    assert verdict.parse_failure is True


def test_legacy_verdict_negation_short_circuits_ship_it_to_abstain() -> None:
    """[Req-015] [TODO-0153] [gemini-followup] [TODO-0153-followup] ``do not ship it`` falls through to default-rung ABSTAIN under the sentinel-only ladder.

    Sentinel-only refactor (TODO-0153-followup): the APPROVE rung's
    informal ``\\bship it\\b`` matcher was removed entirely. With no
    positive matcher for the phrase, ``do not ship it yet`` matches no
    rung and falls through to default-rung ABSTAIN(parse_failure=True).
    The strict-whitelist design collapses the imperative-vs-participle
    coverage gap because the underlying positive matcher no longer
    exists for negation to leak through.
    """
    output = "Verdict: do not ship it yet — pending compliance review.\n"
    verdict = envelope_parser._legacy_prose_verdict_extractor(output)
    assert verdict.verdict == "ABSTAIN"
    assert verdict.parse_failure is True


# ---------------------------------------------------------------------------
# parse_or_fallback happy-path coverage — TODO-0138, TODO-0140, TODO-0147
# ---------------------------------------------------------------------------


def test_parse_or_fallback_round_trip_with_valid_envelope_fixture(
    fixtures_dir: Path,
) -> None:
    """[Req-001] [Req-002] [TODO-0138] valid_envelope.md round-trips through parse_or_fallback into a fully populated ParseResult.

    The non-error happy path was previously only exercised in piecewise
    helper tests (find_envelope_block, _validate, _normalize_recommended_tier,
    _reroute_at_ceiling). This test pins the end-to-end contract: load
    the canonical valid fixture, run parse_or_fallback, and assert the
    ParseResult shape (envelope present, not degraded, no audit, no
    legacy verdict) plus every Envelope field matches the fixture.
    """
    output = (fixtures_dir / "valid_envelope.md").read_text(encoding="utf-8")
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="code-review-high",
        agent_family="claude-native",
        cb_state=_CBStateStub(),
        current_wave="W1",
    )
    assert result.degraded is False
    assert result.legacy_verdict is None
    assert result.degradation_reason is None
    assert result.audit_annotations is None
    envelope = result.envelope
    assert envelope is not None
    assert envelope.envelope_version == "1"
    assert envelope.agent_id == "code-review-high"
    assert envelope.agent_family == "claude-native"
    assert envelope.agent_effort_tier == "high"
    assert envelope.round == 1
    assert envelope.status == "APPROVED"
    assert envelope.next_action == "APPROVE"
    assert envelope.feedback_to_forward == ()
    assert envelope.recommended_next_tier is None
    assert envelope.halt_trigger is None
    assert envelope.spillover_findings_path is None


def test_parse_or_fallback_normalize_runs_before_reroute_for_gemini_escalate_max() -> None:
    """[S-1 R2] [G-1 R2] [TODO-0140] Gemini ESCALATE→max chain verifies normalize→reroute order end-to-end.

    The pipeline applies _normalize_recommended_tier BEFORE _reroute_at_ceiling.
    A Gemini bridge envelope requesting ESCALATE_REVIEWER_TIER to "max"
    (above the gemini-bridge ceiling of "high") must:

    1. normalize: clamp ``recommended_next_tier`` from "max" to "high"
       (S-1 R2 silent ceiling clamp).
    2. reroute: detect that the now-clamped tier equals the family's
       ceiling, and swap ``agent_family`` to ``claude-native``
       (G-1 R2 ceiling-collision reroute).

    The ordering is load-bearing — if reroute ran first with the raw
    "max" request, no reroute would fire (max != high), and the request
    would fall through unchanged. This test fails if the steps swap.
    """
    output = (
        "# Gemini Review\n\n"
        "Diff is deep; recommend escalation to max tier.\n\n"
        "```json envelope\n"
        + json.dumps(
            {
                "envelope_version": "1",
                "agent_id": "gemini-reviewer-high",
                "agent_family": "gemini-bridge",
                "agent_effort_tier": "high",
                "round": 1,
                "status": "ESCALATE",
                "next_action": "ESCALATE_REVIEWER_TIER",
                "feedback_to_forward": [],
                "recommended_next_tier": "max",
                "halt_trigger": None,
            },
            indent=2,
        )
        + "\n```\n"
    )
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="gemini-reviewer-high",
        agent_family="gemini-bridge",
        cb_state=_CBStateStub(),
        current_wave="W2",
    )
    envelope = result.envelope
    assert envelope is not None
    # normalize step lowered "max" → "high" (gemini-bridge ceiling)
    assert envelope.recommended_next_tier == "high"
    # reroute step swapped agent_family → claude-native (ceiling collision)
    assert envelope.agent_family == "claude-native"
    # reroute audit captures the original family for ledger forwarding
    assert result.audit_annotations is not None
    assert len(result.audit_annotations) == 1
    audit = result.audit_annotations[0]
    assert audit.original_family == "gemini-bridge"
    assert audit.reroute_reason == "ceiling_collision"
    assert audit.agent_id == "gemini-reviewer-high"


def test_parse_or_fallback_abstain_retry_reviewer_empty_feedback_round_trip() -> None:
    """[Req-003] [Req-004] [TODO-0147] ABSTAIN+RETRY_REVIEWER+empty_feedback envelope parses without degradation.

    Schema clause at lines 121-123 pins ABSTAIN→RETRY_REVIEWER pairing.
    No feedback minItems constraint applies to RETRY_REVIEWER (clause at
    lines 117-118 only requires next_action), so an empty
    feedback_to_forward array is schema-conformant.

    Verifies the parser accepts and emits the envelope unchanged — no
    normalization (no recommended_next_tier), no reroute (next_action
    is not ESCALATE_REVIEWER_TIER), no degraded fallback.
    """
    output = (
        "# Code Review — Round 2\n\n"
        "Reviewer encountered an internal error and abstains; orchestrator should retry.\n\n"
        "```json envelope\n"
        + json.dumps(
            {
                "envelope_version": "1",
                "agent_id": "code-review-high",
                "agent_family": "claude-native",
                "agent_effort_tier": "high",
                "round": 2,
                "status": "ABSTAIN",
                "next_action": "RETRY_REVIEWER",
                "feedback_to_forward": [],
                "recommended_next_tier": None,
                "halt_trigger": None,
            },
            indent=2,
        )
        + "\n```\n"
    )
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="code-review-high",
        agent_family="claude-native",
        cb_state=_CBStateStub(),
        current_wave="W1",
    )
    assert result.degraded is False
    assert result.audit_annotations is None
    envelope = result.envelope
    assert envelope is not None
    assert envelope.status == "ABSTAIN"
    assert envelope.next_action == "RETRY_REVIEWER"
    assert envelope.feedback_to_forward == ()
    assert envelope.recommended_next_tier is None
    assert envelope.halt_trigger is None
