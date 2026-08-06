# PR Protocol

This document defines the shared PR creation, review, and merge
procedures referenced by the `auto-pr` and `ship` skills.

## Validation Routing for Cloned Repositories

The generic `task lint:staged`, `task lint:changed`, and their test
equivalents only work for files owned by the root project. Changes to
files inside cloned repositories (`repos/<repo>/` or
`tmp/<context>/<repo>/`) require repo-specific lint and test commands.

The CI lint scripts (`ci/lint_staged.sh`, `ci/lint_changed.sh`) source
`ci/repo_routing.sh` for automatic repo-specific routing. When
**onboarding a new cloned repository**, you MUST add a routing block
to `ci/repo_routing.sh` alongside the new `taskfiles/repos/<repo>.yml`.

**Resolution order (for agent-driven validation):**

1. **Check platform rule files**: Scan for a matching rule that
   covers the changed file paths:
   - **Claude Code**: `.claude/rules/*.md` — match via the
     `paths:` field (YAML frontmatter glob list).
   - **Copilot**: `.github/instructions/*.instructions.md` — match
     via the `applyTo` field (YAML frontmatter glob string).
   - Rules contain the exact lint and test commands to use instead
     of the generic tasks (e.g., `task <repo>:lint TARGET=...`).
2. **Check root Taskfile for repo-specific tasks**: The root
   `Taskfile.yml` can include task definitions under `taskfiles/repos/`
   for the repositories you clone. Check if a matching
   `taskfiles/repos/<repo>.yml` exists for the target repo.
3. **Discover from the repo itself**: If no rule or root task
   matches, explore the cloned repo for its native build tools
   (`Makefile`, `Taskfile.yml`, CI scripts) and use the appropriate
   targets (e.g., `make lint`, `make test`).
4. **Ask the user**: If none of the above yields a lint/test
   command, stop and ask the user for the correct commands.

**CRITICAL**: Never run `task lint:staged` or `task lint:changed` for
files under `repos/` or `tmp/` unless a matching rule explicitly
says to. These commands will silently pass without checking the
cloned repo's files.

## User Confirmation Gates

- **Pre-Push**: Always ask the user if they want to review changes
  before creating and pushing a PR. If the user says "Yes", stop and
  allow them to review. Do not proceed until they approve. If
  permission was not explicitly granted, assume "No permission" and
  ask for confirmation.
- **Pre-Merge**: Always give the user the option to review changes
  (or the PR link) before proceeding to merge. Even if CI passes, do
  not merge automatically without user consent.

## Automation Signal Vocabulary

Both `auto-pr` and `ship` recognize the following shorthand signals
in `$ARGUMENTS` to bypass specific confirmation gates. Signals are
matched as case-insensitive substrings. Unrecognized text is ignored.

| Signal | Pre-push confirmation | CI fix persistence | Pre-merge confirmation |
|--------|----------------------|-------------------|----------------------|
| *(none)* | Stops to ask | Delegates fix; stops if unresolved | Stops to ask |
| `auto push` | Skipped | Persistent autonomous fix cycles | Stops to ask |
| `auto merge` | Stops to ask | Delegates fix; stops if unresolved | Skipped |
| `auto push+merge` | Skipped | Persistent autonomous fix cycles | Skipped |

- **`auto push`**: Grants prior permission to push without user
  review. CI failures are resolved via persistent autonomous subagent
  fix-retry cycles — the agent continues delegating fixes and
  re-running CI without stopping to ask, up to 16 fix cycles. After 16
  failed cycles, halt and ask the user (interactive) or checkpoint
  `verdict: fail` and halt (headless).
  **Context bloat mitigation**: Each CI fix round captures only a
  fixed-length error digest (error type, failing check name, root cause
  hypothesis) — not raw CI logs. This digest is used both in the
  agent's working context AND in the PR comment CI Gate Resolution Log.
  Raw logs stay on GitHub Actions. **Diminishing returns circuit
  breaker**: If the same error signature repeats 3 consecutive rounds
  with no change, halt early rather than exhausting all 16 attempts.
  **Error signature normalization**: Before comparing signatures across
  rounds, strip ephemeral content (timestamps, hex addresses, line
  numbers, container IDs) to prevent false negatives from incidental
  output variation.
  Does NOT skip the pre-merge confirmation gate.
