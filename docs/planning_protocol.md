# Planning & Orchestration Protocol

To ensure high-quality architecture and prevent bias, the [Planner](../.claude/agents/planner.md) and [Orchestrator](../.claude/agents/orchestrator.md) act solely as managers and **MUST NOT** write implementation code or validate plans in isolation. For term definitions (Domain, Wave, Task, etc.), see the [Glossary](glossary.md).

## 1. Agent Roles

### Planner Role

- **Scope**: Requirements analysis, architectural design, and drafting the plan.
- **Pre-requisite (Environment Consistency)**: Before analyzing existing code or structural paths (especially under `repos/*`), the Planner MUST establish a clean environment. The Planner must either spawn an executor to run `task repos:reset` or rely on remote sources (e.g., executing `gh search` or `gh repo view`) rather than assuming the local [repos/](../repos) directories are up-to-date and clean.
- **Restriction**: Do **NOT** write code directly (e.g., using `create` or `edit` tools for application code). Delegate all implementation to sub-agents.
- **Allowed**: You may manage `plan.md` and session artifacts, but application code changes must be delegated.

### Orchestrator Role

- **Scope**: Delegation, execution management, and synthesis.
- **Restriction**: Do **NOT** write code directly. Delegate all implementation and testing to sub-agents.
- **Allowed**: You may monitor progress and manage session artifacts.

## 2. Dual-Model Plan Review

Before starting implementation, every plan must be validated by **two independent reviewers** at the highest and second-highest model tiers available. When cross-family models are available, one reviewer must be cross-family. Both must GREEN before proceeding. See [verification_protocol.md](verification_protocol.md) for the full Dual-Model Review Gate protocol.

### State Tracking (Execution Ledger vs. plan.md)

To prevent context loss and provide shared visibility across sessions, project tracking is split across two sources:

- **Execution Ledger**: The persistent, repository-wide project registry. The Planner MUST query the ledger (`execution-ledger index-epics`) before designing new features to grasp ongoing epics and dependencies. At the completion of an epic, the Orchestrator MUST update the ledger status to `completed` via the `execution-ledger status` command.
- **`plan.md`**: The ephemeral scratchpad. Used solely by the Planner and Orchestrator during the active session to track step-by-step state (e.g., `[ ] Sub-task:` check-boxing). It is ignored by version control and is safe to overwrite between contexts.
- **`todo-plan.md`**: A user-facing scratchpad for tracking follow-up TODOs that are expected to be planned and implemented shortly after the current work. Distinct from `plan.md` (the active session execution plan) and the Execution Ledger (persistent project registry). Ignored by version control.

### Process

