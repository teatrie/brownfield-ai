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

**Ownership marker (mandatory, both paths).** Line 1 of every PR body we
create is the hidden marker `<!-- pr-lifecycle:pr-body -->`, ahead of any
template content. It is the **unconditional, workflow-specific** proof of
authorship the §"Per-Round PR Reconciliation" ownership check relies on:
the ledger artifact is skipped for ad-hoc runs and the execution comments
are conditional, so neither is guaranteed to exist, while the
`Co-authored-by:` trailer is generic enough that a human's AI-assisted PR
carries it too. Without this marker a later round cannot prove the PR is
ours and stalls for sign-off. Preserve it through every description sync.

**If no template exists:** Use this standard format. Bullet-first per
**Writing Style (Mandatory)** above:

```markdown
<!-- pr-lifecycle:pr-body -->
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
[CLAUDE.md](../CLAUDE.md) §10. Claude Code's Write tool creates missing parent
directories; on a runtime whose file-write tool does not, run
`mkdir -p tmp/<branch-short-name>` first. Then create the PR:

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
3. Does the body carry a **Work Item** line naming both the ID and the
   system (see **Work Item Reference** above)? `none — <reason>` is valid;
   an absent line is not.
4. Does the body carry an **`## Impact`** section, unless an upstream PR
   template governs it or the change is genuinely inert? Agent-governance
   files are never inert.
5. Is the body bullet-first per §"Writing Style (Mandatory)" — no prose
   paragraphs where bullets belong, tables folded per the **Collapsible
   Details Convention**?

**If GREEN**: Proceed. State: "Subagent review passed GREEN."

**If RED**: Delegate a new subagent to update the PR
(`task gh:pr -- edit <number> --body-file ... --add-label ...`) until the
review explicitly reports GREEN.

## PR Execution Comments

**Post-or-PATCH (applies to all three comments below).** Each carries a
stable `pr-lifecycle:` marker on line 1. Before posting any of them,
resolve whether a comment bearing that marker already exists on the PR:

```bash
task gh:api -- --paginate /repos/{owner}/{repo}/issues/<number>/comments \
  --jq '.[] | {id, body}'
```

If one does, **PATCH it in place** per §"Per-Round PR Reconciliation"
step 4 instead of posting; the `task gh:pr -- comment` invocations shown
below are the **first-post** form only.

**`--paginate` is load-bearing, and it needs `--jq` to be usable.** The
endpoint returns 30 comments per page by default. A long-running PR —
precisely the multi-round case this procedure exists for — can carry the
marked comment on a later page; an unpaginated lookup would conclude no
marker exists and post a duplicate, defeating the invariant.

`--paginate` alone emits **each page as a separate JSON array**, which is
not valid JSON once concatenated. `--jq '.[] | …'` applies per page and
yields a **flat stream of one object per comment**, which is what you
want. Do **not** reach for `--slurp` here: it wraps the *pages* in an
outer array, giving an array-of-arrays, and `gh` rejects it outright when
combined with `--jq` (`the --slurp option is not supported with --jq`).

This rule lives here, at the point of posting, because it cannot be
delegated to the pre-push reconciliation pass: all three comments are
written **after** that pass runs, and the CI Gate Resolution Log is
written later still — after CI completes. Without post-or-PATCH, every
update round would append another copy and defeat the
exactly-one-per-marker invariant.

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

- **<what the plan set out to do>** — <one line, sourced from plan context>
- **<what was implemented>** — <one line>
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

**Final gate verdict**: APPROVED (Round 1 — 1 code-change applied, 6 no-action findings validated via Finding Resolution Review)

<details>
<summary>Round summary (2 reviewers, 7 findings)</summary>

| Round | Reviewer | Verdict | Findings | Resolutions |
|-------|----------|---------|----------|-------------|
| 1 | Opus | APPROVED WITH NOTES | 7 | 1 code-change, 6 no-action |
| 1 | Sonnet | APPROVED WITH NOTES | 7 | 0 code-change, 7 no-action |

</details>

<details>
<summary>Finding details (3)</summary>

