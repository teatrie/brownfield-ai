---
name: ship
description: Group dirty working tree into sequential, logically-cohesive PRs and create them via gh CLI.
---
# Ship — Group & PR Uncommitted Changes

You are a single subagent (medium-tier). Your job is to analyze the
dirty working tree, group changes into logical PRs, get user approval,
then create the PRs sequentially.

**Shared procedures**: This skill references
[docs/pr_protocol.md](../../../docs/pr_protocol.md) for work item
resolution, PR template detection, body generation, trailer format,
auto-review, and CI/merge procedures. Read that document before
proceeding.

**User hints:** $ARGUMENTS

---

## PHASE 1 — Analysis & Grouping Plan

### Step 1: Inventory Changes

Run `task git:status` and `task git:diff -- --stat` to see all modified, untracked, and deleted files. For each changed file, read the diff (`task git:diff -- <file>` for tracked files, `cat` for untracked) to understand the nature of the change.

### Step 1b: Ignore File Audit

Before grouping, perform a two-part audit:

**Part A — Check untracked files against known patterns:**

- **Compiled binaries** (Go binaries, `.pyc`, `node_modules/`, `dist/`) — must be in `.gitignore`
- **Cache/temp directories** (`.pytest_cache/`, `__pycache__/`, `.task/`, `tmp/`, `temp/`) — must be in `.gitignore`
- **Auto-generated agent state** (`.claude/projects/`, `.claude/history/`) — must be in `.gitignore`
- **Large non-essential files** (`go.sum`, vendor locks, binary assets) — should be in `.claudeignore` (context optimization, still tracked by git)

**Part B — Scan the repo for new artifact types introduced by the current changes:**

Run a broad search for common build/runtime artifacts that may not yet be in the ignore files:

```bash
# Find artifacts that might need ignoring
find . -maxdepth 4 \( \
  -name "*.egg-info" -o -name "*.pyc" -o -name "__pycache__" -o \
  -name ".pytest_cache" -o -name "*.class" -o -name "*.jar" -o \
  -name "derby.log" -o -name "metastore_db" -o -name "spark-warehouse" -o \
  -name "*.log" -o -name "*.tmp" -o -name "*.swp" -o \
  -name ".ivy2" -o -name ".m2" -o -name "target" -o \
  -name "*.o" -o -name "*.so" -o -name "*.dylib" \
\) -not -path "./.git/*" 2>/dev/null
```

For each artifact found, verify it's covered by `.gitignore`. If a new technology was introduced (e.g., Spark, Airflow, Marquez, a new language runtime), check for its common artifacts:

| Technology | Common artifacts to ignore |
|-----------|--------------------------|
| PySpark | `derby.log`, `metastore_db/`, `spark-warehouse/`, `*.egg-info/` |
| Java/Maven | `target/`, `.m2/`, `*.class`, `*.jar` (local builds) |
| Airflow | `airflow.db`, `airflow-webserver.pid`, `logs/` |
| Docker | `*.tar`, dangling layers (not in repo, but check for exported images) |
| Terraform/Pulumi | `.terraform/`, `*.tfstate`, `Pulumi.*.yaml` (secrets) |

If any artifact is present but not ignored, add the pattern to `.gitignore` (if it should never be tracked) or `.claudeignore` (if tracked by git but wasteful for AI context). Include ignore file updates in the first PR or a dedicated housekeeping PR.

### Step 1c: Artifact & Hygiene Review (Delegated)

Before finalizing groups, you MUST delegate to a subagent (e.g., `explore` or `tdd-refactor`) to specifically review the `git status` uncommitted/untracked files for temporary artifacts, generated test junk, or anomalies (e.g., `testItEOF`, `*.tmp`, test dumps).

- If the subagent has very high confidence the file is temporary garbage, the Orchestrator MUST safely remove it (e.g., `rm <file>`).
- If there is uncertainty, the Orchestrator MUST explicitly flag the file in the plan and ask for the user's review before proceeding.

### Step 2: Group into PRs

Group files into logical PRs based on:

1. **Domain cohesion** — files in the same architectural domain together (e.g., all Flink SQL changes, all Go service changes, all frontend changes)
2. **Functional cohesion** — files that implement the same logical change together (e.g., a feature + its test + its docs update)
3. **Dependency order** — PRs that must merge before others (e.g., infra/config before app code)

