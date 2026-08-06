---
description: PR Artifact Constraints
applyTo: "**/pr_body.md,**/pr_exec_summary.md,**/pr_qa_log.md,**/pr_ci_log.md,**/pr_review_findings.md,**/merge_body.md"
---

# PR Artifact Constraints

You are writing a **PR body or comment artifact**. It will be posted to GitHub
via `--body-file`. Canonical templates and full procedure live in
`docs/pr_protocol.md`; this file carries the **style and mechanical**
constraints that apply to every such artifact. Body *structure* (template
detection, `## Impact`, merge order) still comes from `docs/pr_protocol.md`.

**This rule binds regardless of how you got here** -- `auto-pr`, `ship`, a
diff-review follow-up, or a direct ad-hoc request. There is no skill-triggered
exemption.

**Scope: agent-authored artifacts.** These constraints govern an *agent*
drafting a body or comment. Deterministic tooling that renders a PR body from
a checked-in template -- `src/brownfield_ai/tools/ralph/pr.py` is the live
example -- is out of scope: it has no drafting step, and the file-write
mechanic below presupposes one. Do not "fix" such a caller to satisfy this
rule.

## Writing Style (Mandatory)

Optimize for a reviewer **scanning**, not reading.

Do:

- **Bullets first.** Default to bullet points. Sub-bullets only where a point
  genuinely nests. Prose paragraphs are the exception.
- **One idea per bullet.** Target **at most 2 lines**. Split anything longer.
- **Bold the key terms** -- file names, flags, verdicts, failure modes, the
  operative noun. A reader scanning **only the bold text** should get the gist.
- **Lead with the conclusion.** Verdict, result, or impact first; supporting
  detail after, or folded into a collapsible block.
- **Stay technical and boring.** Plain declarative statements: what changed,
  what breaks, what it affects.
- **Cite anchors** -- `path/to/file.py:123`, task names, flag names -- instead of
  prose descriptions of where something lives.
- **Use tables** for any repeated 3+ column structure. Fold them per the
  **Collapsible Details Convention** below.

Do NOT:

- **No fluff adjectives** -- "comprehensive", "robust", "seamless", "carefully
  crafted", "significantly improves".
- **No narrative build-up.** Do not set the scene before making the point.
- **No restating the diff** in prose. The diff is linked and readable.
- **No self-congratulation** and no meta-commentary about writing the PR.
- **No hedging** where the fact is known. State it, or mark it **explicitly
  unverified**.

<!-- THREE copies of this block exist: docs/pr_protocol.md,
     .claude/rules/pr.artifacts.md, and this file. Edit all three or none.
     The other two are byte-identical to each other except the Collapsible
     Details Convention above/below pointer and a lead sentence carried only by
     pr_protocol.md. This copy additionally normalizes to ASCII punctuation,
     spells out symbols, and describes HTML tags in prose; it retains inline
     code spans and bold. (Sibling mirrors vary on bold — do not generalize
     from them.) -->

## Mandatory Mechanics

- **`--body-file` only.** Never pass inline `--body` / `-b` to
  `gh pr create|comment|edit|merge`. This governs calls that **supply body
  text**; a metadata-only `gh pr edit` (labels, reviewers, title) passes no
  body flag at all -- adding one would overwrite the current body.
- **File-authoring tool only.** Create the artifact with the editor's
  file-write tool, never a `cat` heredoc or shell redirection.
- **Note on reach**: context-injection timing for path-scoped instructions
  varies by agent runtime, so do not assume this file reached you before you
  began drafting. `docs/pr_protocol.md` is the authoritative source either way.
- **`tmp/` placement.** `tmp/<branch-short-name>/` for PRs we author;
  `tmp/pr<number>/` for third-party review comments. Never the workspace root,
  never a source directory, never absolute `/tmp/`.
- **Hidden identity marker** on line 1 of every *managed lifecycle comment*
  (not the body): an HTML comment carrying `pr-lifecycle:executive-summary`,
  `pr-lifecycle:qa-resolution-log`, or `pr-lifecycle:ci-resolution-log`.
  Third-party review comments use the separate `pr-review:review-findings`
  namespace -- see below. That list is exhaustive: an ad-hoc comment that is
  not one of these artifacts carries no marker. Do not invent one and do not
  reuse a `pr-lifecycle:` marker. Everything else here still binds it.