| # | Severity | File | Finding | Resolution | Justification | Review |
|---|----------|------|---------|------------|---------------|--------|
| O-1 | SIGNIFICANT | `planning_protocol.md` | Broken indentation in Final QA Phase | code-change | Fixed indentation to 5-space | Applied |
| O-2 | SIGNIFICANT | `diff-review/SKILL.md` | 6→16 convergence jump lacks rationale | no-action | Req-007 unifies all limits; CI 6-cycle cap is separate domain | ACCEPTED (2/2) |
| O-3 | MINOR | `pr_protocol.md` | Substring matching fragility | no-action | Known limitation accepted in Req-001 | ACCEPTED (2/2) |

</details>

<details>
<summary>Finding resolution review (2 no-action findings)</summary>

| # | Finding | Opus | Sonnet |
|---|---------|------|--------|
| O-2 | Convergence jump 6→16 | ACCEPTED | ACCEPTED |
| O-3 | Substring matching fragility | ACCEPTED | ACCEPTED |

</details>
```

The verdict leads; the tables fold beneath it per the **Collapsible
Details Convention** above. The Round Summary table provides the
high-level overview. The Finding Details table lists every finding with
its severity, resolution type, justification, and review outcome. The
Finding Resolution Review table shows the per-reviewer verdict for each
no-action finding. Populate all three tables from the agent's execution
context. The examples above are illustrative — actual row counts match
the review.

#### Captured TODOs

After the QA Diff-Review Resolution Log tables, if the diff-review step
returned a TODO summary (list of captured TODO IDs, titles, categories,
and priorities — see [diff-review/SKILL.md](../.claude/skills/diff-review/SKILL.md)
Step 5.3 for the return contract), append a **Captured TODOs**
subsection, folded per the **Collapsible Details Convention** above:

```markdown
<details>
<summary>Captured TODOs (2)</summary>

| ID | Title | Category | Priority |
|----|-------|----------|----------|
| TODO-0001 | Missing validation for edge case | diff-review | 2 |
| TODO-0002 | HACK: temporary workaround | inline-code | 2 |

</details>
```

Skip this subsection if no TODOs were captured during the diff-review.

### Third Comment: CI Gate Resolution Log

After all CI checks pass GREEN (before the merge decision), post a
follow-up comment with the CI resolution history. This comment is
always written — even for first-run clean passes.

**Post-or-PATCH applies here too, and matters most.** This comment is
written after CI completes, which is the furthest point from the
pre-push reconciliation pass, so nothing upstream can dedupe it. On any
round where a `pr-lifecycle:ci-resolution-log` comment already exists,
PATCH it rather than posting a second one.

Write to `tmp/<branch-short-name>/pr_ci_log.md`, then:

```bash
task gh:pr -- comment <number> --body-file tmp/<branch-short-name>/pr_ci_log.md
```

**Format**:

```markdown
<!-- pr-lifecycle:ci-resolution-log -->
## CI Gate Resolution Log

**Result**: All CI gates GREEN.

<details>
<summary>Run history (1)</summary>

| Run | Status | Action Taken |
|-----|--------|-------------|
| 1 | PASS | — |

</details>
```

Multi-run example (with failures, delegated fixes, and rebase):

```markdown
<!-- pr-lifecycle:ci-resolution-log -->
## CI Gate Resolution Log

**Result**: All CI gates GREEN after 2 fix cycles and 1 rebase.

<details>
<summary>Run history (4)</summary>

| Run | Status | Action Taken |
|-----|--------|-------------|
| 1 | FAIL — lint error in `file.py:42` | Delegated to tdd-refactor; fixed import order |
| 2 | REBASE — branch behind main by 5 commits | Rebased onto origin/main, force-pushed, re-ran local verification (PASS) |
| 3 | FAIL — test `test_foo` assertion error | Delegated to tdd-green; updated expected value |
| 4 | PASS | — |

</details>
```

#### Captured TODOs (CI Phase)

If the CI-Phase Inline Marker Scan (see **CI Failure Handling** below)
accumulated any entries, include them in the CI Gate Resolution Log
comment after the run-history block, folded per the **Collapsible
Details Convention** above:

```markdown
<details>
<summary>Captured TODOs (2)</summary>

| ID | Title | Category | Priority |
|----|-------|----------|----------|
| TODO-0005 | HACK: skip validation for empty input | ci-fix | 2 |
| TODO-0006 | TODO: refactor retry logic | ci-fix | 5 |