**Comprehensive Staging Gate**: You must account for *all* valid modified, deleted, and untracked files in your grouping. Deliberately check for newly generated untracked files (e.g. new skills, scripts). If you intentionally leave *any* files unassigned to a PR group, you MUST explicitly list them and ask the user for permission to ignore them.

Keep the number of PRs reasonable (2-6 typically). Don't over-split — a PR with 3-5 related files is better than 5 PRs with 1 file each.

### Step 3: Present the Plan

Output a numbered plan like:

```text
PR 1: "feat(db): add media table migrations"
  Files: db/migrations/20240101000000_media.sql, ...
  Depends on: (none — merges first)

PR 2: "feat(media-service): implement media upload handler"
  Files: repos/<repo>/media-service/main.go, repos/<repo>/media-service/handler.go, ...
  Depends on: PR 1

PR 3: ...
```

### Step 4: Wait for Approval

**Headless mode** (detected via `CI=true` env var or a headless signal in
`$ARGUMENTS`): Skip the grouping confirmation and proceed automatically to
PHASE 1b. Checkpoint a `step_result` artifact to the Execution Ledger with
`{"step": "grouping-approval", "verdict": "skipped-headless", "groups": <summary>}`
before proceeding. If the grouping is ambiguous (no work item resolvable
from `$ARGUMENTS`, branch name, or active Execution Ledger epic via
`execution-ledger resume`), halt immediately and checkpoint
`{"verdict": "fail", "reason": "grouping approval unresolvable in headless mode"}`.

**Interactive mode** (default — no headless signal):

**Stop and ask the user** to confirm the grouping. Present clear options:

- "Looks good, create and merge sequentially" — create PR 1, wait for CI, prompt to merge, update `main`, then proceed to PR 2.
- "I want to adjust the grouping" (let the user describe changes, then re-plan)

**Do NOT create any branches or PRs until the user approves.**

**Because of repository rules requiring PRs to be rebased from `main` before merging, PRs MUST be created, pushed, and merged ONE AT A TIME sequentially.**

If the user approves the sequential plan, proceed to **PHASE 1b** and then execute the sequential loop described in **PHASE 2**.

---

## PHASE 1b — Pre-Push Validation Gate

Before creating any branches or PRs, you must read and execute the
instructions in `workflows/repository-maintenance/skills/docs-review/SKILL.md`
to update any necessary documentation and align with core directives,
and then read and execute
`workflows/repository-maintenance/skills/claude-review/SKILL.md` to
ensure the agent configuration is fully compliant against the latest
protocols. Afterwards, run lint and test checks relevant to the changed
files. **IMPORTANT**: If changes include files under `repos/` or
`tmp/`, follow the **Validation Routing** section in
[docs/pr_protocol.md](../../../docs/pr_protocol.md) to determine the
correct lint/test commands. Otherwise use the defaults:

```bash
task lint:changed
task test:changed
```

**Hard-fail rule**: If a linter or test runner itself fails to execute
(e.g., Docker build error, missing image, network timeout), treat the
gate as **RED**. Do not push. A linter that cannot run is not a pass —
it is an unknown. Resolve the tooling issue before retrying.

If the checks fail, **do not attempt to fix the code directly**. Per
the delegation protocol, delegate the fix to a subagent (e.g.,
`tdd-refactor`, `tdd-green`, or equivalent). Once resolved, explicitly
re-stage (`task git:add`) and re-run the lint/test commands to verify.
Do not assume the fix worked. Do not push broken files.

### User Confirmation (Pre-Push)