- **`auto merge`** / **`auto-merge`**: Existing behavior (already
  documented in both skills). The hyphenated form is a legacy alias.
  Skips pre-merge confirmation after CI and PR auto-review are GREEN.
  Does NOT skip pre-push confirmation. CI fix persistence is default
  (delegates one fix, stops if unresolved).
- **`auto push+merge`**: Combines both signals. Canonical compound
  form uses `+` (no spaces around operator). The `&` form and the
  spaced form (`auto push + merge`) are NOT recognized — `&` avoids
  shell backgrounding ambiguity; the spaced form avoids substring
  matching fragility.

**Headless mode interaction**: When `CI=true` is active, all
interactive confirmation gates are already skipped per headless
protocol. The CI fix persistence column still applies in headless
mode — `auto push` / `auto push+merge` grant persistent fix cycles
regardless of session type. Without these signals, headless mode
delegates one fix attempt and halts if unresolved per
[verification_protocol.md](verification_protocol.md).

## Work Item Reference

Every PR must carry a **work item reference** — the link between the change
and wherever the work is tracked. This repository is tracker-agnostic: the
reference names both the **system** and the **identifier**.

### Why the system must be named, not inferred

JIRA and Linear issue keys are structurally identical — both are
`ABC-123` (uppercase team/project key, hyphen, numeric ID). **No pattern
match can distinguish them.** An earlier version of this document assumed
JIRA and validated with `[A-Z]{2,}-\d+`; that both mis-rejects legitimate
Execution Ledger epic IDs and silently mislabels Linear issues as JIRA.
The system is therefore declared explicitly and never guessed.

### Supported systems

| System | Identifier form | Example | Machine-verifiable |
|---|---|---|---|
| **Execution Ledger** (default here) | no fixed pattern — see below | `UPSTREAM-PORT-001`, `TODO-0092-DEFERRED` | **Yes** — `task ledger:index` |
| **JIRA** | `[A-Z]{2,}-\d+` | `ACME-1234` | No |
| **Linear** | `[A-Z]{2,}-\d+` | `ENG-456` | No |
| **GitHub Issues** | `#\d+` or `<owner>/<repo>#\d+` | `#123` | **Yes** — `task gh:api` |
| **None** | the literal `none` plus a reason | `none — CI flake re-run` | n/a |

**Lookup beats pattern-matching — and supersedes it.** For the Execution
Ledger and GitHub Issues the reference is checkable, so **check it**: a
fabricated or mistyped ID is worse than none because it reads as
authoritative. Confirm a ledger epic with `task ledger:index` and a GitHub
issue with:

```bash
task gh:api -- repos/<owner>/<repo>/issues/<n> --jq '{state, is_pr: has("pull_request")}'
```

**`is_pr` must be `false`.** GitHub's issues endpoint serves pull requests too —
`/issues/13` returns the PR numbered 13 with a `state` field like any issue — so
checking `.state` alone will happily validate a PR number as an issue reference.
Verified against this repository: `/issues/13` returns
`{"is_pr": true, "state": "closed"}` for PR #13.

**Query the epic registry, with an explicit limit.** Existence is a property
of the `epics` registry, and `task ledger:index` is what reads it — but it
paginates, so call it with an explicit high `--limit` and match the exact ID:

```bash
task ledger:index -- --limit 1000
```

Two traps, both verified against the live ledger:

- **Default pagination.** Without `--limit`, only the first page is
  returned, so a valid older epic can appear missing — a false negative that
  would hard-stop a legitimate workflow.
- **`ledger:resume` is NOT an existence check.** It queries Chroma artifacts
  and open TODOs, not the registry, so a real-but-artifact-free epic
  (freshly created, no checkpoints yet) returns exactly what a nonexistent
  ID returns: empty collections. Using it to test existence both rejects
  valid new epics and lets a "looks free" check reuse an ID that is already
  taken. Use `resume` to load an epic's context, never to prove it exists.

For these two systems a successful lookup is **conclusive** — do not
additionally validate the ID's shape, and never reject an ID that the
system confirms. Ledger epic IDs deliberately have no fixed pattern: the
ledger holds `UPSTREAM-PORT-001` alongside `TODO-0092-DEFERRED`, so any
regex tight enough to look tidy will reject real epics. This document
previously specified such a regex and it was wrong on live data.