- **The marker is what makes deduplication possible.** The Per-Round PR
  Reconciliation procedure in `docs/pr_protocol.md` resolves the existing
  comment bearing the marker and edits it in place, so exactly one of each
  marker exists per PR. A missing or bare-suffix marker defeats that lookup
  and stacks duplicates. It also keeps `pr-lifecycle:` (PRs we own) separable
  from `pr-review:` (PRs we do not).
- **Mandatory Work Item line** in `pr_body.md` -- an ID plus the system that
  owns it, per the Work Item Reference section of `docs/pr_protocol.md`. A
  `none` value with a stated reason is valid; an absent line is not.
- **`## Impact` section** in `pr_body.md` states blast radius. Omit only when
  an upstream PR template governs the body, or the change is genuinely inert --
  prose-only docs, comments, formatting. **Agent-governance files are never
  inert**: `CLAUDE.md`, `.claude/rules/`, `.github/instructions/`,
  `docs/*_protocol.md`, and skills change agent behaviour repo-wide.
- **Co-authored-by trailer** per the Agent Identity & Co-authored-by Trailer
  section of `docs/pr_protocol.md`. Applies to PR bodies, not to review
  comments on third-party PRs.
- **`merge_body.md` exception.** It becomes a squash **commit message**, not
  rendered Markdown -- `git log` shows literal asterisks, raw HTML tags, and
  pipe-delimited tables. Plain text only: no bold, no collapsible blocks, no
  tables, no identity marker. Only the `--body-file` and file-write mechanics
  above apply.

## Collapsible Details Convention

Keep a short always-visible summary on top and fold verbose material -- tables,
per-finding logs, harvested history -- into an HTML `details` element with a
concise `summary` label that carries a count when the content is a list or
table.

**Blank lines are load-bearing** -- GitHub renders Markdown inside a `details`
element only when a blank line follows the closing `summary` tag and another
precedes the closing `details` tag. Omit either and tables render as raw
pipe-delimited text.

## Third-Party PRs

When the PR is **not ours** (`pr_review_findings.md`):

- Findings are **reported, not resolved** -- no resolution column, no verdict on
  our own work.
- **Never post without explicit user sign-off.** Review output is a draft.
- **Headless (`CI=true`)**: do NOT post. Write the artifact, checkpoint
  `verdict: blocked-needs-signoff`, and halt.
- **Never edit or delete the author's comments.**
- **Marker namespace is `pr-review:`, never `pr-lifecycle:`** -- `pr-lifecycle:`
  is reserved for comments on PRs we own, and the Per-Round PR Reconciliation
  procedure in `docs/pr_protocol.md` acts on exactly those: edit-in-place,
  supersede-with-banner, and delete. `pr-review:` comments are out of
  reconciliation scope entirely -- a PR we do not own must never be reachable
  by those paths.
- State the **reviewer roster and models**.
- Mark unverified claims **explicitly unverified**; never present
  pattern-matched inference as validated.

## Enforcement

**Layered, and thin.** There is no hook denying an inline `--body`, so an agent
that bypasses the artifact write bypasses this rule silently.

- **Your runtime's always-in-context project instructions** -- the only
  mechanism that fires on every path, including ad-hoc PR comments. In Claude
  Code that is `CLAUDE.md`; on other runtimes it is the equivalent
  always-loaded file. `docs/pr_protocol.md` remains the authoritative source.
- **The PR Auto-Review gate** (`docs/pr_protocol.md`) -- checks the PR **body**
  only, and only on the `auto-pr` / `ship` paths. Comments are never checked.
- **The diff-review gate -- not a backstop.** Every artifact here lives under
  `tmp/`, which is gitignored, so it never appears in a reviewed diff. A PR
  body passed as UPDATE-path intent input is not an exception: reviewers are
  explicitly forbidden from raising findings against intent.

Related: `comments.conciseness.instructions.md` governs the same terseness
discipline for in-code comments.