**Auto-push mode**: If `$ARGUMENTS` contains `auto push` or
`auto push+merge` (case-insensitive), skip this confirmation gate
and proceed directly to Phase 2. No ledger checkpoint is needed for
interactive-mode signal-based skips — the signal is visible in
`$ARGUMENTS` which is recorded in the PR body and agent context. See
the [Automation Signal Vocabulary](../../../docs/pr_protocol.md#automation-signal-vocabulary)
in `pr_protocol.md` for the full signal table.

**Headless mode** (detected via `CI=true` env var or a headless signal in
`$ARGUMENTS`): Skip this confirmation gate and proceed automatically.
Checkpoint a `step_result` artifact to the Execution Ledger with
`{"step": "pre-push-confirmation", "verdict": "skipped-headless"}` before
proceeding.

**Interactive mode** (default — no headless signal):

**STOP and Ask the User:**
"All pre-flight checks passed. Do you want to review the exact code diffs before I branch and push?"

- **If User says "Yes"**: Stop execution. Let the user review. Wait for their explicit "Proceed" or "Go ahead" command.
- **If User says "No" (or gave prior permission)**: Proceed.
- **If Unsure**: Assume "Yes" and stop to ask.

---

## PHASE 2 — Sequential Branch/Commit/PR Creation

For each PR **in dependency order**, you MUST wait for the previous PR to be merged into `main` and pull `main` locally before proceeding.

### Step 1: Create Branch

Branch from the updated `main`. This ensures the new branch contains the previously merged changes and stays strictly up-to-date with `main` to satisfy repository rebase rules.

Resolve the work item per
[docs/pr_protocol.md](../../../docs/pr_protocol.md) §Work Item Reference (user hint, branch
name, or ask).

```bash
task git:checkout -- main
task git:pull
# Execution Ledger, GitHub Issues, or none — no ID suffix:
task git:checkout -- -b ship/<short-name> main

# JIRA or Linear — ID suffix required:
task git:checkout -- -b ship/<short-name>_<ID> main
```

Use the prefix `ship/` for all branches (e.g.,
`ship/media-schemas_ACME-1234`).

### Step 2: Stage & Commit

Stage **only** the files belonging to this PR group. Use `task git:add -- <file>` for each file. Write a descriptive conventional commit message.

### Step 2a: Code Diff Review (MANDATORY GATE)

**First, run the existing-PR detection** in
[pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
Reconciliation" — that section is the single canonical home of this
procedure; do NOT copy it here. If it resolves to the **UPDATE path**
(an OPEN PR already exists for this branch), complete its per-round
procedure **before** invoking diff-review below, so a human opening the
PR mid-round sees a description that matches the diff. Note the sync does
**not** feed the gate — diff-review treats the diff as the sole artifact
under review. On the **CREATE path** no reconciliation runs and you
proceed directly.

Then invoke the
[diff-review](../diff-review/SKILL.md) skill scoped to the files in this PR's
commit group. Pass the **active ledger epic** as `epic_id`, resolved via
`execution-ledger resume` independently of the Work Item reference — a group
tracked in JIRA, Linear, or GitHub can still belong to a ledger epic, and the
later ledger transition and PR-ref steps depend on it. Omit only when there is
no active epic, and never set it to a foreign tracker's ID (see
`pr_protocol.md` §The work item and the ledger epic are independent). Use the PR's
target branch as the base. **If running in headless mode**, propagate the
headless signal per delegation protocol §5. Do NOT proceed to push until the
diff-review gate returns APPROVED.

### Step 3: Push & Create PR

```bash
task git:push
```

**UPDATE path**: if Step 2a's detection found an OPEN PR for this branch,
do **NOT** create a second one. The description sync already ran as step 1
of the per-round procedure, so the body is current — **skip items 1–5
below entirely and go straight to Step 3a.** Item 5 is creation-only: the
`in_progress` → `in_review` transition would be re-applied to an epic
already in `in_review`, which the state machine rejects, halting every
subsequent update round.

**CREATE path** (no OPEN PR): follow the procedures in
[docs/pr_protocol.md](../../../docs/pr_protocol.md) for:

1. **Template Detection** — locate and use PR template if present.
2. **Generate PR Body** — fill template or use standard format with
   mandatory Work Item line. For multi-PR flows, include the
   **Merge Order** section from the protocol.
3. **Append Trailer** — add the Co-authored-by trailer for your
   agent platform.
4. **Create PR** — write body to `tmp/<branch>/pr_body.md`, then
   `task gh:pr -- create`.
5. **Epic Status Transition** — After creating the PR and checkpointing
   `pr_created`, transition the epic from `in_progress` to `in_review`
   via `task ledger:status -- <epic_id> --new-status in_review`. Then
   set the PR refs via the ledger's `set_current_prs` function by
   running `task ledger:set-prs -- <epic_id> --pr-refs "<owner/repo#number>"`.
   If multiple PRs are created (e.g., via `ship`), store all refs
   comma-separated.

### Step 3a: PR Auto-Review & Correction (MANDATORY GATE)

Follow the **PR Auto-Review** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md). Do NOT wait for
CI or run any merge commands until this gate is GREEN.

### Step 3b: PR Execution Comments (Conditional)

Follow the **PR Execution Comments** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md). Post up to two
separate comments: (1) Executive Summary as the first comment, and
(2) QA Diff-Review Resolution Log with full finding details as the
second comment. Each is conditional — skip whichever is not available
in the execution context. Ad-hoc PRs without plan context skip this
step entirely.

