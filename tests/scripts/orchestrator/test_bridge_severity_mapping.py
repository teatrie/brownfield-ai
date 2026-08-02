"""Bridge CLI-prose → envelope translation contract tests (plan §6.1.1, B-5).

Epic: REVIEWER-ENVELOPE-001 (Wave 2).

The bridge agents (`codex-reviewer*`, `gemini-reviewer*`) translate external
CLI prose output into structured envelopes. Per the NG-2 exception, this
translation is a logic change scoped strictly to envelope authorship — the
bridge MUST NOT re-rubric, re-rank, or invent findings the CLI did not raise.

These tests are the contract surface: each row in the §6.1.1 mapping table
is exercised by feeding a canned bridge envelope (representing the bridge's
post-translation output for a given CLI prose conclusion) through the parser
and asserting the resulting `Envelope` / `Finding` values match the table
exactly. The parser is the only deterministic layer that can be tested
without an LLM in the loop; the agent-side translation is contract-checked
via the lint test (``tests/lint/test_reviewer_envelope_required.py``) that
asserts the §6.1.1 table is embedded verbatim in each bridge agent body.

Each test docstring cites at least one Requirement ID per the TDD
traceability mandate (CLAUDE.md §13).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from scripts.orchestrator import envelope_parser

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = _REPO_ROOT / "docs" / "schemas" / "reviewer_envelope.schema.json"
_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "envelopes"


@dataclass(frozen=True)
class _CBStateStub:
    """Minimal stand-in for the GREEN-phase ``CircuitBreakerState``.

    The parser only consumes ``cb_legacy_fallback_families`` (a set of
    agent-family strings); tests pin the minimum surface needed.
    """

    cb_legacy_fallback_families: frozenset[str] = frozenset()


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


def _bridge_envelope(
    *,
    agent_family: str,
    agent_id: str,
    agent_effort_tier: str,
    status: str,
    next_action: str,
    findings: list[dict[str, Any]] | None = None,
    recommended_next_tier: str | None = None,
    halt_trigger: str | None = None,
) -> dict[str, Any]:
    """Construct a minimally-shaped bridge envelope dict for schema/parser tests.

    The factory keeps the test rows close to the §6.1.1 table — each test
    constructs the envelope it expects from a given CLI prose conclusion
    via this helper rather than re-typing the boilerplate keys.
    """
    return {
        "envelope_version": "1",
        "agent_id": agent_id,
        "agent_family": agent_family,
        "agent_effort_tier": agent_effort_tier,
        "round": 1,
        "status": status,
        "next_action": next_action,
        "feedback_to_forward": findings or [],
        "recommended_next_tier": recommended_next_tier,
        "halt_trigger": halt_trigger,
    }


# ---------------------------------------------------------------------------
# §6.1.1 severity-mapping table — one test per row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "next_action", "blocking"),
    [
        ("critical", "RETURN_TO_WORKER", True),
        ("significant", "RETURN_TO_WORKER", True),
        ("minor", "RETURN_TO_WORKER_ADVISORY", False),
        ("informational", "RETURN_TO_WORKER_ADVISORY", False),
    ],
)
def test_severity_mapping_row_round_trips_through_schema(
    validator: jsonschema.Draft202012Validator,
    severity: str,
    next_action: str,
    blocking: bool,
) -> None:
    """[Req-007] [B-5] Each §6.1.1 severity row produces a schema-valid envelope.

    Asserts the four severity → next_action → blocking combinations from
    the §6.1.1 table are individually schema-valid. A row that drifts
    (e.g., ``minor`` → ``RETURN_TO_WORKER`` without ``RETURN_TO_WORKER_ADVISORY``
    routing) would still validate against the schema today — the contract
    is that the BRIDGE produces the right combination per the table; the
    schema only enforces the enum domains. The complementary lint test
    (``test_each_bridge_scope_agent_has_severity_mapping_table``) ensures
    the table is in the agent body verbatim, so the bridge has the
    information it needs to apply the row.
    """
    payload = _bridge_envelope(
        agent_family="codex-bridge",
        agent_id="codex-reviewer-high",
        agent_effort_tier="high",
        status="REJECTED" if blocking else "APPROVED_WITH_NOTES",
        next_action=next_action,
        findings=[
            {
                "severity": severity,
                "file_path": "scripts/example.py",
                "line_range": "10-12",
                "description": "[codex@high] Verbatim CLI prose conclusion preserved here.",
                "blocking": blocking,
            },
        ],
    )
    validator.validate(payload)


@pytest.mark.parametrize(
    ("severity", "blocking"),
    [
        ("critical", True),
        ("significant", True),
        ("minor", False),
        ("informational", False),
    ],
)
def test_severity_mapping_blocking_flag_preserved_through_parser(
    severity: str,
    blocking: bool,
) -> None:
    """[Req-007] [B-2] Bridge `blocking` flag survives parse_or_fallback round-trip.

    The merge function (W4) consumes `blocking` to decide whether bridge
    minor/informational findings can trigger `RETURN_TO_WORKER`. If the
    parser drops or coerces the flag, the merge function would silently
    over- or under-block. This test pins the flag's transit fidelity for
    each §6.1.1 severity row. ``status`` is set to a row-compatible
    value so the schema's status × next_action matrix accepts the payload.
    """
    next_action = "RETURN_TO_WORKER" if blocking else "RETURN_TO_WORKER_ADVISORY"
    status = "REJECTED" if blocking else "APPROVED_WITH_NOTES"
    payload = _bridge_envelope(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer-high",
        agent_effort_tier="high",
        status=status,
        next_action=next_action,
        findings=[
            {
                "severity": severity,
                "description": "[gemini@high] Verbatim CLI prose conclusion preserved here.",
                "blocking": blocking,
            },
        ],
    )
    output = "# Gemini Review\n\n```json envelope\n" + json.dumps(payload) + "\n```\n"
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="gemini-reviewer-high",
        agent_family="gemini-bridge",
        cb_state=_CBStateStub(),
        current_wave="W2",
    )
    assert result.envelope is not None
    assert len(result.envelope.feedback_to_forward) == 1
    finding = result.envelope.feedback_to_forward[0]
    assert finding.severity == severity
    assert finding.blocking is blocking


# ---------------------------------------------------------------------------
# §6.1.1 verdict-mapping table — one test per row
# ---------------------------------------------------------------------------


def test_verdict_mapping_approved_no_findings(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5] Verdict row: 'approved'/'looks good' → APPROVED + APPROVE."""
    payload = _bridge_envelope(
        agent_family="codex-bridge",
        agent_id="codex-reviewer",
        agent_effort_tier="medium",
        status="APPROVED",
        next_action="APPROVE",
    )
    validator.validate(payload)