1. **Context Initialization**: Planner queries the Execution Ledger (`execution-ledger index-epics` and `execution-ledger resume` for active epics) to align with current work.

   **Domain Research (Mandatory Pre-Grilling)**: Immediately after
   ledger initialization, the Planner MUST extract domain signals
   (repository names, service names, pipeline names, technology
   keywords), including implicit references that map to specific
   repos via [company.md](company.md) business-to-tech mapping,
   from the user's prompt and proactively research them
   using the tiered discovery strategy defined in
   [CLAUDE.md](../CLAUDE.md) Principle 12. This research front-loads
   codebase context so the grilling phase produces targeted,
   informed questions rather than cold assumptions. If no domain
   signals can be extracted from the prompt even after applying
   the [company.md](company.md) business-to-tech mapping (e.g.,
   a request with no identifiable product features, services, or
   technical keywords), skip this research phase and proceed
   directly to grilling — all domain context is treated as
   unresolved.

   **Execution order** (stop at the earliest tier that resolves
   each signal — tier 3 is restricted to pre-existing checkouts;
   do not perform new clones during grilling):

   1. **Local guides**: Invoke the `repos-guide` skill for each
      extracted domain signal to surface matching entries from
      `docs/repo-guides/`. This is zero-cost and authoritative.
      A signal is resolved by local guides if a matching
      `docs/repo-guides/` entry exists and provides actionable
      context. If no entry is found, the signal falls through to
      tier 2.
   2. **Remote search**: For signals not covered by local guides,
      invoke the `github-search` skill to query the upstream org
      (`<org>/<repo>`) for cross-repo context — API contracts,
      schema definitions, deployment topology, or naming conventions
      relevant to the user's prompt. If github-search returns zero
      results or only irrelevant results for a signal, the signal
      falls through to tier 3 if a local checkout exists; otherwise
      it becomes an open question for grilling.
   3. **Existing checkouts** (subset of Principle 12's sparse-clone
      tier, restricted to pre-existing checkouts during grilling):
      If `repos/<repo>/` already exists locally,
      delegate an `explore` agent scoped to that directory to
      extract implementation details (function signatures, config
      schemas, test patterns) that inform grilling questions.
      If the `explore` agent errors or
      returns no usable output, treat the signal as unresolved
      and record the failure in the Domain Research Summary.
      Do NOT clone a repo solely for grilling (grilling does not
      constitute "deep multi-file analysis" per CLAUDE.md Principle
      12, so the cloning tier does not apply) — cloning is reserved
      for the implementation phase when deep multi-file analysis is
      required.

   **Output**:

   - **Domain Context Brief**: An internal summary covering
     (a) which repos and services are in scope, (b) key
     conventions and constraints surfaced from guides, (c) any
     cross-repo dependencies or blast radius concerns, and
     (d) open questions that guides and search could not resolve
     (these become grilling questions). This brief informs every
     subsequent grilling question and recommended answer. It is
     held in the agent's context window only — it is not
     persisted to any file.
   - **Domain Research Summary**: A condensed, auditable subset
     of the Brief — it contains the research checklist and open
     questions but omits the full contextual analysis. The
     Planner MUST persist this lightweight summary to `plan.md`
     containing: a checklist of signals researched, which
     discovery tiers were exercised (local guides / remote
     search / existing checkout), and any open questions
     forwarded to the grilling phase. The Planner MUST write
     the summary to `plan.md` after tier 1 completes and update
     it incrementally as tiers 2 and 3 are exercised. The
     Domain Research Summary in `plan.md` is the sole persisted
     artifact of this phase (the Draft step in step 3 MUST
     carry the Domain Research Summary forward when building
     `plan.md` — it is not discarded during plan evolution).
     This summary makes the research auditable by reviewers and
     the Orchestrator.

   **Headless mode** (`CI=true`): All three tiers are
   non-interactive and proceed identically in headless mode.
   Domain research is a best-effort enrichment step, not a
   validation gate, so graceful degradation is appropriate —
   unlike the grilling phase, which remains fail-closed.
   Tier-specific failure handling:
   - If `repos-guide` returns no match for any signal, proceed
     to the next tier.
   - If `github-search` fails (e.g., missing `GH_TOKEN`),
     proceed with local guides and existing checkouts only.
   - If the `explore` agent fails on a tier 3 checkout, treat
     the signal as unresolved.
   If all tiers fail or are inapplicable for a given signal,
   proceed to grilling with that signal recorded as fully
   unresolved — no halt is triggered.
   Record any skipped or failed tiers in the Domain Research
   Summary (e.g., "Remote search: SKIPPED — GH_TOKEN
   unavailable", "Existing checkout repos/foo: FAILED —
   explore agent error") so the degraded state is auditable.

   **Context Sufficiency Gate (Mandatory Pre-Grilling Decision)**:
   After persisting the Domain Research Summary, the Planner MUST
   evaluate whether the available documentation is sufficient to
   produce an informed plan. This gate prevents planning on thin
   context — plans built on assumptions instead of verified
   codebase knowledge cascade into implementation failures, wasted
   resolution loops, and false `[UNVERIFIED]` markers.

   **Evaluation criteria** — for each in-scope service, check
   `docs/repo-guides/<repo>/<service>.md`:

   | Guide State | Coverage Assessment | Action |
   |-------------|-------------------|--------|
   | **Exists and substantive** — covers DI wiring, storage schemas, API endpoints, event contracts, key patterns with no major `[GAP:*]` clusters | Sufficient | Run staleness check (see below) |
   | **Exists but skeletal** — most sections are `[GAP:UNVERIFIED]`, `[GAP:INCORRECT]`, or `[INCOMPLETE:*]`; missing critical domains (storage, events, API) | Insufficient | Recommend research prerequisite |
   | **Missing entirely** — no guide exists for the target service | Insufficient | Recommend research prerequisite |
   | **Partial coverage** — guide covers some domains well but has significant gaps in areas directly relevant to the planned feature | Conditional | Recommend research if the feature touches gap areas; proceed if it doesn't. In headless mode, treat as Insufficient (fail-closed) |
   | **Stale** — guide exists and was substantive at time of writing, but upstream repo has significant changes since guide was last updated | Insufficient | Recommend research update (see below) |

   **Staleness detection** (applies when a guide exists and passes
   the coverage assessment above): Even a substantive guide can
   become unreliable if the upstream service has evolved
   significantly since the guide was last written. The Planner
   MUST check for staleness before declaring context sufficient.

   1. **Guide last-updated date**: Delegate to a `task` agent to
      run `task git:log -- -1 --format="%ci" -- docs/repo-guides/<repo>/<service>.md`
      for each in-scope guide. This returns the date of the last
      commit that modified the guide. If `git log` returns no
      output (file not yet in git history), treat the guide as
      newly created with today's date — skip staleness detection
      and proceed with the coverage assessment verdict alone.
   2. **Upstream change detection**: Compare the guide date against
      recent upstream activity. Use the `task gh:api` path as the
      canonical method for commit counting — it directly supports
      the numeric threshold:
      - `task gh:api -- repos/<Upstream_Repo>/commits?path=<service_path>&since=<guide_date_iso>&per_page=100`
      - If the API returns a full page (100 items), the count
        exceeds the threshold — no pagination required.
      - **Local checkout fallback** (if `repos/<repo>/` exists and
        the API is unavailable): delegate
        `task git:run -- -C repos/<repo> log --after="<guide_date>" --oneline -- <relative_service_path>/`
        scoped to the cloned repo's git context (note: `git -C`
        changes the working directory to the cloned repo, which
        has the upstream git history — do NOT run this against
        the `brownfield-ai` repo root).
      - **Degraded signal**: If both paths fail, record the
        failure in the Domain Research Summary and treat the
        staleness check as inconclusive — proceed with the
        coverage assessment verdict alone.
   3. **Staleness threshold**: If the guide is older than 7 days
      AND the upstream service path has accumulated **10+ commits**
      or **any commits touching high-impact paths** since the
      guide date, the guide is classified as **Stale**. Consult
      `.claude/rules/repos.<repo>.md` for repo-specific
      high-impact path patterns (e.g., `migrations/`, `providers/`,
      `routes/`, `cmd/`, event schema directories). The 7-day
      minimum prevents false positives from routine minor commits
      (typo fixes, comment updates) that don't affect guide
      accuracy.
   4. **Output**: Record the staleness assessment in the Domain
      Research Summary: guide date, upstream commit count since
      that date, and whether any high-impact paths were modified
      (migrations, route definitions, provider registrations,
      event schemas).

   **Generated artifact freshness** (applies when a guide
   directory contains generated files): Some repo guide
   directories include artifacts produced by generation scripts
   — for example, an inventory YAML under
   `docs/repo-guides/<repo>/` produced by that repo's own
   generator task. These generated artifacts
   carry `generated_at` timestamps and `generator` script paths
   in their metadata. When generated artifacts exist, the
   Planner MUST check whether they need regeneration.

   1. **Detect generated artifacts**: Delegate to a `task` agent
      to scan `docs/repo-guides/<repo>/` for files containing a
      `generated_at` field (YAML front matter or embedded
      metadata). Collect the `generated_at` timestamp and
      `generator` script path from each file.
   2. **Check source data freshness**: For each generator script,
      identify its source data inputs — typically visible from
      the script's preconditions in the corresponding Taskfile
      (e.g., `repos/analytics` migrations, `repos/dbt` models)
      or from the script's imports. Compare the `generated_at`
      timestamp against the last-modified date of the source data
      using `task git:log -- -1 --format="%ci" -- <source_path>/`.
      If the generator script's source data inputs cannot be
      determined by reading the Taskfile preconditions and the
      script, treat the artifact as requiring regeneration
      (fail-safe default — avoid silent false "fresh"
      assessments).
   3. **Regeneration threshold**: If source data has been modified
      after the `generated_at` timestamp, or if source inputs
      could not be determined (fail-safe), the artifacts are stale
      and should be regenerated.
   4. **Action**: Recommend regeneration as either:
      - A **standalone action** before planning proceeds — when
        the generator task is quick and self-contained, the
        Planner can delegate
        it to a `task` agent immediately without a full
        `repos-research` epic. Present to the user:
        > Generated artifacts in `docs/repo-guides/<path>/`
        > are stale (`generated_at: <date>`, source data
        > modified: `<date>`). Recommend re-running
        > `task <generator_task>` before planning proceeds.
      - Part of the **research prerequisite** — when the guide
        itself is also stale or insufficient, bundle the
        regeneration into the `repos-research` recommendation.
   5. **Output**: Record the generated artifact assessment in the
      Domain Research Summary: artifact paths, `generated_at`
      dates, source data last-modified dates, and whether
      regeneration was recommended or executed.

   **Recommendation format** (when context is insufficient or stale):

   > **Context Sufficiency Gate: INSUFFICIENT**
   >
   > The repo guide for `<service>` in `<repo>` is
   > [missing | skeletal — major gaps in: <list> | stale —
   > last updated <date>, <N> upstream commits since then
   > including changes to <high-impact paths>]. Planning
   > this feature without verified codebase context risks
   > incorrect assumptions about [specific concerns: DI wiring,
   > storage schemas, event contracts, etc.].
   >
   > **Recommended prerequisite**: Run a deep repos research
   > epic via the `repos-research` prompt
   > (`workflows/repository-maintenance/prompts/repos-research.prompt.md`)
   > to [produce comprehensive guides | update existing guides]
   > before planning this feature.
   >
   > **Override**: Say "proceed without research" to skip this
   > gate and plan with available context. Open questions will
   > be surfaced during grilling.

   **Decision**:

   - If the user approves the research prerequisite, the Planner
     halts feature planning and initiates the `repos-research`
     prompt workflow with the appropriate arguments. For stale
     guides, the `repos-research` prompt's Prior Art Discovery
     step will automatically scope research to gaps and changed
     areas rather than re-researching from scratch. The feature
     plan resumes in a subsequent session after guides are
     produced or updated.
   - If the user overrides ("proceed without research"), the
     Planner proceeds to grilling with the context deficit
     recorded in the Domain Research Summary. All assumptions
     derived from thin or stale context MUST be flagged as
     grilling questions so the user can validate them explicitly.
     For stale guides, the Planner MUST note which specific
     upstream changes may have invalidated guide sections, so
     grilling questions target those areas.
   - If context is sufficient and fresh for all in-scope
     services, the Planner proceeds to grilling without
     presenting this gate to the user (no unnecessary friction).

   **Headless mode** (`CI=true`): If context is insufficient,
   stale, or conditional (see Partial coverage row), fail-closed
   — checkpoint a `step_result` artifact and halt. Headless
   sessions cannot make the judgment call to proceed on thin
   or stale context — that requires user override.

   For missing/skeletal guides:
   `{"step": "context-sufficiency-gate", "verdict": "fail",
   "reason": "insufficient guide coverage for <service>",
   "recommended_action": "repos-research"}`

   For stale guides:
   `{"step": "context-sufficiency-gate", "verdict": "fail",
   "reason": "stale guide for <service> — last updated <date>, <N> upstream commits since",
   "recommended_action": "repos-research"}`

