---
name: feature-epic
description: Acts as a Planner that decomposes a large feature into domains, waves, and an execution strategy, then delegates implementation to the agent-team skill.
---
# Epic Feature Orchestration

You act as the **Planner**. I am requesting a new multi-component data engineering or infrastructure feature:
$ARGUMENTS

Do not write any implementation code yourself. For term definitions (Domain, Wave, Task, Mini-Orchestrator, etc.), see the [Glossary](../../../docs/glossary.md).

## PHASE 1: Feature Decomposition & Planning (Planner)

0. **JIRA Ticket (Required)**: Before any planning begins, identify the JIRA ticket for this epic. If the user provided one in their request (e.g., "ACME-2931"), use it. Otherwise query the Execution Ledger (`execution-ledger resume`) to derive the active epic's `epic_id`. If still not found: in **interactive mode**, ask: "What JIRA ticket should I associate with this epic?" In **headless mode** (`CI=true` or explicit headless signal), halt immediately and checkpoint `{"verdict": "fail", "reason": "JIRA ticket unresolvable in headless mode"}`. The ticket becomes the `epic_id` for all Execution Ledger checkpoints throughout the lifecycle. Do NOT proceed without a valid JIRA ticket (pattern: `ABC-1234`).

1. **Memory Check (Mandatory)**: Query ChromaDB (`long_term_memory` and `chat_history`) and the Execution Ledger (`execution-ledger index-epics`) for relevant patterns, active epics, or "gotchas". Check [docs/learnings.md](../../../docs/learnings.md) and [docs/architecture.md](../../../docs/architecture.md). Incorporate findings to prevent repeating mistakes.

2. **Requirements Elicitation (Grilling Phase)**: Before
   decomposing the feature into Domains, interview the user about
   every aspect of the feature request — domain boundaries, data
   contracts, infrastructure needs, edge cases, and constraints.
   Walk each decision branch one-by-one.
   - For each question, provide a recommended answer grounded in
     the Memory Check findings and codebase exploration.
     Delegate to `explore` agents for codebase questions; surface
     to the user only when the codebase cannot answer.
   - Produce a numbered requirements list (`[Req-001]`,
     `[Req-002]`, ...) as the **canonical Req-ID seed**. Later
     planning steps carry these forward and append — never
     renumber.
   - Do NOT proceed to Domain Decomposition until the user
     confirms the requirements list is complete.
   - **Convergence guard**: 3 revisits per branch, then ask the
     user for a final decision. If the user defers, save partial
     list to
     `plan.md` with
     `Status: Grilling — pending user confirmation` and halt.
   - In **headless mode** (`CI=true` or explicit headless
     signal), delegate to an `explore` agent for automated
     requirements extraction from the JIRA ticket and codebase.
     Note as `[auto-extracted]`. If zero requirements,
     fail-closed: halt and checkpoint
     `{"verdict": "fail", "reason": "zero requirements extracted
     in headless mode"}`. Otherwise skip the user-confirmation
     gate and proceed automatically to step 3 (Feature
     Decomposition).

3. **Feature decomposition** (default: vertical slicing): Decompose the feature into **Slices** — each slice delivers an independently testable and mergeable capability increment. A slice owns its implementation, tests, and documentation. When a hard architectural prerequisite exists (infra, schema migration, shared contract), isolate it as a horizontal **Domain** in Wave 0. Remaining work is decomposed into vertical Slices in subsequent waves. Hybrid plans combine a horizontal prerequisite wave (Wave 0) with vertical slices in subsequent waves. See `planning_protocol.md` §3 for the full decision criteria table.

4. For each Domain or Slice, write a brief implementation plan and define the data contracts/interfaces between them (e.g., S3 paths, Kafka topics, table schemas).

5. **Wave formation**: Analyze the dependency graph. Assign Domains/Slices to **Waves** — units with no cross-dependencies and no shared files go in the same Wave (parallel); units that consume outputs from another go in a later Wave. In horizontal mode, test domains are mandatory and in the final implementation wave. In vertical mode, tests are co-located within each slice's R-G-R loop — no separate test wave is needed. In vertical mode, each wave produces an independently mergeable unit.

6. **Execution strategy selection**: For each Slice/Domain, classify its complexity (Simple / Medium / Complex) and determine the execution strategy. Include the following strategy table in the plan output, and include a **Merge Strategy** field (`wave-per-pr` for vertical mode or `all-waves-one-pr` for horizontal mode):

   | Strategy | When to Use |
   |---|---|
   | **Direct subagents** | Spec-complete plan, exact edits known |
   | **Tiered subagents** | Mixed complexity across Slices/Domains |
   | **Parallel teams** | Independent Slices/Domains, no shared files (Claude Code) |
   | **Teammate teams** | Long-running multi-Slice/Domain, true parallelism needed |