def test_verdict_mapping_approved_with_notes_minor_only_routes_to_approve(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5] Verdict row: 'approved with notes' + only minor findings → APPROVE.

    Per §6.1.1: "APPROVE if all findings minor/informational; RETURN_TO_WORKER
    if any critical/significant". This test pins the APPROVE branch.
    """
    payload = _bridge_envelope(
        agent_family="codex-bridge",
        agent_id="codex-reviewer-high",
        agent_effort_tier="high",
        status="APPROVED_WITH_NOTES",
        next_action="APPROVE",
        findings=[
            {
                "severity": "minor",
                "description": "[codex@high] Consider renaming local variable for clarity.",
                "blocking": False,
            },
        ],
    )
    validator.validate(payload)


def test_verdict_mapping_approved_with_notes_critical_routes_to_return(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5] Verdict row: 'approved with notes' + critical finding → RETURN_TO_WORKER.

    The complementary branch of the conditional in the verdict table:
    a critical finding promotes APPROVED_WITH_NOTES + APPROVE to
    APPROVED_WITH_NOTES + RETURN_TO_WORKER per §6.1.1.
    """
    payload = _bridge_envelope(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer-high",
        agent_effort_tier="high",
        status="APPROVED_WITH_NOTES",
        next_action="RETURN_TO_WORKER",
        findings=[
            {
                "severity": "critical",
                "description": "[gemini@high] MUST address this before merge.",
                "blocking": True,
            },
        ],
    )
    validator.validate(payload)


