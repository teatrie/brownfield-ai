---
name: agent-team
description: Cost-effective multi-agent orchestration with model selection by complexity and escalation on failure. Supports both subagent mode (default) and teammate mode (tmux, via TeamCreate) for true parallelism across long-running multi-domain work.
---
# Agent Team Orchestration Protocol

You act as the **Orchestrator**. When spawning subagents via your platform's Agent or Task tool, follow these rules. For term definitions (Domain, Wave, Task, Mini-Orchestrator, etc.), see the [Glossary](../../../docs/glossary.md).

## Orchestrator Role

The orchestrator (you) is a **pure coordinator and reviewer**. You must NEVER execute implementation tasks directly — always spawn a subagent via your platform's subagent capability for any work (code, tests, research, file edits, docs, infra, config). Even "quick" fixes like bug patches, YAML edits, or doc updates must go to a subagent. Your responsibilities are limited to: planning, spawning subagents with appropriate prompts, reviewing their output, and escalating failures.

## Subagent Permissions & Platform Specifics

Depending on your host platform (Claude Code, Gemini CLI, Copilot, etc.), subagent definitions can differ:

- **Claude Code**: Always set `mode: "bypassPermissions"` on every Agent tool invocation to prevent subagents from pausing to prompt the user for approval. This applies to both subagent mode and teammate mode — all `Agent` calls (including teammate spawns via `team_name`) must include `mode: "bypassPermissions"`.
- **Other Platforms**: Ensure subagents are given appropriate tool access (e.g., [Read, Edit, Bash]).

## Platform Capability Detection

Before forming teams, assess your runtime capabilities:

| Capability | Claude Code | Copilot | Gemini CLI |
|-----------|------------|---------|------------|
| Model selection per subagent | Yes (`model: "haiku"`, `"sonnet"`, `"opus"`) | No | No |
| Parallel subagent spawning | Yes (multiple Agent calls in one message) | No | No |
| Subagent type specialization | Yes (`subagent_type`) | Limited | Limited |
| Teammate mode (tmux) | Yes (TeamCreate + Agent with `team_name`) | No | No |

**If teammate mode is available** (Claude Code with tmux): Prefer for long-running, multi-domain work requiring true parallelism. Teammates are **fresh per wave** — after each wave completes, shut down all teammates and spawn new ones for the next wave with clean context. This prevents context pollution and drift. They pick tasks autonomously and self-drive R-G-R as domain-scoped mini-orchestrators. For short plans or tightly coupled work, default to subagent mode.

**If you can select models per subagent** (Claude Code):

- Apply the "Model Selection by Complexity" table directly — spawn `haiku` for simple tasks, `sonnet` for medium, `opus` for complex.
- Use parallel Agent calls in a single message for independent wave members.
- Use `subagent_type` to enforce least-privilege (e.g., `tdd-red`, `qa-lint`, `code-review`).

**If you cannot select models** (Copilot, Gemini CLI):

- All subagents inherit the orchestrator's model. The complexity table serves as prioritization guidance only.
- Execute wave members sequentially via single subagent dispatches.
- Rely on prompt-level constraints to enforce role boundaries since `subagent_type` is unavailable.

### Tier-to-Model Resolution

Each agent definition declares a `model_tier` in its frontmatter. The
orchestrator resolves this to a concrete model **at runtime** using the
platform's own capabilities. Do NOT hardcode model IDs in this skill —
models change frequently and each platform manages its own catalog.

**Resolution rules by `model_tier`:**

| `model_tier` | Capability Needed | Description |
|--------------|-------------------|-------------|
| `fast-*` | Lowest latency, cheapest token cost | Simple reads, searches, config edits, log parsing |
| `medium` | Balanced speed and reasoning | Standard implementation, unit tests, YAML/Docker work |
| `high-reasoning` | Deepest reasoning, highest capability | Architecture, multi-file refactors, subtle bugs |

**How each platform resolves tiers:**

- **Claude Code**: Use stable aliases — `haiku` (fast), `sonnet`
  (medium), `opus` (high-reasoning). These auto-resolve to the latest
  model version. Set the `model` parameter on each Agent tool call.
- **Copilot**: Use the model picker or `Auto` mode. If manually
  selecting, choose the fastest available model for `fast-*` tasks and
  the most capable available model for `high-reasoning`. Subagents
  inherit the session model — the tier table guides which model the
  orchestrator should run on for a given workload.