</details>
```

Skip this subsection if no new inline markers were found across all CI
fix cycles.

## Per-Round PR Reconciliation

This section is the **single canonical home** of the existing-PR UPDATE
path and its per-round reconciliation procedure. Both `auto-pr` and
`ship` INVOKE it by reference — neither copies it.

### Entry condition — existing-PR detection

Before the PR step (`auto-pr` Step 3 / `ship` Phase 2 Step 3, and before
the round's Code Diff Review Gate), detect whether an open PR already
exists for the current branch:

```bash
task gh:pr -- view <branch> --json number,url,title,body,state
```

**Pass the branch explicitly, and pass the FULL name.** `<branch>` is the
complete head ref the calling skill resolved — prefix and any `_<ID>`
suffix included, e.g. `ship/media-schemas_ACME-1234` — **not** the
`<branch-short-name>` used for `tmp/` artifact directories elsewhere in
this document. A short name does not identify the head ref, so the lookup
would report no PR and route to CREATE while an open PR exists, producing
a duplicate-creation attempt instead of reconciliation. Omitting the
argument entirely is worse still: `gh` then resolves the implicitly
checked-out branch, wrong or empty under detached HEAD or headless.

`gh pr view <branch>` resolves the branch's **most-recent** PR
**including merged/closed** ones, so the `state` field is load-bearing:
the UPDATE path is gated on an **OPEN** PR only.

Three outcomes, not two — a non-`OPEN` state is **not** the same as no PR:

- **No PR at all** (non-zero exit and stderr, not an empty success) →
  **CREATE path**: proceed with **Create PR** as normal (first-round PR
  generation). No reconciliation runs.
- **A merged or closed PR** (a PR is returned with a non-`OPEN` `state`) →
  the branch is **spent**. If it was squash-merged, its commits are already
  in the base, so creating from it would open a follow-up PR carrying
  already-merged history, based behind the current base. **Halt** and
  return to branch selection: rebase the work onto the fresh base or move
  it to a new branch. Never treat this as a first-round create.
- **An OPEN PR already exists** (a PR is returned AND `state == "OPEN"`)
  → check ownership below, then take the **UPDATE path**: do NOT create a
  second PR. Run the **per-round procedure** below each round, then
  UPDATE (edit) the existing PR rather than re-creating it.

**Ownership check — `state` alone is not sufficient.** An OPEN PR on this
branch may have been opened by a human or another tool. Reconciliation
overwrites the description and mutates `pr-lifecycle:` comments, so
entering the UPDATE path on a PR we do not own would breach the
third-party rule in [CLAUDE.md](../CLAUDE.md) §"Tool Chain & PR
Protocol", which requires explicit sign-off and forbids the
`pr-lifecycle:` namespace on such PRs. As with the comment audit,
**author login is not a valid discriminator** (agent PRs are opened under
the operator's `gh` token). Evidence is **tiered**:

- **Conclusive — proceed to UPDATE.** Any one of: the
  `<!-- pr-lifecycle:pr-body -->` marker on line 1 of the PR body, a
  `pr_created` ledger artifact for this PR number, or an existing
  `pr-lifecycle:` marker on one of its comments. All three are produced
  only by this workflow. The **body marker is the one that always
  exists** — §"Generate PR Body" mandates it on every PR we create,
  whereas the ledger artifact is skipped for ad-hoc runs and the
  execution comments are conditional, so a run that stopped right after
  creation has only the body marker to prove itself by.
- **Suggestive, not sufficient — ask.** The agent `Co-authored-by:`
  trailer alone. §"Agent Identity & Co-authored-by Trailer" mandates it
  on every PR body we create, but it is a **generic** AI trailer: a
  human-authored PR written with the same assistant carries an identical
  line. It cannot separate "this workflow's PR" from "someone else's
  AI-assisted PR", so it may not authorize mutation by itself.
- **Nothing** — treat as third-party.

On anything short of conclusive, **fail SAFE**: do not reconcile, do not
edit the body. Present the PR to the user and ask whether it is ours;
under `CI=true` do not ask — halt and checkpoint
`verdict: blocked-needs-signoff` per CLAUDE.md Principle 16.

This is deliberately biased toward stopping. A stall costs one question;
a wrong UPDATE silently rewrites someone else's PR description.

Both `auto-pr` and `ship` perform this detection at their PR step and
share this one procedure.

**Re-run the check immediately before acting on it — and before the
push.** The first lookup happens before the diff-review gate and before
the pre-push confirmation, which can pause indefinitely on a human. Treat
that result as *provisional*: it only tells the skill whether to expect
UPDATE work. Repeat the state and ownership lookup **immediately before
`task git:push`**, and act on that fresh answer.

Order it ahead of the push, not after. The push is itself a remote
mutation: if a third-party PR was opened on this branch during the pause,
pushing appends your commits to *their* PR before any ownership guard has
run. Revalidating afterwards is too late. A PR opened during the pause
must not receive a duplicate.

**A PR that closed or merged during the pause is not a CREATE.** Separate
"no PR has ever existed for this branch" from "the PR we detected is now
closed or merged". The second means the branch is **spent** — if it was
squash-merged, its commits are already in the base — so pushing more
commits to it would raise a follow-up PR carrying the merged history,
based behind the current base. **Halt** there: return to branch selection
so the work is rebased onto the fresh base or moved to a new branch. Do
not treat it as a first-round create.

### Per-round procedure (UPDATE path)

Run these steps **in order** each round the PR is revised.

**1. Description sync (mandatory — runs immediately AFTER the round's
`task git:push`, before the PR Auto-Review gate).** Re-read the current
PR body (`task gh:pr -- view <number> --json body`), patch it so it
matches the current diff (Summary bullets, `## Impact`, the
`**Work Item**` line, folded change-history per the **Collapsible
Details Convention**), and push the update:

