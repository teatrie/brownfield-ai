---
name: diff-review
description: >-
  Dual-Model code diff review gate that validates implementation quality
  (security, standards, architecture) against the base branch.
---

# Code Diff Review Gate

Validates implementation quality by running a **Dual-Model Review Gate** on the
code diff against a base branch. Use this skill to catch security vulnerabilities,
coding standard violations, accidental deletions, and architectural drift that
tests alone cannot detect.

**User hints:** $ARGUMENTS

## Parameters

- **Base branch**: The branch to diff against. Default: `origin/main`. Override
  via `$ARGUMENTS` (e.g., "diff-review against origin/develop").
- **File scope**: Optional file or directory filter. Default: full diff. Override
  via `$ARGUMENTS` (e.g., "diff-review scoped to src/").
- **Epic ID**: Optional JIRA ticket for Execution Ledger checkpointing. If
  provided, `gate_verdict` artifacts are checkpointed. If omitted (ad-hoc
  invocation), results are reported directly without ledger interaction.

## Headless Mode

This skill supports both interactive and headless execution. Headless mode is
active when `CI=true` is set or the calling pipeline explicitly signals
non-interactive execution.

In headless mode, if the BLOCKED resolution loop (Step 3) exhausts all retry
attempts without achieving APPROVED from all active reviewers, the skill MUST:

1. Checkpoint a `step_result` artifact to the Execution Ledger with
   `verdict: fail` and the full reviewer findings in the body.
2. Halt execution immediately. Do NOT proceed past the gate.
3. The next session (human or bot) resumes via `execution-ledger resume`.

In interactive mode, the skill presents unresolved findings to the user for
manual resolution after exhausting retry attempts.

## Critical Invariants

These rules apply unconditionally to every diff-review execution. They
are restated here for positional prominence — buried mid-section
directives are the primary cause of silent violations.