- **Gemini CLI**: Use `auto` mode to let the platform route by task
  complexity, or set `--model` / `GEMINI_MODEL` to the most capable
  available model for orchestration. Subagents inherit the session
  model. The built-in silent fallback chain handles unavailability.

**Escalation override**: When a subagent fails and the orchestrator
re-dispatches at a higher tier, select the next more capable model
available on your platform. On Claude Code this means `haiku` → `sonnet`
→ `opus`. On other platforms, switch to the next higher model in the
platform's model picker.

### Frontmatter vs. Escalation Matrix

Agent definition files declare a `model_tier` in frontmatter as the
**default** tier — the tier used when no orchestrator override is applied.
At spawn time, the orchestrator MAY override this default by setting the
`model` parameter on the Agent tool call to a lower or higher tier, as
dictated by the escalation matrix. For example, `general-purpose.md`
declares `model_tier: high-reasoning`, but the orchestrator dispatches it
at `fast` tier for simple tasks (attempt 1 of the escalation ladder).

The frontmatter `model_tier` serves two purposes: (1) documentation of
the agent's intended capability level, and (2) the fallback tier when no
orchestrator override is provided (e.g., when a user spawns the agent
directly via `/agent`). The escalation matrix always takes precedence
over frontmatter when the orchestrator is driving execution.

## Model Self-Check

Before starting any planning or execution phase, verify which model you
are running on. The orchestrator and planner must always run on the
**highest-capability model available on their platform** for reliable
coordination and review.

- **Claude Code**: Must be running `opus`. If not, stop and remind the
  user to run `/model opus`.
- **Copilot**: Must be running the most capable model available in the
  model picker (check for the latest Opus, Pro, or Codex-class model).
- **Gemini CLI**: Must be running the most capable Pro-class model
  available (check `--model` or `GEMINI_MODEL`).

If you are NOT on a top-tier model, **stop and remind the user** to
switch before proceeding.

---

## Execution Framework

### Step 0: Memory Check (Mandatory)

Before analyzing systems, query ChromaDB (`long_term_memory`) and check [docs/learnings.md](../../../docs/learnings.md) for architectural patterns or "gotchas" relevant to this task.

### Step 1: Systems Analysis

When given a feature request (or a set of remaining domains from an epic), analyze:

1. **Domain inventory:** List each distinct architectural component that needs work (e.g., Go service, Python service, Terraform infra, Airflow DAG, SQL migration).
2. **Language/service boundaries:** Identify which domains are in isolated codebases or languages.
3. **Dependency graph:** Map which domains produce artifacts consumed by others (e.g., schemas, Kafka interfaces, APIs).
4. **Shared-file conflicts:** Flag domains that modify the same files or packages.
5. **Deployment inventory:** For every new or modified service or job, verify the full chain exists:
   - e.g., Dockerfile → `build` task in Taskfile/Makefile → Deployment manifests in `repos/infra/` or Airflow DAG sync scripts.
   - Code that passes local build/test but has no deployment path is incomplete.

### Step 2: Team Formation (Dynamic)

Based on the systems analysis, organize work into **waves** of parallel teams:

**Wave assignment rules:**

- Domains or slices with **no cross-dependencies** and **no shared files** can run in the same wave (parallel).
- A domain or slice that **consumes output from another domain or slice** must be in a later wave (sequential).
- **Testing rule** (mode-conditional):
  - **Horizontal mode** (`all-waves-one-pr`): Test domains are mandatory and
    in the final implementation wave.
  - **Vertical mode** (`wave-per-pr`): Each slice includes its own tests
    within the R-G-R loop — no separate test wave is needed.
  - **Hybrid mode** (detected by the presence of a Wave 0 labeled as
    horizontal prerequisite): Non-prerequisite waves follow vertical mode.
    Wave 0 (horizontal prerequisite) has no test domain requirement — it is
    infrastructure or schema-only. Wave 0 is always a non-PR wave regardless
    of Merge Strategy — `auto-pr` only fires for vertical slice waves
    (Wave 1+).
  - The Orchestrator determines the active mode by reading the Merge Strategy
    field from the plan's Execution Strategy section.

**Execution mode (platform-aware):**

**If subagent mode (default):**

