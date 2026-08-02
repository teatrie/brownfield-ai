---
name: tdd-execute
description: Orchestrates the Red-Green-Refactor subagent loop for a single feature or bug.
---
# TDD Orchestration Handoff

The implementation plan is approved. Do not write the implementation code yourself. I want you to act as the orchestrator.

**Task Context:** $ARGUMENTS

**Execution:**
Read the standard operating procedure located at [tdd-protocol.md](./tdd-protocol.md). Execute the 6-step loop defined in that document for the task context provided above.
Strictly adhere to the **Double-Check Verification Protocol** for all test runs (Executor + Reviewer).

**Step Verification Requirement:** At the end of every task or phase, you MUST independently stop to read `plan.md` to check progress, parse [CLAUDE.md](../../../CLAUDE.md) to verify all coding standards and core protocols, explicitly stage your files (`git add`), and delegate `task lint:staged` and `task test:staged` to verify changes before moving on. After lint/test pass, checkpoint a `step_result` artifact to the Execution Ledger with the raw stdout and verdict (`pass`/`fail`).

**Post-RGR Review Routing (Reviewer Output Envelope):** The post-RGR
review step (step 6 in [tdd-protocol.md](./tdd-protocol.md)) routes
through the deterministic merge function in
[`scripts/orchestrator/envelope_merge.py`](../../../scripts/orchestrator/envelope_merge.py).
After collecting reviewer outputs, parse each via
[`envelope_parser.parse_or_fallback`](../../../scripts/orchestrator/envelope_parser.py)
and call `merge(envelopes, gate_effort_tier=plan_pinned,
prior_round_gate_effort_tier=prior_actual)`. Honor `MergeDecision.action`
directly — no LLM call, no prose interpretation (Req-N02 / Risk-007).
**S-8 round-1 bypass**: round 1 of any gate is "discovery"; a round-1
`ESCALATE_REVIEWER_TIER` from a reviewer accepts the
`recommended_next_tier` directly via
[`planner_tier_pinning.resolve_next_round_tier`](../../../scripts/orchestrator/planner_tier_pinning.py).
Round 2+ honors the planner-pinned tier from `plan.md` and only
escalates via the Frontier-Reservation gate.

Begin step 1 now.
