# Glossary

Canonical terminology reference for this repository's orchestration model and agent architecture.
Terms are grouped by concept. For full protocol details, follow the "See:" links.

---

## Relationship Diagram

```text
Orchestrator (high-reasoning)
│
├─ Wave 1 (parallel domains or slices, no shared files)
│  ├─ Domain A / Slice A → Task "auth service"
│  │  └─ Mini-Orchestrator (medium) ←── teammate in tmux pane
│  │     ├─ tdd-red (fast-*)        ← subagent
│  │     ├─ tdd-green (fast-*)      ← subagent
│  │     └─ tdd-refactor (fast-*)   ← subagent
│  ├─ Domain B / Slice B → Task "data pipeline"
│  │  └─ Mini-Orchestrator (medium)
│  │     ├─ tdd-red (medium)
│  │     ├─ tdd-green (medium)
│  │     └─ tdd-refactor (fast-*)
│  └─ [post-wave gate: Executor + Dual-Model Reviewers + git diff + code-quality review]
│
├─ [wave 1 teammate shutdown + fresh respawn for wave 2]
│
├─ Wave 2 (depends on Wave 1 outputs)
│  ├─ Domain C / Slice C → Task "integration contracts"
│  │  └─ Mini-Orchestrator (medium) ←── fresh teammate, no wave-1 context
│  │     └─ ... R-G-R subagents ...
│  └─ [post-wave gate: Executor + Dual-Model Reviewers + git diff + code-quality review]
│
├─ [final teammate shutdown]
│
└─ Regression Gate (Step 5)
   ├─ Executor (fast-*)          ← fresh subagent
   ├─ Reviewer 1 (high-reasoning) ← fresh subagent
   └─ Reviewer 2 (medium)         ← fresh subagent
```

In subagent mode, the Orchestrator spawns wave members directly (no TeamCreate,
no TaskList, no mini-orchestrators). The hierarchy collapses to: Orchestrator → Wave → Subagent.

In vertical decomposition, Domains may be replaced by Slices as the wave member unit.
In horizontal decomposition and hybrid prerequisite waves, Domains remain the wave member unit.

---

## Orchestration Hierarchy

**Domain** — A single architectural component requiring work (e.g., a Go service, Airflow DAG, Terraform module). The atomic unit of team formation and wave assignment.

**Slice** — An end-to-end capability increment that produces an independently mergeable unit. A slice may span multiple architectural components but owns all implementation, tests, and documentation for a single user-facing behavior. The default decomposition unit when using vertical slicing.

In vertical decomposition, Slices replace Domains as the primary decomposition unit. In horizontal decomposition and hybrid prerequisite waves, Domains remain the decomposition unit.

**Merge Strategy** — Declares how completed waves map to PRs. Values: `wave-per-pr` (each wave = one PR, vertical default), `all-waves-one-pr` (single PR after all waves, horizontal default). `custom` is reserved for future use.

**Wave** — A set of wave members (domains or slices) that execute concurrently because they share no files and have no producer-consumer dependency. Waves are strictly ordered; wave N+1 does not start until wave N passes the post-wave verification gate. In vertical mode with `wave-per-pr` merge strategy, each wave produces an independently mergeable unit. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

**Task** — A discrete unit of work assigned to a single teammate or subagent, scoped to one domain or slice. In teammate mode, tasks are managed via `TaskCreate` / `TaskUpdate` and polled from `TaskList`.

---

## Agent Roles

**Orchestrator** — Pure coordinator and reviewer. Spawns subagents, reviews their output, and manages wave gating. Must NEVER write code or run validation commands directly. See: [delegation_protocol.md](delegation_protocol.md)

**Planner** — Queries the Execution Ledger, drafts `plan.md`, and selects the execution strategy. Read-only access; delegates all implementation. See: [planning_protocol.md](planning_protocol.md)

**Executor (Agent A)** — A `task`-type subagent that discovers the correct build tool and runs lint/test commands. Returns raw stdout/stderr. Never writes code. See: [verification_protocol.md](verification_protocol.md)

**Reviewer (Agent B)** — A `code-review`-type subagent that analyzes Executor output and inspects artifacts for hallucinated success or faked data. Must not trust the Executor's summary blindly. See: [verification_protocol.md](verification_protocol.md)

