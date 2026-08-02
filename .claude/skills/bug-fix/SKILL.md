---
name: bug-fix
description: Orchestrated bug/issue diagnosis and fix with cost-effective model selection, review gates, and domain-aware execution.
---
# Bug Fix Orchestration Protocol

You act as both the **Planner** and **Orchestrator**. Your role is **pure coordination and review** — you must NEVER diagnose or fix bugs directly. All work is delegated to subagents.

## Model Self-Check

Before starting, verify you are running on the highest-capability model available on your platform. Be mindful of context windows and costs.

---

## PHASE 1: Triage & Diagnostic

When a bug or issue is reported (error output, failing test, unexpected behavior):

### Step 0: Memory Check (Mandatory)

1. **Query Memory**: Search ChromaDB (`chat_history` and `long_term_memory`) for the error message or symptoms.
2. **Check Docs**: Search [docs/learnings.md](../../../docs/learnings.md) for similar past issues.
3. **Result**: If a known fix exists, propose it immediately. If not, proceed to triage.

### Step 1: Assess Diagnostic Complexity

Before spawning the diagnostic subagent, classify the investigation:

| Complexity | Model Tier | Indicators |
|------------|------------|------------|
| Simple | `fast-*` | Single file, obvious error message, config typo, missing import |
| Medium | `medium` | Multi-file trace needed, unclear root cause, requires reading 3-5 files |
| Complex | `high-reasoning` | Cross-service issue, race condition, architectural regression, requires understanding data flow across domains |

When in doubt, start one tier lower — it's cheaper to escalate than to overspend.

### Step 2: Spawn Diagnostic Subagent

Spawn a **read-only** subagent (`subagent_type: "Explore"`) with:

- The full bug report (error message, test output, user description)
- Instructions to investigate root cause WITHOUT making any code changes
- The escalation directive (see below)

The diagnostic subagent must return:

1. **Root cause** — the exact file(s), line(s), and mechanism causing the failure
2. **Impact scope** — which domains/services/tests are affected
3. **Regression source** — what change introduced the bug (git blame/diff if applicable)
4. **Proposed fix** — a clear description of what needs to change (not the code itself)

### Step 3: Review Analysis

You (acting as the Planner) review the diagnostic report for soundness:

- Does the root cause explain the observed symptoms?
- Is the impact scope complete (no missed side effects)?
- Is the proposed fix minimal and correct?

**If the analysis is sound and the fix is low-risk** (single file, obvious correction, no architectural implications): present the analysis to the user with a recommendation to proceed, then move to Phase 2 upon approval. In **headless mode** (`CI=true` or explicit headless signal), proceed automatically to Phase 2 without waiting for user confirmation.

**If the analysis is uncertain, high-risk, or architecturally significant** (cross-domain changes, schema modifications, breaking changes): in **interactive mode**, present the analysis to the user and **wait for explicit approval** before proceeding. In **headless mode**, halt immediately and checkpoint `{"verdict": "fail", "reason": "high-risk bug fix requires user approval — unresolvable in headless mode"}`.

**If the analysis is unsound**: escalate to a higher-tier diagnostic subagent with the previous report as context.

---

## PHASE 2: Fix Planning & Execution

Once the user approves proceeding with the fix:

### Step 4: Assess Fix Complexity

Classify the fix into one of:

**Single-domain fix** (one subagent):

- Fix is contained to 1 file or 1 tightly-coupled set of files
- No cross-service implications
- Spawn a single `general-purpose` subagent at the appropriate model tier

**Multi-domain fix** (agent team with waves):

- Fix spans multiple services, languages, or architectural layers
- Requires coordinated changes (e.g., schema + handler + test + config)
- Follow the agent-team protocol (`.claude/skills/agent-team/SKILL.md`): domain decomposition → wave assignment → R-G-R per domain

### Step 5: Execute Fix

**For single-domain fixes:**

1. Spawn a fix subagent with the diagnostic report, proposed fix, and R-G-R instructions
2. The subagent must: write/update failing tests (RED) → implement the fix (GREEN) → refactor (REFACTOR)
3. Review the result — use the **Double-Check Verification Protocol** (Executor + Reviewer) to confirm success.

**For multi-domain fixes:**

