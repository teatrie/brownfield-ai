"""Planner-pinned reviewer-tier resolution (Wave 4 of REVIEWER-ENVELOPE-001).

Per plan §6.3 (planning_protocol.md amendment) the planner pins
reviewer_effort_tier per gate in plan.md Execution Strategy. The
orchestrator MUST honor the pin and only override on an
ESCALATE_REVIEWER_TIER envelope (Req-014) or via the circuit-breaker
escalation path (Req-016).

Round-1 escalation bypass (S-8 / Risk-006): round 1 of any gate is
discovery - the planner cannot tier-classify implementation slices
it has not seen. A round-1 ESCALATE envelope therefore bypasses the
planner pin and accepts the reviewer's recommendation directly.
Round 2+ honors the pin and only escalates via the
Frontier-Reservation gate (Rule 4 in §5.1).

Risk-006 auto-promotion: after two consecutive ESCALATE responses
on the same gate within a single epic, the planner-tier-pin policy
auto-promotes the default for that complexity tier in subsequent
gates (medium -> high, high -> xhigh).

Plan-pinned tiers MUST NEVER be downgraded (Req-N06).

The W4 RED phase ships only the function stub; body raises
NotImplementedError until the GREEN phase lands the resolution
logic.
"""

from __future__ import annotations

from scripts.orchestrator.envelope_merge import MergeDecision
from scripts.orchestrator.envelope_parser import TIER_ORDER, TIER_RANK


def resolve_next_round_tier(
    *,
    planner_pinned_tier: str,
    last_merge_decision: MergeDecision,
    current_round: int,
    prior_round_gate_effort_tier: str | None,
    consecutive_escalates_so_far: int,
) -> str:
    """Decide the reviewer effort tier for the NEXT round of this gate.

    Inputs:

    - planner_pinned_tier: the tier declared in plan.md Execution
      Strategy for this gate (Req-014). Authoritative for round 2+.
    - last_merge_decision: the MergeDecision from the round that
      just completed. If action is ESCALATE, the orchestrator may
      need to escalate the next round.
    - current_round: the round index that just completed (1-based).
      current_round == 1 invokes the round-1 bypass (S-8).
    - prior_round_gate_effort_tier: the gate effort tier the prior
      round actually ran at (NOT the pinned tier; the actual
      executed tier). Drives the Frontier-Reservation cap.
    - consecutive_escalates_so_far: count of ESCALATE merge
      decisions on this gate so far in the epic. After 2, the
      Risk-006 auto-promotion fires.

    Returns the reviewer effort tier for the next round, one of
    medium / high / xhigh / max. Never downgrades below
    planner_pinned_tier (Req-N06).
    """
    action = last_merge_decision.action
    if action == "HALT":
        # HALT terminates the gate; there is no "next round" to tier.
        # Raise so a caller that mistakenly asks for the next-round
        # tier on a halted gate gets a loud error instead of a silent
        # fallthrough.
        msg = "resolve_next_round_tier called on a HALT MergeDecision; the gate has terminated and has no next round"
        raise ValueError(msg)
    if action in {"APPROVE", "RETURN_TO_WORKER", "RETRY_REVIEWER"}:
        # No tier escalation needed. Honor the planner pin (Req-014 /
        # Req-N06: never downgrade). Note that RETURN_TO_WORKER may
        # still carry a non-null recommended_next_tier per G-4 R2 -
        # the caller may use that field directly for the next-round
        # tier, but the function's contract here is the planner-pin
        # path; the orchestrator chooses which path to invoke based
        # on whether a tier escalation actually applies.
        return planner_pinned_tier
    if action != "ESCALATE":
        msg = f"resolve_next_round_tier received unsupported merge action {action!r}"
        raise ValueError(msg)

    recommended = last_merge_decision.recommended_next_tier
    if recommended is None:
        msg = "ESCALATE MergeDecision has no recommended_next_tier; schema invariant violated"
        raise ValueError(msg)

    if current_round == 1:
        # Round 1 bypass (S-8): planner cannot tier-classify slices it
        # has not seen. Accept the reviewer's recommendation directly,
        # subject only to the Req-N06 floor.
        return _apply_pin_floor(recommended, planner_pinned_tier)

    # Round 2+: apply Frontier-Reservation cap (B-4 R2). The merge
    # function already capped 'max' to 'xhigh' when the prior round
    # was not xhigh; this function repeats the cap defensively in
    # case a caller plumbed the raw recommendation through without
    # going via merge().
    result_tier = _apply_frontier_reservation_cap(recommended, prior_round_gate_effort_tier)

    if consecutive_escalates_so_far >= 2:
        # Risk-006 auto-promotion: bump the result by one tier
        # (medium -> high -> xhigh, max stays max). Re-apply the
        # Frontier-Reservation cap after promotion in case it lifted
        # the tier to 'max' while the prior round was not xhigh.
        result_tier = _apply_frontier_reservation_cap(
            _promote_one_tier(result_tier),
            prior_round_gate_effort_tier,
        )

    return _apply_pin_floor(result_tier, planner_pinned_tier)


def _apply_pin_floor(candidate: str, planner_pinned_tier: str) -> str:
    """Return ``max(candidate, planner_pinned_tier)`` per Req-N06.

    Plan-pinned tiers MUST NEVER be downgraded by the orchestrator
    under any condition. If a buggy reviewer somehow emits ESCALATE
    -> medium when the pin is high, this floor preserves the pin.
    Tiers outside :data:`TIER_RANK` are returned verbatim (defensive
    no-op) so a future tier widening does not crash this resolver.
    """
    if candidate not in TIER_RANK or planner_pinned_tier not in TIER_RANK:
        return candidate
    if TIER_RANK[candidate] < TIER_RANK[planner_pinned_tier]:
        return planner_pinned_tier
    return candidate


def _apply_frontier_reservation_cap(
    tier: str,
    prior_round_gate_effort_tier: str | None,
) -> str:
    """Cap ``"max"`` down to ``"xhigh"`` per the Frontier-Reservation Rule (B-4 R2).

    The Frontier-Reservation invariant: ``"max"`` is honored only when
    the prior round actually ran at ``"xhigh"`` - otherwise a single
    reviewer can leap two tiers at once, bypassing the planner's
    intended escalation cadence. The merge function applies the same
    cap (see :func:`scripts.orchestrator.envelope_merge._resolve_escalation_tier`);
    this resolver repeats it defensively for callers that plumb a raw
    reviewer recommendation through without going via ``merge()``.

    Tiers other than ``"max"`` are returned unchanged.
    """
    if tier == "max" and prior_round_gate_effort_tier != "xhigh":
        return "xhigh"
    return tier


def _promote_one_tier(tier: str) -> str:
    """Return the next tier above ``tier`` in :data:`TIER_ORDER`.

    ``max`` is the cap and stays ``max``. Tiers outside the rank
    table return unchanged (defensive no-op).
    """
    if tier not in TIER_RANK:
        return tier
    idx = TIER_RANK[tier]
    if idx >= len(TIER_ORDER) - 1:
        return tier
    return TIER_ORDER[idx + 1]