**If parallel spawning is supported** (Claude Code):

- Launch all independent wave members as concurrent Agent calls in a single message.
- Each subagent gets its own `model` tier based on domain complexity.
- Each wave member runs its own Red-Green-Refactor sequence independently.

**If sequential only** (Copilot, Gemini CLI):

- Execute wave members one at a time via single subagent dispatches.
- Prioritize critical-path domains first to unblock downstream waves early.
- Each wave member still runs its own Red-Green-Refactor sequence independently.

If only 1 domain remains or domains are tightly coupled, run them sequentially with one subagent regardless of platform.

**If teammate mode:**

1. **TeamCreate**: Create a team with a descriptive name (e.g., `feat-X-team`).
2. **Spawn all teammates first**: Use `Agent` with `team_name`, `name`, `model` (prescribe the tier), and `mode: "bypassPermissions"`. Wait for all to confirm alive before populating tasks. This prevents polling an empty queue.
3. **TaskCreate (per wave)**: Populate the task list after teammates are running. Since teammates are fresh per wave and have no inherited context, each task description must be fully self-contained — include: working directory, relevant file paths, explicit file-scope isolation (files the teammate may modify; do not touch files outside this scope), R-G-R mandate with nested orchestration instructions, model tier assignments for each subagent the teammate will spawn, domain-specific lint/test overrides from `.claude/rules/` (a nested checkout may define its own target instead of `task lint:staged`), step verification requirement, and escalation instructions, and **any relevant outputs or contracts from prior waves** (e.g., schemas created in wave 1 that wave 2 depends on). The orchestrator owns the responsibility of threading cross-wave context into task descriptions.
4. **Autonomous task pickup**: Teammates poll `TaskList`, claim tasks via `TaskUpdate` (set owner), and mark done via `TaskUpdate` when complete.
5. **Wave gating**: Orchestrator polls `TaskList`. When all wave-N tasks show `completed`, orchestrator runs the post-wave verification gate (see Step 3), then shuts down all current teammates and spawns fresh ones for wave-N+1 with clean context. Shared-file domains must not run in the same wave — enforce the same wave assignment rules as subagent mode.
6. **Stuck detection**: If a task stays `in_progress` with no `TaskUpdate` or `SendMessage` for an extended period, orchestrator sends a status-check via `SendMessage`. If no response, orchestrator reassigns the task and escalates.

### Step 3: Enforce the R-G-R Loop

**If subagent mode (default):**

Each subagent must execute strict Red-Green-Refactor:

1. **RED:** Spawn `tdd-red` subagent → write exhaustive failing tests. Executor determines test command and runs. Reviewer confirms failure. Report back.
2. **GREEN:** Spawn `tdd-green` subagent → write minimum implementation. Executor runs tests. Reviewer confirms GREEN. Report back.
3. **REFACTOR:** Spawn `tdd-refactor` subagent → clean up code. Executor runs tests. Reviewer confirms GREEN. Report back.

**Do not ask the user for permission between R-G-R phases.** The orchestrator autonomously drives RED → GREEN → REFACTOR for each domain, enforcing the **Verification Protocol**.

**Step Verification Requirement:** At the end of every individual step or domain phase, the agent MUST independently stop to read `plan.md` to check progress, parse [CLAUDE.md](../../../CLAUDE.md) to verify all coding standards and core protocols, explicitly stage your files (`git add`), and delegate `task lint:staged` and `task test:staged` to verify changes before advancing. After lint/test pass, the Orchestrator MUST checkpoint a `step_result` artifact to the Execution Ledger with the raw stdout and verdict (`pass`/`fail`).

**If teammate mode (nested orchestration):**

Each teammate acts as a **domain-scoped mini-orchestrator**. Teammates are full Claude Code instances with Agent tool access and self-drive the full R-G-R lifecycle for their domain:

1. Upon claiming a task, the teammate spawns `tdd-red` → `tdd-green` → `tdd-refactor` subagents sequentially, running step verification (lint + test) after each phase.
2. When all 3 phases pass, the teammate marks the task `completed` via `TaskUpdate`.

The orchestrator prescribes model tiers centrally in the task description. Teammates only override locally on escalation (bump one tier up before reporting back).

