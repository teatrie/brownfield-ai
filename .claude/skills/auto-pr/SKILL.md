---
name: auto-pr
description: "End-to-end PR orchestration: automates branching, hygiene reviews, pre-push verification, PR generation, CI monitoring, and merging via subagents."
---
# Auto-PR — Push, Verify, Merge

End-to-end PR orchestration skill: handles branching uncommitted/unpushed changes, enforcing workspace hygiene, executing local validation gates (`lint` / `test`), pushing to a branch, opening a templated PR against `main`, validating PR formatting, monitoring CI checks, and optionally auto-merging.

Unlike the `ship` skill, this does NOT group changes into multiple PRs.
It treats the working tree as a single unit.

**Shared procedures**: This skill references
[docs/pr_protocol.md](../../../docs/pr_protocol.md) for work item
resolution, PR template detection, body generation, trailer format,
auto-review, and CI/merge procedures. Read that document before
proceeding.

**User hints:** $ARGUMENTS

---

## Step 1: Inventory

Run `task git:status` and `task git:log -- --oneline origin/main..HEAD` to understand:

- Are there uncommitted changes?
- Are there unpushed commits?
- What's the total diff?

## Step 2: Branch & Commit

If there are uncommitted changes:

1. Resolve the work item per [docs/pr_protocol.md](../../../docs/pr_protocol.md) §Work Item Reference (user hint, branch name, active ledger epic, or ask).
   **Resolve the full branch name once, then reuse that exact string** for the
   probe, the checkout, and the creation. The form depends on the tracking
   system, and probing an unsuffixed name while creating a suffixed one makes
   every JIRA/Linear rerun miss:

   - Execution Ledger, GitHub Issues, or none → `<type>/<short-name>`
   - JIRA or Linear → `<type>/<short-name>_<ID>` (ID suffix required)

   Call the result `<branch>`. Test whether it already exists — the normal case
   on a rerun. `git status` reports only the *current* branch, so it cannot
   answer this on its own. Query both refs: after a fresh clone, or once the
   local branch has been pruned, an open PR's branch exists only on the remote.

   ```bash
   task git:fetch -- origin
   task git:run -- rev-parse --verify --quiet refs/heads/<branch>
   task git:run -- rev-parse --verify --quiet refs/remotes/origin/<branch>
   ```

   Exit 0 (prints the SHA) on **either** means a branch of that name exists.
   **A matching ref does not by itself mean "resume".** It may back a
   closed/unmerged PR, or be an unrelated older branch whose generated name
   collided — resuming either would push stale commits into a PR they do not
   belong to. Before checking it out, run the existing-PR detection and
   ownership check in
   [pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
   Reconciliation" against `<branch>`:

   - **OPEN PR, conclusively ours** → resume:
     `task git:checkout -- <branch>` (this also creates the local tracking
     branch when only the remote ref is present), then **`task git:pull` to
     sync**. The remote branch may have advanced — a reviewer's suggestion
     committed from the GitHub UI, a CI auto-formatter push — and pushing a
     stale local branch is rejected as non-fast-forward, halting the run.
     This is the UPDATE path.
   - **Anything else** — closed/merged PR, no PR, or ownership not conclusive
     → do **NOT** silently resume and do **NOT** silently create over it.
     Stop and ask the user whether to reuse the branch, pick another name, or
     branch fresh from the base. Under `CI=true`, halt and checkpoint per
     CLAUDE.md Principle 16.

   Only when **both** probes fail is the branch genuinely new:

   ```bash
   task git:checkout -- -b <branch>
   ```

   This branches from the **current HEAD**, by design: `auto-pr` packages the
   working tree you are already sitting on, so the uncommitted changes must
   come with you. `ship` differs — it groups a dirty tree into several PRs and
   so bases each new branch on a freshly pulled `main`. Confirm HEAD is where
   you intend before creating: from an unrelated feature branch this carries
   that branch's history into the PR.

   `checkout -b` on an existing branch fails with
   `fatal: A branch named '...' already exists` and aborts the run. Omitting the
   ID suffix makes that collision more likely, not less.

2. **Artifact & Hygiene Review (Delegated)**: Before staging, you MUST delegate to a subagent (e.g., `explore` or `tdd-refactor`) to specifically review the `git status` output for temporary artifacts, debug files, or anomalies (e.g., `testItEOF`, `*.tmp`, `x[a-z][a-z]` split artifacts, out-of-place logs).
   - If the subagent has very high confidence the file is a temporary garbage artifact, the Orchestrator MUST safely remove it (e.g., `rm <file>`).
   - If there is uncertainty, the Orchestrator MUST flag the file and explicitly ask for the user's review before proceeding.
3. **Comprehensive Staging Gate**: Run `task git:status` to view all modified and untracked files. Stage all relevant files (`task git:add`). **CRITICAL**: You must deliberately check for newly created untracked files (e.g., new skills, scripts) alongside modified files. If there are *any* tracked or untracked files left in the working directory that you decide NOT to stage, you MUST list them and ask the user for explicit permission to exclude them from the PR.
4. Commit with a conventional commit message.

If there are only unpushed commits (clean working tree):

1. Resolve the work item, then create a branch from HEAD using the same
   two-form convention given in step 1 of "If there are uncommitted changes"
   above — no ID suffix for Execution Ledger, GitHub Issues, or none;
   `_<ID>` suffix for JIRA or Linear.

## Step 2b: Pre-Push Validation Gate

Before pushing, you must read and execute the instructions in
`workflows/repository-maintenance/skills/docs-review/SKILL.md` to update
any necessary documentation and align with core directives, and then read
and execute `workflows/repository-maintenance/skills/claude-review/SKILL.md`
to ensure the agent configuration is fully compliant against the latest
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

## Step 2c: Code Diff Review (MANDATORY GATE)

**First, run the existing-PR detection and its ownership check** in
[pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
Reconciliation" — that section is the single canonical home of this
procedure; do NOT copy it here. You need the CREATE/UPDATE answer now
because Step 3 branches on it; the per-round procedure itself runs
**after** the push, not here. If ownership cannot be positively
established, halt per that section rather than reconciling.

Then, on either path, invoke the
[diff-review](../diff-review/SKILL.md) skill to validate implementation quality.
Pass the **active ledger epic** as `epic_id`, resolved via
`execution-ledger resume` independently of the PR's Work Item reference — a PR
tracked in JIRA, Linear, or GitHub can still belong to a ledger epic, and the
later `pr_created` checkpoint, `in_review` transition, and PR-ref steps all
depend on it. Omit `epic_id` only when there is genuinely no active epic, and
never set it to a foreign tracker's ID (see `pr_protocol.md` §The work item and
the ledger epic are independent). Use the PR's target branch
as the base. **If running in headless mode**, propagate the headless signal per
delegation protocol §5. Do NOT proceed to push until the diff-review gate
returns `MergeDecision.action == "APPROVE"`.

The diff-review skill routes through
[`envelope_merge.merge`](../../../scripts/orchestrator/envelope_merge.py) — a
pure-Python deterministic function (no LLM call; Req-N02 / Risk-007). Honor
`MergeDecision.action` directly. When `MergeDecision.cross_family_dissent` is
non-null at gate-effort xhigh/max (B-1 R2), the gate still passes as APPROVE,
but the Orchestrator MUST checkpoint a `cross_family_dissent` artifact to the
Execution Ledger **before** the `gate_verdict` so the audit precedes the
verdict in chronological order. Bridge `HALT_FOR_OPERATOR` is NEVER softened
(B-5 R2) — it always halts the gate via merge Rule 1.

## Step 2d: User Confirmation (Pre-Push)

**Auto-push mode**: If `$ARGUMENTS` contains `auto push` or
`auto push+merge` (case-insensitive), skip this confirmation gate
and proceed directly to Step 3. No ledger checkpoint is needed for
interactive-mode signal-based skips — the signal is visible in
`$ARGUMENTS` which is recorded in the PR body and agent context. See
the [Automation Signal Vocabulary](../../../docs/pr_protocol.md#automation-signal-vocabulary)
in `pr_protocol.md` for the full signal table.

**Headless mode** (detected via `CI=true` env var or a headless signal in
`$ARGUMENTS`): Skip this confirmation gate and proceed automatically to
Step 3. Checkpoint a `step_result` artifact to the Execution Ledger with
`{"step": "pre-push-confirmation", "verdict": "skipped-headless"}` before
proceeding. If no work item was supplied via `$ARGUMENTS` or branch name,
query the Execution Ledger (`execution-ledger resume`) to derive the active
epic's `epic_id` and use that. If none resolves, headless mode MUST NOT
invent one and MUST NOT silently record `none` — `none` requires user
confirmation that no tracked item exists, which is unavailable here. Halt
immediately and checkpoint
`{"verdict": "fail", "reason": "work item unresolvable in headless mode"}`.

**Interactive mode** (default — no headless signal):

**STOP and Ask the User:**
"Do you want to review these changes before I push and create the PR?"

- **If User says "Yes"**: Stop execution. Let the user review. Wait for their explicit "Proceed" or "Go ahead" command.
- **If User says "No" (or gave prior permission)**: Proceed to Step 3.
- **If Unsure**: Assume "Yes" and stop to ask.

## Step 3: Push & Create PR

**Re-run the detection and ownership check FIRST — before the push.**
Step 2c's answer is provisional and the pre-push confirmation may have
paused indefinitely; per the revalidation rule in
[pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
Reconciliation", act only on a fresh answer. Order it **ahead of**
`task git:push` because the push is itself a remote mutation: if a
third-party PR was opened on this branch during the pause, pushing adds
your commits to *their* PR before any guard has run. If ownership is not
conclusive, halt per that section rather than pushing.

```bash
task git:push
```

**UPDATE path**: if the PR is still OPEN and ours, do **NOT** create a
second one. Instead run the **per-round procedure** in
[pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
Reconciliation" now — the push above has just landed the round's
commits, which is exactly when its description sync must run — then
**skip items 1–6 below entirely and go straight to Step 3a.** Items 5
and 6 are creation-only: `pr_created` would duplicate an artifact that
already exists for this PR, and the `in_progress` → `in_review`
transition would be re-applied to an epic already in `in_review`, which
the state machine rejects — halting every subsequent update round.

**CREATE path** (no OPEN PR): follow the procedures in
[docs/pr_protocol.md](../../../docs/pr_protocol.md) for:

1. **Template Detection** — locate and use PR template if present.
2. **Generate PR Body** — fill template or use standard format with
   mandatory Work Item line.
3. **Append Trailer** — add the Co-authored-by trailer for your
   agent platform.
4. **Create PR** — write body to `tmp/<branch>/pr_body.md`, then
   `task gh:pr -- create`.
5. **Ledger Checkpoint** *(steps 5 and 6 apply only when an active ledger epic was resolved — see the `epic_id` note in Step 2c. For an ad-hoc PR with no epic, **skip both entirely**; do not invent an epic and do not call ledger commands with an empty ID, which fails after the PR already exists)* — After successfully creating the PR, checkpoint a `pr_created` artifact to the Execution Ledger with the PR URL, branch name, and the Work Item reference in the metadata. If the PR is subsequently merged (Step 4), checkpoint a `pr_merged` artifact with the merge SHA and PR number.
6. **Epic Status Transition** — After creating the PR and checkpointing
   `pr_created`, transition the epic from `in_progress` to `in_review`
   via `task ledger:status -- <epic_id> --new-status in_review`. Then
   set the PR refs via the ledger's `set_current_prs` function by
   running `task ledger:set-prs -- <epic_id> --pr-refs "<owner/repo#number>"`.
   If multiple PRs are created (e.g., via `ship`), store all refs
   comma-separated.

## Step 3a: PR Auto-Review & Correction (MANDATORY GATE)

Follow the **PR Auto-Review** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md). Do NOT wait for
CI or run any merge commands until this gate is GREEN.

## Step 3b: PR Execution Comments (Conditional)

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
and PATCH it, so exactly one of each marker exists per PR. Post a fresh
comment only when no comment with that marker exists yet.

If the diff-review step (invoked during the Final QA Phase) returned a
TODO summary, follow the **Captured TODOs** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md) to append the
subsection to the QA Diff-Review Resolution Log comment. Skip if no
TODOs were captured.

## Step 4: Wait for CI & Merge

Follow the **CI Wait & Merge** procedure in
[docs/pr_protocol.md](../../../docs/pr_protocol.md).

Before presenting the merge decision, follow the **CI Gate Resolution
Log** procedure in
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
intent (case-insensitive), skip the pre-merge user confirmation and
merge automatically once all CI gates pass GREEN and the PR
auto-review gate is GREEN. The Pre-Push confirmation (Step 2d) still
applies unless `auto push` or `auto push+merge` is also present. See
the [Automation Signal Vocabulary](../../../docs/pr_protocol.md#automation-signal-vocabulary)
in `pr_protocol.md` for the full signal table.

- If CI passes (and no auto-merge): ask the user to review or merge.
- If CI passes (with auto-merge): merge immediately.
- If CI fails: delegate fix to a subagent, re-run CI.
- If user chooses "Leave open": report PR URL, return to `main`.

## Step 5: Clean Up

After merge (if applicable):

```bash
task git:checkout -- main
task git:pull
```

Confirm clean state with `task git:status`.

---

## Rules

- **Never push directly to main.** Always use a branch + PR.
- **Never force-push.**
- **CI awareness:** Check repo visibility (`task gh:api -- /repos/{owner}/{repo} --jq '.private'`). If private, warn about Free tier CI minute limits before merging.
- **Return to main** after completion.
- **Respect user hints** in `$ARGUMENTS` for branch name or PR title.