```bash
task gh:pr -- edit <number> --body-file tmp/<branch-short-name>/pr_body.md
```

**Merge; do not blindly regenerate.** This edit replaces the **whole**
body, so anything a human added through the GitHub UI — review context, a
checklist, a deployment note — is erased unless you carry it forward.
That is why step 1 re-reads the current body first: diff your regenerated
sections against it, update only what the diff changed, and **preserve
every section you did not author**. Silently dropping a reviewer's note is
the same class of harm as editing their comment.

**Retain the `<!-- pr-lifecycle:pr-body -->` marker on line 1 and the
`Co-authored-by:` trailer verbatim.** This edit replaces the whole body,
and the marker is the ownership anchor the entry condition depends on.
Dropping it risks the *next* round failing the ownership check and
falling through to the sign-off path — stalling the loop on a PR we do in
fact own. The other two conclusive signals may cover for it, but neither
is guaranteed: the ledger artifact is skipped for ad-hoc runs and the
comment markers are conditional, so the body marker is the only one
always present. The `## Impact` section and the `**Work Item**` line must
survive the rewrite for the same reason the auto-review gate checks them.

This enforces PR-description↔diff consistency. **Order it after the
push, never before.** Editing the body while the round's commits are
still local publishes a description of a diff GitHub is not yet showing,
and the pre-push user-confirmation gate can hold that mismatch open
indefinitely — the opposite of the consistency this step exists for.

**It does not currently feed the diff-review gate.** The reviewer prompt
in [diff-review](../.claude/skills/diff-review/SKILL.md) declares the
diff the **SOLE artifact under review**; this repo has no intent-input
channel, so the synced body reaches humans and the merge record, not the
reviewers. Wiring the body in as intent input belongs with the pending
diff-review dimension expansion — do not assume it already happens.

**Re-sync after every subsequent push, through merge.** One pass makes
the body current *at that moment*, not *at merge*. Every later push
re-opens the gap, and the UPDATE path skips body generation at the PR
step, so this sync is the only place the description↔diff invariant is
ever re-established. Run it again after **each** of:

- **diff-review resolution** — a `code-change` finding mutates the diff
  after this step ran; re-sync once the gate returns APPROVE.
- **a CI-fix push** — CI Failure Handling delegates a fix, pushes, and
  restarts CI without re-entering this procedure; a fix that changes the
  implementation otherwise ships with a body describing the pre-fix diff.
- **a rebase push** — a rebase onto the base branch can change the
  effective diff the PR presents.