JIRA and Linear cannot be verified from this repo, so their references are
taken on trust and should come from the user rather than be constructed.
Pattern-matching is a weak fallback used only where lookup is unavailable.

**`none` is a legitimate answer, not a failure.** Dependency bumps, CI
re-runs, typo fixes, and hygiene changes often have no tracked work item.
Recording `none — <reason>` is honest; inventing an ID to satisfy a field
is not. What is forbidden is leaving the reference off entirely.

### Resolution order

1. **User-supplied**: a reference in `$ARGUMENTS` or the conversation.
2. **Branch name**: the segment after the last underscore, when present
   (`feat/refactor-sub-system_ACME-1234`).

   **First, decide whether that segment is an ID at all.** Descriptive
   branch names legitimately contain underscores — `feat/add_user_login`
   yields `login`, which is not an identifier. Treat the segment as a
   candidate ID **only** if it matches `[A-Z]{2,}-\d+` (JIRA/Linear shape) or
   resolves in the Execution Ledger. Otherwise it is part of the description:
   ignore it and continue to source 3. Do **not** halt on it.

   **A candidate ID carries no system.** `ACME-1234` could be JIRA or Linear —
   the forms are identical — and the body line requires the system. Resolve it
   in this order, and do not guess:

   1. Look the ID up in the epic registry (`task ledger:index -- --limit 1000`
      — see the traps above). A hit is conclusive: it is a ledger epic.
   2. Otherwise, if the user named the system in this conversation, use that.
   3. Otherwise the system is **ambiguous**. In interactive mode, ask which
      tracker it is. In headless mode, halt and checkpoint
      `{"verdict": "fail", "reason": "work item system ambiguous from branch name"}`
      — do not default to JIRA, and do not omit the system from the body.
3. **Active ledger epic**: if the work belongs to an in-flight epic,
   `execution-ledger resume` supplies its `epic_id`.
4. **Ask the user.** If none of the above resolves, stop and ask. Do NOT
   invent an identifier, and do NOT substitute an identifier from one
   system while labelling it as another.
5. **Record `none`** only when the user confirms there is no tracked item.

**Placeholder rejection**: reject `XXX-1234`, `ABC-0000`, and similar
obvious fillers. Note that `TODO-0001` is **not** a placeholder in this
repository — it is a valid TODO identifier — so judge by whether the
referent exists, not by its shape.

### Branch naming

Include the identifier as a suffix when the tracking system is JIRA or
Linear: `<type>/<short-name>_<ID>`. There the ID is the primary handle
people search by, so having it in the branch name earns its verbosity.

For Execution Ledger, GitHub Issues, and `none`, a descriptive branch name
is sufficient — the PR body is the authoritative carrier of the reference,
and the ledger already links epics to PR refs via `task ledger:set-prs`.

### The work item and the ledger epic are independent

These are two different things and resolving one does **not** resolve the
other:

| | Work Item reference | Ledger epic (`epic_id`) |
|---|---|---|
| Answers | "what tracked request is this PR for?" | "which epic's lifecycle does this work belong to?" |
| Lives in | the PR body | Execution Ledger artifacts |
| Resolved from | user, branch name, active ledger epic, or ask | `execution-ledger resume` |
| May be absent | yes — `none` is valid | yes — ad-hoc work has no epic |

They coincide only when the work item *is* a ledger epic. A PR whose work
item is `ACME-1234 (JIRA)` can still be running under ledger epic
`UPSTREAM-PORT-001`, and in that case `epic_id` **is** `UPSTREAM-PORT-001` —
withholding it because the work item came from a different tracker would
strand the `pr_created` checkpoint, the `in_review` transition, and the PR
refs that depend on it.

**Rule**: resolve `epic_id` from the active ledger epic, always and
independently of the work item. Only omit it when there is genuinely no
active epic. Never populate it with a foreign tracker's identifier.

### Placement in the PR body

The reference appears after the Summary section and before the
Co-authored-by trailer, naming the system in parentheses:

```markdown
## Summary
<1-3 bullet points>

**Work Item**: <ID> (<System>)

---
Co-authored-by: ...
```

