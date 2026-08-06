---
paths:
  - "**/pr_body.md"
  - "**/pr_exec_summary.md"
  - "**/pr_qa_log.md"
  - "**/pr_ci_log.md"
  - "**/pr_review_findings.md"
  - "**/merge_body.md"
---

# PR Artifact Constraints

> **Note**: The fenced code block below is deliberately omitted from the
> `.github/instructions/` mirror per the established repository convention for
> `.github/instructions/` mirrors (code/example blocks are described inline
> there instead). Do not "helpfully" sync it.

You are writing a **PR body or comment artifact**. It will be posted to GitHub
via `--body-file`. Canonical templates and full procedure live in
[pr_protocol.md](../../docs/pr_protocol.md); this rule carries the **style and
mechanical** constraints that apply to every such artifact. Body *structure*
(template detection, `## Impact`, merge order) still comes from
[pr_protocol.md](../../docs/pr_protocol.md).

**This rule binds regardless of how you got here** — `auto-pr`, `ship`, a
diff-review follow-up, or a direct ad-hoc request. There is no skill-triggered
exemption.

**Scope: agent-authored artifacts.** These constraints govern an *agent*
drafting a body or comment. Deterministic tooling that renders a PR body from
a checked-in template — `src/brownfield_ai/tools/ralph/pr.py` is the live
example — is out of scope: it has no drafting step, and the Write-tool
mechanic below presupposes one. Do not "fix" such a caller to satisfy this
rule.

## Writing Style (Mandatory)

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
  **Collapsible Details Convention** below.

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

## Mandatory Mechanics

- **`--body-file` only.** Never pass inline `--body` / `-b` to
  `gh pr create|comment|edit|merge`. This governs calls that **supply body
  text**; a metadata-only `gh pr edit` (labels, reviewers, title) passes no
  body flag at all — adding one would overwrite the current body.
- **Write tool only.** Create the artifact with the Write tool, never a `cat`
  heredoc or shell redirection (CLAUDE.md §10).
- **`tmp/` placement.** `tmp/<branch-short-name>/` for PRs we author;
  `tmp/pr<number>/` for third-party review comments. Never the workspace root,
  never a source directory, never absolute `/tmp/`.
- **Hidden identity marker** on line 1 of every *managed lifecycle comment*
  (not the body). Write the full form — a bare suffix is not a valid
  discriminator:
  - `<!-- pr-lifecycle:executive-summary -->`
  - `<!-- pr-lifecycle:qa-resolution-log -->`
  - `<!-- pr-lifecycle:ci-resolution-log -->`
  - `<!-- pr-review:review-findings -->` — third-party only, see below.

  The list is **exhaustive**. An ad-hoc comment that is not one of these
  artifacts carries **no marker** — do not invent one and do not reuse a
  `pr-lifecycle:` marker to satisfy the rule. Everything else in this rule
  still binds such a comment.

  **The marker is an identity tag, not deduplication.** Per-Round PR
  Reconciliation — the procedure that reads these markers to edit, supersede,
  or delete a prior comment — is **not implemented in this repo**. Every
  documented path posts a fresh `gh pr comment`, so repeated rounds stack
  comments today. Write the marker regardless: it is the discriminator a
  future reconciliation step keys on, and it is what keeps `pr-lifecycle:`
  (PRs we own) separable from `pr-review:` (PRs we do not).
- **`**Work Item**:` line** is mandatory in `pr_body.md` — an ID plus the
  system that owns it, per [pr_protocol.md](../../docs/pr_protocol.md)
  §"Work Item Reference". `none — <reason>` is a valid value; an absent line
  is not.
- **`## Impact` section** in `pr_body.md` states blast radius. Omit only when
  an upstream PR template governs the body, or the change is genuinely inert —
  prose-only docs, comments, formatting. **Agent-governance files are never
  inert**: `CLAUDE.md`, `.claude/rules/`, `.github/instructions/`,
  `docs/*_protocol.md`, and skills change agent behaviour repo-wide.
- **Co-authored-by trailer** per §"Agent Identity & Co-authored-by Trailer" of
  [pr_protocol.md](../../docs/pr_protocol.md). Applies to PR **bodies**, not to
  review comments on third-party PRs.
- **`merge_body.md` exception.** It becomes a squash **commit message**, not
  rendered Markdown — `git log` shows literal `**asterisks**`, raw `<details>`
  tags, and pipe-delimited tables. Plain text only: no bold, no `<details>`,
  no tables, no identity marker. Only the `--body-file` and Write-tool
  mechanics above apply.

## Collapsible Details Convention

Short always-visible summary on top; verbose material folded:

```markdown
<one-line summary or verdict — always visible>

<details>
<summary>Short label (with a count when the content is a list/table)</summary>

<verbose content>

</details>
```

**Blank lines are load-bearing** — GitHub renders Markdown inside `<details>`
only with a blank line after `</summary>` and before `</details>`. Omit either
and tables render as raw pipe-delimited text.

## Third-Party PRs

When the PR is **not ours** (`pr_review_findings.md`):

- Findings are **reported, not resolved** — no resolution column, no verdict on
  our own work.
- **Never post without explicit user sign-off.** Review output is a draft.
- **Headless (`CI=true`)**: do NOT post. Write the artifact, checkpoint
  `verdict: blocked-needs-signoff`, and halt (CLAUDE.md Principle 16).
- **Never edit or delete the author's comments.**
- **Marker namespace is `pr-review:`, never `pr-lifecycle:`** — `pr-lifecycle:`
  is reserved for comments on PRs we own. When Per-Round PR Reconciliation
  lands (not implemented here yet), its supersede-with-banner and delete paths
  will act on `pr-lifecycle:` comments; a PR we do not own must never be
  reachable by them.
- State the **reviewer roster and models**.
- Mark unverified claims **explicitly unverified**; never present
  pattern-matched inference as validated.

## Enforcement

**Layered, and thin.** There is no hook denying an inline `--body`, so an agent
that bypasses the artifact write bypasses this rule silently.

**This rule does not reach a first draft.** Measured behaviour: path-scoped
injection fires on **Read/Edit of an existing artifact, not on Write**. You are
seeing this because an artifact was re-read — on the UPDATE path, across rounds.
An agent authoring an artifact from scratch never receives it. The CLAUDE.md
pointer is what has to carry first-draft compliance.

- **CLAUDE.md §"Tool Chain & PR Protocol"** — the only mechanism that fires on
  every path, including ad-hoc `task gh:pr -- comment`.
- **PR Auto-Review gate** (`pr_protocol.md`) — checks the PR **body** only,
  and only on the `auto-pr` / `ship` paths. Comments are never checked.
- **[`diff-review`](../skills/diff-review/SKILL.md) — not a backstop.** Every
  artifact here lives under `tmp/`, which is gitignored, so it never appears in
  a reviewed diff. A PR body passed as UPDATE-path intent input is not an
  exception: reviewers are explicitly forbidden from raising findings against
  intent.

Related: [comments.conciseness.md](comments.conciseness.md) governs the same
terseness discipline for in-code comments.