The invariant is checked at merge, not at first sync: if the last thing
pushed is not described by the body, this step has not been satisfied.

**2. Comment audit.** Enumerate the **AGENT-AUTHORED** comments on the
PR and classify each. Use the **paginated REST endpoint**, not
`gh pr view --json comments` — the latter returns a bounded GraphQL
connection, so on a long-running PR it silently omits older comments and
the duplicate markers this audit exists to find:

```bash
task gh:api -- --paginate /repos/{owner}/{repo}/issues/<number>/comments \
  --jq '.[] | {id, body}'
```

A comment counts as **AGENT-AUTHORED for reconciliation purposes ONLY IF**
it bears a signature a human comment would not carry — specifically
either:

- a `pr-lifecycle:` hidden marker (`<!-- pr-lifecycle:… -->` on the first
  line), or
- a comment id this session recorded when it posted the comment.

**The `Co-authored-by:` trailer is NOT a valid discriminator here**, for
the same reason it is only suggestive in the ownership check above: it is
a generic AI trailer, so a human's AI-assisted comment carries an
identical line. Treating it as proof would let reconciliation supersede
or edit a human comment — exactly what the hard guardrail below forbids.

Author **login MUST NOT** be used either: agent comments are posted under
the operator's `gh` auth token, so an agent-posted comment and a human
comment written by that same operator share one GitHub author login —
author identity is NOT reliably determinable from metadata.

Any comment lacking a marker or a session-recorded id is treated as HUMAN
(out of scope for edit / delete — see the guardrail below). For the
comments that pass this test, classify each:

- **Current** — still accurate for the present diff; leave as-is (or
  edit-in-place per the marker rule in step 4).
- **Superseded** — a later round replaced its content.
- **Stale** — no longer applicable to the current diff.

**3. Delete-vs-supersede policy.** DEFAULT to
**supersede-with-banner** — preserve the audit trail (consistent with
never-silent-dismissal). Fold the superseded/stale body into a
collapsible `<details>` block per the **Collapsible Details Convention**
above — **include its mandatory blank lines** (after `</summary>`, before
`</details>`):

```markdown
<details>
<summary>⚠️ Superseded — see &lt;link&gt;</summary>

<old comment body, with any pr-lifecycle marker neutralized>

</details>
```

**Neutralize the old marker when you supersede.** If the superseded body
still carries its `<!-- pr-lifecycle:… -->` line, the PR keeps two
comments matching that marker and the next round's lookup can resolve —
and PATCH — the superseded copy. Rewrite the marker in the retained body
to its inert form, `<!-- superseded:pr-lifecycle:<suffix> -->`, which
preserves the audit breadcrumb while no longer matching a lookup. This
applies to every supersede, and is what actually delivers the
one-live-comment-per-marker steady state.

Supersede-with-banner MUST operate **ONLY** on comments the step-2 audit
positively identified as agent-authored — that is, carrying a
`pr-lifecycle:` marker, or posted by the agent **this session** and
tracked by comment id. A generic `Co-authored-by:` trailer does **not**
qualify (step 2), since a human's AI-assisted comment carries the same
line. If a comment cannot be positively identified as agent-authored, it
is treated as HUMAN and left untouched (reply-and-link only per the
guardrail) — fail **SAFE** toward "human, do not edit." No author-login
inference is ever load-bearing on this mutation path.

**Delete ONLY** pure same-round duplicates or noise the agent itself just
posted **this round** (e.g. a double-posted comment from a retried tool
call). NEVER delete anything from a prior round, and NEVER a human
comment (see the guardrail below).

**4. Recurring structured comments — edit-in-place on the hidden
marker.** The three structured PR-execution comments each carry a
stable, **skill-AGNOSTIC** hidden identity marker on the first line of
the comment body:

| Comment | Hidden marker |
|---------|---------------|
| Executive Summary | `<!-- pr-lifecycle:executive-summary -->` |
| QA Diff-Review Resolution Log | `<!-- pr-lifecycle:qa-resolution-log -->` |
| CI Gate Resolution Log | `<!-- pr-lifecycle:ci-resolution-log -->` |

Third-party **Review Findings** comments are deliberately absent from
this table: they carry the `pr-review:` prefix, live on PRs we do not
own, and are **out of reconciliation scope entirely** — never edited,
superseded, or deleted. See
[pr.artifacts.md](../.claude/rules/pr.artifacts.md) §"Third-Party PRs".