Examples of the reference line:

```markdown
**Work Item**: UPSTREAM-PORT-001 (Execution Ledger)
**Work Item**: ACME-1234 (JIRA)
**Work Item**: ENG-456 (Linear)
**Work Item**: #123 (GitHub Issues)
**Work Item**: none — dependency bump, no tracked item
```

## Template Detection

Check for a PR template before generating the body:

```bash
PR_TEMPLATE=".github/pull_request_template.md"
if [ ! -f "$PR_TEMPLATE" ]; then
  PR_TEMPLATE="docs/pull_request_template.md"
  [ ! -f "$PR_TEMPLATE" ] \
    && PR_TEMPLATE=".github/PULL_REQUEST_TEMPLATE.md"
  [ ! -f "$PR_TEMPLATE" ] && PR_TEMPLATE=""
fi
```

## Collapsible Details Convention

PR descriptions and comments (both generated here and posted later)
keep a short, always-visible summary at the top, then fold any verbose
supporting material — multi-row tables, harvested change-history,
per-finding logs — into collapsible `<details>` blocks so reviewers see
the verdict first and expand only what they need.

Use this shape:

```markdown
<one-line summary or verdict — always visible>

<details>
<summary>Short label (with a count when the content is a list/table)</summary>

<verbose content: tables, narrative, logs>

</details>
```

**GitHub rendering rule (mandatory):** GitHub only renders Markdown
(tables, lists, headings) inside a `<details>` block when there is a
**blank line** after the `</summary>` tag and a **blank line** before
the closing `</details>` tag. Omitting either blank line makes tables
render as raw pipe-delimited text. Always include both blank lines.

## Writing Style (Mandatory)

Governs **every** PR body, description, and comment produced under this
protocol — including ad-hoc calls made outside the `auto-pr` / `ship` skills.
Optimize for a reviewer **scanning**, not reading.

Do:

- **Bullets first.** Default to bullet points. Sub-bullets only where a point
  genuinely nests. Prose paragraphs are the exception.
- **One idea per bullet.** Target **≤ 2 lines**. Split anything longer.
- **Bold the key terms** — file names, flags, verdicts, failure modes, the
  operative noun. A reader scanning **only the bold text** should get the gist.
- **Lead with the conclusion.** Verdict, result, or impact first; supporting
  detail after, or folded into `<details>`.
- **Stay technical and boring.** Plain declarative statements: what changed,
  what breaks, what it affects.
- **Cite anchors** — `path/to/file.py:123`, task names, flag names — instead of
  prose descriptions of where something lives.
- **Use tables** for any repeated 3+ column structure. Fold them per the
  **Collapsible Details Convention** above.

Do NOT:

- **No fluff adjectives** — "comprehensive", "robust", "seamless", "carefully
  crafted", "significantly improves".
- **No narrative build-up.** Do not set the scene before making the point.
- **No restating the diff** in prose. The diff is linked and readable.
- **No self-congratulation** and no meta-commentary about writing the PR.
- **No hedging** where the fact is known. State it, or mark it **explicitly
  unverified**.

<!-- THREE copies of this Writing Style block exist:
       docs/pr_protocol.md
       .claude/rules/pr.artifacts.md
       .github/instructions/pr.artifacts.instructions.md
     Edit all three or none. This guard is itself part of the copied block and
     is deliberately self-reference-free so it stays identical in the first two.
     docs/pr_protocol.md and .claude/rules/pr.artifacts.md stay byte-identical
     except (a) the Collapsible Details Convention above/below pointer and
     (b) the "Governs every PR body..." lead sentence, which only
     docs/pr_protocol.md carries.
     The mirror normalizes to ASCII punctuation, spells out symbols, and
     describes HTML tags in prose; it retains inline code spans and bold.
     (Sibling mirrors vary on bold — do not generalize from them.) Treat any
     other wording difference in the mirror as intentional; do not "resync". -->

## Generate PR Body

**If template exists:** Read the template content, fill in sections
with details of the changes, and mark relevant checkboxes (`[x]`).

**If no template exists:** Use this standard format. Bullet-first per
**Writing Style (Mandatory)** above:

