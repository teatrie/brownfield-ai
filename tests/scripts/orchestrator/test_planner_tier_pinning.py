"""Unit tests for the planner-pinned reviewer-tier resolver.

Epic: REVIEWER-ENVELOPE-001 (Wave 4 RED phase).

The resolver under test lives at
``scripts/orchestrator/planner_tier_pinning.py`` and decides the
reviewer effort tier for the NEXT round of a gate given:

- The planner-pinned tier (Req-014).
- The MergeDecision from the round that just completed.
- The current round number (1-based).
- The prior round's actual gate effort tier (Frontier-Reservation
  cap).
- The count of consecutive ESCALATE merge decisions on this gate
  (Risk-006 auto-promotion).

Behavior is governed by Req-014, Req-N06 (no downgrade), S-8
(round-1 escalation bypass), B-4 R2 (Frontier-Reservation gate),
and Risk-006 (two-consecutive-ESCALATE auto-promotion).

Every test docstring cites at least one Req-ID per the W1/W2/W3
RED-phase precedent.
"""

from __future__ import annotations

import pytest

from scripts.orchestrator.envelope_merge import MergeDecision
from scripts.orchestrator.planner_tier_pinning import resolve_next_round_tier


def test_orchestrator_honors_pin() -> None:
    """[Req-014] When the merge decision is APPROVE, the next-round tier matches the planner pin."""
    decision = MergeDecision(action="APPROVE")
    next_tier = resolve_next_round_tier(
        planner_pinned_tier="high",
        last_merge_decision=decision,
        current_round=2,
        prior_round_gate_effort_tier="high",
        consecutive_escalates_so_far=0,
    )
    assert next_tier == "high"


def test_escalate_envelope_overrides_pin_for_next_round() -> None:
    """[Req-014] An ESCALATE MergeDecision overrides the pin and promotes the next-round tier."""
    decision = MergeDecision(
        action="ESCALATE",
        recommended_next_tier="xhigh",
    )
    next_tier = resolve_next_round_tier(
        planner_pinned_tier="high",
        last_merge_decision=decision,
        current_round=2,
        prior_round_gate_effort_tier="high",
        consecutive_escalates_so_far=1,
    )
    assert next_tier == "xhigh"


def test_plan_tier_never_downgraded() -> None:
    """[Req-N06] An ESCALATE recommended_next_tier BELOW the planner pin does NOT downgrade.

    Req-N06: plan-pinned tiers MUST NEVER be downgraded by the
    orchestrator under any condition. If a buggy reviewer somehow
    emits ESCALATE->medium when the pin is high, the resolver
    keeps the pin.
    """
    decision = MergeDecision(
        action="ESCALATE",
        recommended_next_tier="medium",
    )
    next_tier = resolve_next_round_tier(
        planner_pinned_tier="high",
        last_merge_decision=decision,
        current_round=2,
        prior_round_gate_effort_tier="high",
        consecutive_escalates_so_far=1,
    )
    assert next_tier == "high"


def test_round_1_escalate_bypasses_pin() -> None:
    """[S-8] Round 1 ESCALATE bypasses the planner pin (planner cannot tier-classify unseen slices).

    Round 1 is "discovery" - a round-1 ESCALATE_REVIEWER_TIER
    envelope is accepted directly without invoking the
    Frontier-Reservation gate.
    """
    decision = MergeDecision(
        action="ESCALATE",
        recommended_next_tier="xhigh",
    )
    next_tier = resolve_next_round_tier(
        planner_pinned_tier="medium",
        last_merge_decision=decision,
        current_round=1,
        prior_round_gate_effort_tier=None,
        consecutive_escalates_so_far=1,
    )
    assert next_tier == "xhigh"


def test_round_2plus_honors_pin_via_frontier_gate() -> None:
    """[S-8 / B-4 R2] Round 2+ ESCALATE->max requires prior_round_gate_effort_tier == xhigh to honor max.

    The Frontier-Reservation Rule: max only honored if the prior
    round actually ran at xhigh. Otherwise the merge function caps
    at xhigh with frontier_reservation_capped audit; the resolver
    accepts the capped value as the next-round tier.
    """
    # Without prior-xhigh, the merge function should already have
    # capped recommended_next_tier to xhigh; the resolver passes
    # that through unchanged.
    decision_capped = MergeDecision(
        action="ESCALATE",
        recommended_next_tier="xhigh",
        audit_note="frontier_reservation_capped",
    )
    next_tier = resolve_next_round_tier(
        planner_pinned_tier="high",
        last_merge_decision=decision_capped,
        current_round=2,
        prior_round_gate_effort_tier="high",
        consecutive_escalates_so_far=2,
    )
    assert next_tier == "xhigh"

    # With prior-xhigh, max is honored.
    decision_max = MergeDecision(
        action="ESCALATE",
        recommended_next_tier="max",
    )
    next_tier_max = resolve_next_round_tier(
        planner_pinned_tier="xhigh",
        last_merge_decision=decision_max,
        current_round=3,
        prior_round_gate_effort_tier="xhigh",
        consecutive_escalates_so_far=2,
    )
    assert next_tier_max == "max"


def test_two_consecutive_escalates_promote_default_tier() -> None:
    """[Risk-006] After 2 consecutive ESCALATE responses, the planner-tier-pin policy auto-promotes.

    The auto-promotion is the Risk-006 mitigation: a planner that
    persistently mis-classifies a gate's complexity should not
    cause an indefinite loop. consecutive_escalates_so_far == 2
    triggers the promotion of the planner default tier (medium ->
    high, high -> xhigh).
    """
    decision = MergeDecision(
        action="ESCALATE",
        recommended_next_tier="high",
    )
    # Pinned at medium, two consecutive ESCALATEs already
    # observed. The resolver promotes the planner default such
    # that the next round does NOT run at medium.
    next_tier = resolve_next_round_tier(
        planner_pinned_tier="medium",
        last_merge_decision=decision,
        current_round=3,
        prior_round_gate_effort_tier="high",
        consecutive_escalates_so_far=2,
    )
    # Next tier must be at least high (no downgrade per Req-N06,
    # promoted from medium per Risk-006).
    assert next_tier in {"high", "xhigh", "max"}


def test_halt_action_does_not_promote_tier() -> None:
    """[Req-014] A HALT MergeDecision does not produce a valid next-round tier; the resolver may raise or return the pin.

    HALT terminates the gate; there is no "next round" to tier.
    The resolver's contract for HALT is implementation-defined in
    GREEN; pin this test as a NotImplementedError signal so RED
    is unambiguous.
    """
    decision = MergeDecision(
        action="HALT",
        halt_trigger="operator_auth_boundary",
    )
    # GREEN may either raise or return the pin; either way RED
    # MUST be NotImplementedError, not a silent pass.
    with pytest.raises((NotImplementedError, ValueError)):
        resolve_next_round_tier(
            planner_pinned_tier="high",
            last_merge_decision=decision,
            current_round=2,
            prior_round_gate_effort_tier="high",
            consecutive_escalates_so_far=0,
        )
