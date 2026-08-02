"""End-to-end integration tests for envelope routing.

Epic: REVIEWER-ENVELOPE-001 (Wave 4 RED phase) - plan §10.2
(``tmp/plan-reviewer-output-envelope.md`` lines 1240-1248).

The integration test synthesizes three reviewer outputs (one
claude-native, one codex-bridge, one gemini-bridge), runs them
through the parser + merge pipeline, and asserts the orchestrator's
routing surface matches the plan §5.2 truth table at both gate
effort tiers.

Each case is the deterministic composition of:

1. ``parse_or_fallback`` per envelope (W1 surface; not exercised
   here for the full envelope-text path - the test fixtures emit
   envelopes as already-parsed Envelope dataclass instances; the
   focus is the W4 merge surface).
2. ``merge`` of the parsed envelope set (W4 GREEN scope - tests
   in this module fail with NotImplementedError until then).

Coverage:

- B-1 R2: at gate=high, no asymmetry rule fires - bridge RETURN
  flips the merge result to RETURN_TO_WORKER.
- B-1 R2: at gate=xhigh, the same envelope set produces APPROVE
  with a non-null cross_family_dissent audit - faithful to
  ``docs/effort_tiers.md`` "signal to investigate, not automatic
  veto".
- B-5 R2: bridge HALT_FOR_OPERATOR with halt_trigger
  operator_auth_boundary at xhigh routes to HALT, NEVER to
  cross_family_dissent (operator-auth boundary never softened).
- Req-015: mixed envelope+legacy fallback - one legacy bridge
  parsed via the prose extractor, one Claude reviewer with a real
  envelope. The merge function evaluates only the envelopes that
  successfully parsed; the orchestrator emits the degraded
  artifact alongside.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.orchestrator.envelope_circuit_breaker import CircuitBreakerState
from scripts.orchestrator.envelope_merge import (
    CrossFamilyDissentAudit,
    merge,
)
from scripts.orchestrator.envelope_parser import (
    Envelope,
    Finding,
    parse_or_fallback,
)


@dataclass(frozen=True)
class _CBStateStub:
    """Minimal cb_state stub for parse_or_fallback (mirrors the parser tests)."""

    cb_legacy_fallback_families: frozenset[str] = frozenset()


def _envelope(
    *,
    agent_id: str,
    agent_family: str,
    next_action: str,
    status: str | None = None,
    feedback: list[Finding] | None = None,
    halt_trigger: str | None = None,
    recommended_next_tier: str | None = None,
) -> Envelope:
    """Construct an Envelope for the e2e routing fixtures."""
    if status is None:
        status_map = {
            "APPROVE": "APPROVED",
            "RETURN_TO_WORKER": "REJECTED",
            "HALT_FOR_OPERATOR": "BLOCKED",
            "ESCALATE_REVIEWER_TIER": "ESCALATE",
            "RETRY_REVIEWER": "ABSTAIN",
            "RETURN_TO_WORKER_ADVISORY": "APPROVED_WITH_NOTES",
        }
        status = status_map[next_action]
    return Envelope(
        envelope_version="1",
        agent_id=agent_id,
        agent_family=agent_family,
        agent_effort_tier="high",
        round=1,
        status=status,
        next_action=next_action,
        feedback_to_forward=tuple(feedback or ()),
        recommended_next_tier=recommended_next_tier,
        halt_trigger=halt_trigger,
    )


def test_e2e_three_reviewers_high_returns_to_worker() -> None:
    """[B-1 R2 / Req-012] gate=high: claude APPROVE + codex APPROVE + gemini RETURN(critical) -> RETURN_TO_WORKER, no dissent.

    Below xhigh, the Cross-Family Asymmetry rule does NOT fire.
    The bridge's blocking RETURN flips the merge result and is
    aggregated into the feedback array.
    """
    gemini_finding = Finding(
        severity="critical",
        description="Gemini found a depth issue in the merge sort buffer.",
        file_path="src/sort.py",
        line_range="42-58",
        blocking=True,
    )
    envelopes = [
        _envelope(agent_id="code-review-high", agent_family="claude-native", next_action="APPROVE"),
        _envelope(agent_id="codex-reviewer-high", agent_family="codex-bridge", next_action="APPROVE"),
        _envelope(
            agent_id="gemini-reviewer-high",
            agent_family="gemini-bridge",
            next_action="RETURN_TO_WORKER",
            feedback=[gemini_finding],
        ),
    ]
    decision = merge(envelopes, gate_effort_tier="high")
    assert decision.action == "RETURN_TO_WORKER"
    assert decision.cross_family_dissent is None
    descriptions = [f.description for f in decision.feedback]
    assert any("Gemini found a depth issue" in d for d in descriptions)


def test_e2e_three_reviewers_xhigh_approves_with_dissent_audit() -> None:
    """[B-1 R2] gate=xhigh: same set -> APPROVE with non-null cross_family_dissent (NOT HALT).

    Faithful to docs/effort_tiers.md "signal to investigate, not
    automatic veto". The earlier v2 plan asserted HALT here; v3
    reverted to APPROVE+audit and the cross_family_dissent_unresolvable
    halt_trigger value was removed from the schema (Req-006).
    """
    gemini_finding = Finding(
        severity="critical",
        description="Gemini found a depth issue in the merge sort buffer.",
        file_path="src/sort.py",
        line_range="42-58",
        blocking=True,
    )
    envelopes = [
        _envelope(agent_id="code-review-xhigh", agent_family="claude-native", next_action="APPROVE"),
        _envelope(agent_id="codex-reviewer-xhigh", agent_family="codex-bridge", next_action="APPROVE"),
        _envelope(
            agent_id="gemini-reviewer-high",
            agent_family="gemini-bridge",
            next_action="RETURN_TO_WORKER",
            feedback=[gemini_finding],
        ),
    ]
    decision = merge(envelopes, gate_effort_tier="xhigh", prior_round_gate_effort_tier="high")
    assert decision.action == "APPROVE"
    assert isinstance(decision.cross_family_dissent, CrossFamilyDissentAudit)
    assert "gemini-reviewer-high" in decision.cross_family_dissent.bridge_agent_ids
    audit_descriptions = [f.description for f in decision.cross_family_dissent.findings]
    assert any("Gemini found a depth issue" in d for d in audit_descriptions)


def test_e2e_three_reviewers_xhigh_bridge_halt_still_halts() -> None:
    """[B-5 R2] gate=xhigh: bridge HALT(operator_auth_boundary) -> HALT, no cross_family_dissent.

    Operator-auth boundaries are NEVER softened to audit-only,
    regardless of agent_family or gate effort. HALT routing wins
    via Rule 1; the dissent audit is suppressed because Rule 1
    short-circuits before Rule 5.
    """
    halt_finding = Finding(
        severity="critical",
        description="PR touches .claude/settings.json - operator authorization required.",
        file_path=".claude/settings.json",
        line_range="12-18",
        blocking=True,
    )
    envelopes = [
        _envelope(agent_id="code-review-xhigh", agent_family="claude-native", next_action="APPROVE"),
        _envelope(agent_id="codex-reviewer-xhigh", agent_family="codex-bridge", next_action="APPROVE"),
        _envelope(
            agent_id="gemini-reviewer-high",
            agent_family="gemini-bridge",
            next_action="HALT_FOR_OPERATOR",
            halt_trigger="operator_auth_boundary",
            feedback=[halt_finding],
        ),
    ]
    decision = merge(envelopes, gate_effort_tier="xhigh", prior_round_gate_effort_tier="high")
    assert decision.action == "HALT"
    assert decision.halt_trigger == "operator_auth_boundary"
    assert decision.cross_family_dissent is None


def test_e2e_mixed_envelope_legacy_fallback() -> None:
    """[Req-015] One envelope-emitting Claude reviewer + one legacy prose-only bridge -> merge sees only the envelope.

    The migration-window safety path. The legacy bridge's prose is
    parsed by parse_or_fallback into a degraded ParseResult with a
    LegacyVerdict.verdict of APPROVE. The orchestrator emits the
    degraded artifact alongside; the merge function only sees the
    envelopes that successfully parsed.

    For this test we model the situation by:

    1. Driving parse_or_fallback on the legacy prose with a stub
       cb_state and current_wave=W4. Because the bridge fixture
       agent_family is forward-compat (copilot-bridge has no
       waves) the parser falls back to LegacyVerdict; the
       orchestrator does NOT pass that ParseResult into merge().
    2. Constructing a synthetic 1-envelope merge input from the
       Claude reviewer's parsed Envelope and asserting APPROVE.

    This mirrors the orchestrator's real flow: the merge function
    is called only with successfully-parsed envelopes, and the
    degraded artifact is checkpointed to the ledger separately.
    """
    legacy_prose = "looks good to me\n\napproved with no further comments"
    cb_state = _CBStateStub()
    legacy_result = parse_or_fallback(
        legacy_prose,
        agent_id="copilot-reviewer",
        agent_family="copilot-bridge",
        cb_state=cb_state,
        current_wave="W4",
    )
    # copilot-bridge has empty waves in the registry, so envelope
    # absence falls back to a degraded LegacyVerdict, not an error.
    assert legacy_result.degraded is True
    assert legacy_result.legacy_verdict is not None
    assert legacy_result.legacy_verdict.verdict == "APPROVE"

    # The orchestrator only feeds successfully-parsed envelopes to
    # merge(). Here that is the lone Claude reviewer.
    parsed_envelopes = [
        _envelope(agent_id="code-review-high", agent_family="claude-native", next_action="APPROVE"),
    ]
    decision = merge(parsed_envelopes, gate_effort_tier="high")
    assert decision.action == "APPROVE"


def test_e2e_circuit_breaker_state_threads_into_merge_path() -> None:
    """[Req-015 / G-3 R2] CB-tripped family falls back at parser, then merge() handles the surviving envelope set.

    End-to-end check that CircuitBreakerState (W4 dataclass)
    duck-types correctly into envelope_parser.parse_or_fallback
    via the cb_legacy_fallback_families attribute, and that merge()
    is invoked on the surviving envelopes. After codex-bridge has
    tripped, an absent envelope from codex-bridge falls back to a
    degraded LegacyVerdict; merge() is then called only on the
    successfully parsed Claude envelope and approves.
    """
    cb_state = CircuitBreakerState(
        epic_id="EPIC-E2E-001",
        cb_legacy_fallback_families=frozenset({"codex-bridge"}),
        orchestrator_tier="high",
    )
    # Use a prose phrase that matches the W1 parser's documented
    # `_legacy_prose_verdict_extractor` patterns (plan §9 lines
    # 1118-1131). Lowercase "approved" alone does not match any of
    # the priority-ordered patterns ("APPROVED" is case-sensitive
    # ALL-CAPS; the lowercase phrases are "looks good" / "ship it" /
    # "approved with notes"). Use "looks good" to exercise the
    # APPROVE branch faithfully.
    legacy_prose = "looks good to me"
    legacy_result = parse_or_fallback(
        legacy_prose,
        agent_id="codex-reviewer-high",
        agent_family="codex-bridge",
        cb_state=cb_state,
        current_wave="W4",
    )
    assert legacy_result.degraded is True
    assert legacy_result.legacy_verdict is not None
    assert legacy_result.legacy_verdict.verdict == "APPROVE"

    # The orchestrator now invokes merge() on the surviving
    # successfully-parsed envelopes (just the Claude reviewer in
    # this scenario). merge() is the W4 GREEN scope and raises
    # NotImplementedError until then - the load-bearing RED signal
    # for this end-to-end path.
    parsed_envelopes = [
        _envelope(agent_id="code-review-high", agent_family="claude-native", next_action="APPROVE"),
    ]
    decision = merge(parsed_envelopes, gate_effort_tier="high")
    assert decision.action == "APPROVE"