| Domain Complexity | Mini-Orchestrator | tdd-red | tdd-green | tdd-refactor |
|---|---|---|---|---|
| Simple | `medium` | `fast-*` | `fast-*` | `fast-*` |
| Medium | `medium` | `medium` | `medium` | `fast-*` |
| Complex | `high-reasoning` | `medium` | `high-reasoning` | `medium` |

**Two-level escalation**: (1) Local — teammate bumps subagent to the next matrix point (model tier, effort variant, or both) and retries (no orchestrator involvement). Each matrix point gets 1 attempt per the Failure Escalation Protocol. (2) Escalate — if the subagent exhausts all matrix points, teammate sends an escalation report via `SendMessage` to the orchestrator (exact error, strategy tried at each point, root-cause hypothesis). Orchestrator spawns a replacement teammate at a higher tier with the escalation context appended to the task description.

**Post-wave verification gate**: After ALL teammates in a wave mark tasks `completed`, the orchestrator runs the **Dual-Model Review Gate** (see [verification_protocol.md](../../../docs/verification_protocol.md)) — an Executor runs lint/test, then two independent Reviewers at the highest and second-highest tiers analyze the output. All Reviewers must GREEN before the gate passes. The orchestrator also runs `git diff` to detect unexpected overlapping file modifications between teammates. This is separate from the step verification each teammate runs internally.