2. **Requirements Elicitation (Grilling Phase)**: Before drafting
   any plan, the Planner MUST interview the user about every
   aspect of the feature request to surface hidden requirements,
   edge cases, and architectural constraints. Walk down each
   branch of the decision tree one-by-one, resolving dependencies
   between decisions sequentially.

   **Rules**:
   - For each question, provide a recommended answer based on
     the Domain Context Brief (from the Domain Research
     sub-phase of step 1), codebase exploration,
     and prior context (Execution Ledger, ChromaDB,
     `docs/learnings.md`). If the Brief and a targeted `explore`
     agent invocation cannot resolve the question, surface it to
     the user.
   - If a question can be answered by exploring the codebase,
     delegate to an `explore` agent instead of asking the user.
   - Continue until ALL decision branches are resolved.
   - Summarize resolved decisions as a numbered requirements list
     (`[Req-001]`, `[Req-002]`, ...) and ask the user to confirm
     completeness. This list becomes the **canonical Req-ID
     seed** for the Draft step — the Draft MUST carry these IDs
     forward and append new IDs from the highest existing number.
     It MUST NOT renumber or restart the sequence.
   - The Planner MUST NOT proceed to the Draft step until the
     user explicitly confirms the requirements list is complete.
   - **Decomposition-mode questions** (ask for every feature request):
     - "Does this feature have hard architectural prerequisites (infra,
       schema migrations, shared contracts) that ALL subsequent work
       depends on?"
     - "Can the feature be decomposed into independently mergeable
       capability slices, each delivering end-to-end user-facing value?"
     - "What is the natural merge cadence — one PR per capability, or a
       single PR for all changes?"
   - **Negative constraints (lower bound)**: The Planner MUST
     explicitly ask: "What approaches are off-limits?" and
     document them as `[Req-NXX]` entries prefixed with "MUST
     NOT". Examples: agents must not delete code to resolve
     lint/test failures (must provide replacements), must not
     weaken existing validation to unblock a feature, must not
     broaden type signatures (e.g., `Any`) to silence type
     errors. These negative Req-IDs are binding on implementer
     subagents and reviewers must flag violations.
   - **Scope boundary (upper bound)**: The Planner MUST
     explicitly ask: "What is out of scope?" and document
     excluded areas as a `## Out of Scope` section in `plan.md`.
     Any implementer subagent that touches files or concerns
     listed in Out of Scope is in violation — the Orchestrator's
     scope boundary check (per
     [delegation_protocol.md](delegation_protocol.md) §3) uses
     this list as the reference.
   - **Convergence guard**: If the same decision branch has been
     revisited 3 times without resolution, summarize the
     outstanding ambiguity, flag unresolved items, and ask the
     user for a final decision. If the user defers or declines
     to confirm, save the partial list to `plan.md` with
     `Status: Grilling — pending user confirmation` and halt. A
     resumed session re-presents the partial list.
   - **Headless mode** (`CI=true` or explicit headless signal):
     The Planner MUST NOT skip this phase silently. Instead,
     delegate to an `explore` agent to perform automated
     requirements extraction from the ticket description, prompt
     context, and codebase. Produce a machine-generated Req-ID
     list and note it as `[auto-extracted]` in the plan output.
     If automated extraction yields zero requirements,
     fail-closed: checkpoint
     `{"verdict": "fail", "reason": "zero requirements extracted
     in headless mode"}` and halt.