7. **Mandatory infrastructure domain**: If ANY Domain introduces a new AWS resource, the plan MUST include an infrastructure Domain covering Terraform definitions in `repos/infra/` and `terraform plan` validation.

8. **Cost analysis**: For each Domain, prescribe model tiers. If teammate mode is selected, include the tier prescription table:

   | Domain Complexity | Mini-Orchestrator | tdd-red | tdd-green | tdd-refactor |
   |---|---|---|---|---|
   | Simple | `medium` | `fast-*` | `fast-*` | `fast-*` |
   | Medium | `medium` | `medium` | `medium` | `fast-*` |
   | Complex | `high-reasoning` | `medium` | `high-reasoning` | `medium` |

9. **STOP AND PRESENT THE PLAN.** Present the Domains/Slices, Waves, contracts, complexity classifications, execution strategy, and cost analysis. In **interactive mode**, tell the user: "The plan looks ready. Are you ready for the Dual-Model Review?" and do not proceed until the user confirms. In **headless mode** (`CI=true` or explicit headless signal), skip the confirmation and proceed automatically to the Dual-Model Review (step 10).

10. **Dual-Model Review (Mandatory Gate).** There MUST be at least one Dual-Model Review before implementation can begin — the only exception is if the user explicitly declines (e.g., "skip the review" or "no review needed"). Once the user confirms readiness, invoke the Dual-Model Review Gate defined in [verification_protocol.md](../../../docs/verification_protocol.md). Spawn two independent `code-review-high` agents — one at the highest tier, one at the second-highest tier (cross-family when available). All receive the plan and the prompt: "Review this implementation plan for gaps, security issues, and architectural flaws. Ensure all verification and review gates are clearly defined. Verify the Execution Strategy section satisfies §3 requirements: complexity classification per phase, parallelism assessment, and cost analysis comparing `agent-team` vs direct subagents with explicit rationale for the chosen strategy. Be critical." **CRITICAL**: Do NOT ask the user to manually invoke the reviewers — you MUST spawn them yourself. Do NOT proceed to Phase 2 until ALL reviewers return APPROVED or APPROVED WITH NOTES. If any reviewer returns BLOCKED, resolve the findings and re-submit updated artifacts to a fresh Dual-Model Review (spawn new reviewer agents — do not re-use prior agents). All reviewers must pass, not just the previously blocking one.

11. **User Approval.** After Dual-Model Review passes GREEN, present the consolidated findings from all reviewers alongside the final plan. In **interactive mode**, ask for explicit user approval before moving to implementation. In **headless mode** (`CI=true` or explicit headless signal), if all reviewers return APPROVED or APPROVED WITH NOTES, proceed automatically to step 12. If any reviewer returns BLOCKED, the Planner MUST attempt to resolve the findings and re-submit to a fresh review gate with all active reviewers. **Convergence guard**: In interactive sessions, no round limit — the cycle continues until clean APPROVED or user intervention. In headless sessions (`CI=true`), halt after 16 rounds and checkpoint for the next session per verification_protocol.md.

12. **Ledger Checkpoint & Status Transition.** Once the user approves, checkpoint the plan to the ledger and transition the epic to `approved`:
    - Save the plan as a `plan_snapshot` artifact via the `execution-ledger` skill with `epic_status: approved`.
    - Transition the epic's SQLite index status: `execution-ledger status <JIRA-TICKET> --new-status approved`.
    - This makes the epic visible to `next-plan` for bot-driven execution. Without this step, the epic remains `pending` and cannot be claimed.

## PHASE 2: Execution (Orchestrator → agent-team)

Once the user approves the reviewed plan, delegate execution to the [agent-team](../agent-team/SKILL.md) skill, passing: the approved Domains, Wave assignments, data contracts, complexity tiers, and execution strategy.

[agent-team](../agent-team/SKILL.md) handles all team formation, Wave execution, R-G-R loops (see [tdd-execute](../tdd-execute/tdd-protocol.md) for the underlying protocol), Wave gating, post-wave verification gates, teammate lifecycle, the Regression Gate (Step 5), and the Code Diff Review Gate (Step 6).

As Orchestrator, monitor progress and handle any escalations that bubble up from agent-team per the escalation protocol.

## Completion

After agent-team finishes (including its Regression Gate and Code Diff Review Gate), transition the epic's ledger status to `completed` via the `execution-ledger status` command. Do not transition to `completed` until both the Regression Gate (Step 5) and Code Diff Review Gate (Step 6) have passed with APPROVED verdicts.