def test_verdict_mapping_rejected_routes_to_return(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5] Verdict row: 'rejected'/'do not merge' → REJECTED + RETURN_TO_WORKER."""
    payload = _bridge_envelope(
        agent_family="codex-bridge",
        agent_id="codex-reviewer-high",
        agent_effort_tier="high",
        status="REJECTED",
        next_action="RETURN_TO_WORKER",
        findings=[
            {
                "severity": "critical",
                "description": "[codex@high] Do not merge: data-loss risk in migration.",
                "blocking": True,
            },
        ],
    )
    validator.validate(payload)


def test_verdict_mapping_blocked_operator_auth_routes_to_halt(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5] Verdict row: 'operator authorization required' → BLOCKED + HALT_FOR_OPERATOR.

    The §6.1.1 row requires the `halt_trigger` to be set to
    `operator_auth_boundary` (the disambiguation note in B-5 R2 makes
    this the gate-effort-independent contract — operator-auth boundaries
    NEVER soften to audit-only regardless of agent_family).
    """
    payload = _bridge_envelope(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer-high",
        agent_effort_tier="high",
        status="BLOCKED",
        next_action="HALT_FOR_OPERATOR",
        findings=[
            {
                "severity": "critical",
                "file_path": ".claude/settings.json",
                "description": "[gemini@high] PR adds Bash(task aws:*) to the production allowlist — operator authorization required per CLAUDE.md §17.",
                "blocking": True,
            },
        ],
        halt_trigger="operator_auth_boundary",
    )
    validator.validate(payload)


def test_verdict_mapping_escalate_routes_to_escalate_reviewer_tier(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5] Verdict row: 'cannot determine' → ESCALATE + ESCALATE_REVIEWER_TIER.

    The recommended_next_tier MUST be set per §4.1.1 if/then. The bridge
    is responsible for choosing a tier above its current pin; the parser's
    `_normalize_recommended_tier` will cap it at the bridge's family ceiling
    (codex=xhigh, gemini=high) and `_reroute_at_ceiling` will swap the
    family to claude-native if the requested tier IS the ceiling — see the
    parser-level test at `test_envelope_parser.py::test_reroute_at_ceiling*`.
    """
    payload = _bridge_envelope(
        agent_family="codex-bridge",
        agent_id="codex-reviewer-high",
        agent_effort_tier="high",
        status="ESCALATE",
        next_action="ESCALATE_REVIEWER_TIER",
        recommended_next_tier="xhigh",
    )
    validator.validate(payload)


def test_verdict_mapping_abstain_routes_to_retry_reviewer(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5] Verdict row: 'cannot reach a verdict' → ABSTAIN + RETRY_REVIEWER.

    ABSTAIN is the truly-indeterminate row. Per the schema's allOf clause,
    ABSTAIN status REQUIRES next_action == RETRY_REVIEWER (any other
    next_action is a schema violation).
    """
    payload = _bridge_envelope(
        agent_family="gemini-bridge",
        agent_id="gemini-reviewer",
        agent_effort_tier="medium",
        status="ABSTAIN",
        next_action="RETRY_REVIEWER",
    )
    validator.validate(payload)


# ---------------------------------------------------------------------------
# Edge-case fixtures (Wave 2 plan §10.1)
# ---------------------------------------------------------------------------


def test_bridge_escalate_at_ceiling_gemini_rerouted_to_claude(
    fixtures_dir: Path,
) -> None:
    """[G-1 R2] Gemini ESCALATE at its own ceiling (high) → reroute to claude-native.

    Loads the `bridge_escalate_at_ceiling_gemini.md` fixture (Gemini bridge
    requesting ESCALATE_REVIEWER_TIER with recommended_next_tier=high, which
    IS the gemini-bridge ceiling). The parser's `_reroute_at_ceiling`
    primitive must swap `agent_family` to `claude-native` and emit a
    `RerouteAudit` on `ParseResult.audit_annotations` — without changing
    any other envelope field, and without violating the schema's
    `additionalProperties: false` invariant.
    """
    output = (fixtures_dir / "bridge_escalate_at_ceiling_gemini.md").read_text(encoding="utf-8")
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="gemini-reviewer-high",
        agent_family="gemini-bridge",
        cb_state=_CBStateStub(),
        current_wave="W2",
    )
    assert result.envelope is not None
    assert result.envelope.agent_family == "claude-native"
    assert result.envelope.recommended_next_tier == "high"
    assert result.audit_annotations is not None
    assert len(result.audit_annotations) == 1
    audit = result.audit_annotations[0]
    assert audit.original_family == "gemini-bridge"
    assert audit.reroute_reason == "ceiling_collision"


