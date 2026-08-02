---
name: Deep Repos Research
description: >-
  Plan a deep research epic for one or more upstream services to produce
  repos-guides, .claude/rules/, and .github/instructions/ documentation
  artifacts. Requires arguments: SERVICE_NAMES, UPSTREAM_REPO, JIRA_TICKET.
---

# Deep Repos Research Prompt

> **Agent Instructions:**
>
> - Requires arguments: `<SERVICE_NAMES>`, `<UPSTREAM_REPO>`, `<JIRA_TICKET>`.
> - Optional arguments: `<CLIENT_REPOS>`, `<STORAGE_BACKENDS>`,
>   `<INGESTION_METHODS>`, `<DOWNSTREAM_REPOS>`.
> - If `<SERVICE_NAMES>`, `<UPSTREAM_REPO>`, or `<JIRA_TICKET>` is missing from
>   the user's request, **HALT and ask the user** to provide it. Do NOT
>   hallucinate or guess missing values.
> - This prompt produces a **plan** — it does not execute implementation. The
>   output is an approved `plan.md` ready for execution via `/agent-team`.

## Arguments

| Argument | Required | Description | Example |
|----------|----------|-------------|---------|
| `<SERVICE_NAMES>` | Yes | Comma-separated service names to research | `billing, accounts` |
| `<UPSTREAM_REPO>` | Yes | The upstream repository (`Org/repo`) | `<org>/<repo>` |
| `<JIRA_TICKET>` | Yes | Tracking ticket ID | `PROJ-1234` |
| `<CLIENT_REPOS>` | No | Client repos for light-trace | `ios, android, web` |
| `<STORAGE_BACKENDS>` | No | Storage technologies used by services | `MySQL, DynamoDB` |
| `<INGESTION_METHODS>` | No | How data leaves the service for analytics | `JDBC, CDC, REST API, event stream` |
| `<DOWNSTREAM_REPOS>` | No | Downstream consumers to light-trace | `<org>/<consumer-repo>` |

## Execution

Plan first the following: A deep research of `<UPSTREAM_REPO>`'s these services:
`<SERVICE_NAMES>` in order to craft comprehensive and detailed repos-guides and
`.claude/rules/` and `.github/instructions/`.

### Prior Art Discovery (MANDATORY)

Before starting any research phase, agents MUST read existing
documentation to establish a baseline and avoid redundant work:

1. **Target guide**: Read `docs/repo-guides/<repo>/<service>.md` for
   each service in `<SERVICE_NAMES>` (if it exists). Identify
   `[GAP:UNVERIFIED]`, `[GAP:INCORRECT]`, and `[INCOMPLETE:*]`
   markers — these are the priority research targets.
2. **Sibling guides**: Read other guides in `docs/repo-guides/<repo>/`
   (e.g., the repo `README.md` and other service guides). Gaps in
   one service guide may already be resolved by a sibling guide that
   documents the same domain from a different angle.
3. **Cross-repo guides**: Read guides from related repos that the
   target service interacts with. A downstream consumer's guide often
   already documents the target's table schemas and integration points
   from the other side of the boundary.
4. **Scope research to gaps**: If existing guides cover a topic with
   no gap markers, do NOT re-research it unless the user explicitly
   requests an update (e.g., "re-research storage schemas" or
   "update the API endpoints section"). Focus research time on
   filling gaps, verifying unverified claims, and adding missing
   coverage. If no guides exist for the target service, proceed with
   full research.

This step applies on every iteration. The prompt is designed for
iterative use — each cycle deepens and refines existing guides
rather than starting from scratch.

### Research Focus

The research must trace the complete data lineage from API endpoints (contracts)
through storage persistence (database schemas) to downstream consumption.
Specifically:

1. **Upstream repo foundation**: Monorepo structure, build system, shared libraries,
   service registry, API routing, deployment topology.
2. **Per-service deep dive** (for each service in `<SERVICE_NAMES>`):
   - Service entry point, dependency injection, route registration
   - API endpoints that produce datalake-relevant data (annotate ingestion method)
   - Domain models and business logic packages
   - Storage schemas: all tables across `<STORAGE_BACKENDS>`, annotated with how each
     one leaves the service for analytics (per `<INGESTION_METHODS>`) — CDC-replicated,
     JDBC-ingested, API-pulled, emitted as events, or not exported at all
   - SQL migration folder structure and `service-db-schema` skill applicability
   - Event broadcasting (SNS/SQS topics, event consumers)
   - Background workers and CLI tools (`cmd/` directory)
   - External service integrations