**Implementer** — A `tdd-green`, `tdd-refactor`, or `general-purpose` subagent that applies code fixes after a Reviewer flags a failure. Must never run tests itself.

**Mini-Orchestrator** — A teammate acting as a domain-scoped orchestrator in teammate mode. Self-drives the full R-G-R lifecycle by spawning `tdd-red` → `tdd-green` → `tdd-refactor` subagents for its assigned domain. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

---

## Execution Modes

**Subagent mode** — Default execution model. The Orchestrator spawns isolated subagents sequentially or in parallel (platform-dependent) for each wave member. Each subagent is short-lived and exits after its task.

**Teammate mode** — Tmux-backed Claude Code instances created via `TeamCreate`. Teammates are **fresh per wave** (shutdown after each wave, new ones spawned for the next) to prevent context pollution. They poll `TaskList` autonomously and act as mini-orchestrators. Preferred for long-running, multi-domain work requiring true parallelism. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

**Wave member** — Any subagent or teammate assigned to a single domain or slice within a wave, regardless of execution mode.

---

## Lifecycle

**Bridge Agent** — An execution agent that proxies review prompts to an external AI CLI running inside the `agent-cli`
Docker container. Bridge agents perform minimal reasoning: pre-flight checks, prompt construction, task alias invocation,
and raw output capture. Each bridge agent is invoked independently; their pre-flights run in parallel when multiple are
requested. See: `copilot-reviewer.md`, `gemini-reviewer.md`.

**Cross-Family Review Extension** *(review mechanism)* — An optional upgrade to the Dual-Model Review Gate that
introduces additional reviewers from different AI model families via bridge agents (copilot-reviewer, gemini-reviewer).
When activated, elevates the gate from 2-of-2 to N-of-N where N = 2 Claude reviewers + the number of active bridge
agents. Each bridge agent's availability is determined independently at pre-flight; unavailable bridge agents are
excluded and the remaining active reviewers continue. The standard 2-of-2 gate proceeds unmodified when no bridge
agents are available.
See: [verification_protocol.md](verification_protocol.md)

**R-G-R (Red-Green-Refactor)** — The mandatory TDD loop every domain must complete: (1) `tdd-red` writes failing tests, (2) `tdd-green` writes minimum implementation to pass, (3) `tdd-refactor` cleans up without changing behavior. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

**Wave gating** — The rule that wave N+1 tasks are not created until all wave N tasks show `completed` and the post-wave verification gate passes.

**Post-wave verification gate** — After a wave completes, the Orchestrator runs the Dual-Model Review Gate (Executor + two Reviewers + `git diff` overlap check) followed by a per-wave code quality review (single `code-review-high` on wave-scoped diff) before advancing to the next wave. Critical or significant findings block; minor or informational are captured as TODOs. See: [verification_protocol.md](verification_protocol.md)

**Per-wave code quality review** — A lightweight single-reviewer (`code-review-high`) code diff review run after the post-wave lint/test gate passes. Scoped to wave-changed files only. Uses a 5-point focused prompt (security, standards, accidental deletions, anti-faking, linter suppressions). Severity-gated: critical/significant block wave N+1 with 4-attempt escalation ladder (implementer: `fast` → `medium` → `high-reasoning` → `high-reasoning`/max; reviewer: `code-review-high` → `code-review-max` on attempt 4); minor/informational become TODOs. See: [verification_protocol.md](verification_protocol.md)

**Regression gate** — A full test suite run (Executor + Dual-Model Reviewers) executed after ALL waves complete to confirm no pre-existing tests were broken. Runs with fresh subagents after teammate shutdown. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

**Double-Check Verification Protocol** — The 3-agent boundary (Executor → Reviewer → Implementer) that prevents self-validation. The Orchestrator never runs tests directly. See: [verification_protocol.md](verification_protocol.md)

**Dual-Model Review Gate** — Two independent reviewers at the highest and second-highest model tiers must both GREEN before a gate passes. Applied at plan reviews, post-wave verification gates, and the final regression gate. When cross-family models are available, one reviewer must be cross-family. See: [verification_protocol.md](verification_protocol.md)

**Step verification** — At the end of every individual step, the agent must read `plan.md`, parse `CLAUDE.md`, stage changed files (`git add`), run `task lint:staged` + `task test:staged`, and checkpoint a `step_result` artifact to the Execution Ledger before declaring the step complete. See: [verification_protocol.md](verification_protocol.md)