**On the UPDATE path, edit in place rather than posting.** Each of these
comments carries a stable `pr-lifecycle:` marker on line 1; per
[pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
Reconciliation" step 4, resolve the existing comment bearing the marker
and PATCH it, so exactly one of each marker exists per PR. The marker is
skill-agnostic by design: a PR that alternates between `ship` and
`auto-pr` across rounds still resolves to one comment per type.

If the diff-review step (invoked during the Final QA Phase) returned a
TODO summary, follow the **Captured TODOs** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md) to append the
subsection to the QA Diff-Review Resolution Log comment. Skip if no
TODOs were captured.

### Step 4: Record, Wait, and Merge

Save each PR's URL and number for the final summary.

**Ledger Checkpoint:** *(Applies only when an active ledger epic was resolved. For an ad-hoc group with no epic, skip every ledger operation in this step — checkpoint, `ledger:status`, and `ledger:set-prs` alike. Do not invent an epic and do not pass an empty ID, which fails after the PRs already exist.)* After each PR is created, checkpoint a `pr_created` artifact to the Execution Ledger with the PR URL, branch name, Work Item reference, and merge order position. **`pr_created` is CREATE-only** — on the UPDATE path (Step 2a's detection found an OPEN PR) no PR was created this round, so skip it rather than emitting a duplicate creation artifact for a PR that already has one. After each PR is merged, checkpoint a `pr_merged` artifact with the merge SHA and PR number; that one is unconditional, since a merge happens exactly once regardless of path.

Follow the **CI Wait & Merge** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md). Ask the user
for explicit permission to merge each PR before executing.

Before presenting the merge decision (or auto-merging), follow the
**CI Gate Resolution Log** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md) to post the CI
resolution history as a follow-up comment on the PR.

During CI fix cycles, follow the **CI-Phase Inline Marker Scan**
procedure in [docs/pr_protocol.md](../../../docs/pr_protocol.md) (CI
Failure Handling section) to capture new inline markers in each fix
diff. After CI is GREEN, include any accumulated entries in the CI Gate
Resolution Log comment per the **Captured TODOs (CI Phase)** format in
the same document.

**Auto-merge mode**: If `$ARGUMENTS` contains `auto merge`,
`auto-merge`, `auto push+merge`, `proceed with merge`, or similar
intent (case-insensitive), skip the per-PR merge confirmation and
merge automatically once all CI gates pass GREEN and the PR
auto-review gate is GREEN. The Phase 1b Pre-Push confirmation still
applies unless `auto push` or `auto push+merge` is also present. See
the [Automation Signal Vocabulary](../../../docs/pr_protocol.md#automation-signal-vocabulary)
in `pr_protocol.md` for the full signal table.

Proceed to the next PR ONLY after the previous PR has been merged
and `main` is updated. If CI fails on any PR, delegate the fix to
a subagent (e.g., `tdd-green`, `bug-fix`, or `tdd-refactor`). If
the subagent fails after a few attempts, **stop the entire
sequence** and ask the user for help.

---

## PHASE 3 — Summary

After all PRs are created and merged sequentially, output a final summary:

```text
## Ship Complete 🚢

The following PRs were successfully created and merged:

1. #101 — feat(db): add media table migrations
   https://github.com/user/repo/pull/101
2. #102 — feat(media-service): implement upload handler
   https://github.com/user/repo/pull/102
3. ...
```

---

## Rules

- **Only merge if the user chose "proceed and merge".** If they chose "create PRs only", never merge.
- **Never force-push.** If something goes wrong, report it and stop.
- **Clean up on failure.** If a step fails mid-execution, report what was created so the user can clean up.
- **Return to main.** After all PRs are created (and merged, if applicable), `task git:checkout -- main` so the working tree is back to the starting branch.
- **Respect user hints.** If `$ARGUMENTS` contains grouping preferences (e.g., "keep docs separate", "group all infra"), honor them.
- **Audit ignore files.** Never commit compiled binaries, cache dirs, or agent state. If `.gitignore` or `.claudeignore` need updates, include them in the first PR.
- **CI minutes awareness.** Before presenting the plan, check repo visibility (`task gh:api -- /repos/{owner}/{repo} --jq '.private'`). If the repo is **private**, warn the user: "This repo is private — GitHub Free tier has 2,000 CI minutes/month. Each merged PR triggers CI builds. Consider batching PRs (max 1-2 merges/day) or choosing 'create PRs only' and merging them together." If public, no warning needed (unlimited free minutes).