3. **Downstream trace** (if `<DOWNSTREAM_REPOS>` provided):
   - Light-trace analytics pipelines, transformation models, or other consumers that
     read the service's tables or events
   - Where the consumer is a multi-stage pipeline, record the stage boundaries
     (raw → transformed → serving) and the source-to-target table mappings, plus the
     orchestrator that schedules them
   - Document model/job names and source table references only — no deep-dive
4. **Client trace** (if `<CLIENT_REPOS>` provided):
   - Light-trace which client repos call which service endpoints
   - Entry points and endpoint constants only — no client implementation deep-dive
5. **Core API surface** (ALWAYS include — not gated by optional args):
   - Inventory the endpoints that define the service's contract with the rest of the
     system — the operations a caller must understand to use or change it safely
   - For each endpoint: HTTP method, path, request/response shape, auth requirements,
     downstream data effects (what tables are written, what events are emitted)
   - Annotate which endpoints have side effects versus which are pure reads
   - Record any domain vocabulary whose code name differs from its business name.
     Mismatched nouns are a top source of agent error; capture the mapping in the
     guide and, if the repo has one, in its `.claude/rules/repos.<repo>.md`
6. **Event & observability surface** (ALWAYS include — not gated by optional args):
   - Inventory the events and metrics the service emits: message-bus/stream events,
     application metrics, structured log signals
   - For each event: name, trigger condition (which business action fires it), payload
     fields, and destination
   - Map business actions to event names — this action-to-event mapping is what
     downstream data consumers need most and is rarely documented in the code
   - Document how events are registered and versioned (schema definitions, registry
     entries, sample rates, rollout/migration flags)