---

## Communication

**Escalation (local)** — In teammate mode, a teammate bumps its subagent to the next matrix point (model tier, effort variant, or both) and retries before involving the Orchestrator. Each matrix point gets 1 attempt. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

**Escalation (orchestrator)** — If a subagent exhausts its escalation matrix (all matrix points attempted), the agent sends a structured escalation report (`ESCALATION_REQUIRED: <reason>`) to the Orchestrator via `SendMessage`. The Orchestrator spawns a replacement at a higher tier with the report as context. See: [delegation_protocol.md](delegation_protocol.md)

**Parallel escalation** — Failure recovery strategy that bumps model tier, effort variant, or both in a single step. Each unique (model tier, effort variant) matrix point gets exactly 1 attempt. The total attempt budget is an emergent property of the agent's variant chain (e.g., base → high → xhigh → max = up to 5 matrix points from a `fast` start). See: **Failure Escalation Protocol** in [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md).

**Shutdown protocol** — The Orchestrator sends `{ type: "shutdown_request" }` to each teammate and awaits `{ type: "shutdown_response" }`. Occurs in two cases: (1) between waves — all teammates are shut down and fresh ones spawned for the next wave to prevent context pollution; (2) before the regression gate — final shutdown before spawning regression-gate subagents. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

**TaskList polling** — In teammate mode, teammates autonomously poll `TaskList`, claim tasks via `TaskUpdate` (set owner), and mark them `completed` when done. The Orchestrator also polls `TaskList` for wave gating decisions.

---

## State Tracking

**`plan.md`** — The ephemeral session scratchpad. Used by the Planner and Orchestrator during an active session for step-by-step check-boxing. Ignored by version control; safe to overwrite between sessions. See: [planning_protocol.md](planning_protocol.md)

**Execution Ledger** — The authoritative persistent record for the planning and implementation lifecycle. A ChromaDB-backed store (`execution_ledger` collection) that records plans, design decisions, gate verdicts, step results, wave summaries, and PR lifecycle events (`pr_created`, `pr_merged`) for every epic. `plan.md` remains the ephemeral session scratchpad; the ledger is the source of truth for cross-session resumability and audit. CLI: `execution-ledger index-epics`, `execution-ledger resume`, `execution-ledger status`, `execution-ledger checkpoint`. See: [execution-ledger SKILL.md](../workflows/agent-memory/skills/execution-ledger/SKILL.md)

**ChromaDB / Knowledge Base (general-purpose)** — The shared ChromaDB vector database
instance (`global-chromadb` container) accessed via
`knowledge_base.py`. User references to "ChromaDB," "chroma," or
"save to chroma" always mean this general-purpose document store — never
the Execution Ledger. The ledger uses a separate `execution_ledger`
ChromaDB collection internally but is only referenced by its explicit
name ("ledger," "execution-ledger"). See:
[knowledge_base.py](../workflows/agent-memory/skills/knowledge-base/scripts/knowledge_base.py)

---

## Model Tiers

Model tiers are abstract capability labels declared in agent frontmatter. The Orchestrator resolves them to concrete models at runtime based on platform capabilities — model IDs are never hardcoded in skills. See: [agent-team SKILL.md](../.claude/skills/agent-team/SKILL.md)

**`fast-*`** — Lowest latency, cheapest token cost. Used for config changes, log parsing, file searches, and doc formatting. The suffix is a semantic hint for the agent's purpose: `fast-execution` (CLI runners, bridge proxies), `fast-search` (read-only exploration), `fast-iteration` (rapid lint/test cycles). All subtypes resolve to the same concrete model at runtime.
**`medium`** — Balanced speed and reasoning. Used for standard implementation, unit tests, Dockerfiles, and YAML rewrites.
**`high-reasoning`** — Deepest reasoning, highest capability. Used for architecture, multi-file refactors, subtle bugs, and novel infrastructure.

**effort** — Claude Code reasoning depth control (`low`/`medium`/`high`/`max`). Set via `/effort`, agent frontmatter, or `CLAUDE_CODE_EFFORT_LEVEL` env var. Higher levels increase reasoning quality and token cost. Default: `medium`. Effort is orthogonal to model tiers — a `high-reasoning` model at `low` effort uses the most capable model with minimal thinking.
