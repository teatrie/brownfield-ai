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
   task git:fetch -- origin --prune
   task git:run -- rev-parse --verify --quiet refs/heads/<branch>
   task git:run -- rev-parse --verify --quiet refs/remotes/origin/<branch>
   ```

   **`--prune` is required.** A plain fetch keeps
   `refs/remotes/origin/<branch>` after the remote branch is deleted — as it
   is on every squash-merge with `--delete-branch`. Without pruning, the probe
   reports a branch that no longer exists remotely and routes an ordinary
   CREATE run into the collision/sign-off path.

   Exit 0 (prints the SHA) on **either** means a branch of that name exists.
   **A matching ref does not by itself mean "resume".** It may back a
   closed/unmerged PR, or be an unrelated older branch whose generated name
   collided — resuming either would push stale commits into a PR they do not
   belong to. Before checking it out, run the existing-PR detection and
   ownership check in
   [pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
   Reconciliation" against `<branch>`:

   - **Already on `<branch>`** (`task git:status` reports it as current) → it
     is your working branch; the local ref is expected, not a collision.
     Proceed with no prompt when the detection returned **no PR at all** (the
     ordinary case — a local branch with commits and no PR yet, which must
     never halt) or an **OPEN PR conclusively ours** (UPDATE).

     Two outcomes are **not** plain CREATEs, even standing on the branch:

     - An **OPEN PR not conclusively ours** halts here exactly as it would
       below. Being on the branch does not waive the ownership guard.
     - A **closed or merged PR** means the branch is **spent**. This is the
       state you are left in after a squash-merge with `--delete-branch`:
       the remote ref is gone and detection reports no *open* PR, but the
       local commits are already in `main`. Reusing it would open a PR
       carrying the previous PR's commits, based behind the current base.
       Rebase onto the fresh base first, or branch anew — do not push it
       as-is.
   **Two rules govern every switch away from your current branch**, whichever
   outcome below applies:

   - **Unpushed commits block the switch.** Resolve the upstream first with
     `task git:run -- rev-parse --abbrev-ref @{upstream}`. If it resolves,
     compare against it: `task git:log -- --oneline @{upstream}..HEAD`. If it
     does **not** (non-zero exit — no tracking configured), fall back to
     `origin/main..HEAD` rather than assuming everything is unpushed: a
     branch sitting at the fetched base has nothing to lose, and calling it
     wholly unpushed would halt an ordinary run. Commits merely absent
     from `main` are the normal state of any unmerged feature branch and
     must not block anything; only commits absent from the *remote* are at
     risk. When the branch has **no upstream**, nothing has been pushed, so
     treat every commit on it as unpushed. A stash moves the dirty tree but
     leaves committed work behind, so switching would push `<branch>`
     without the very commits you were asked to publish — silently. If
     unpushed commits exist and `<branch>` is a different branch, **halt and
     ask** which to publish. Under `CI=true`, halt per CLAUDE.md
     Principle 16.
   - **Stash a dirty tree first.** You arrive here from the
     uncommitted-changes path, and `checkout` aborts with
     `Your local changes ... would be overwritten by checkout` when the
     target branch differs in any modified path. The `--autostash` on the
     pull does not help — it runs later. Wrap **every** checkout below:
     `task git:run -- stash push --include-untracked`, the checkout, **then
     any sync**, and only then `task git:run -- stash pop`.

     **Skip the pair entirely on a clean tree — this is a data-safety rule,
     not a tidiness one.** `stash push` on a clean tree is a no-op
     (`No local changes to save`), but the paired `pop` is **not**
     harmless: it pops whatever is on top of the stack. It only errors
     `No stash entries found` when the stack is empty, so on a repo holding
     any pre-existing stash it would silently apply that unrelated work
     onto your branch. Decide with `task git:status`, never by running the
     pop and seeing what happens.

     **Pop last, after the sync.** Popping before the pull only forces the
     rebase to autostash the same changes again — and if the pop conflicts,
     the pull then hard-fails on the unmerged tree.

     **A conflicting pop stops the run.** The resumed branch may hold an
     earlier version of these files. `git stash pop` **keeps its entry** on
     conflict, so nothing is lost: report the conflicting paths and let the
     user reconcile, rather than staging a half-merged tree. Under
     `CI=true`, halt per CLAUDE.md Principle 16. Never `stash drop` to clear
     it.

   Then, by outcome:

   - **Not on it, but an OPEN PR is conclusively ours** → resume with
     `task git:checkout -- <branch>` (which also creates the local tracking
     branch when only the remote ref is present), then sync with
     **`task git:pull -- --rebase --autostash origin <branch>`**. This is the
     UPDATE path. Name the remote and branch explicitly: a branch that lost
     or never had upstream tracking makes a bare `git pull` fail with
     `no tracking information`. **`--rebase`** keeps the diverged case — the
     remote advanced via a reviewer's UI commit or a CI auto-formatter —
     from opening `$EDITOR` and adding a merge commit, and an unsynced local
     branch would otherwise be rejected as non-fast-forward.
     **`--autostash`** is a fallback here rather than the main mechanism:
     the stash above already holds your changes, so the tree is clean and
     the flag is usually a no-op. It matters on the paths where no stash was
     taken — a tree clean at checkout but dirtied since — where the rebase
     would otherwise refuse to start.
   - **Not on it, and the ref is someone else's or spent** — closed/merged
     PR, or an OPEN PR whose ownership is not conclusive → do **NOT**
     silently resume and do **NOT** silently create over it. Stop and ask
     the user whether to reuse the branch, pick another name, or branch
     fresh from the base. Under `CI=true`, halt and checkpoint per
     CLAUDE.md Principle 16.
   - **Not on it, and no PR exists at all** → the *name* is free of any PR,
     which is **not** proof the *branch* is free. It may be an abandoned or
     unrelated branch that merely collides with the generated name, and
     pushing to it would graft your commits onto someone else's work. Decide
     on commits, not on the absent PR:
     - **No commits beyond the base** — a bare leftover ref. Reuse it: check
       it out (stashing per the rule above) and carry on. Name the ref the
       probe actually found: `task git:log -- --oneline origin/main..<branch>`
       when the **local** ref exists, `origin/main..origin/<branch>` when
       only the **remote** one does. A remote-only branch is not a valid
       local revision, and naming it bare fails with `unknown revision`.
       Compare against **`origin/main`**, not local `main` — you just
       fetched `origin --prune`, so `origin/main` is current while local
       `main` may lag; against a stale base a bare branch cut at the fetched
       tip looks like it carries commits and would halt for nothing.
     - **It carries commits** — ambiguous. **Ask** before reusing: offer
       reuse, a different name, or a fresh branch. Under `CI=true`, halt and
       checkpoint per CLAUDE.md Principle 16.

   **Pull whenever the remote probe succeeded**, on every resume above — not
   only when an owned OPEN PR was found. A branch that exists remotely can
   have advanced regardless of PR state, and an unsynced local ref makes the
   later push fail as non-fast-forward, which is the failure this whole
   probe exists to avoid. Always name the remote and branch —
   `task git:pull -- --rebase --autostash origin <branch>` — since upstream tracking may be
   absent. Skip the pull only when the branch is local-only: there is
   nothing on the remote to pull from.

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

1. Resolve the work item, then apply **the whole of** step 1 of "If there are
   uncommitted changes" above — the two-form branch-name resolution, the
   local-and-remote existence probe, the existing-PR/ownership check, and the
   resume-or-create decision. This is the most common update-round entry
   state: a clean tree on an existing branch with unpushed commits. Creating
   from HEAD unconditionally would fail on `checkout -b` when the branch is
   already local, and would never reach the UPDATE reconciliation path.

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
your commits to *their* PR before any guard has run.

The halt applies **only when an OPEN PR exists and ownership is not
conclusive** — that is the case where pushing would touch someone else's
PR. **No OPEN PR at all is the ordinary CREATE case**: there is nothing
to own, nothing to halt on, so push and continue below.

```bash
task git:push
```

**UPDATE path**: if the PR is still OPEN and ours, do **NOT** create a
second one. Instead run the **per-round procedure** in
[pr_protocol.md](../../../docs/pr_protocol.md) §"Per-Round PR
Reconciliation" now — the push above has just landed the round's
commits, which is exactly when its description sync must run — then
**skip items 1–6 below and go straight to Step 3a.**

What you skip is the **creation-time** work in items 5 and 6:
`pr_created` would duplicate an artifact this PR already has, and the
`in_progress` → `in_review` transition would be re-applied to an epic
already in `in_review`, which the state machine rejects — halting every
subsequent update round.

**`pr_merged` is not part of that skip.** It happens to be mandated
inside item 5, but it is a *merge*-time artifact: checkpoint it at
Step 4 as usual when the PR merges.

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