7. **AI coding readiness assessment** (ALWAYS include — not gated by optional args):
   - **Domain boundary clarity (DDD)**: Are there clean bounded contexts? Is business
     logic separated from infrastructure (handlers → service → storage layering)? Can
     an agent modify one domain without understanding the entire service? Rate each
     service: `clear` / `mixed` / `entangled`
   - **Test infrastructure**: Unit test coverage (existence, patterns, mocking style),
     integration tests (real DB via Docker, mocked, or absent), end-to-end tests,
     staging environment availability and parity. Test execution method (Docker,
     `make test`, host `go test`, CI-only). Rate: `comprehensive` / `partial` /
     `minimal` / `none`
   - **Build & CI ergonomics**: Can agents run lint/test/build locally via Makefile or
     Taskfile targets? Docker-based builds? Pre-commit hooks? CI pipeline steps and
     typical cycle time?
   - **Code navigability**: Are entry points discoverable (single `main.go`, clear
     DI wiring)? Godfiles (>500 LOC)? Dependency graph depth? Magic or convention-
     over-configuration patterns that require implicit knowledge?
   - **Configuration complexity**: Env var count, secrets management pattern
     (Secrets Manager, env injection, config files), feature flags, multi-environment
     config divergence between staging and prod
   - **Change safety signals**: Circuit breakers, graceful degradation, rollback
     mechanisms, canary deployment support, typical blast radius of a 1-file change
   - **Documentation quality**: Inline comment density, README accuracy, API docs
     (OpenAPI/Swagger), migration history clarity, existing repo-guides coverage
   - Produce a **Readiness Scorecard** per service summarizing ratings with specific
     evidence (file paths, line counts, test counts) — this scorecard is the primary
     input for coding agents estimating implementation effort
   - Produce **Improvement Recommendations** per service: a prioritized list of
     concrete changes that would improve AI coding readiness. Each recommendation
     MUST include:
     - **Priority**: `P0-critical` (blocks agent work — agents cannot safely make
       changes without this), `P1-high` (significantly slows agents — causes frequent
       failures, re-research, or manual intervention), `P2-nice-to-have` (improves
       agent efficiency but agents can work around it)
     - **Category**: which readiness dimension it addresses (domain boundaries, test
       infra, build ergonomics, navigability, config, safety, docs)
     - **Effort estimate**: `small` (<1 day), `medium` (1-3 days), `large` (>3 days)
     - **Concrete action**: what specifically to do (e.g., "extract wallet domain into
       `internal/wallet/` package with its own interface", not "improve domain
       boundaries")
     - **Evidence**: the specific files, patterns, or gaps that justify the
       recommendation
   - Priority calibration guidelines:
     - `P0-critical`: No test infrastructure at all, entangled domains where a 1-line
       change cascades unpredictably, no local build/test path (CI-only), missing
       migration history, undocumented shared-state mutations
     - `P1-high`: Tests exist but lack integration coverage for critical paths,
       godfiles >500 LOC with mixed concerns, >20 env vars with no documentation,
       implicit DI wiring requiring tribal knowledge, no staging environment for
       services with external integrations
     - `P2-nice-to-have`: Missing OpenAPI docs, low inline comment density in
       straightforward code, minor naming inconsistencies, test helpers that could
       be DRYed up

### Output Artifacts

The plan must produce these documentation artifacts in `brownfield-ai`:

| Artifact | Path Pattern |
|----------|-------------|
| Repo overview guide | `docs/repo-guides/<repo>/README.md` |
| Per-service guide | `docs/repo-guides/<repo>/<service>.md` |
| General rules | `.claude/rules/repos.<repo>.md` |
| Per-service rules | `.claude/rules/repos.<repo>.<service>.md` |
| Copilot instructions (general) | `.github/instructions/repos.<repo>.instructions.md` |
| Copilot instructions (per-service) | `.github/instructions/repos.<repo>.<service>.instructions.md` |
| AI readiness scorecard | `docs/repo-guides/<repo>/<service>-readiness.md` (standalone; linked from per-service guide) |
| Additional guides | `docs/repo-guides/<repo>/*.md` (agent discretion) |

### Quality Requirements

- **Self-contained guides** (`[Req-009]` pattern): Agents must be able to answer
  most questions from the guide alone without needing `gh search` or cloned repos.
  This is the primary design constraint — the guide IS the agent's reference.
- **Complete first draft** with `[GAP:UNVERIFIED]` markers where claims could not
  be confirmed from codebase, and `[GAP:INCORRECT]` markers where claims were
  verified as wrong but could not be corrected after re-research.
- **No secrets**: Summarize credential retrieval patterns — never render raw ARNs,
  secret paths, or credential variable names.
- **Extensible**: The repo overview guide must serve as a foundation that future
  service-specific guides can build on.
- **Naming**: Reference `brownfield-ai` (not the local folder name) in all artifacts.

---

## Agent Capacity Budgeting (CRITICAL)

A single `explore` agent cannot read an entire service codebase in one session.
Agent tool-use budgets are finite (~100-180 tool calls). **Services with >60
source files MUST be decomposed into sub-domain clusters of 30-60 source files
each.** Failure to decompose causes agents to exhaust their budget mid-research
and produce incomplete output with false `[UNVERIFIED]` markers.

### Decomposition Pattern

For each service in `<SERVICE_NAMES>`, the Planner MUST:

1. **Count source files** (excluding tests and mocks): Run
   `find repos/<repo>/path/to/<service> -name "*.go" -not -name "*_test.go" -not -path "*/mocks/*" | wc -l`
   (adjust for language — `*.py`, `*.ts`, etc.).
2. **If count > 60**: Split the service into sub-domain clusters based on directory
   structure. Each cluster targets a coherent domain (e.g., storage, wallet, paywall)
   with ≤60 source files. All sub-tasks within a service run in parallel.
3. **If count ≤ 60**: A single agent per service is sufficient.
4. **File estimates in sub-task headers** count source files only (excluding
   `*_test.*` and `mocks/`). Agents SHOULD selectively read test files when they
   illuminate unclear behavior but test files are not mandatory research targets.

### Capacity Markers

If an agent cannot complete its assigned scope, it MUST document what was covered
and what remains as explicit `[INCOMPLETE:<reason>]` markers (distinct from
`[UNVERIFIED]` which means a claim could not be confirmed against source, and
`[GAP:INCORRECT]` which means a claim was verified as wrong). An agent MUST NOT
silently assume files are missing or attribute gaps to "sparse checkout" when files
exist locally.

---

## Repository Inventory & Clone Policy

The plan MUST include a **Repository Inventory** table listing all repos that
research agents will access, with columns: Repository, Local Path, Usage, Clone
Type.

### Branch Freshness (MANDATORY)

Before reading any repo under `repos/`, the research agent MUST run
`task git:fetch` and `task git:checkout` to ensure the default branch is checked
out and up-to-date with the remote. If `git:fetch` fails (network error, auth
failure), the agent MUST log the failure and note the current local HEAD commit
SHA in its output, then proceed with local state.

### Clone Policy for Unlisted Repos

Research agents MAY freely use `task gh:search` and `task git:sparse-clone` on
demand for any additional repos discovered during research — no pre-approval
required. Prefer `gh:search` for targeted lookups; use `sparse-clone` when
multi-file analysis is needed. The agent MUST document any additional repo access
in its research output.

---

## Research Output Format Contract

All research sub-tasks produce intermediate Markdown files under `tmp/research/`.
The Orchestrator uses these to feed verification agents and assembly agents.

**Naming convention**: `tmp/research/phase<N><letter>-<service>-<domain>.md`

Example for a 2-service epic with 6 sub-tasks per service:

```text
tmp/research/phase1-<repo>-foundation.md
tmp/research/phase2a-<svc1>-core.md
tmp/research/phase2b-<svc1>-storage.md
...
tmp/research/phase3a-<svc2>-core.md
...
```

**Consolidated files** (produced by Orchestrator before verification/assembly):

- `tmp/research/phase2-<svc1>-consolidated.md` — concatenation of all sub-tasks
- `tmp/research/phase3-<svc2>-consolidated.md` — concatenation of all sub-tasks

Each research file MUST cite exact file paths for all factual claims to enable
targeted verification in Tier 1 checks.

---

## Verification Protocol

The plan MUST include a **three-tier verification** approach:

### Tier 1 — Post-Research Factual Accuracy (advisory, single-reviewer)

After each research wave completes, an Opus `explore` agent cross-checks research
findings against the actual codebase. This is a **single-reviewer advisory factual
check**, not a full Dual-Model gate. Its findings feed into Tier 3 where the
authoritative gate applies.

**Input consolidation**: Before dispatching the Tier 1 verifier, the Orchestrator
MUST consolidate all sub-task research outputs for the service into a single file.
The verifier receives one consolidated document, not N separate sub-task outputs.

**Verification scoping**: Each verification agent uses **targeted file reads** —
reading the specific file paths cited in the research notes — rather than
open-ended grep operations. This bounds tool usage to approximately 2× the number
of critical claims.

**Scope**: Table names match migrations, endpoint paths match route definitions,
DynamoDB schemas match storage packages, data flow claims are traceable in code,
pipeline table names match Spark app source.

**Resolution loop**: max 2 rounds. INCORRECT claims trigger re-research.
UNVERIFIED claims are annotated for `[GAP]` rendering in assembly.

### Tier 2 — Post-Assembly Spot-Check

Sonnet `explore` agents verify assembled guides faithfully represent verified
research notes. Covers all artifact types including `.claude/rules/` and
`.github/instructions/`. Resolution loop: max 3 rounds.

### Tier 3 — Cross-Family Diff Review (authoritative gate)

3-of-3 Code Diff Review Gate (Opus + Sonnet + copilot-reviewer) on the full
documentation diff. Reviewers receive Tier 1 and Tier 2 verification reports
as context. Includes `docs-review` and `claude-review` skill invocations for
structural alignment. Resolution loop: max 6 rounds.

---

## Artifact Assembly Pattern

### Task-to-Agent Mapping

Phase 6a (assembly) MUST include an explicit task-to-agent mapping table showing
which agent handles which tasks and their input files. The mapping must enforce
these sequencing constraints:

1. **Per-service guides** (parallel): Each service guide + its rules file runs as
   one agent. Input: consolidated research notes + lineage + client trace notes.
2. **Repo overview / README** (sequential, after per-service guides): The README
   agent receives finalized per-service guides (not raw research) to produce a
   consistent cross-service summary.
3. **Audit agent** (sequential, after all above): Produces `.github/instructions/`
   files, runs self-containment audit, and compiles `[GAP]` inventory. Input: all
   finalized guides + rules + Phase 5 research notes for cross-check.

### Cross-Sub-Task Merges

When a requirement spans multiple parallel sub-tasks (e.g., notification flow
split across a core sub-task and a store-specific sub-task), the assembly task
MUST include an explicit merge note directing the assembly agent to reconcile
the partial findings into a single coherent narrative.

---

## Execution Strategy

The plan MUST use `/agent-team` with:

- **Wave-based execution**: Foundation research → per-service deep research
  (parallel sub-tasks) → verification → lineage + client traces (parallel) →
  verification → assembly + spot-check → final QA
- **Tiered model selection**: Complex cross-file reasoning on Opus (e.g., store
  notification flow tracing), medium research on Sonnet, QA lint on Haiku.
  Decomposition enables most sub-tasks to run on Sonnet instead of Opus.
- **Cost analysis**: Token estimates per phase, total cost, worst-case cost with
  resolution loop footnotes (per-round costs), comparison vs direct subagents

### Decomposition Cost Benefit

Decomposing large phases from monolithic Opus agents into parallel Sonnet
sub-tasks typically reduces cost by 50-70% per phase (Sonnet is 5x cheaper per
input token, 5x cheaper per output token). The per-agent overhead (~35K tokens
system prompt + tool definitions) increases total tokens but at Sonnet rates the
cost is marginal (~$0.10/agent).

---

## Planning Protocol

Follow the full planning protocol from `docs/planning_protocol.md`:

1. **Requirements Elicitation**: Grill the user one question at a time to surface
   hidden requirements. Provide recommended answers based on codebase exploration.
   Produce a numbered `[Req-*]` list. Do not proceed until user confirms.
2. **Draft**: Write `plan.md` with phases, verification sub-tasks, execution
   strategy, cost analysis, and output artifact inventory.
3. **Dual-Model Review**: Submit to 3-of-3 gate (Opus + Sonnet + copilot-reviewer).
   Resolve ALL findings. Re-submit until all reviewers return APPROVED.
4. **Present to user**: Ask user to approve, save as draft, or adjust.
5. **Pre-Execution Ledger Checkpoints**: After approval and BEFORE execution,
   checkpoint `plan_snapshot` and `requirement_map` to the Execution Ledger.

### Grilling Seed Questions

When eliciting requirements, use these as a starting framework (adapt per service):

1. **Output scope**: What artifacts? Per-service guides, shared overview, rules?
2. **Rules layering**: General repo rules + per-service rules?
3. **API scope**: All endpoints or only datalake-relevant?
4. **Storage scope**: All tables or only datalake-ingested?
5. **Client integration depth**: Light-trace or deep-dive?
6. **Downstream scope**: Which analytics pipelines, transformation models, or
   dashboards consume this service's data?
7. **Iteration strategy**: Complete first draft with gaps, or skeleton?
8. **Related services**: Any shared libraries or adjacent services to include?
9. **Event-driven patterns**: Real-time event processing? Which event sources?
10. **Pre-cloned repos**: Which repos are already cloned locally? Which need cloning?
11. **Event inventory**: Which events and metrics does the service emit, and what
    business actions trigger them?
12. **Core API surface**: Which endpoints define the service's contract with the rest
    of the system? Which have side effects versus being pure reads?
13. **Domain vocabulary**: Are there code names that differ from their business names?
14. **AI coding readiness**: How important is the readiness assessment for your use
    case? Should it cover all 7 dimensions or focus on specific areas (e.g., test
    infra only, domain boundaries only)?
15. **Change planning context**: Are there upcoming changes planned against these
    services? What kind — new features, bug fixes, migrations, refactors? This
    calibrates which readiness dimensions matter most.

### Invocation Shape

Fill every required argument and only the optional ones that apply:

```text
SERVICE_NAMES: <comma-separated services>
UPSTREAM_REPO: <org>/<repo>
JIRA_TICKET: <ticket-id>
CLIENT_REPOS: <optional, comma-separated>
STORAGE_BACKENDS: <optional, comma-separated>
INGESTION_METHODS: <optional, comma-separated>
DOWNSTREAM_REPOS: <optional, comma-separated>
```

### Learnings Baked Into This Template

These come from running the prompt against large production monorepos and are the
reason for the decomposition and verification machinery above:

- Two monolithic agents over a 350-file and a 200-file service exhausted their tool
  budgets and emitted false `[UNVERIFIED]` gaps. Splitting them into 12 parallel
  sub-tasks eliminated the false gaps entirely — this is why the capacity budgeting
  section is mandatory rather than advisory.
- A 288-file pipeline lineage trace needed 5 parallel sub-tasks for the same reason.
- Intermediate research files need a format contract, or the assembly agents cannot
  reliably consume them.
- Tier 1 verification only stays affordable with input consolidation plus
  targeted-read scoping; open-ended grep verification blows the budget.
- Assembly sequencing matters: per-service guides in parallel, then the README
  sequentially from the finished guides, then the audit agent last.
- Shifting decomposed sub-tasks from the top tier to the mid tier cut cost by roughly
  half with no measurable quality loss.