3. **Draft**: Planner drafts the local execution plan (in `plan.md` or memory).
   - **Crucial Plan Structure**: When generating the steps in `plan.md`, the Planner MUST ALWAYS append the following verification sub-tasks to the end of *every single execution step/phase* in the checklist to prevent context drift:
     - `[ ] Sub-task: Parse [CLAUDE.md](../CLAUDE.md) to verify strict adherence to architectural standards/limits.`
     - `[ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.`
     - `[ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.`

     Per-step `task test:staged` verification remains universal in both decomposition modes (CLAUDE.md Principle 13 is unchanged). The conditionality introduced by vertical slicing is solely about whether a separate test domain wave exists in the plan structure — not about whether per-step verification runs.
   - **Final QA Phase (Mandatory)**: The Planner MUST append a final
     QA phase to every plan that produces code or documentation changes:
     (0) invoke `/protocols` to re-anchor the Orchestrator on core
     rules before entering the QA phase,
     (1) run `task lint:changed` and `task test:changed` for branch-level
     regression coverage,
     (2) execute the **Spec Verification Gate** per
     [verification_protocol.md](verification_protocol.md) — a Dual-Model
     review that cross-references every Req-ID in the Requirements
     Traceability Map against the implementation diff to verify
     completeness (all requirements satisfied, negative constraints
     not violated, residual risk mitigations in place),
     and (3) execute the Code Diff Review Gate per
     [verification_protocol.md](verification_protocol.md) — a Dual-Model
     review that validates implementation quality (security, standards,
     architecture).
     The Spec Verification Gate checks **completeness against the plan**.
     The Code Diff Review Gate checks **quality of the code**. Both
     must pass. They are separate concerns and must NOT be combined
     into a single review.
     If the user
     requests cross-family review (e.g., "include copilot-reviewer",
     "with copilot", "with gemini-reviewer", "add gemini", "with codex-reviewer",
     "add codex", "N-of-N"),
     the QA phase MUST note which bridge agents were requested so the
     Orchestrator activates the Cross-Family Review Extension during the
     Code Diff Review Gate. Example user prompt: *"For the QA phase,
     include copilot-reviewer and gemini-reviewer in the diff review"* —
     the Planner appends to the Final QA Phase checklist:
     `[ ] Execute Code Diff Review Gate with Cross-Family Review
     Extension (copilot-reviewer and gemini-reviewer requested by user).`
     This phase is mandatory even when the PR will be created via
     `auto-pr` or `ship` — plans must not rely on implicit skill behavior
     for QA coverage.
     After the Code Diff Review Gate completes, invoke `/protocols`
     again before proceeding to PR creation via the selected PR
     protocol.
   - **Structural Conformance Check**: If the implementation plan mutates/creates files in `.claude/skills/` or `workflows/`, the Planner MUST append a final global phase: `[ ] Execute docs-review and claude-review skills to validate structural alignment.`
   - **Requirements Traceability Map (Mandatory)**: The Planner MUST
     format every distinct logical requirement, edge case, and
     architectural rule as a structured traceability table. This table
     is the canonical contract between planning and verification — the
     Spec Verification Gate (see
     [verification_protocol.md](verification_protocol.md)) uses it to
     verify implementation completeness.

     **Requirement table format** (one table per domain/component):

     | Req-ID | Requirement | Impl Step | Test Coverage | Verification |
     |--------|-------------|-----------|---------------|--------------|
     | Req-001 | Description of requirement | Plan step reference | Test file:TestClass | How to verify |

     - Each requirement gets a unique `[Req-001]` prefix.
     - `Impl Step` references the plan step that implements the
       requirement.
     - `Test Coverage` names the test file and class/method that
       exercises the requirement. Requirements without test coverage are
       flagged by the Spec Verification Gate as UNVERIFIED.
     - `Verification` describes the concrete assertion or manual check.

     If a Requirements Elicitation phase preceded this step, the
     Planner MUST carry the grilling-produced Req-IDs forward as
     the canonical seed and append new IDs from the highest
     existing number. It MUST NOT renumber or restart the
     sequence.

     **Negative Constraints (Mandatory)**: The Planner MUST include a
     separate table for things the implementation MUST NOT do:

     | Req-ID | Constraint | Verification |
     |--------|-----------|--------------|
     | Req-N01 | Must NOT do X | How to verify absence |

     **Accepted Residual Risks (Mandatory)**: The Planner MUST document
     risks that are acknowledged but not mitigated, with their
     rationale:

     | Risk-ID | Risk | Mitigation |
     |---------|------|------------|
     | Risk-001 | Description | Why this is acceptable |

     These three tables form the **Requirements Traceability Map**. The
     Spec Verification Gate cross-references every entry against the
     implementation diff. Missing tables fail the Dual-Model Plan
     Review.

   - <a id="artifact-type-introduction-checklist"></a>**Artifact-Type Introduction Checklist**: When a plan adds entries
     to `VALID_ARTIFACT_TYPES` in
     `src/brownfield_ai/ledger/artifacts/constants.py`, the plan MUST
     enumerate the four integration touch points below as verb-led
     actionable directives (conventionally in a **Files in Scope**
     section listing source touches). These are non-obvious
     lifecycle dependencies that the
     [Ledger Checkpoint Appendix](verification_protocol.md#ledger-checkpoint-appendix)
     in `verification_protocol.md` documents on the artifact-body side;
     this checklist captures the source-code touch points that flow
     from each new artifact type.

     - Add to `SANITIZED_ARTIFACT_TYPES` (or document the explicit non-membership decision) in `src/brownfield_ai/ledger/artifacts/constants.py` — defines whether the artifact body is sanitized by `src/brownfield_ai/ledger/artifacts/sanitize.py` before persistence.
     - Touch `get_resume_context()` in `src/brownfield_ai/ledger/epics/queries.py` to add the new artifact type to the appropriate category bucket — controls whether `task ledger:resume` surfaces the artifact when bootstrapping context for an active epic.
     - Add test mirror at both `tests/src/brownfield_ai/ledger/artifacts/test_sanitize.py` (sanitize membership) and `tests/src/brownfield_ai/ledger/epics/test_queries.py` (resume-category coverage) — both touch points must have direct test coverage in the plan's test wave.
     - Update dashboard mirrors at `services/dashboard/frontend/src/types.ts` (`ArtifactType` discriminated union), `services/dashboard/frontend/src/utils/tooltips.ts` (`ARTIFACT_TYPE_TIPS` record — TypeScript's `Record<ArtifactType, …>` typing surfaces missing entries at compile time), and `services/dashboard/frontend/src/components/TimelineFilter.tsx` (`ARTIFACT_TYPES` array for the pill toggle) — the union and pill array are not statically derived and require manual mirror updates.
4. **Plan Checkpoint**: After completing the draft, the Planner MUST present the following options to the user:
   - **Option 1 — Review**: "Proceed to Dual-Model Review Gate now." This is the default and recommended path.
   - **Option 2 — Save as draft**: "Save this plan to `plan.md` as a work-in-progress draft for future refinement." The Planner writes the plan to `plan.md` with `Status: Draft — pending Dual-Model Review` as the first line of the file. Draft plans MUST NOT be checkpointed to the Execution Ledger — only reviewed and approved plans are eligible for ledger `plan_snapshot` artifacts. Drafts in `plan.md` are durable until review is complete; the session can end here and a future session resumes by reading `plan.md`. In a resumed session, the Planner presents the same three options again with the current draft pre-loaded.
   - **Option 3 — Implement**: "Skip review and proceed directly to implementation." The Planner MUST only proceed with this option if the user explicitly requests it (e.g., "skip the review", "no review needed"). This exception is for trivial or time-sensitive changes where review overhead is not justified.

   **Headless mode** (`CI=true`): Auto-select Option 1 (Review) —
   the default and recommended path. Checkpoint a `step_result`
   artifact with `{"step": "plan-checkpoint", "verdict":
   "auto-headless", "selected": "review"}`. Draft plans are not
   supported in headless mode — the plan proceeds directly to
   Dual-Model Review.

   **Promotion to `docs/plans/` (human review)**: `plan.md` is *working
   scratch* — untracked, no history, overwritten by the next epic. When a
   plan needs review by human teammates rather than by review-gate agents,
   promote it to a tracked folder at
   **`docs/plans/<EPIC-ID>/`** so it arrives as a reviewable PR. The three
   layers are distinct and none substitutes for another:

   | Layer | Artifact | Tracked | Audience |
   |---|---|---|---|
   | Working scratch | `plan.md` | no | the active session |
   | Machine record | ledger epic + `plan_snapshot` / `step_result` | ChromaDB | agents resuming work |
   | Human review | `docs/plans/<EPIC-ID>/` | yes | teammates reviewing a plan |

   Folder contents follow a conventional shape:

   | File | Role |
   |---|---|
   | `README.md` | Index. Opens with an HTML-comment lifecycle block carrying `Status`, `Owners`, `Epic`, and `Purpose`, then a document index table |
   | `<topic>_plan.md` | The primary implementation plan |
   | `slice<N>-spec.md` | Per-vertical-slice specs, one per slice |
   | `validation_plan.md` / `validation_results.md` | How correctness was to be established, and what it showed |
   | `pr_summary.md` | The PR-facing narrative |

   Only `README.md` and the primary plan are required; add the rest as the
   epic produces them. Directory names are epic identifiers and need not be
   ticket keys — a descriptive slug is fine for work with no ticket.

   Two properties make the folder worth keeping after the epic ships:

   - It is a **reusable template** for the next epic of the same shape.
   - When an epic produces a *generalized* convention, that convention is
     promoted out into `.claude/rules/` or `docs/repo-guides/`, and the
     folder remains the **derivation record** showing how it was reached.
     Do not leave the only copy of a general rule inside an epic folder.

   See [docs/plans/README.md](plans/README.md).
5. **Dual-Model Review** (mandatory): The Planner must invoke the
   **Dual-Model Review Gate** defined in
   [verification_protocol.md](verification_protocol.md). Spawn two
   independent `code-review-high` agents — one at the highest tier, one
   at the second-highest tier (cross-family when available). Both receive
   the plan contents and the prompt: "Review this implementation plan for
   gaps, security issues, and architectural flaws. Ensure all verification
   and review gates are clearly defined. Verify the Execution Strategy
   section satisfies §3 requirements: complexity classification per phase,
   parallelism assessment, and cost analysis comparing `agent-team` vs
   direct subagents with explicit rationale for the chosen strategy. Be
   critical." **Do not ask the user to manually invoke the reviewers.**

   When the user explicitly requests cross-family review (e.g., "with
   copilot-reviewer", "with gemini-reviewer", "with codex-reviewer", "cross-family review",
   "N-of-N"), the plan review gate benefits from the Cross-Family Review
   Extension: spawn additional reviewers beyond the standard two (Opus +
   Sonnet + each requested bridge agent). Each requested bridge agent
   (copilot-reviewer, gemini-reviewer, codex-reviewer) is run using its respective agent
   type, not `code-review`. Each bridge agent's pre-flight is invoked
   independently. The N-of-N gate behavior, resolution loop, and
   convergence guard rules from the extension apply. If a bridge agent
   returns an UNAVAILABLE or ERROR signal, proceed without that reviewer
   — other active reviewers continue normally. By default (no explicit
   request), the standard 2-of-2 gate runs without invoking any bridge
   agent pre-flights.

   **Rework plan fast-path** (Req-004): When a backlog epic with
   `pr_changes_required` artifacts needs re-planning, the Planner MAY
   use `backlog -> approved` fast-path if the rework only addresses the
   changes requested in the PR review + existing TODOs. The fast-path
   requires `pr_changes_required` artifacts to exist (enforced by the
   ledger). The Planner invokes `task ledger:status -- <epic_id>
   --new-status approved --fast-path`.

   **Rework review escalation** (Req-013): Rework Dual-Model Review
   gates MUST use `code-review-max` variant for both reviewers. The
   Planner specifies this in the plan's Execution Strategy.

   **Cross-family inheritance** (Req-016): Rework plans inherit
   cross-family activation from the original plan. The Planner checks
   `gate_verdict` artifacts with `reviewer_platform` metadata to detect
   which bridge agents successfully reviewed the original plan.

6. **Resolution**: The Planner reads all reviews and resolves findings:
   1. Read all reviews and resolve ALL findings — critical, significant, AND minor.
   2. For BLOCKED verdicts, address the blockers with plan edits and re-submit to a fresh Dual-Model Review. The full review cycle restarts — all reviewers must pass, not just the previously blocking one — because amendments may introduce new issues visible only to another reviewer.
   3. For APPROVED WITH NOTES verdicts, the Planner MUST apply the [Finding Resolution Review](verification_protocol.md#finding-resolution-review) process. Findings the Planner believes require plan edits are incorporated into the proposed wording. Findings the Planner believes require no action are submitted to the resolution review for independent validation — the Planner MUST NOT self-dismiss them.
   4. Every finding resolved via plan edit must have a corresponding change in the Proposed Wording section of `plan.md` before the gate can pass.
   5. The Planner MUST NOT mark findings as "addressable during implementation" without updating the proposed wording to reflect the resolution — implementer subagents only see the plan, so unresolved findings will be silently dropped.
   6. **Convergence guard**: In interactive sessions there is no round
      limit — the cycle continues until clean APPROVED or user
      intervention. In headless sessions, halt after 16 rounds and
      checkpoint for the next session per
      [verification_protocol.md](verification_protocol.md).
7. **Presentation**: Present the consolidated findings from ALL reviewers alongside the updated plan. Ask for user approval before moving to implementation.

   **Headless mode** (`CI=true`): If all Dual-Model Review verdicts
   are clean APPROVED (zero findings of any severity), auto-approve
   the plan and proceed to Step 8. If any reviewer returned APPROVED
   WITH NOTES, the Planner MUST run the
   [Finding Resolution Review](verification_protocol.md#finding-resolution-review)
   process to validate all no-action rationales — this substitutes
   for user judgment on dismissed findings. If the resolution review
   rejects any finding, edit the plan and re-submit to a fresh
   Dual-Model Review (full cycle restart). Only when all findings
   are resolved (code-changes applied + no-actions validated by
   resolution review) may the plan auto-approve. Checkpoint a
   `step_result` artifact with `{"step": "plan-approval", "verdict":
   "auto-headless"}`. Proceed to Step 8.

8. **PR Protocol Selection**: After the user approves the plan, the
   Planner MUST present a PR protocol recommendation and wait for
   explicit user confirmation before proceeding to implementation.

   **Recommendation logic** (based on the §3 Execution Strategy
   complexity classification):

   - **`auto-pr`**: Recommended when the plan produces changes for a
     single cohesive PR — all phases are simple/medium complexity,
     single domain, few files, no merge-order dependencies between
     groups.
   - **`ship`**: Recommended when the plan spans multiple domains,
     has dependency-ordered phases, or produces changes that benefit
     from separate, independently reviewable PRs.
   - **Manual**: Recommended when changes are exploratory, touch
     sensitive infrastructure, or the user prefers full manual
     control over PR creation.

   **Presentation format**:

   > **PR Protocol Selection**
   >
   > Based on this plan's complexity, I recommend **`<option>`**.
   >
   > 1. `auto-pr` — single PR for all changes
   > 2. `ship` — multiple sequential PRs grouped by domain
   > 3. `Manual` — you handle PR creation yourself
   >
   > Which option would you like to use? You can also specify
   > automation signals:
   > - `auto push` — skip pre-push review, persistent CI fix cycles
   > - `auto merge` — auto-merge after CI GREEN
   > - `auto push+merge` — both (fully autonomous until merge)

   The Planner MUST NOT begin implementation until the user selects
   an option. The selected PR protocol and any automation signals are
   recorded in `plan.md` under `## Execution Strategy`. The
   Orchestrator uses this at the end of execution to invoke the
   appropriate skill (or skip PR creation for Manual).

   **Headless mode** (`CI=true`): The Planner uses its own
   recommendation automatically. Checkpoint a `step_result` artifact
   with the step name, verdict `auto-headless`, and the selected
   option as a concrete string (e.g., `"selected": "auto-pr"` or
   `"selected": "ship"`). If the recommendation cannot be determined
   (ambiguous complexity with no dominant signal), fail-closed:
   checkpoint `{"verdict": "fail", "reason":
   "PR protocol selection unresolvable in headless mode"}` and halt.

9. **Commit Protocol Selection**: After PR protocol selection, the
   Planner MUST present a commit protocol recommendation. This
   determines whether the Orchestrator commits autonomously after
   verification gates pass or pauses for user confirmation at each
   commit boundary.

   **Options**:

   - **`auto-commit`** (recommended default): After step verification
     gates (`task lint:staged` + `task test:staged`) pass and the
     ledger checkpoint succeeds, the Orchestrator commits staged
     changes without user confirmation. The verification gate IS the
     approval gate — a separate commit prompt is redundant friction.
   - **`manual-commit`**: The Orchestrator pauses after each
     verification gate and presents the staged diff summary for user
     review before committing. Use when the user wants to inspect
     each commit individually (e.g., security-sensitive changes,
     exploratory work).

   **Presentation format**:

   > **Commit Protocol Selection**
   >
   > I recommend **`auto-commit`** — the Orchestrator commits after
   > each wave's verification gates pass (lint + test + ledger
   > checkpoint). This is required for headless execution.
   >
   > 1. `auto-commit` — commit after verification gates pass
   > 2. `manual-commit` — pause for your review before each commit
   >
   > Which option would you like to use?

   The selected commit protocol is recorded in `plan.md` under
   `## Execution Strategy`. The Orchestrator enforces it at every
   commit boundary during implementation.

   **Headless mode** (`CI=true`): Auto-select `auto-commit`. Plans
   that require `manual-commit` cannot execute headlessly — the
   Planner MUST note this constraint if the user selects
   `manual-commit`. Checkpoint a `step_result` artifact with
   `{"step": "commit-protocol", "verdict": "auto-headless",
   "selected": "auto-commit"}`.

## 3. Execution Strategy Selection (Mandatory)

Before delegating implementation, the Planner MUST evaluate which execution
model to use and document the decision in `plan.md`. Skipping this step
wastes tokens (running simple edits on expensive models) or misses
parallelism opportunities.

### Decision Process

1. **Decompose and classify complexity**: For each Slice or Domain in
   the plan, assign a complexity tier.

   **Decomposition mode** (select before classifying complexity):

   - **Vertical (default)**: Decompose by end-to-end capability. Each Slice
     includes implementation + tests + docs for one user-facing behavior.
     Each wave = an independently mergeable unit.
   - **Horizontal (exception)**: Decompose by architectural layer. Use when
     hard prerequisites exist that ALL subsequent slices depend on (infra,
     schema migrations, shared contracts). Tests are in a final wave.
   - **Hybrid**: Horizontal prerequisite wave(s) followed by vertical slices.
     Example: Wave 0 = schema migration (horizontal prerequisite), Wave 1-N =
     vertical slices that build on the schema.

   | Signal | Decomposition |
   |--------|---------------|
   | Any layer is a hard prerequisite for all subsequent work | Hybrid (horizontal Wave 0 + vertical slices) |
   | Feature has no cross-cutting prerequisites | Vertical |
   | All work is in a single architectural component | Horizontal (nothing to slice across) |
   | Feature spans multiple components with independent behaviors | Vertical |

   **Complexity tiers** (assign one per Slice or Domain):
   - **Simple**: Config changes, version bumps, dependency edits, doc
     updates, file deletions — predictable edits with no design judgment.
   - **Medium**: Dockerfile rewrites, task migration, unit test authoring,
     YAML restructuring — requires context but follows clear patterns.
   - **Complex**: Multi-file refactors, cross-service contracts, novel
     infrastructure, subtle bug diagnosis — requires deep reasoning.

### Cross-Family Review Activation

Cross-family review activation is **tiered by plan complexity**:

| Complexity | Activation | Rationale |
|-----------|------------|-----------|
| Simple | 2-of-2 only (Opus + Sonnet) | Overhead not justified |
| Medium | 2-of-2 default; user can upgrade | Standard coverage sufficient |
| Complex | **Auto-activate** if bridge agents available | Security-critical and architectural work benefits from model diversity; same-family blind spots are the primary threat |

When the Planner classifies any domain as Complex, it MUST:

1. Run pre-flight for all configured bridge agents (copilot-reviewer,
   gemini-reviewer, codex-reviewer).
2. If any bridge agent is available, auto-activate cross-family review
   and note in the plan: "Cross-family review auto-activated
   (complexity: Complex). Active bridge agents: <list>."
3. Inform the user: "This plan includes cross-family review
   (auto-activated for Complex plans). Say 'skip cross-family' to
   opt out."

**User override** (always honored, either direction):

- "Add copilot-reviewer" / "with gemini" / "add codex" → activates regardless of
  complexity.
- "Skip cross-family" / "no cross-family" → deactivates regardless
  of complexity.
- User override is recorded in `plan.md` under `## Execution Strategy`.

Auto-activation applies to ALL gates in the plan's lifecycle: plan
review, per-wave quality review resolution loops, Spec Verification
Gate, and Code Diff Review Gate. The activation decision is made once
at plan approval and inherited by all downstream gates (per the
existing cross-family inheritance rules in verification_protocol.md).

1. **Assign effort per phase**: Map each phase's complexity tier to an
   effort level. Simple → `low`, Medium → `medium`, Complex → `high`,
   Very Complex → `xhigh`. The Planner MAY override this default mapping
   with justification (e.g., a Simple phase that requires careful
   formatting might warrant `medium`). `max` is never assigned as a
   session-level effort by the Planner — it is reserved for the user's
   discretion via `/effort max`, or as the final escalation step when
   `-xhigh` has demonstrably failed (see [docs/effort_tiers.md](effort_tiers.md)
   §Frontier-Reservation Rule). For multi-domain epics that the Planner
   judges to require frontier reasoning at *plan-design time* (not as
   escalation), `planner-max` is the encoded variant; ordinary complex
   multi-domain epics should use `planner-xhigh`.

   **Effort enforcement**: Tier 1 agents (planner, orchestrator, task,
   qa-lint, deep-researcher) have `effort:` hardcoded in frontmatter and
   override the session level automatically. For variable-profile agents,
   the Orchestrator selects the appropriate variant by `subagent_type`
   name: use the base agent (e.g., `code-review`) for routine work, the
   high-effort variant (e.g., `code-review-high`) for complex phases, and
   the very-high-effort variant (e.g., `code-review-xhigh`) for very
   complex phases requiring deeper reasoning. For epics the Planner has
   pre-classified as frontier (rare), use `*-max` variants directly. The
   Agent tool has no `effort` parameter, so variant selection is the only
   mechanism for per-spawn effort control.

   **Domain-level consistency**: Within a domain, effort variant selection
   follows the domain's complexity classification. If the domain is
   Complex, use ALL high variants for the entire R-G-R loop
   (`tdd-red-high` → `tdd-green-high` → `tdd-refactor-high`); if Very
   Complex, use the corresponding `-xhigh` variants. Do not mix base,
   high, and xhigh variants within the same domain — complexity is a
   property of the feature, not the individual TDD phase. `*-max` variants
   are escalation-only by default — they are not used for initial domain
   assignment unless the Planner has explicitly classified the domain as
   frontier-grade per `docs/effort_tiers.md` §Frontier-Reservation Rule.
   Escalation on failure is per-agent and follows the 1-per-matrix-point
   rule: if an agent fails, the orchestrator re-dispatches at the next
   (model tier, effort variant) matrix point. Other agents in the R-G-R
   loop stay at their assigned level unless they also fail.

2. **Assess parallelism**: Identify phases or domains with no shared-file
   conflicts and no producer-consumer dependencies. These can execute
   concurrently.

3. **Select strategy**: The right choice depends on both the task profile
   AND the platform's capabilities. Not all platforms support per-subagent
   model selection or parallel spawning (see the `agent-team` skill's
   Platform Capability Detection table for details).

   **When to use `agent-team`:**

   | Signal | Benefit (full platform) | Benefit (limited platform) |
   |--------|------------------------|---------------------------|
   | Mixed complexity across phases | Tiered model selection saves cost | Complexity classification guides prioritization |
   | Independent domains | Parallel wave execution | Sequential waves still enforce clean gating |
   | Iterative QA with failure recovery | Built-in escalation protocol | Escalation protocol still applies (same model) |

   **When to use direct subagents instead:**

   - All phases are similar complexity, strictly sequential, no escalation
     needed — simpler orchestration overhead.
   - Single small task, 1-2 files — team formation overhead not justified.

   **Platform-aware default**: On platforms with per-subagent model
   selection (e.g., Claude Code), prefer `agent-team` for mixed workloads
   — it is strictly cheaper when simple phases run on fast-tier models. On
   platforms where subagents inherit the orchestrator's model (e.g.,
   Copilot, Gemini CLI), `agent-team` is still preferred for its
   escalation protocol and regression gates, but the cost benefit of
   tiered selection does not apply. Choose direct subagents only when the
   orchestration overhead exceeds the task itself.

4. **Document in `plan.md`**: Add an `## Execution Strategy` section that
   states the chosen strategy, the platform context, the rationale, the
   merge strategy, and the complexity classification per Slice or Domain.
   On platforms with model selection, include the tier assignment. Example:

   ```markdown
   ## Execution Strategy

   **Strategy**: `agent-team`
   **Platform**: Claude Code (supports per-subagent model selection)
   **Rationale**: Mixed complexity (5 simple + 2 medium + 1 complex);
   built-in QA regression gate covers Phase 6.
   **Merge Strategy**: `wave-per-pr` or `all-waves-one-pr`

   | Slice/Domain | Complexity | Model Tier | Effort | Sub-plan |
   |--------------|-----------|------------|--------|----------|
   | 1            | Simple    | fast       | low    | A        |
   | 2            | Simple    | fast       | low    | A        |
   | ...          | ...       | ...        | ...    | ...      |
   ```

   Operational mechanics: `wave-per-pr` means the Orchestrator invokes
   `auto-pr` once per wave after that wave's post-wave verification gate
   passes. `all-waves-one-pr` means a single `auto-pr` invocation after
   all waves complete. Merge Strategy is an input to the PR Protocol
   Selection recommendation logic (§2 step 8), not a replacement for it.

   On platforms without model selection, omit the Model Tier column but
   keep the Effort column — the Complexity column still serves as
   prioritization guidance for the orchestrator.

   **Effort enforcement**: Tier 1 agents override the session level via
   frontmatter. Tier 2 agents use variant selection — the Orchestrator
   spawns the base agent (inherits session default) for routine phases,
   the `-high` variant for complex phases, the `-xhigh` variant for very
   complex phases requiring deeper reasoning, and reserves `-max` for
   frontier/escalation cases. The Effort column in the table guides
   which variant the Orchestrator should select. See
   [docs/effort_tiers.md](effort_tiers.md) for the canonical 4-level
   ladder.

   **Orchestrator default effort drops to medium**: with the merge
   function shouldering routing determinism (see Per-Gate Effort
   Tier Pinning below), the Orchestrator no longer needs a
   high-reasoning budget by default. The orchestrator agent
   declares `effort: medium` in its frontmatter and escalates to
   `high` only on circuit-breaker trip — see
   [verification_protocol.md §Envelope Circuit-Breaker](verification_protocol.md#envelope-circuit-breaker-req-016--req-017)
   for the trip semantics. This is a deliberate cost reduction
   enabled by Req-N02 (no LLM in the routing path).

### Per-Gate Effort Tier Pinning (Req-014 / Req-N06 / Risk-010 / S-8)

The Planner is the **authority** on `reviewer_effort_tier` and
`implementer_effort_tier` per gate. Tiers are declared in the
Execution Strategy table (`Slice/Domain | Complexity | Model Tier |
Effort | Sub-plan`) and propagated to every reviewer and implementer
subagent the Orchestrator spawns for that slice or domain. The
orchestrator MUST honor the pin and only override on an
`ESCALATE_REVIEWER_TIER` envelope.

**Default mapping from complexity → reviewer tier**:

| Complexity | Default `reviewer_effort_tier` | Notes |
|------------|-------------------------------|-------|
| Simple | `medium` | Routine review; the merge function default |
| Medium | `high` | Standard reviewer floor for non-trivial work |
| Complex | `xhigh` | Deep diff/plan review; matches the canonical `-xhigh` tier in [docs/effort_tiers.md](effort_tiers.md) |

The Planner MAY override the default with justification (e.g., a
Simple slice that touches a security boundary may warrant `xhigh`).
The override MUST be documented inline in the Execution Strategy
table or a footnote.

**Operator-auth gate floor (Risk-010)**: gates touching
`.claude/settings.json`, `Taskfile.yml` task allowlists,
`OPERATOR_AUTHORIZED_DESTRUCTIVE`-adjacent code, or
`.claude/hooks/` MUST be planner-pinned at
`reviewer_effort_tier=xhigh` minimum. Operator-auth boundaries are
too high-stakes for `medium` or `high` review depth — the pin
ensures the reviewer has sufficient depth to reason about the
boundary.

**Dual-Model Review Gate floor (S-4 R2)**: any gate routed through
the Dual-Model Review Gate has a hard floor of `high` — a planner
pin below `high` is rejected. See
[verification_protocol.md §Reviewer Model Selection (platform-aware)](verification_protocol.md#reviewer-model-selection-platform-aware).
Above the floor, the planner pin is authoritative — a planner pin
of `xhigh` for a Risk-010 operator-auth gate is honored verbatim.

**Round-1 escalation bypass (S-8)**: round 1 of any gate is
"discovery" — the planner cannot tier-classify implementation
slices it has not seen yet. A round-1 `ESCALATE_REVIEWER_TIER`
envelope from a reviewer therefore **bypasses the planner pin**:
the orchestrator accepts the reviewer's `recommended_next_tier`
directly via
[`scripts/orchestrator/planner_tier_pinning.py::resolve_next_round_tier`](../scripts/orchestrator/planner_tier_pinning.py)
(subject only to the Req-N06 floor). Rounds 2+ honor the planner
pin and only escalate via the Frontier-Reservation gate (encoded
as Rule 4 in
[`envelope_merge.py`](../scripts/orchestrator/envelope_merge.py)).

**Orchestrator override on ESCALATE only**: outside the round-1
bypass, the orchestrator MUST NOT override the planner pin
downward. Upgrades happen only via an `ESCALATE_REVIEWER_TIER`
envelope or via the circuit-breaker sticky tier escalation
(Req-016 / Req-017). Downgrades are forbidden by Req-N06 — the
resolver (`planner_tier_pinning.resolve_next_round_tier`) floors
every output against the planner pin.

**Risk-006 auto-promotion**: after two consecutive `ESCALATE` merge
decisions on the same gate within a single epic, the resolver
auto-promotes the resolved tier by one step (`medium → high →
xhigh`; `max` stays `max`). The Frontier-Reservation cap is
re-applied after promotion so `max` is honored only when the prior
round actually ran at `xhigh`.

## 4. Sub-plan Splitting

When estimated total session context exceeds the **250K token budget**
(25% of the 1M context window), the Planner MUST split the plan into
sub-plans. See [§6 Context Budget](#6-context-budget-research-backed)
for the research basis.

### When to Split

Split when estimated total session context exceeds the 250K token
budget. Sum per-wave costs from the budget table in §6. Account for
execution mode:

- **Teammate mode**: Orchestrator sees ~5-10K per domain (completion
  reports only) — sub-plans can contain more waves.
- **Subagent mode**: Orchestrator sees ~30-80K per domain (full R-G-R
  I/O) — sub-plans contain fewer waves.

### Split Boundaries

- Default: align with wave boundaries.
- Respect the wave dependency chain (no splitting mid-dependency).
- Interactive track: align with natural human-intervention points
  (deny-ruled file commits, complexity tier boundaries).
- Headless track: align with natural checkpoint boundaries (wave
  completion, verification gates).

### Wave Splitting (Planner Discretion)

The Planner MAY split a wave into two or more smaller waves to improve
sub-plan context budget utilization. This avoids two common sizing
problems: (a) a single large wave that exceeds the 250K budget, making
the sub-plan unsizeable, and (b) an imbalanced pair where splitting the
larger wave produces two sub-plans of roughly equal size instead of one
undersized and one oversized.

**Constraints for wave splitting:**

1. **Independence**: Domains in the original wave must have no
   cross-dependencies and no shared files (same rule as wave assignment
   in `agent-team` §2). If Domain A's output feeds Domain B within the
   same wave, the wave cannot be split between them.
2. **Ordering**: Split sub-waves inherit the original wave's position in
   the dependency chain. If Wave 3 is split into 3a and 3b, both remain
   after Wave 2 and before Wave 4. Sub-waves 3a and 3b may execute in
   parallel (same wave semantics) or sequentially (if placed in
   different sub-plans). When sub-waves are placed in different
   sub-plans, the sub-plan ordering must respect the wave dependency
   chain (see "Constraint" below).
3. **Labeling**: Split waves use alphabetic suffixes: `3a`, `3b`, `3c`.
   The `sub_plans` encoding reflects this (e.g.,
   `A:P,0,1,2,3a|B:3b,4,QA`).
4. **Verification gates**: Each sub-wave gets its own post-wave
   verification gate and per-wave code quality review, same as a full
   wave.

**When to split:**

| Scenario | Action |
|---|---|
| Single wave exceeds 250K budget | Split required — wave is otherwise unsizeable |
| Sub-plan A = 80K, Sub-plan B = 170K, and B's first wave has independent domains | Split B's first wave to rebalance (e.g., A = 120K, B = 130K) |
| All waves fit within budget without splitting | Do not split — unnecessary complexity |

### Constraint

Sub-plans must respect the wave dependency chain. A sub-plan's first
wave may depend on the prior sub-plan's final wave, but no circular
dependencies across sub-plan boundaries. **Independent waves may be
reordered and grouped across sub-plans purely for context budget
optimization** — e.g., in vertical slicing mode where slices have no
cross-dependencies, the Planner may encode `A:2,5|B:1,3` to balance
sub-plan sizes, even though the original wave numbering was sequential.
The only ordering constraint is that prerequisite waves (e.g., Wave 0
horizontal infra) must appear in an earlier sub-plan than any wave that
depends on them.

### Merge Strategy Interaction

- `all-waves-one-pr`: Works across sub-plans (same branch). PR created
  after final sub-plan completes.
- `wave-per-pr`: Each wave is independently shippable. `auto-pr` fires
  after each wave's post-wave verification gate. Headless track
  restriction: ralph MUST poll PR status via `ledger:check-reviews`
  before proceeding to the next sub-plan. If any PR has changes
  requested, ralph transitions the epic to `blocked`.

### Parseable Sub-plan Boundaries (Headless Requirement)

Sub-plan boundaries MUST be encoded as **wave ranges** in the
`plan_snapshot` artifact metadata. This enables ralph to determine
scope programmatically without LLM inference.

Since ChromaDB metadata only supports scalar values, use pipe-delimited
encoding consistent with the existing document ID delimiter convention:

```text
A:P,0,1|B:2,3|C:4,5,6,QA
```

Stored as a single metadata string:

```json
{"sub_plans": "A:P,0,1|B:2,3|C:4,5,6,QA"}
```

**Parsing**: Split on `|`, then split each segment on `:`. Left side is
the label, right side is the comma-separated wave list. **Wave IDs are
opaque strings** — they may be numeric (`0`, `1`) or alphanumeric
(`3a`, `3b`) due to wave splitting. Parsing helpers MUST NOT cast wave
IDs to integers.

### Repo-to-Branch Mapping (Multi-Repo Epics)

Epics often span multiple upstream repositories (cloned under
`repos/<repo>/`), each requiring its own feature branch and PR. The
`plan_snapshot` artifact MUST include a **repo-to-branch mapping**
alongside the `sub_plans` encoding.

Same pipe-delimited convention:

```text
brownfield-ai:feat/ACME-1234-protocol|service-b:feat/ACME-1234-sub-check|analytics:feat/ACME-1234-datalake
```

Stored as metadata:

```json
{"branches": "brownfield-ai:feat/ACME-1234-protocol|service-b:feat/ACME-1234-sub-check|analytics:feat/ACME-1234-datalake"}
```

**Parsing**: Split on `|`, then `:`. Left = repo key (matching
`repos/<key>/` directory path), right = branch name. `brownfield-ai` is a
reserved key for the workspace root (`.`). Repos not in the mapping
have no branch (not modified by this epic). **Empty input contract**:
`parse_branches("")` MUST return an empty dict `{}` — this occurs for
single-repo epics or legacy `plan_snapshot` artifacts created before
the `branches` field was added. When the dict is empty, ralph falls
back to operating on the `brownfield-ai` workspace root only with a branch
name derived from the epic ID.

## 5. Skill Routing Guide

The Planner decides the execution strategy (§3) but must also recommend
the appropriate orchestration skill when complexity warrants it. The
Planner MUST include a `**Recommended Skill**` line in the
`## Execution Strategy` section of `plan.md`.

| Signal | Recommended Skill | When to Use |
|--------|-------------------|-------------|
| Large feature spanning multiple domains/repos | `/feature-epic` | Decomposes into domains, waves, and delegates to `agent-team` |
| Multi-domain implementation with mixed complexity | `/agent-team` | Tiered model selection, wave gating, escalation protocol |
| Single feature or bug requiring TDD | `/tdd-execute` | Orchestrates the Red-Green-Refactor subagent loop |
| Bug diagnosis and targeted fix | `/bug-fix` | Cost-effective diagnosis with model selection and review gates |
| Simple single-domain edits (docs, config) | Direct subagents | No skill overhead; Planner/Orchestrator delegates directly |

When the task is simple enough for direct subagents, the Planner should
state `**Recommended Skill**: None (direct subagents)` in the execution
strategy to make the routing decision explicit.

> **Note**: Orchestrator-driven skills like `/diff-review` are not listed —
> they are invoked automatically by QA phases and PR skills per
> [verification_protocol.md](verification_protocol.md).

## 6. Context Budget (Research-Backed)

### Research Basis

| Study | Finding | Implication |
|---|---|---|
| **MRCR v2 8-needle** (Anthropic, 2026) | Opus 4.6: 93% at 256K → 76% at 1M. Multi-hop reasoning degrades non-linearly beyond ~25% utilization | 250K target for reliable cross-wave reasoning |
| **Veseli et al.** (COLM 2025) | U-shaped primacy/recency curve holds below 50% of context window. Above 50%, primacy bias collapses — model stops recalling initial prompt instructions | 400K hard ceiling (40% with safety margin). Beyond this, protocol adherence is unreliable |
| **Du et al.** (EMNLP 2025) | Context length alone degrades performance 13.9-85%, independent of retrieval quality. Even with perfect retrieval and optimal positioning, length hurts | Shorter sessions are the only reliable mitigation. `/protocols` re-read before critical decisions is a partial mitigation (transforms into short-context subtask) |
| **Claude Code internals** | Auto-compaction fires at ~83.5% (~835K for 1M window) | Absolute maximum before context destruction. Never approach this threshold |

**Limitation**: MRCR v2 measures multi-needle retrieval accuracy in
synthetic benchmarks, which is a proxy for — but not identical to — the
multi-hop plan reasoning an orchestrator performs. The actual degradation
curve for complex orchestration could differ. The 250K target is a
conservative engineering bound, not a precise inflection point. Empirical
calibration should refine this threshold over time.

### Operating Zones

| Zone | % of 1M | Tokens | Characteristics |
|------|---------|--------|-----------------|
| **Golden** | ≤25% | ≤250K | Multi-hop reasoning high-quality. Primacy bias holds. Protocols reliably followed. **TARGET.** |
| **Degradation** | 25-40% | 250-400K | Multi-hop declining. Primacy bias weakening. Usable with mitigations. **HARD CEILING at 400K.** |
| **Instruction amnesia** | 40-50% | 400-500K | Primacy bias collapsing per Veseli. Initial prompt instructions unreliably recalled. **DO NOT ENTER.** |
| **Compression** | >83.5% | >835K | Auto-compaction fires. Earlier context destroyed. **CATASTROPHIC.** |

### Budget Breakdown (per sub-plan session)

**Target: 250K total session context.**

| Component | Est. Tokens | Frequency | Notes |
|---|---|---|---|
| Initial prompt (template + resume + failure context) | 10-25K | Once | Grows with retry attempt |
| Protocol reads (`/protocols`) | 10K | 1-2× | Start of session + before Exit Review Gate |
| Plan read | 3-8K | 1-2× per wave | Re-read at step verification |
| **Subagent R-G-R I/O** (subagent mode) | 30-80K per domain | Per domain | **Dominant cost in subagent mode** |
| **Teammate completion report** (teammate mode) | 5-10K per domain | Per domain | Much cheaper — orchestrator stays lean |
| Step verification (lint/test I/O) | 5-10K | Per domain | Executor + reviewer output |
| Post-wave verification gate | 15-25K | Per wave | Executor + 2 reviewers |
| Per-wave code quality review | 10-15K | Per wave | Single code-review-high |
| Wave gating overhead | 3-5K | Per wave | Orchestrator bookkeeping |
| Exit Review Gate (**reserved**) | 30-45K | Once | Reserved budget — triggers stop-executing threshold |
| Safety margin | 15K | Once | Buffer for unexpected I/O |

**Fixed overhead (non-wave costs): 65-95K.** The Exit Review Gate budget
(30-45K) is reserved separately via the stop-executing threshold — it is
not "already spent" overhead but a reservation that prevents the
orchestrator from consuming those tokens on wave work.

**Available for waves: 250K − overhead − exit gate reserve.** Pessimistic:
250K − 95K − 45K = 110K. Optimistic: 250K − 65K − 30K = 155K. **Use
the pessimistic end (110-155K) for sub-plan sizing** to avoid
overcommitting.

### Mode-Aware Sub-plan Sizing

| Execution Mode | Waves per Sub-plan (Simple) | Waves per Sub-plan (Medium) | Waves per Sub-plan (Complex) |
|---|---|---|---|
| Teammate | 3-4 | 2-3 | 1-2 |
| Subagent | 2-3 | 1-2 | 1 |

Rule of thumb: if estimated total session context > 250K, split. If >
400K, the sub-plan is dangerously oversized regardless of mitigations.

## 7. Implementation Delegation

- **Coding**: Use `general-purpose` agents (which have tool access) or specialized agents (e.g., `tdd-green`) to apply code changes. The agent type and model tier (where supported) MUST align with the execution strategy selected in §3.
- **Orchestrator**: Monitors progress, unblocks sub-agents, and ensures the **Verification Protocol** is followed.

## 8. Execution Ledger Checkpoints

After the Dual-Model Review Gate returns all reviewers GREEN → the Planner
MUST checkpoint the approved plan to the execution ledger via the
`execution-ledger` skill, creating a `plan_snapshot` artifact.

After the Draft step finalizes the merged requirements list
(grilling-produced Req-IDs plus any Draft-appended IDs) →
checkpoint a single `requirement_map` artifact with the complete
Req-ID to description mapping. Do not checkpoint a preliminary
`requirement_map` after the grilling phase alone — the Draft step
is the sole finalization point.

For each non-obvious design choice, architectural decision, or requirement
trade-off → checkpoint a `design_decision` artifact with the rationale fully
documented in the artifact body.

When the plan is updated mid-execution (e.g., scope expansion, re-scoping
blocked domains) → checkpoint a new `plan_snapshot` with an incremented
`version` to create an audit trail of plan mutations and maintain context
during epic resumption.