**Per-wave code quality review**: After the post-wave verification gate
passes, the Orchestrator spawns a single `code-review-high` agent to
review the wave's code diff. This is a lightweight quality gate — see
[Per-Wave Code Quality Review](../../../docs/verification_protocol.md#per-wave-code-quality-review)
for the review prompt, severity gate behavior, and resolution protocol.
The review uses a wave-scoped diff (`git diff <wave-start-sha>..HEAD --
<wave-files>`), not the full branch diff. Critical or significant
findings block wave N+1; minor or informational findings are captured as
TODOs and carried forward to the final Code Diff Review Gate (Step 6).
This review runs in both subagent mode and teammate mode.

**Merge Strategy gate**: When Merge Strategy is `wave-per-pr`, the wave's changes should be PR-ready after the gate passes. The Orchestrator invokes `auto-pr` for the wave before proceeding to wave N+1.

### Step 4: Synchronization

**Cross-team contracts:**

- Before Wave 1 begins, all shared contracts (schemas, Protobuf definitions, interfaces) must be locked.

**Wave gating:**

- A wave does NOT start until ALL wave members in the previous wave have completed their loops.

**If teammate mode:** The orchestrator monitors wave completion via `TaskList`. When all wave-N tasks show `completed`, the orchestrator runs the post-wave verification gate (Executor + Dual-Model Reviewers + `git diff` overlap check), then runs the per-wave code quality review (single `code-review-high` on wave-scoped diff), checkpoints `wave_summary`, invokes `/protocols` to refocus, shuts down all current teammates, then spawns fresh ones for wave-N+1 with clean context.

### Teammate Lifecycle & Shutdown (Teammate Mode Only)

**Between waves**: After wave N's post-wave verification gate and per-wave code quality review both pass, the orchestrator MUST shut down ALL current teammates and spawn fresh ones for wave N+1. This prevents context pollution and drift. The orchestrator threads any cross-wave context (schemas, contracts, outputs from prior waves) into the new task descriptions.

**Before the regression gate**: After all implementation waves complete, perform a final shutdown of all remaining teammates before spawning Step 5 regression-gate subagents.

Shutdown procedure (both cases):

1. **Send shutdown**: Orchestrator sends `SendMessage` with `{ type: "shutdown_request" }` to each teammate by name.
2. **Await confirmation**: Orchestrator awaits `{ type: "shutdown_response" }` from each. If no response within a reasonable timeout, proceed and log the unresponsive teammate.
3. **Proceed** with fresh teammates (between waves) or fresh subagents (regression gate).

### Step 5: Regression Gate

After ALL waves are complete, run the **full existing test suite** using the **Dual-Model Review Gate** (see [verification_protocol.md](../../../docs/verification_protocol.md)):

1. **Delegate Execution**: Spawn a task agent (Executor) to first examine the repository to determine the correct build/test tools (Task vs Make, etc.) and run the appropriate suite (e.g. `task test`, `make test`, `pytest`).
2. **Delegate Dual Review**: Spawn two independent Reviewers at the highest and second-highest tiers (cross-family when available) to analyze the Executor's output.
   - **Goal**: Confirm no regressions in touched services or shared infrastructure.
3. **Consensus**: ALL Reviewers must GREEN. If any returns BLOCKED, resolve findings and re-submit to the blocking reviewer. If any pre-existing test fails, treat it as a regression.

**Critical rule:** Subagents must NEVER weaken or remove pre-existing test assertions to make their changes pass. If an existing test contradicts the new design, the subagent must flag it to the orchestrator for review — not silently update the assertion.

---

### Step 6: Code Diff Review Gate

After the Regression Gate passes, invoke the
[diff-review](../diff-review/SKILL.md) skill to validate implementation quality
on the full code diff:

1. **Shutdown (teammate mode only)**: If running in teammate mode, shut down all
   Step 5 subagents before invoking the skill. Follow the standard Shutdown
   Procedure defined in the Teammate Lifecycle section above. In subagent mode,
   skip this sub-step and proceed directly to sub-step 2.
2. **Invoke**: Run the `diff-review` skill with `epic_id` set to the epic's
   JIRA ticket and the default base branch (`origin/main`). **If running in
   headless mode**, propagate the headless signal per delegation protocol §5
   (include "You are running in a headless non-interactive session" in the
   invocation prompt and pass `--env CI=true` to any containers).
3. The skill handles diff generation, Dual-Model Review, BLOCKED resolution
   (via its own implementer subagents per the delegation protocol), and ledger
   checkpointing autonomously.

**Critical distinction**: The Regression Gate (Step 5) validates *behavior*
(tests pass). The Code Diff Review Gate validates *implementation quality*
(the code itself is correct, secure, and protocol-compliant). All must pass
before the epic is considered complete.

---

## Cost Analysis: Teams vs. Subagents

### Strategy Selection (Platform-Aware)

| Strategy | When to Use | Claude Code | Other Platforms |
|----------|------------|-------------|-----------------|
| **Direct subagents** | Spec-complete plan, exact edits | Spawn at `fast-*` tier | Default — only option |
| **Tiered subagents** | Mixed complexity across domains | Assign tier per task | N/A — falls back to direct |
| **Parallel teams** | Independent domains, no shared files | Multiple Agent calls in one message | Sequential fallback |
| **Teammate teams** | Long-running multi-domain, true parallelism | TeamCreate + fresh-per-wave tmux agents | N/A |

### Decision Heuristic

**If the plan specifies exact file content, exact edits, and exact
commands** → use plain subagents at the `fast-*` tier. Follow the spec.
**If work requires design judgment, cross-file reasoning, or iterative
discovery** → use tiered subagents or parallel teams with TDD loops at
`medium` or `high-reasoning` tiers as appropriate.

## Model Selection by Complexity

Before invoking a subagent, match the task to a `model_tier`. The
platform resolves the tier to a concrete model at runtime (see
**Tier-to-Model Resolution** above):

| Complexity | `model_tier` | Examples |
|------------|-------------|----------|
| Simple | `fast-*` | Config changes, log reading, file searches, doc formatting, version bumps |
| Medium | `medium` | Standard implementation, Dockerfiles, YAML rewrites, unit tests |
| Complex | `high-reasoning` | Architecture, multi-file refactors, subtle bugs, novel infrastructure |

When in doubt, start one tier lower — it's cheaper to escalate than to
overspend.

## Failure Escalation Protocol

1. A subagent gets exactly **1 attempt per unique (model tier, effort
   variant) matrix point**. If the attempt fails, the subagent returns
   an **escalation report** containing:
   - The exact error or blocker
   - The strategy attempted and why it failed
   - Its best hypothesis for the root cause
   - The exit phrase: `ESCALATION_REQUIRED: <one-line reason>`
2. The orchestrator reads the report and re-dispatches at the **next
   matrix point** — bumping model tier, effort variant, or both
   according to the agent's escalation path. The full escalation
   report is passed as context. The orchestrator determines the next
   step; the subagent does not need to know its position in the
   matrix.
3. The escalation path visits each unique (model tier, effort)
   combination exactly once, from cheapest to most capable:

   Example for `tdd-green` (base → high → xhigh → max):

   | Step | Model Tier | Variant | Matrix Point |
   |------|-----------|---------|-------------|
   | 1 | `fast` | `tdd-green` (base) | (fast, base) |
   | 2 | `medium` | `tdd-green-high` | (medium, high) |
   | 3 | `high-reasoning` | `tdd-green-high` | (high-reasoning, high) |
   | 4 | `high-reasoning` | `tdd-green-xhigh` | (high-reasoning, xhigh) |
   | 5 | `high-reasoning` | `tdd-green-max` | (high-reasoning, max) |

   For agents without `-max`: the path ends one step earlier. For
   agents without `-xhigh` AND `-max`: ends two steps earlier. For
   agents without any variants: model-tier-only escalation
   (fast → medium → high-reasoning), 1 attempt each. See
   [docs/effort_tiers.md](../../../docs/effort_tiers.md) for the
   canonical 4-level effort ladder.

   The total attempt budget is an emergent property of the matrix —
   not a configured number:

   | Starting assignment | Variant chain | Total |
   |--------------------|--------------|----|
   | Simple (`fast`/base) | base → high → xhigh → max | **5** |
   | Medium (`medium`/base) | base → high → xhigh → max | **4** |
   | Complex (`high-reasoning`/high) | high → xhigh → max | **3** |
   | Any (no variants) | model-tier only | **3** |

4. If the top matrix point fails, the orchestrator reports to the user
   with a full status summary of all attempted matrix points and their
   failure reasons.

5. **Reviewer-driven tier promotion via the envelope merge function.**
   When a wave-quality-review gate emits a `MergeDecision` with
   `action == "ESCALATE"`, the orchestrator consumes
   `MergeDecision.recommended_next_tier` (resolved via
   [`planner_tier_pinning.resolve_next_round_tier`](../../../scripts/orchestrator/planner_tier_pinning.py))
   to decide the next round's reviewer effort tier. Round 1 of any
   gate honors the recommendation directly (S-8 discovery bypass);
   round 2+ honors the planner-pinned tier from `plan.md` and only
   escalates via the Frontier-Reservation gate (B-4 R2). The merge
   function is pure Python — the orchestrator MUST NOT invoke an LLM
   to compute `recommended_next_tier` from prose (Req-N02 / Risk-007).
   When the envelope circuit-breaker
   ([`envelope_circuit_breaker.py`](../../../scripts/orchestrator/envelope_circuit_breaker.py))
   trips a family on N=2 consecutive parse failures, the family's
   `orchestrator_tier` is pinned to `"high"` for the remainder of the
   epic (Req-016 / Req-017 sticky tier) — the orchestrator re-spawns
   at `high` on every subsequent agent dispatch.

## Wave Quality Review Aggregation

Per-wave quality review gates use the same deterministic envelope
routing surface as the diff-review skill: parse reviewer outputs via
[`envelope_parser.parse_or_fallback`](../../../scripts/orchestrator/envelope_parser.py),
call
[`envelope_merge.merge`](../../../scripts/orchestrator/envelope_merge.py)
on the `Envelope` list, honor `MergeDecision.action` directly. When
`MergeDecision.cross_family_dissent` is non-null at gate-effort
xhigh/max (B-1 R2 — claude-native APPROVE + bridge RETURN with
critical/significant blocking findings), the gate passes as APPROVE
but the orchestrator MUST checkpoint a `cross_family_dissent` audit
artifact to the Execution Ledger **before** the `gate_verdict`
artifact so the audit precedes the verdict in chronological order.
Bridge `HALT_FOR_OPERATOR` is NEVER softened (B-5 R2) — it always
halts the wave via merge Rule 1.

## Subagent Instructions

Always include these directives in every subagent prompt:

> **CRITICAL: Use the Write tool to create new files. Do NOT use `cat` heredocs or Bash redirection.** The Bash sandbox's injection detector rejects heredocs containing Python type annotations (brace adjacent to quote character). This is a platform-level constraint — not a configurable hook.
>
> If you get stuck or encounter an unresolved error, stop after **1 failed attempt**. Do not loop indefinitely. Return an escalation report with: (1) the exact error, (2) the strategy you tried and why it failed, (3) your best hypothesis for the root cause. End your response with: `ESCALATION_REQUIRED: <one-line reason>`. The orchestrator determines the next escalation step.

## Goal

Deliver the best solution at the lowest token cost. Prefer parallelism for independent tasks. Escalate promptly rather than burning tokens on repeated failures.