- **ALL findings MUST be resolved.** Every finding from every reviewer
  — including non-blocking notes, informational observations, and
  APPROVED WITH NOTES items — MUST be routed through the
  [Finding Resolution Review](../../../docs/verification_protocol.md#finding-resolution-review).
  The resolution determines the action: `code-change` (delegated to
  an implementer subagent), `doc-or-todo` (documentation or TODO
  capture, still requiring reviewer consensus), or `no-action`
  (validated by reviewers as requiring no change). The Orchestrator
  MUST NOT dismiss, defer, or triage findings as "follow-up" or
  "non-blocking" — never silent dismissal.
- **The Orchestrator MUST NOT self-declare APPROVED.** Only fresh
  reviewer agents can declare the gate passed.

## Execution Steps

### Step 0: Protocol Alignment

**Before taking any other action**, read and execute the instructions in
`../protocols/SKILL.md` to refresh your context and internalize the
core directives. **If the protocols file cannot be read, HALT and report the
error. Do not proceed.**

### Step 1: Generate Diff

1. Fetch the latest base branch: `task git:fetch -- origin main` (or the specified base).
2. **Pre-flight guard**: Inspect the diff file list (`task git:diff --
   --name-only origin/main...HEAD`). If any paths match `tmp/`, `*.env`,
   `*credentials*`, `*.pem`, or `*.key`, HALT and warn the user — these files
   must not be in the diff. Do not proceed until the diff is clean.
3. Generate the diff and write it to `tmp/qa-diff.txt`:
   `task git:diff -- origin/main...HEAD > tmp/qa-diff.txt` (or scoped with
   `-- <path>` if a file scope was provided). Bridge reviewer invocations
   (Step 2) consume this path via the `DIFF_FILE=tmp/qa-diff.txt` caller
   contract; Claude reviewers receive the same diff inline.
4. **Diff size guard**: If the diff exceeds ~3000 lines, split the diff by
   domain or by file and run multiple parallel review passes in Step 2. ALL
   splits must be reviewed — do not pass the gate on a partial or truncated diff.
   When splitting, every split must independently receive APPROVED from all active reviewers;
   one BLOCKED on any split fails the entire gate.

### Step 2: Delegate Dual-Model Review

Spawn two independent `code-review-high` Reviewers at the highest and second-highest
tiers (cross-family when available). For reviewer model selection, apply the
Reviewer Model Selection table in
[docs/verification_protocol.md](../../../docs/verification_protocol.md).

All reviewers receive the diff (or diff splits) and the following prompt.
Bridge agent invocations MUST pass the per-workspace wrapper contract
established in Phase A: `REVIEW_TYPE=diff DIFF_FILE=tmp/qa-diff.txt` plus
`ROUND=1` for the initial review (spawn bridge agents via
`task agent:review:{copilot,gemini,codex}` — or the `:local` variants —
with these KEY=value args after `--`).

> **CRITICAL SCOPE CONSTRAINT (read this first):**
> The `git diff` below is the SOLE artifact under review. It has been verified
> against the git index and is authoritative — do NOT read changed files solely
> to confirm the diff is accurate. You MAY read unchanged files for context (e.g.,
> checking a callee's signature or type contract that the diff interacts with),
> but do NOT audit pre-existing logic in unchanged files or issue findings
> against them. Findings must target lines added, removed, or modified in the
> diff. Findings that target unchanged files will be rejected as out of scope.
>
> "Review this code diff against the base branch for:
>
> 1. Security vulnerabilities (OWASP top 10, credential leaks, injection risks)
> 2. CLAUDE.md and coding standard violations
> 3. Accidental file deletions or unintended modifications
> 4. Architectural consistency with existing patterns
> 5. Missing or degraded documentation (docstrings, type hints)
> 6. Anti-Faking Duty: inspect for hardcoded stubs, skipped validation steps,
>    or faked configurations that tests would not catch
> 7. Linter suppression additions or modifications (`# noqa`, `# type: ignore`,
>    `// eslint-disable`, `# shellcheck disable`) — flag any new or changed
>    suppressions as they may mask real issues
> 8. Performance anti-patterns: N+1 queries, unnecessary loops over large
>    collections, excessive memory allocations, unindexed lookups, and
>    missing pagination on unbounded result sets
> 9. Readability and complexity: poor naming, high cognitive complexity,
>    unnecessary abstraction layers, and overly clever code that hinders
>    maintainability
> 10. Boy Scout Rule: did touched legacy functions get upgraded to modern
>     standards per `docs/coding_standards.md`? (e.g., added type hints,
>     PEP-257 docstrings, replaced raw boto3 with `get_client`)
> 11. Runtime infrastructure dependencies: flag code that dynamically
>     creates Docker containers, pulls images, or depends on Docker daemon
>     availability outside of CI/build tooling. Flag new runtime
>     dependencies in `requirements.txt` that lack justification or could
>     be avoided by using existing APIs in the environment.
>
> Approach this review with adversarial rigor — assume the code has
> defects until you have proven otherwise. Examine ALL edge cases,
> error paths, boundary conditions, and possible branches in the
> changed code. Trace data flow through every conditional and loop to
> verify correctness. Do not accept 'looks reasonable' as a conclusion
> — either prove each changed function is correct or identify the
> specific flaw. If you believe experiments or tests are required to
> validate requirements, conclusions, or assumptions, detail the exact
> experimentation to be run (commands, inputs, expected outputs) — do
> NOT run them yourself. The Orchestrator will delegate experimentation
> to a task agent using `tmp/` or worktrees. When requesting an
> experiment, use this format per finding:
>
>     **Experiment Request:**
>     - **Command:** `<exact command to run>`
>     - **Expected output:** <what confirms or refutes the finding>
>     - **Purpose:** <what this proves about the finding>
>
> DO NOT modify existing
> code in the repository. Flag any change that tests alone cannot
> catch. Raise every issue you deem relevant, even if you are unsure
> — do not self-censor. Tag each finding with a confidence score
> (1-10, where 10 is highest certainty)."

**Cross-reference**: The `tdd-refactor` agent
([tdd-refactor.md](../../agents/tdd-refactor.md), Code Quality Checklist)
applies the same evaluation dimensions during implementation refactoring.
If the reviewer prompt wording is updated, verify the tdd-refactor
checklist remains consistent.

#### Cross-Family Pre-flight (User-Requested)

> **Note**: This pre-flight is placed in Step 2 for locality with
> reviewer spawning, but it MUST complete before any reviewers are
> spawned. The gate mode (2-of-2 or N-of-N) is fixed before the
> review begins, per
> [verification_protocol.md](../../../docs/verification_protocol.md).

The Cross-Family Review Extension is opt-in — it runs only when the
user or calling agent explicitly requests it (e.g.,
"with copilot-reviewer", "with gemini-reviewer", "with codex-reviewer", "cross-family review",
"N-of-N"). By default, spawn two reviewers (Opus + Sonnet) without
running any bridge agent pre-flights.

When requested, invoke each requested bridge agent's pre-flight
independently:

- [`copilot-reviewer`](../../agents/copilot-reviewer.md): runs
  `task agent:preflight:copilot`
- [`gemini-reviewer`](../../agents/gemini-reviewer.md): runs
  `task agent:preflight:gemini`
- [`codex-reviewer`](../../agents/codex-reviewer.md): runs
  `task agent:preflight:codex`

For each bridge agent whose pre-flight returns available, add it to
the active reviewer pool. Spawn 2 Claude reviewers + M available
bridge agents = N total reviewers. If all bridge agents return
`UNAVAILABLE`, proceed with the standard 2-of-2 gate. If a bridge
agent returns an `ERROR` signal during the review, exclude its
verdict and continue with the remaining active reviewers.

When cross-family review is desired, the pre-flight is mandatory —
not skippable.

### Step 3: Consensus

**Protocol refocus (mandatory)**: Before processing findings from
any review round, the Orchestrator MUST invoke `/protocols` to
re-anchor on core rules. Context drift during resolution loops is
the primary cause of self-dismissal and delegation boundary
violations. This applies to the initial review (Step 2 results) and
every subsequent resolution round.

#### Deterministic Envelope Routing (W4 contract)

After collecting reviewer outputs, the Orchestrator MUST route each
output through [`envelope_parser.parse_or_fallback`](../../../scripts/orchestrator/envelope_parser.py)
to obtain `Envelope` objects, then call
[`envelope_merge.merge(envelopes, gate_effort_tier=plan_pinned, prior_round_gate_effort_tier=prior_actual)`](../../../scripts/orchestrator/envelope_merge.py)
to compute the gate result. The merge function is **pure Python** —
no LLM call, no prose interpretation. The Orchestrator MUST honor
`MergeDecision.action` directly:

- `APPROVE` → gate passes; if `cross_family_dissent` is non-null,
  checkpoint a `cross_family_dissent` artifact to the Execution
  Ledger **before** the `gate_verdict` artifact (B-1 R2 audit
  surfacing).
- `RETURN_TO_WORKER` → run the resolution loop below with
  `MergeDecision.feedback`.
- `ESCALATE` → next round's reviewer tier is
  `MergeDecision.recommended_next_tier` (resolved via
  [`planner_tier_pinning.resolve_next_round_tier`](../../../scripts/orchestrator/planner_tier_pinning.py)).
- `HALT` → checkpoint `gate_verdict: fail` with
  `MergeDecision.halt_trigger` and surface to operator.
- `RETRY_REVIEWER` → re-spawn the abstaining reviewer(s) per
  `MergeDecision.retry_agent_ids`.

The legacy APPROVED / APPROVED_WITH_NOTES / BLOCKED vocabulary below
maps to the envelope `next_action` enum (APPROVE / APPROVE +
RETURN_TO_WORKER_ADVISORY / RETURN_TO_WORKER respectively); the
merge function is the deterministic routing primitive and the
authoritative gate result, while the prose findings remain for human
audit and the implementer-subagent's resolution context. See
[docs/verification_protocol.md §Envelope Merge Decision](../../../docs/verification_protocol.md)
for the full contract.

#### Findings Ledger

The Orchestrator MUST maintain a findings ledger to track each review
finding through the resolution loop. The ledger is persisted to
`tmp/<epic_id>-findings-ledger.json` (following the `tmp/` artifact
rule) to survive session interruptions.

**After each review round**, for every finding reported by any reviewer:

1. **Batch the create calls.** Each `task findings:*` invocation spins
   up the `python-cli` container (~1–2s). For round-N's findings (often
   5–30 across all reviewers), build a single JSONL batch and apply it
   in one container start. Write the batch via the Write tool to
   `tmp/<epic_id>-findings-create-r<N>.jsonl`, then run:

   ```bash
   task findings:apply-batch -- --batch-path tmp/<epic_id>-findings-create-r<N>.jsonl
   ```

   Each line is a create op (one per finding). Schema:

   ```json
   {"op": "create", "id": "<finding-id>-create",
    "args": {"finding_id": "<id>", "reviewer": "<r>", "severity": "<s>",
             "description": "<d>", "round_num": <n>, "confidence": <c>},
    "in_path": "tmp/<epic_id>-findings-ledger.json",
    "out_path": "tmp/<epic_id>-findings-ledger.json"}
   ```

   Omit `confidence` when the reviewer did not provide a score (defaults
   to 0). The batch is **atomic** — the first failing op aborts and
   returns partial results plus the error in the response JSON, but no
   ledger mutation persists to disk unless every op in the batch
   succeeds. Inspect `errors[]`, correct the offending line, and
   re-run the same batch unchanged: there is no risk of duplicate
   create-op writes from earlier successful lines (the prior partial
   write was rolled back). The per-finding `task findings:create` form
   is still available for interactive single-finding additions.
2. When an implementer subagent resolves a finding, update its status via
   `task findings:update-status -- --in-path <ledger> --out-path <ledger>
   --finding-id <id> --new-status resolved`. (Sequential by nature —
   one update per implementer return — so no batch advantage.)
3. On session resumption, load the existing ledger via
   `task findings:load -- --in-path <ledger>` to continue tracking from
   the last round. (There is no separate save step: every mutating
   wrapper above writes the updated ledger back via `--out-path`.)
4. After all reviewers in a round report findings, apply the
   **Duplicate Finding Consolidation** step from
   [docs/verification_protocol.md](../../../docs/verification_protocol.md):
   identify semantically duplicate findings across reviewers and merge
   them. For multiple groups, batch the merges into one apply-batch
   call (`tmp/<epic_id>-findings-merge-r<N>.jsonl`):

   ```json
   {"op": "merge-duplicates", "id": "group-1",
    "args": {"duplicate_ids": ["ID1", "ID2", "ID3"]},
    "in_path": "tmp/<epic_id>-findings-ledger.json",
    "out_path": "tmp/<epic_id>-findings-ledger.json"}
   ```

   For a single group, `task findings:merge-duplicates -- --in-path
   <ledger> --out-path <ledger> --duplicate-ids ID1 --duplicate-ids ID2
   [--duplicate-ids ID3 ...]` remains the simpler form. Only canonical
   entries proceed to resolution.
5. When iterating findings for resolution delegation post-consolidation,
   the Orchestrator MUST use `filter_active()` (not `filter_unresolved()`)
   to exclude merged entries that should not be resolved independently.
   `filter_active()` uses an open-world exclusion — it drops only
   explicitly terminal statuses (`"resolved"`, `"merged"`) — whereas
   `filter_unresolved()` uses a closed equality check
   (`status == "unresolved"`) that would silently exclude any future
   non-terminal status. Prefer `filter_active()` for forward-compatibility
   (see `filter_active()` docstring in `scripts/findings_tracker.py` for
   the authoritative specification).

> **CLI_ARGS quoting advisory** (TODO-0092t): every `task findings:* --`
> call above flows its `KEY=value` tokens through the Taskfile's
> `{{.CLI_ARGS}}` template variable. The variable is expanded by
> Task before any shell quoting is applied, so values that contain
> whitespace or shell-meta characters (`$`, backtick, single/double
> quotes, `|`) MAY be re-interpreted by the outer shell when Task
> composes the recipe command. The hook `block-sandbox-prompt-patterns.sh`
> blocks the env-var-prefix form (`KEY=value task foo`) for this
> reason, and `cli-args-to-env.sh` validates values against
> `[A-Za-z0-9._/:@+=-]*` — but finding descriptions written by
> reviewer LLMs often contain spaces, colons, and punctuation that
> trip the regex. When a description is rejected, write the value
> to a temp file and pass the path via a dedicated flag instead of
> embedding the description inline. See
> [docs/tool_chain.md](../../../docs/tool_chain.md) §`task` Invocation
> Convention for the canonical contract.

The Orchestrator MUST track the current resolution round number (1-indexed,
starting at 1 for the initial review in Step 2). The round counter resets
to 1 at each new top-level diff-review invocation. When invoking bridge
agents, pass the round number so output files are round-stamped
(`tmp/<agent>-review-output-<N>.md`). Previous rounds are retained for
audit. When reading bridge agent output after invocation, reference the
round-specific filename.

All active reviewers must return APPROVED with no findings that require artifact
amendments before the gate passes. **ALL findings — including non-blocking notes
— MUST be resolved.** Do not defer findings as "non-blocking" or "follow-up";
the Orchestrator MUST delegate every finding to an implementer subagent. If any
reviewer returns BLOCKED, APPROVED WITH NOTES, or APPROVED with informational
observations that imply a code change:

1. Spawn a `tdd-green` or `general-purpose` implementer subagent (at `fast`
   model tier) per the delegation protocol to resolve the findings. The invoking
   agent MUST NOT resolve findings directly — this is a delegation boundary.

> **Experimentation advisory**: If any reviewer flags that experiments or
> tests are required to validate a finding or assumption, the Orchestrator
> MUST spawn a `task` agent to execute the described experiment. The task
> agent is restricted to read-only access on existing repository files and
> may only write to `tmp/` or an isolated worktree created solely for the
> experiment. Look for structured `**Experiment Request:**` blocks from
> Claude reviewers and free-form experiment descriptions from bridge agent
> reviewers (Copilot, Gemini) — both are dispatched identically to the
> task agent. The Orchestrator feeds experiment results into the resolution
> decision — either confirming the finding (delegate code fix to
> implementer) or disconfirming it (submit to Finding Resolution Review as
> `no-action` with experiment evidence).

1. **Regression guard**: After the implementer completes, run `task lint:staged`
   and `task test:staged` on the changed files before regenerating the diff. If
   lint or tests fail, the implementer's fix introduced a regression — spawn a
   **fresh** implementer subagent to fix the regression (do not re-use the prior
   subagent — its context is contaminated by the failed attempt). Do not proceed
   to re-review until lint and tests pass.
2. Regenerate the diff (`task git:diff -- origin/main...HEAD`).
3. Re-submit the updated diff to a **fresh** Dual-Model Review (spawn new
   reviewer agents — do not re-use prior agents). **When the diff was split**
   (per Step 1.4), re-submit only the specific failing split — not the full
   diff — to avoid redundant re-review of passing splits.

> **STOP — DO NOT SELF-DECLARE APPROVED.** After the implementer commits
> fixes, you MUST regenerate the diff and re-submit to FRESH reviewers.
> The Orchestrator declaring the gate passed without fresh reviewer
> confirmation is a protocol violation — it collapses the 3-agent
> verification boundary. Only fresh reviewers can declare APPROVED.

**Maximum 16 resolution attempts.** If the gate remains BLOCKED after 16 attempts:

When the Cross-Family Review Extension is active (N reviewers), ALL
active reviewers must return APPROVED for the gate to pass. The
resolution protocol above applies identically — re-submit to ALL
active reviewers, not just the blocking reviewer. The split-re-review
optimization applies equally to all active reviewers.

**Reviewer inheritance for resolution reviews**: When findings enter
the [Finding Resolution Review](../../../docs/verification_protocol.md#finding-resolution-review)
(APPROVED WITH NOTES path), the resolution review inherits the active
reviewer set established in Step 2 pre-flight — including all active
bridge agents. The resolution review re-runs each inherited bridge
agent's pre-flight before spawning; see
[verification_protocol.md §2](../../../docs/verification_protocol.md#finding-resolution-review)
for degradation handling when bridge agents become unavailable between
rounds.

- **Interactive mode**: Present the unresolved findings to the user and request
  manual intervention.
- **Headless mode**: Checkpoint a `step_result` artifact with `verdict: fail`
  and the full findings, then HALT. Do not proceed past the gate.

### Step 4: Ledger Checkpoint (conditional)

**If `epic_id` was provided**: Checkpoint one `gate_verdict` artifact
per active reviewer to the Execution Ledger — with `epic_id`, verdict,
`agent_model`, and full reasoning in the body. Bridge agent artifacts
MUST include `reviewer_platform` in metadata (`copilot-bridge`,
`gemini-bridge`, or `codex-bridge`).

**Informational notes**: When both reviewers return APPROVED but include
informational observations, include those notes in the `gate_verdict`
artifact body alongside the reviewer reasoning. This prevents silent loss
of reviewer observations — especially in headless mode. (Only applies when
`epic_id` is present; ad-hoc invocations have no ledger interaction.)

**If no `epic_id`** (ad-hoc invocation): Report the consolidated findings from
all reviewers (2 or 3) directly to the user. No ledger interaction.

### Step 5: Finding TODO Capture (conditional — all non-code-change findings)

**Runs after the gate closes** (APPROVED verdict from all reviewers).
Captures unresolved findings and inline code markers as TODOs via a
single batch file — no dynamic content is interpolated into shell
commands.

**If `epic_id` was provided**:

1. **Run the discovery batch.** Step 5 used to issue one container call
   per filter and per marker lookup (≥8 sequential `task findings:*`
   invocations). Instead, refresh the diff and fold all data-extraction
   ops into a single `findings:apply-batch`:

   ```bash
   task git:fetch -- origin main
   task git:diff -- origin/main...HEAD --output=tmp/qa-diff.txt
   ```

   (Use `--output=` rather than shell `>` redirection — CLAUDE.md §10
   forbids bash output redirection in agent-driven flows.)

   Then write `tmp/<epic_id>-step5-discovery.jsonl` via the Write tool
   with these eight lines (no shell interpolation of dynamic content):

   ```json
   {"op": "filter", "id": "active", "args": {"kind": "active"},
    "in_path": "tmp/<epic_id>-findings-ledger.json"}
   {"op": "filter", "id": "no-action", "args": {"kind": "no-action-validated"},
    "in_path": "tmp/<epic_id>-findings-ledger.json"}
   {"op": "filter", "id": "doc-or-todo", "args": {"kind": "doc-or-todo-validated"},
    "in_path": "tmp/<epic_id>-findings-ledger.json"}
   {"op": "parse-diff-markers", "id": "markers", "diff_path": "tmp/qa-diff.txt"}
   {"op": "marker-priority", "id": "mp-TODO", "args": {"marker": "TODO"}}
   {"op": "marker-priority", "id": "mp-FIXME", "args": {"marker": "FIXME"}}
   {"op": "marker-priority", "id": "mp-HACK", "args": {"marker": "HACK"}}
   {"op": "marker-priority", "id": "mp-XXX", "args": {"marker": "XXX"}}
   ```

   (The four marker-priority ops are preemptive — only four distinct
   markers exist, so caching them up front avoids per-marker lookups
   below.) Then execute:

   ```bash
   task findings:apply-batch -- --batch-path tmp/<epic_id>-step5-discovery.jsonl
   ```

   The response is a single JSON document; bind its `results` map for
   the construction step.

2. **Compute validated priorities.** Each entry in `results.no-action`
   and `results.doc-or-todo` carries `validators_count` and
   `total_reviewers` (set when `findings:update-status` recorded the
   resolution). Build a second batch
   `tmp/<epic_id>-step5-validated.jsonl` with one
   `validated-priority` op per **distinct** `(validators_count,
   total_reviewers)` tuple — many findings share the same tuple, so
   keying by tuple keeps the batch small:

   ```json
   {"op": "validated-priority", "id": "vp-<n>-<t>",
    "args": {"validators_count": <n>, "total_reviewers": <t>}}
   ```

   Run `task findings:apply-batch -- --batch-path
   tmp/<epic_id>-step5-validated.jsonl` and bind the resulting priority
   map. (When every validated finding shares one tuple — common for
   N-of-N gates — this batch is a single line.) Skip this batch entirely
   when both validated lists are empty.

3. **Build the TODO batch file**: Collect all TODO entries into a
   single JSON array and write it to `tmp/<epic_id>-todo-batch.json`
   via the Write tool (no shell interpolation of dynamic content).

   **Unresolved findings** (`results.active`): For each, create an entry:

   ```json
   {
     "title": "<finding description>",
     "category": "diff-review",
     "priority": <P>,
     "epic_id": "<epic_id>"
   }
   ```

   where priority is mapped from severity (critical->1, significant->2,
   minor->3, informational->5).

   **No-action validated findings** (`results.no-action`): For each,
   create an entry:

   ```json
   {
     "title": "<finding description>",
     "category": "diff-review-validated",
     "priority": <P>,
     "epic_id": "<epic_id>"
   }
   ```

   where priority is read from the validated-batch result for the
   finding's `(validators_count, total_reviewers)` tuple: all
   accepted->4, partial->3, orchestrator only->2.

   **Doc-or-todo validated findings** (`results.doc-or-todo`): Same
   shape as no-action; priority resolved from the validated-batch
   result for the finding's tuple.

   **Inline code markers** (`results.markers`): For each matched
   marker, create an entry:

   ```json
   {
     "title": "<marker>: <context from surrounding line>",
     "category": "inline-code",
     "priority": <P>,
     "epic_id": "<epic_id>"
   }
   ```

   where priority is read from the discovery-batch result for the
   marker's name (`results.mp-TODO`, `results.mp-FIXME`, `results.mp-HACK`,
   `results.mp-XXX`): HACK/XXX->2, FIXME->3, TODO->5. The four
   `mp-<MARKER>` ids form a hard contract between the discovery batch
   above and this lookup; renaming any one without updating both
   sites yields a `KeyError` at orchestration time.

   The single-call `task findings:filter`, `task findings:marker-
   priority`, `task findings:validated-priority`, and `task
   findings:parse-diff-markers` forms remain available for ad-hoc
   interactive use (e.g., spot-checking a single finding outside the
   skill's gate flow).

4. **Submit the batch**: Run:

   ```bash
   task todo:add-batch -- --batch-file tmp/<epic_id>-todo-batch.json
   ```

   This single invocation creates all TODOs and assigns them to the
   epic. No individual `task todo:add` or `task todo:assign` calls.

5. **Return TODO summary**: Collect all created TODO IDs, titles,
   categories, and priorities. Return this summary to the calling skill
   for PR comment integration (used by auto-pr/ship for Req-009).

6. **Failure handling**: If `task todo:add-batch` exits non-zero:

   - **Interactive mode** (user present): Report the failure to the user
     with the error output. The gate verdict stands (APPROVED), but TODO
     capture is flagged as incomplete.
   - **Headless mode** (`CI=true`): Checkpoint a `step_result` artifact
     to the Execution Ledger with `verdict: fail`, body containing
     "TODO capture failed: <error>" and the findings that were not
     captured. **Halt immediately. Do NOT proceed to Step 6.** The
     diff-review skill MUST NOT return successfully if TODO capture
     fails in headless mode.

**If no `epic_id`** (ad-hoc invocation): Skip TODO capture entirely.

### Step 6: Report

Present a summary to the user or calling skill:

- Overall verdict (APPROVED / BLOCKED)
- Consolidated findings from all reviewers
- Files reviewed and diff scope