The prefix is `pr-lifecycle:` — deliberately NOT `auto-pr:` / `ship:` —
so a PR that alternates between `auto-pr` and `ship` across rounds still
resolves to exactly ONE identity per comment-type. Each round,
reconciliation **dedupes on the marker across BOTH callers**: resolve the
existing comment carrying the marker (from the step-2 audit) and **edit
it in place** rather than posting a new one, so exactly ONE of each
marker exists per PR (no stacking):

```bash
task gh:api -- --method PATCH \
  /repos/{owner}/{repo}/issues/comments/<id> \
  -F body=@tmp/<branch-short-name>/<comment>.md
```

Here `<id>` is the **numeric REST comment id** the PATCH endpoint
requires: `task gh:pr -- view <number> --json comments` yields
GraphQL-shaped comment objects with a `url` but no bare numeric id, so
take `<id>` from the audited comment's `url` fragment
`#issuecomment-<id>` (or enumerate the comments via
`task gh:api -- --paginate /repos/{owner}/{repo}/issues/<number>/comments \
  --jq '.[] | {id, body}'`,
whose REST objects carry a numeric `id` directly — keep `--paginate`, see
§"PR Execution Comments"). Only if no comment with the marker exists yet
does the skill post a fresh one. Reserve
supersede-with-banner (step 3) for genuinely one-off comments a later
round obsoletes; in the steady state the three marked comments are
edited in place, never superseded.

**Collapsing pre-existing duplicates.** A PR opened before this procedure
existed — or one whose earlier rounds posted rather than edited — can
already carry **several** comments bearing the same marker. Edit-in-place
alone cannot reach "exactly one per marker" there, so on the first
reconciliation round that finds duplicates:

- **Keep the most recent** comment carrying the marker; that is the one
  edited in place from this round on.
- **Supersede-with-banner the older duplicates** per step 3, linking to
  the kept comment, and **neutralize their markers** to
  `<!-- superseded:pr-lifecycle:<suffix> -->` as that step requires —
  without which the duplicates keep matching and nothing is collapsed.
  This is the one sanctioned exception to "the three marked comments are
  never superseded" — that rule assumes the steady state of exactly one.
- **Do not delete them.** The step-3 prohibition on deleting prior-round
  comments is unconditional; collapsing duplicates preserves the audit
  trail rather than erasing it.
- The **HARD GUARDRAIL** below still applies: only comments the step-2
  audit positively identified as agent-authored may be touched.

Once collapsed, subsequent rounds find exactly one comment per marker and
take the plain edit-in-place path.

**⚠️ HARD GUARDRAIL — NEVER touch human comments.** Reconciliation
operates **ONLY** on AGENT-AUTHORED comments. It MUST NEVER delete or
edit a HUMAN comment. To respond to a human comment, **reply-and-link
only** (post a new reply that references it); for inline review threads,
use GitHub's native **"Resolve conversation"** control — never edit or
delete the human's text. The comment audit (step 2) enumerates
agent-authored comments exclusively; any comment not authored by the
agent identity is out of scope for delete / supersede / edit. Because
agent and human comments can share one author login under the operator's
`gh` auth token, authorship MUST be established by the step-2
discriminator — a `pr-lifecycle:` marker or a session-recorded comment id
— never by author login, and never by the generic `Co-authored-by:`
trailer, which a human's AI-assisted comment carries identically. When
agent-vs-human authorship is **ambiguous** — no marker, no recorded id,
shared operator login — reconciliation MUST default to treating the
comment as **HUMAN** and never edit or delete it.

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

   **Then re-sync the PR description** per §"Per-Round PR
   Reconciliation" step 1. A rebase changes the effective diff the PR
   presents, so the body written before it is now stale, and nothing
   later in this procedure would refresh it — the PR would reach merge
   describing the pre-rebase state.

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

**Re-sync the PR description after each fix push** that changed the
implementation, per §"Per-Round PR Reconciliation" step 1. This loop
pushes and restarts CI without otherwise revisiting the body, so a fix
that alters behaviour would otherwise reach merge with a description of
the pre-fix diff.

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