```markdown
## Summary

- **<key change>** — <what changed and why, one line>
- **<key change>** — <one line>

## Impact

- <behaviour change, blast radius, or "Behaviour-neutral — <flag> defaults off">

**Work Item**: <ID> (<System>)
```

The Work Item line is mandatory (see **Work Item Reference** above).
`none — <reason>` is a valid value; an absent line is not.

Omit `## Impact` only when the change is genuinely inert — prose-only docs,
comments, formatting — or when an upstream PR template governs the body.
Anything touching runtime behaviour, CI, or infra states its blast radius.

**Agent-governance files are never inert**: `CLAUDE.md`, `.claude/rules/`,
`.github/instructions/`, `docs/*_protocol.md`, and skills are loaded and acted
on as instructions, so a change to them alters agent behaviour repo-wide.

**For sequential multi-PR flows** (e.g., `ship`), always include:

```markdown
## Merge Order
This is PR N of M. Merge in order: PR 1 → PR 2 → ... → PR N.
<If this depends on a previous PR, note: "Depends on #<number>">
```

## Agent Identity & Co-authored-by Trailer

**CRITICAL**: Regardless of whether a template was used, **ALWAYS**
append a horizontal rule (`---`) and the Co-authored-by trailer to
the end of the PR body. Do NOT guess the email, and do NOT include
bullet points, bold prefixes, or markdown backticks in the final PR
body.

Use the identity of your **Agent System/Platform** (e.g., GitHub
Copilot, Claude Desktop, Cursor) and **NOT the underlying LLM
Model**. Use the exact raw string below based on your active agent
identity:

- **GitHub Copilot**: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
- **Claude** (Anthropic CLI / Desktop): `Co-authored-by: Claude <noreply@anthropic.com>`
- **Gemini**: `Co-authored-by: Gemini <noreply@google.com>`
- **Other**: `Co-authored-by: <AgentName> <noreply@<agent-domain>.com>`

## Create PR

**CRITICAL PROTOCOL**: ALL temporary files (PR bodies, logs, plans)
MUST be created in a subfolder within `tmp/` named after the current
git branch. NEVER create temporary files in source directories.

Write the generated PR body to `tmp/<branch-short-name>/pr_body.md` **with the
Write tool** — never a `cat` heredoc or shell redirection, per
[CLAUDE.md](../CLAUDE.md) §10. Then create the PR:

```bash
LABELS="${ARGUMENTS_LABELS:-ai-assisted}"
task gh:pr -- create --base main --label "$LABELS" \
  --title "<title>" \
  --body-file "tmp/<branch-short-name>/pr_body.md"
```

## PR Auto-Review & Correction (Mandatory Gate)

**CRITICAL**: You MUST NOT skip this step even if a PR template does
not exist. Do NOT wait for CI or run any merge commands until review
is fully completed.

Delegate to a subagent (e.g., `explore` or `orchestrator`) providing
the PR number and generated PR body metadata
(`task gh:pr -- view <number> --json title,body,labels`). The subagent must
verify:

1. Does the PR contain the required labels (e.g., `ai-assisted`)?
2. Does the PR have the Co-authored-by trailer at the exact bottom?

**If GREEN**: Proceed. State: "Subagent review passed GREEN."

**If RED**: Delegate a new subagent to update the PR
(`task gh:pr -- edit <number> --body-file ... --add-label ...`) until the
review explicitly reports GREEN.

## PR Execution Comments

### First Comment: Executive Summary

After the PR Auto-Review gate passes GREEN, if the agent's execution
context contains an Executive Summary (from a plan implementation),
post it as the **first comment** on the PR. This is conditional —
ad-hoc PRs without plan context skip this step.

Write the comment body to `tmp/<branch-short-name>/pr_exec_summary.md`, then:

```bash
task gh:pr -- comment <number> --body-file tmp/<branch-short-name>/pr_exec_summary.md
```

**Format**:

```markdown
<!-- pr-lifecycle:executive-summary -->
## Executive Summary

<Brief description of the plan's purpose and what was implemented.
1-3 sentences sourced from plan context.>
```

### Second Comment: QA Diff-Review Resolution Log

After posting the Executive Summary (or immediately after PR
Auto-Review if no Executive Summary is available), if the agent's
execution context contains a QA diff-review resolution log, post it
as a **separate comment** on the PR. This is conditional — ad-hoc PRs
without a diff-review gate skip this step.