def test_bridge_blocking_dissent_critical_parses_with_blocking_true(
    fixtures_dir: Path,
) -> None:
    """[Req-007] [B-2] Bridge critical-severity dissent fixture parses with blocking=true preserved.

    Loads `bridge_blocking_dissent_critical.md` (codex bridge, REJECTED +
    RETURN_TO_WORKER, single critical finding with blocking=true).
    Asserts the parser preserves all four load-bearing values — severity,
    next_action, blocking, status — that the W4 merge function will
    consume to decide whether bridge dissent triggers a `cross_family_dissent`
    audit artifact.
    """
    output = (fixtures_dir / "bridge_blocking_dissent_critical.md").read_text(encoding="utf-8")
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="codex-reviewer-high",
        agent_family="codex-bridge",
        cb_state=_CBStateStub(),
        current_wave="W2",
    )
    assert result.envelope is not None
    env = result.envelope
    assert env.status == "REJECTED"
    assert env.next_action == "RETURN_TO_WORKER"
    assert len(env.feedback_to_forward) == 1
    finding = env.feedback_to_forward[0]
    assert finding.severity == "critical"
    assert finding.blocking is True


def test_bridge_escalate_not_dissent_carries_no_findings(
    fixtures_dir: Path,
) -> None:
    """[Req-009] Bridge ESCALATE_REVIEWER_TIER is a tier-recommendation, NOT dissent.

    Loads `bridge_escalate_not_dissent.md` (codex bridge, ESCALATE +
    ESCALATE_REVIEWER_TIER, empty `feedback_to_forward`,
    recommended_next_tier="xhigh"). Per Req-009: the dissent rule fires
    only on RETURN_TO_WORKER with critical/significant findings — NOT on
    ESCALATE_REVIEWER_TIER. This test pins the bridge envelope shape that
    the W4 merge function must NOT classify as dissent.

    The fixture's recommended_next_tier="xhigh" equals the codex-bridge
    ceiling (xhigh). Equality (not strict greater-than) is the trigger
    for `_reroute_at_ceiling`, so the reroute branch fires here even
    though the fixture is named "not dissent" — exercising the
    G-1 R2 ceiling-collision path on a bridge ESCALATE_REVIEWER_TIER.
    """
    output = (fixtures_dir / "bridge_escalate_not_dissent.md").read_text(encoding="utf-8")
    result = envelope_parser.parse_or_fallback(
        output,
        agent_id="codex-reviewer",
        agent_family="codex-bridge",
        cb_state=_CBStateStub(),
        current_wave="W2",
    )
    assert result.envelope is not None
    env = result.envelope
    assert env.next_action == "ESCALATE_REVIEWER_TIER"
    assert env.feedback_to_forward == ()
    assert env.recommended_next_tier == "xhigh"
    # Ceiling reroute IS expected — codex's ceiling is xhigh, requested == xhigh.
    assert env.agent_family == "claude-native"
    assert result.audit_annotations is not None
    assert result.audit_annotations[0].reroute_reason == "ceiling_collision"


# ---------------------------------------------------------------------------
# Forbidden bridge behaviors — schema-level enforcement smoke
# ---------------------------------------------------------------------------


def test_unknown_severity_value_rejected_by_schema(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """[Req-007] [B-5 forbidden behaviors] Severity outside the §6.1.1 enum is a schema violation.

    The §6.1.1 forbidden-behaviors list includes "Inventing severity
    classifications not derivable from the mapping table." The schema's
    severity enum is the load-bearing enforcement: the bridge cannot ship
    a `severity="unknown"` finding through the schema gate, so the
    forbidden behavior is structurally impossible.
    """
    payload = _bridge_envelope(
        agent_family="codex-bridge",
        agent_id="codex-reviewer-high",
        agent_effort_tier="high",
        status="REJECTED",
        next_action="RETURN_TO_WORKER",
        findings=[
            {
                "severity": "ultracritical",
                "description": "[codex@high] Bridge invented a severity outside the §6.1.1 enum.",
                "blocking": True,
            },
        ],
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)
