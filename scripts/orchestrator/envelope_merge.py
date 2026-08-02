"""Reviewer Output Envelope merge function (Wave 4 of REVIEWER-ENVELOPE-001).

This module provides the deterministic merge primitive that combines
N reviewer envelopes into a single MergeDecision. Per the plan
(tmp/plan-reviewer-output-envelope.md §5.1) the function is pure: no
I/O, no LLM calls, no time dependency, no network access. All routing
is computed from the discrete enum fields on each envelope
(next_action, recommended_next_tier, halt_trigger, agent_family,
per-finding severity and blocking) - the free-form description field
is forwarded verbatim and is NEVER inspected for routing
(Risk-007 / Req-N02).
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.orchestrator.agent_family_registry import (
    bridge_ceilings as _registry_bridge_ceilings,
)
from scripts.orchestrator.envelope_parser import (
    TIER_RANK,
    Envelope,
    Finding,
)

# ---------------------------------------------------------------------------
# Constants (plan §5.1 lines 550-555)
# ---------------------------------------------------------------------------

#: Canonical claude-native family name. Used to identify load-bearing
#: claude-native envelopes for the Cross-Family Asymmetry rule (B-1 R2).
CLAUDE_NATIVE: str = "claude-native"

#: Set of bridge agent-family names. Derived from the agent_family_registry
#: at module import time (TODO-0146 single source of truth) so adding a
#: new bridge family in the registry automatically widens the merge
#: function's bridge-detection set.
BRIDGE_FAMILIES: frozenset[str] = frozenset(_registry_bridge_ceilings().keys())

#: Bridge ``next_action`` values that count as cross-family dissent at
#: xhigh/max (B-5 R2: HALT_FOR_OPERATOR is intentionally absent —
#: operator-auth boundary still HALTs the gate via Rule 1).
DISSENT_BRIDGE_ACTIONS: frozenset[str] = frozenset({"RETURN_TO_WORKER"})

#: Severity floor for cross-family dissent audit (Req-009): only
#: critical/significant findings count; minor and informational do not.
DISSENT_SEVERITIES: frozenset[str] = frozenset({"critical", "significant"})

#: APPROVE-or-advisory next_action set for the unanimous-approve Rule 5.
_APPROVE_LIKE: frozenset[str] = frozenset({"APPROVE", "RETURN_TO_WORKER_ADVISORY"})

#: Gate-effort tiers at which the Cross-Family Asymmetry rule (B-1 R2)
#: fires - bridge RETURN dissent is softened to an audit signal at these
#: tiers only. Centralized here so both
#: :func:`_compute_cross_family_dissent_audit` and
#: :func:`_soften_bridge_dissent` derive their tier guard from one source.
_DISSENT_TIERS: frozenset[str] = frozenset({"xhigh", "max"})

#: Audit-note string emitted when the Frontier-Reservation Rule (B-4 R2)
#: caps a ``max`` recommendation down to ``xhigh``. Used by both Rule 3
#: (concurrent-ESCALATE tier carry on RETURN_TO_WORKER) and Rule 4
#: (the standalone ESCALATE path).
_FRONTIER_RESERVATION_AUDIT_NOTE: str = "frontier_reservation_capped"

#: Severity rank for deterministic feedback aggregation (S-4). Missing
#: keys default to 99 so unknown severities sort to the end.
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "significant": 1,
    "minor": 2,
    "informational": 3,
}


@dataclass(frozen=True)
class CrossFamilyDissentAudit:
    """Audit record for cross-family bridge dissent at xhigh/max (B-1 R2).

    Per plan §5.3, when (a) gate_effort is xhigh or max, (b) all
    claude-native envelopes APPROVE, (c) at least one bridge envelope
    has next_action RETURN_TO_WORKER carrying critical or significant
    blocking findings, the merge function returns APPROVE with this
    audit attached. The orchestrator MUST checkpoint the audit to the
    Execution Ledger as a cross_family_dissent artifact for post-hoc
    operator surfacing.

    HALT_FOR_OPERATOR from a bridge is NOT mapped to dissent (B-5 R2):
    operator-auth boundaries always HALT regardless of agent_family.
    """

    bridge_agent_ids: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class MergeDecision:
    """The deterministic result of merging N reviewer envelopes (plan §5.3).

    :ivar action: Routing primitive; one of APPROVE, RETURN_TO_WORKER,
        ESCALATE, HALT, or RETRY_REVIEWER.
    :ivar feedback: Aggregated blocking findings for RETURN_TO_WORKER /
        HALT / RETRY_REVIEWER / fallback paths.
    :ivar advisory_feedback: Non-blocking findings forwarded as audit
        only when action is APPROVE and at least one envelope carried
        RETURN_TO_WORKER_ADVISORY.
    :ivar recommended_next_tier: Non-null for ESCALATE; G-4 R2 also
        permits a non-null value on RETURN_TO_WORKER when a concurrent
        ESCALATE envelope was present in the same round.
    :ivar halt_trigger: Non-null for HALT. Values come from the same
        enum as the wire envelope's ``halt_trigger`` field
        (``destructive_action``, ``operator_auth_boundary``,
        ``repeated_envelope_failure``, ``null``) — see
        ``docs/schemas/reviewer_envelope.schema.json``. For ``HALT``
        actions sourced from a reviewer envelope (Rule 1), the value
        is copied verbatim from the first HALT envelope's
        ``halt_trigger``. The merge function may also synthesize
        ``"repeated_envelope_failure"`` directly on the empty-envelope
        guard (Rule 0); that value is also a member of the schema
        enum. There are no merge-only halt_trigger values: any value
        the orchestrator checkpoints downstream is round-trip valid
        against the wire schema.
    :ivar audit_note: Optional audit string;
        e.g. frontier_reservation_capped when an ESCALATE recommendation
        of max was capped by the Frontier-Reservation Rule (B-4 R2).
    :ivar cross_family_dissent: Non-null when the §5.1 dissent test
        fires (xhigh/max + claude APPROVE + bridge RETURN dissent).
    :ivar retry_agent_ids: Agent IDs to re-spawn when action is
        RETRY_REVIEWER.
    """

    action: str
    feedback: tuple[Finding, ...] = ()
    advisory_feedback: tuple[Finding, ...] = ()
    recommended_next_tier: str | None = None
    halt_trigger: str | None = None
    audit_note: str | None = None
    cross_family_dissent: CrossFamilyDissentAudit | None = None
    retry_agent_ids: tuple[str, ...] = ()


class EnvelopeMergeError(Exception):
    """Raised for unrecoverable merge invariant violations.

    Per plan §5.1 Rule 4 (Cosmetic R2 - convert assert to raise so
    python -O does not strip the check), the merge function raises
    this when it detects an envelope set that the schema contract
    should have prevented (e.g. ESCALATE envelope set with no
    recommended_next_tier populated). Indicates parser / schema drift,
    not user-recoverable data.
    """


def merge(
    envelopes: list[Envelope],
    *,
    gate_effort_tier: str,
    prior_round_gate_effort_tier: str | None = None,
) -> MergeDecision:
    """Merge N reviewer envelopes into a single MergeDecision.

    Pure function. Precedence (plan §5.1 lines 567-581):

    0. Empty envelope list -> HALT (S-2)
    1. Any HALT_FOR_OPERATOR -> HALT (Req-010)
    2. Any RETRY_REVIEWER -> RETRY_REVIEWER (S-7)
    3. Any RETURN_TO_WORKER -> RETURN_TO_WORKER (G-4 R2: carries
       concurrent ESCALATE tier)
    4. Any ESCALATE_REVIEWER_TIER -> ESCALATE (Frontier-Reservation
       cap, B-4 R2)
    5. Unanimous APPROVE / RETURN_TO_WORKER_ADVISORY -> APPROVE
       (advisory findings forwarded as audit)
    6. Defensive fallback -> RETURN_TO_WORKER with synthetic finding

    Cross-Family Asymmetry (B-1 R2): at xhigh/max gate effort, when
    claude-native APPROVES and bridges raise blocking RETURN dissent
    at critical/significant severity, the result is APPROVE with a
    CrossFamilyDissentAudit attached - bridge dissent at xhigh/max
    does NOT veto, per docs/effort_tiers.md "signal to investigate,
    not automatic veto".
    """
    # Rule 0: empty list guard (S-2)
    if not envelopes:
        empty_msg = "merge() called with empty envelope list - all reviewers failed to produce a parseable envelope. Halt for operator."
        empty_finding = Finding(
            severity="critical",
            description=empty_msg,
            rule_id="merge::empty-envelope-list",
        )
        return MergeDecision(
            action="HALT",
            halt_trigger="repeated_envelope_failure",
            feedback=(empty_finding,),
        )

    # Compute cross_family_dissent audit (B-1) - used by Rule 5 if it
    # fires. NOT a routing decision; only an audit annotation on APPROVE.
    cross_family_dissent_audit = _compute_cross_family_dissent_audit(
        envelopes,
        gate_effort_tier=gate_effort_tier,
    )

    # Rule 1: HALT precedence (Req-010 / B-5 R2 - bridge HALT also halts)
    halts = [e for e in envelopes if e.next_action == "HALT_FOR_OPERATOR"]
    if halts:
        return MergeDecision(
            action="HALT",
            halt_trigger=halts[0].halt_trigger,
            feedback=_aggregate_feedback(halts),
        )

    # Rule 2: RETRY_REVIEWER (S-7) - abstainers explicitly requesting re-spawn
    retries = [e for e in envelopes if e.next_action == "RETRY_REVIEWER"]
    if retries:
        return MergeDecision(
            action="RETRY_REVIEWER",
            retry_agent_ids=tuple(e.agent_id for e in retries),
            feedback=_aggregate_feedback(retries),
            cross_family_dissent=cross_family_dissent_audit,
        )

    # Cross-Family Asymmetry softening (B-1 R2): at xhigh/max, when all
    # claude-native envelopes APPROVE and at least one bridge raises
    # RETURN_TO_WORKER, the bridge RETURN is softened from a routing
    # veto to an audit signal. The bridge envelopes are filtered out
    # of the routing list so Rule 3 ("any RETURN_TO_WORKER -> RETURN")
    # does not fire. The dissent audit (computed above) carries the
    # bridge findings to the orchestrator's ledger checkpoint when
    # the severity floor is met. Per docs/effort_tiers.md the bridge
    # signal at xhigh/max is "to investigate, not automatic veto".
    routing_envelopes = _soften_bridge_dissent(
        envelopes,
        gate_effort_tier=gate_effort_tier,
    )

    # Rule 3: RETURN_TO_WORKER (Req-012). G-4 R2: if a concurrent
    # ESCALATE envelope is present, carry BOTH the feedback AND the
    # next-round tier recommendation.
    returns = [e for e in routing_envelopes if e.next_action == "RETURN_TO_WORKER"]
    if returns:
        concurrent_escalations = [e for e in routing_envelopes if e.next_action == "ESCALATE_REVIEWER_TIER"]
        recommended_next_tier, audit_note = _resolve_escalation_tier(
            concurrent_escalations,
            prior_round_gate_effort_tier=prior_round_gate_effort_tier,
            require_recommendation=False,
        )
        return MergeDecision(
            action="RETURN_TO_WORKER",
            feedback=_aggregate_feedback(returns),
            recommended_next_tier=recommended_next_tier,
            audit_note=audit_note,
            cross_family_dissent=cross_family_dissent_audit,
        )

    # Rule 4: ESCALATE_REVIEWER_TIER (Req-013) - Frontier-Reservation gate (B-4)
    escalations = [e for e in routing_envelopes if e.next_action == "ESCALATE_REVIEWER_TIER"]
    if escalations:
        recommended, esc_audit_note = _resolve_escalation_tier(
            escalations,
            prior_round_gate_effort_tier=prior_round_gate_effort_tier,
            require_recommendation=True,
        )
        return MergeDecision(
            action="ESCALATE",
            recommended_next_tier=recommended,
            audit_note=esc_audit_note,
            cross_family_dissent=cross_family_dissent_audit,
        )

    # Rule 5: Unanimous APPROVE (or APPROVE + RETURN_TO_WORKER_ADVISORY) (Req-011)
    if all(e.next_action in _APPROVE_LIKE for e in routing_envelopes):
        advisories = [e for e in routing_envelopes if e.next_action == "RETURN_TO_WORKER_ADVISORY"]
        return MergeDecision(
            action="APPROVE",
            advisory_feedback=_aggregate_feedback(advisories),
            cross_family_dissent=cross_family_dissent_audit,
        )

    # Rule 6: Defensive fallback - mixed verdict with no other category
    # match. Schema should make this unreachable; defensive code only.
    fallback_finding = Finding(
        severity="significant",
        description="Non-unanimous verdict with no routing category match. Re-run with quorum or escalate to operator.",
        rule_id="merge::non-unanimous-fallback",
    )
    return MergeDecision(
        action="RETURN_TO_WORKER",
        feedback=(fallback_finding,),
        cross_family_dissent=cross_family_dissent_audit,
    )


def _compute_cross_family_dissent_audit(
    envelopes: list[Envelope],
    *,
    gate_effort_tier: str,
) -> CrossFamilyDissentAudit | None:
    """Return the dissent audit when the §5.1 conditions fire, else None.

    Conditions (plan §5.1 lines 724-762):

    - gate_effort_tier is xhigh or max (:data:`_DISSENT_TIERS`)
    - At least one claude-native envelope present AND all approve
    - At least one bridge envelope with next_action RETURN_TO_WORKER
    - At least one finding on those bridge envelopes with severity
      in critical / significant and blocking is not False

    HALT_FOR_OPERATOR from a bridge is intentionally OUT of scope
    (B-5 R2 disambiguation): operator-auth boundary still HALTs.
    ESCALATE_REVIEWER_TIER is also out of scope: it is a
    tier-recommendation, routed by Rule 4.
    """
    if gate_effort_tier not in _DISSENT_TIERS:
        return None
    claude_envs = [e for e in envelopes if e.agent_family == CLAUDE_NATIVE]
    bridge_envs = [e for e in envelopes if e.agent_family in BRIDGE_FAMILIES]
    if not claude_envs or not bridge_envs:
        return None
    if not all(e.next_action == "APPROVE" for e in claude_envs):
        return None
    bridge_blocking = [e for e in bridge_envs if e.next_action in DISSENT_BRIDGE_ACTIONS]
    if not bridge_blocking:
        return None
    dissent_findings = tuple(
        f for e in bridge_blocking for f in e.feedback_to_forward if f.severity in DISSENT_SEVERITIES and f.blocking is not False
    )
    if not dissent_findings:
        return None
    return CrossFamilyDissentAudit(
        bridge_agent_ids=tuple(e.agent_id for e in bridge_blocking),
        findings=dissent_findings,
    )


def _aggregate_feedback(envelopes: list[Envelope]) -> tuple[Finding, ...]:
    """Deterministically concatenate findings across envelopes (S-4).

    Sort by (severity_rank, agent_id, file_path, line_range, description)
    so a random reordering of the input list produces an identical
    output (Req-008 determinism). The ``description`` text is the final
    tie-breaker only — it is sorted on but NEVER branched on for routing
    (Risk-007 trojan-horse defense). Routing decisions are computed
    earlier in :func:`merge` from discrete enum fields exclusively;
    this sort key drives output ordering, not control flow.
    """
    pairs: list[tuple[Finding, str]] = [(f, e.agent_id) for e in envelopes for f in e.feedback_to_forward]
    pairs.sort(
        key=lambda pair: (
            _SEVERITY_RANK.get(pair[0].severity, 99),
            pair[1],
            pair[0].file_path or "",
            pair[0].line_range or "",
            pair[0].description,  # tie-breaker only; never branched on (Risk-007).
        )
    )
    return tuple(f for f, _ in pairs)


def _soften_bridge_dissent(
    envelopes: list[Envelope],
    *,
    gate_effort_tier: str,
) -> list[Envelope]:
    """Filter bridge RETURN_TO_WORKER from routing under the asymmetry rule (B-1 R2).

    At gate_effort_tier in :data:`_DISSENT_TIERS`, when ALL claude-native
    envelopes are APPROVE and at least one bridge envelope has
    next_action RETURN_TO_WORKER, the bridge RETURNs are removed
    from the returned list so the downstream routing rules treat
    them as absent. The dissent audit is computed separately by
    :func:`_compute_cross_family_dissent_audit` and attached to the
    final MergeDecision; the bridge findings are NOT silently
    dropped, only their veto power is.

    Outside the asymmetry conditions, returns the input list
    unchanged. Bridge HALT_FOR_OPERATOR and bridge
    ESCALATE_REVIEWER_TIER are NEVER softened (B-5 R2: operator-auth
    HALT routes via Rule 1; ESCALATE is a tier-recommendation per
    Rule 4).
    """
    if gate_effort_tier not in _DISSENT_TIERS:
        return list(envelopes)
    claude_envs = [e for e in envelopes if e.agent_family == CLAUDE_NATIVE]
    bridge_envs = [e for e in envelopes if e.agent_family in BRIDGE_FAMILIES]
    if not claude_envs or not bridge_envs:
        return list(envelopes)
    if not all(e.next_action == "APPROVE" for e in claude_envs):
        return list(envelopes)
    if not any(e.next_action == "RETURN_TO_WORKER" for e in bridge_envs):
        return list(envelopes)
    return [e for e in envelopes if not (e.agent_family in BRIDGE_FAMILIES and e.next_action == "RETURN_TO_WORKER")]


def _resolve_escalation_tier(
    escalation_envelopes: list[Envelope],
    *,
    prior_round_gate_effort_tier: str | None,
    require_recommendation: bool,
) -> tuple[str | None, str | None]:
    """Pick the next-round tier from a set of ESCALATE envelopes (B-4 R2).

    Returns ``(recommended_next_tier, audit_note)`` where:

    - ``recommended_next_tier`` is the highest tier across the input
      envelopes' ``recommended_next_tier`` fields (TIER_RANK ordering),
      capped from ``"max"`` to ``"xhigh"`` when the prior round did
      not actually run at xhigh (Frontier-Reservation Rule).
    - ``audit_note`` is :data:`_FRONTIER_RESERVATION_AUDIT_NOTE` when
      the cap fired, else ``None``.

    When ``require_recommendation`` is True (Rule 4: standalone
    ESCALATE), an empty / all-None ``recommended_next_tier`` set
    raises :class:`EnvelopeMergeError` (Cosmetic R2 schema-drift
    guard). When False (Rule 3: RETURN_TO_WORKER carrying a
    concurrent ESCALATE), an empty input is treated as "no concurrent
    escalation present" and ``(None, None)`` is returned - the
    RETURN_TO_WORKER routing path simply omits the next-round tier.
    """
    candidates = [e.recommended_next_tier for e in escalation_envelopes if e.recommended_next_tier]
    if not candidates:
        if require_recommendation:
            # Cosmetic R2: convert assert to raise so python -O does not
            # strip the schema-drift guard.
            msg = "ESCALATE envelopes must carry recommended_next_tier per schema; received empty set. Possible parser/schema drift."
            raise EnvelopeMergeError(msg)
        return None, None
    raw_recommended = max(candidates, key=TIER_RANK.__getitem__)
    if raw_recommended == "max" and prior_round_gate_effort_tier != "xhigh":
        return "xhigh", _FRONTIER_RESERVATION_AUDIT_NOTE
    return raw_recommended, None