Write to `tmp/<branch-short-name>/pr_qa_log.md`, then:

```bash
task gh:pr -- comment <number> --body-file tmp/<branch-short-name>/pr_qa_log.md
```

**Format**:

```markdown
<!-- pr-lifecycle:qa-resolution-log -->
## QA Diff-Review Resolution Log

### Round Summary

| Round | Reviewer | Verdict | Findings | Resolutions |
|-------|----------|---------|----------|-------------|
| 1 | Opus | APPROVED WITH NOTES | 7 | 1 code-change, 6 no-action |
| 1 | Sonnet | APPROVED WITH NOTES | 7 | 0 code-change, 7 no-action |

### Finding Details

| # | Severity | File | Finding | Resolution | Justification | Review |
|---|----------|------|---------|------------|---------------|--------|
| O-1 | SIGNIFICANT | `planning_protocol.md` | Broken indentation in Final QA Phase | code-change | Fixed indentation to 5-space | Applied |
| O-2 | SIGNIFICANT | `diff-review/SKILL.md` | 6→16 convergence jump lacks rationale | no-action | Req-007 unifies all limits; CI 6-cycle cap is separate domain | ACCEPTED (2/2) |
| O-3 | MINOR | `pr_protocol.md` | Substring matching fragility | no-action | Known limitation accepted in Req-001 | ACCEPTED (2/2) |

### Finding Resolution Review

| # | Finding | Opus | Sonnet |
|---|---------|------|--------|
| O-2 | Convergence jump 6→16 | ACCEPTED | ACCEPTED |
| O-3 | Substring matching fragility | ACCEPTED | ACCEPTED |

**Final gate verdict**: APPROVED (Round 1 — 1 code-change applied, 6 no-action findings validated via Finding Resolution Review)
```

The Round Summary table provides the high-level overview. The Finding
Details table lists every finding with its severity, resolution type,
justification, and review outcome. The Finding Resolution Review table
shows the per-reviewer verdict for each no-action finding. Populate
all three tables from the agent's execution context. The examples
above are illustrative — actual row counts match the review.

#### Captured TODOs

After the QA Diff-Review Resolution Log tables, if the diff-review step
returned a TODO summary (list of captured TODO IDs, titles, categories,
and priorities — see [diff-review/SKILL.md](../.claude/skills/diff-review/SKILL.md)
Step 5.3 for the return contract), append a **Captured TODOs**
subsection:

| ID | Title | Category | Priority |
|----|-------|----------|----------|
| TODO-0001 | Missing validation for edge case | diff-review | 2 |
| TODO-0002 | HACK: temporary workaround | inline-code | 2 |

Skip this subsection if no TODOs were captured during the diff-review.

### Third Comment: CI Gate Resolution Log

After all CI checks pass GREEN (before the merge decision), post a
follow-up comment with the CI resolution history. This comment is
always posted — even for first-run clean passes.

Write to `tmp/<branch-short-name>/pr_ci_log.md`, then:

```bash
task gh:pr -- comment <number> --body-file tmp/<branch-short-name>/pr_ci_log.md
```

**Format**:

```markdown
<!-- pr-lifecycle:ci-resolution-log -->
## CI Gate Resolution Log

| Run | Status | Action Taken |
|-----|--------|-------------|
| 1 | PASS | — |

**Result**: All CI gates GREEN.
```

Multi-run example (with failures, delegated fixes, and rebase):

```markdown
<!-- pr-lifecycle:ci-resolution-log -->
## CI Gate Resolution Log

| Run | Status | Action Taken |
|-----|--------|-------------|
| 1 | FAIL — lint error in `file.py:42` | Delegated to tdd-refactor; fixed import order |
| 2 | REBASE — branch behind main by 5 commits | Rebased onto origin/main, force-pushed, re-ran local verification (PASS) |
| 3 | FAIL — test `test_foo` assertion error | Delegated to tdd-green; updated expected value |
| 4 | PASS | — |

**Result**: All CI gates GREEN after 2 fix cycles and 1 rebase.
```

#### Captured TODOs (CI Phase)

If the CI-Phase Inline Marker Scan (see **CI Failure Handling** below)
accumulated any entries, include them in the CI Gate Resolution Log
comment after the resolution table:

