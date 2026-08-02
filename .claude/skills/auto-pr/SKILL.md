---
name: auto-pr
description: "End-to-end PR orchestration: automates branching, hygiene reviews, pre-push verification, PR generation, CI monitoring, and merging via subagents."
---
# Auto-PR — Push, Verify, Merge

End-to-end PR orchestration skill: handles branching uncommitted/unpushed changes, enforcing workspace hygiene, executing local validation gates (`lint` / `test`), pushing to a branch, opening a templated PR against `main`, validating PR formatting, monitoring CI checks, and optionally auto-merging.

Unlike the `ship` skill, this does NOT group changes into multiple PRs.
It treats the working tree as a single unit.

**Shared procedures**: This skill references
[docs/pr_protocol.md](../../../docs/pr_protocol.md) for JIRA ticket
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

1. Resolve the JIRA ticket per [docs/pr_protocol.md](../../../docs/pr_protocol.md) (user hint, branch name, or ask).
   Create a branch: `task git:checkout -- -b <type>/<short-name>_<JIRA-TICKET>` (e.g., `feat/add-metrics_ACME-1234`).
2. **Artifact & Hygiene Review (Delegated)**: Before staging, you MUST delegate to a subagent (e.g., `explore` or `tdd-refactor`) to specifically review the `git status` output for temporary artifacts, debug files, or anomalies (e.g., `testItEOF`, `*.tmp`, `x[a-z][a-z]` split artifacts, out-of-place logs).
   - If the subagent has very high confidence the file is a temporary garbage artifact, the Orchestrator MUST safely remove it (e.g., `rm <file>`).
   - If there is uncertainty, the Orchestrator MUST flag the file and explicitly ask for the user's review before proceeding.
3. **Comprehensive Staging Gate**: Run `task git:status` to view all modified and untracked files. Stage all relevant files (`task git:add`). **CRITICAL**: You must deliberately check for newly created untracked files (e.g., new skills, scripts) alongside modified files. If there are *any* tracked or untracked files left in the working directory that you decide NOT to stage, you MUST list them and ask the user for explicit permission to exclude them from the PR.
4. Commit with a conventional commit message.

If there are only unpushed commits (clean working tree):

1. Resolve the JIRA ticket, then create a branch from HEAD:
   `task git:checkout -- -b <type>/<short-name>_<JIRA-TICKET>`

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

Before pushing, invoke the
[diff-review](../diff-review/SKILL.md) skill to validate implementation quality.
Pass the JIRA ticket as `epic_id` (if available) and use the PR's target branch
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
proceeding. If no JIRA ticket was supplied via `$ARGUMENTS` or branch name,
query the Execution Ledger (`execution-ledger resume`) to derive the active
epic's `epic_id` and use that as the ticket. If the ticket still cannot be
resolved, halt immediately and checkpoint
`{"verdict": "fail", "reason": "JIRA ticket unresolvable in headless mode"}`.

**Interactive mode** (default — no headless signal):

**STOP and Ask the User:**
"Do you want to review these changes before I push and create the PR?"

- **If User says "Yes"**: Stop execution. Let the user review. Wait for their explicit "Proceed" or "Go ahead" command.
- **If User says "No" (or gave prior permission)**: Proceed to Step 3.
- **If Unsure**: Assume "Yes" and stop to ask.

## Step 3: Push & Create PR

```bash
task git:push
```

Follow the procedures in
[docs/pr_protocol.md](../../../docs/pr_protocol.md) for:

1. **Template Detection** — locate and use PR template if present.
2. **Generate PR Body** — fill template or use standard format with
   mandatory JIRA ticket line.
3. **Append Trailer** — add the Co-authored-by trailer for your
   agent platform.
4. **Create PR** — write body to `tmp/<branch>/pr_body.md`, then
   `task gh:pr -- create`.
5. **Ledger Checkpoint** — After successfully creating the PR, checkpoint a `pr_created` artifact to the Execution Ledger with the PR URL, branch name, and JIRA ticket in the metadata. If the PR is subsequently merged (Step 4), checkpoint a `pr_merged` artifact with the merge SHA and PR number.
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