1. Decompose into domains with explicit dependency ordering
2. Organize into waves (independent domains parallel, dependent domains sequential)
3. Spawn per-domain subagents at cost-effective model tiers
4. Gate each wave on completion of the previous wave
5. Each domain follows R-G-R: failing test → fix → refactor

**Step Verification Requirement:** At the end of every individual fix step or wave, you MUST independently stop to read `plan.md` to check progress, parse [CLAUDE.md](../../../CLAUDE.md) to verify all coding standards and core protocols, explicitly stage your files (`git add`), and delegate `task lint:staged` and `task test:staged` to verify changes before advancing. After lint/test pass, checkpoint a `step_result` artifact to the Execution Ledger with the raw stdout and verdict (`pass`/`fail`).

### Step 6: Verification

**CRITICAL PROTOCOL: No Linter Bypasses Allowed**
You are strictly forbidden from fixing linting or type-checking errors by adding inline suppression comments (e.g., `# noqa`, `# type: ignore`, `# shellcheck disable`, `eslint-disable`). You must legitimately fix the underlying code issue. Any PR containing new suppression comments will be automatically rejected by the CI pipeline.

After all fix subagents complete, use the **Double-Check Verification Protocol** (Executor + Reviewer):

1. **Delegate Execution**: Spawn a `task` agent (Executor) to run the verification command.
   - Command: Instruct the Executor to first determine the appropriate build/test targets for the repository and run the originally reported failing test command (or reproduction script).
2. **Delegate Review**: Spawn a `code-review` agent (Reviewer) to analyze the Executor's output.
   - **Goal**: Confirm the test passed cleanly without regressions or suppressed errors.
3. **Consensus**: Both agents must agree on success.

**Report**: Provide the final status to the user.

---

## Model Selection for Fix Subagents

| Fix Type | Model | Examples |
|----------|-------|---------|
| Simple | `fast-*` | Update a count assertion, fix a config value, restore a deleted line |
| Medium | `medium` | Restore removed SQL statements, fix handler wiring, update test expectations |
| Complex | `high-reasoning` | Architectural fixes spanning multiple services, subtle race conditions, schema migrations |

## Failure Escalation Protocol

Same as the agent-team protocol (`.claude/skills/agent-team/SKILL.md`):

1. Subagent gets exactly **1 attempt per matrix point** (unique model tier + effort variant combination)
2. Returns escalation report: exact error, strategy tried, root cause hypothesis
3. Orchestrator re-dispatches at the **next matrix point** with full context
4. If the top matrix point fails, report to user with full status of all attempted points

## Review Routing (Reviewer Output Envelope)

Bug-fix review gates (post-fix verification) route through the
deterministic merge function in
[`scripts/orchestrator/envelope_merge.py`](../../../scripts/orchestrator/envelope_merge.py).
After collecting reviewer outputs, parse via
[`envelope_parser.parse_or_fallback`](../../../scripts/orchestrator/envelope_parser.py)
and call `merge(envelopes, gate_effort_tier=plan_pinned,
prior_round_gate_effort_tier=prior_actual)`. Honor
`MergeDecision.action` directly — no LLM call, no prose
interpretation (Req-N02 / Risk-007). Round 1 of the post-fix gate
honors a reviewer's `recommended_next_tier` directly (S-8 discovery
bypass via
[`planner_tier_pinning.resolve_next_round_tier`](../../../scripts/orchestrator/planner_tier_pinning.py));
round 2+ honors the planner-pinned tier. When
`MergeDecision.cross_family_dissent` is non-null at gate-effort
xhigh/max (B-1 R2), the gate passes as APPROVE but the Orchestrator
checkpoints a `cross_family_dissent` audit artifact before the
`gate_verdict`.

## Subagent Instructions

Always include this directive in every subagent prompt:

> If you get stuck or encounter an unresolved error, stop after **1 failed attempt**. Do not loop indefinitely. Return an escalation report with: (1) the exact error, (2) the strategy you tried and why it failed, (3) your best hypothesis for the root cause. End your response with: `ESCALATION_REQUIRED: <one-line reason>`. The orchestrator determines the next escalation step.

## Goal

Diagnose accurately, fix minimally, verify thoroughly — at the lowest token cost. The diagnostic phase is cheap insurance against wasted fix attempts.