| ID | Title | Category | Priority |
|----|-------|----------|----------|
| TODO-0005 | HACK: skip validation for empty input | ci-fix | 2 |
| TODO-0006 | TODO: refactor retry logic | ci-fix | 5 |

Skip this subsection if no new inline markers were found across all CI
fix cycles.

## CI Wait & Merge

### Branch Freshness Check (Mandatory)

Before waiting for CI results, and again after CI completes, the agent
MUST check whether the PR branch needs rebasing against `main`. A CI
pass on a stale branch is unreliable — new changes in `main` may
introduce conflicts or break assumptions the PR code depends on.

**Detection** (fetch and rev-list MUST run as a single sequential
sequence — the rev-list depends on the fetch having updated the
local `origin/main` ref):

```bash
task git:fetch -- origin main
BEHIND_COUNT=$(task git:run -- rev-list --count HEAD..origin/main)
```

If `BEHIND_COUNT > 0`, the branch is behind `main` and must be
rebased before CI results can be trusted.

**Rebase procedure** (when branch is behind):

1. **Rebase onto latest `main`**:

   ```bash
   task git:rebase -- origin/main
   ```

   If the rebase produces conflicts, do NOT resolve them
   automatically. Report the conflicting files to the user
   (interactive) or checkpoint a `step_result` artifact and
   halt (headless):
   `{"step": "ci-gate-rebase", "verdict": "fail",
   "reason": "rebase conflict",
   "conflicting_files": ["path/to/file1", "path/to/file2"]}`
   (substitute actual conflicting file paths).

2. **Force-push the rebased branch** (this is the one sanctioned
   use of force-push — rebasing rewrites history by definition):

   ```bash
   task git:push -- --force-with-lease
   ```

   Use `--force-with-lease` (not `--force`) to guard against
   concurrent pushes to the same branch.

3. **Re-run the full verification cycle**: The rebase may have
   introduced subtle changes (dependency version shifts, import
   reordering, conflict-adjacent code). The agent MUST re-run
   local lint and test checks before trusting remote CI. Apply
   the same validation routing logic described in the
   **Validation Routing for Cloned Repositories** section above
   — use repo-specific lint/test commands for files under
   `repos/` rather than the generic `task lint:changed` /
   `task test:changed`. If local verification fails, delegate
   the fix to a subagent per the standard delegation protocol —
   do NOT fix directly. After the fix is pushed, restart the CI
   wait loop from the beginning.

4. **Log the rebase in the CI Gate Resolution Log**: Every rebase
   is recorded as a row in the resolution log table:

   ```markdown
   | Run | Status | Action Taken |
   |-----|--------|-------------|
   | 2 | REBASE — branch was behind main by 3 commits | Rebased onto origin/main, force-pushed, re-ran verification |
   ```

   The `BEHIND_COUNT` and any local verification re-run results
   are included in the log entry.

**Rebase loop bound**: If the branch falls behind `main` again
while waiting for CI (e.g., a fast-moving `main`), repeat the
rebase procedure. After 3 consecutive rebases in the same CI gate
cycle, halt — the branch is in a rebase race condition that
requires human coordination. The rebase counter resets when a CI
fix cycle completes and CI monitoring restarts from scratch (i.e.,
a fix-triggered restart counts as a new CI gate cycle entry).

In interactive mode, report the race condition to the user. In
headless mode (`CI=true`), checkpoint
`{"step": "ci-gate-rebase", "verdict": "fail",
"reason": "rebase race — 3 consecutive rebases exhausted"}`
and halt.

### CI Monitoring

```bash
task gh:pr -- checks <number> --watch --fail-fast
```

After CI completes, run the **Branch Freshness Check** again. If
the branch has fallen behind `main` during the CI run, rebase per
the procedure above and restart CI monitoring. Only proceed to the
merge decision when CI is GREEN and the branch is current with
`main`.

### Merge Decision

**If CI passes and branch is current**: Ask the user to review or
merge. If user approves, check merge state:

```bash
STATUS=$(task gh:pr -- view <number> --json mergeStateStatus \
  --jq .mergeStateStatus)
```

- `BEHIND`: This should not occur if the Branch Freshness Check
  passed. If it does (race condition), re-run the rebase procedure
  above and restart CI monitoring.
- `DIRTY` or `BLOCKED`: Report error and stop.
- `CLEAN` or `HAS_HOOKS`: Proceed to merge.

**Merge sequence** (each step is a separate Bash call to avoid
triggering the Bash AST parser's "Unhandled node type" warning on
compound commands — see `docs/learnings.md` §Claude Code Sandbox):

```bash
# Step 1: Capture PR title (single Bash call)
task gh:pr -- view <number> --json title --jq .title

# Step 2: Capture PR body to a file (use Write tool, NOT command substitution)
# Write the output of the above to tmp/<branch>/merge_body.md via the Write tool

# Step 3: Merge (single Bash call — use --body-file, not inline --body)
task gh:pr -- merge <number> --squash \
  --subject "<captured title>" \
  --body-file tmp/<branch>/merge_body.md

# Step 4: Return to main (single Bash call)
task git:checkout -- main
```

```bash
# Step 5: Pull latest (single Bash call)
task git:pull
```

**Note**: Do NOT chain steps with `&&` or use `$(...)` command
substitution to inline PR body content. Do NOT use `--delete-branch`
when merge queue is enabled — the queue manages branch cleanup.

### CI Failure Handling

**If CI fails**: Do NOT merge. Do NOT fix code directly. Delegate
the fix to a subagent (e.g., `tdd-green`, `bug-fix`, or
`tdd-refactor`) passing the failing logs. Re-run CI checks after
the fix is pushed. After the fix, run the Branch Freshness Check
before restarting CI monitoring — if `main` advanced during the
fix cycle, rebase first. Repeat until green.

**CI-Phase Inline Marker Scan**: During each CI fix cycle, capture
new inline code markers (`TODO`, `HACK`, `FIXME`, `XXX`) introduced
by the fix:

1. **Before delegating the fix**: Record the current commit SHA
   (`PRE_FIX_SHA=$(task git:run -- rev-parse HEAD)`).
2. **After the fix is committed and local verification passes**:
   Generate the incremental diff:
   `task git:diff -- <PRE_FIX_SHA>..HEAD`.
3. **Scan for markers**: Read the incremental diff and identify added
   lines containing `TODO`, `HACK`, `FIXME`, or `XXX` markers. Apply
   the marker-to-priority mapping directly:

   | Marker | Priority |
   |--------|----------|
   | HACK | 2 |
   | XXX | 2 |
   | FIXME | 3 |
   | TODO | 5 |

4. **Accumulate**: For each matched marker, create a batch entry using
   the following JSON schema (matching the `diff-review` Step 5
   inline-marker format):

   ```json
   {
     "title": "<MARKER>: <context from surrounding line>",
     "category": "ci-fix",
     "priority": <mapped_priority>,
     "epic_id": "<LEDGER_EPIC_ID>"
   }
   ```

   The `epic_id` is the **active ledger epic**, resolved via
   `execution-ledger resume` independently of the PR's Work Item reference
   (see §"The work item and the ledger epic are independent"). A PR tracked
   in JIRA, Linear, or GitHub still files its CI TODOs under whatever ledger
   epic the work belongs to. Omit `epic_id` only when there is genuinely no
   active epic, and never write a foreign tracker's identifier into it —
   that creates a TODO pointing at an epic that does not exist. When the PR
   also carries an external work item, put that reference in the entry
   `title` for traceability. Accumulate entries across all fix cycles in
   memory.
5. **After all fix cycles complete and CI is GREEN**: If any entries
   were accumulated, write them to
   `tmp/<branch-short-name>/ci-todo-batch.json` (branch-scoped, distinct
   from the epic-scoped `tmp/<epic_id>-todo-batch.json` used by the
   diff-review skill) and submit via
   `task todo:add-batch -- --batch-file tmp/<branch-short-name>/ci-todo-batch.json`.
6. **16-cycle circuit breaker**: If the 16-cycle cap fires before CI
   goes GREEN, still write the accumulated batch file to
   `tmp/<branch-short-name>/ci-todo-batch.json` but do NOT call
   `task todo:add-batch` (the TODOs may reference broken code). Include
   the batch file path in the halt checkpoint so the next session can
   decide whether to submit.
