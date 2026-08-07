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
- **Epic ID**: Optional **Execution Ledger epic ID** for ledger checkpointing —
  not a generic work item reference; a JIRA, Linear, or GitHub ID here would
  create artifacts under an epic that does not exist. If
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
   **Whole-PR dimensions survive the split**: items 12 (co-located siblings) and
   13 (cross-file duplication) cannot be answered from one split alone, and a
   changed-file *list* is not sufficient — recognizing a duplicated block needs
   the added content, not just the filenames. Run ONE additional whole-PR pass
   scoped to items 12 and 13 over the concatenated **added lines** of every
   split. Added lines only, two dimensions only, so it stays far below the depth
   and size of a full review even when the complete diff would not fit. Its
   findings enter the round's findings ledger and block the gate like any other.
   Without that pass, duplication introduced across two files placed in
   different splits merges unreviewed.

### Step 2: Delegate Dual-Model Review

Spawn two independent `code-review-high` Reviewers at the highest and second-highest
tiers (cross-family when available). For reviewer model selection, apply the
Reviewer Model Selection table in
[docs/verification_protocol.md](../../../docs/verification_protocol.md).

All reviewers receive the diff (or diff splits) and the following prompt.
When the diff corresponds to an existing PR, also supply the PR body/description
so item 18 (PR-description ↔ diff consistency) can run; if it is not supplied,
reviewers note that dimension as not run.
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
> diff — except per the Bounded exception below and item 18's
> description-accuracy carve-out. Findings that target unchanged
> files will be rejected as out of scope.
>
> **Bounded exception (high-risk file classes only):** for a file the diff
> *already touches* in a high-risk class (shell `**/*.sh`; CI
> `.github/workflows/**` + `ci/**`; go-task `Taskfile*.yml` + `taskfiles/**/*.yml`;
> Dockerfile; Terraform `**/*.tf`), a reviewer MAY raise a finding on an
> *unchanged line in that same file* IF it is the same mechanical defect class
> as the change (quoting / word-split / pipefail / injection / anchoring /
> escape-and-flag interpretation — e.g. `echo -e` or `echo` of data where
> `printf '%s'` is correct). This does NOT extend to unchanged *files*,
> non-mechanical concerns, or files outside these classes;
> changed-lines-only governs everything else. Such findings MUST be
> labeled `adjacent-mechanical`. Like any finding, an
> `adjacent-mechanical` finding flows through the never-silent-dismissal loop
> and may widen the merged diff (fixing the sibling line) — intended, at a
> proportionate noise cost bounded by the same-defect-class restriction.
>
> **Intent / Background (OPTIONAL — interpretation aid only):**
> When supplied, an Intent / Background block accompanies the diff: a short
> epic/ticket/plan summary (and, when the PR already exists, its body). It exists
> ONLY to help you interpret WHY the changed lines look the way they do — it is
> **NOT a completeness checklist** and **NOT a requirements list to verify
> against**. The CRITICAL SCOPE CONSTRAINT above still governs (subject to the
> Bounded exception above): findings must target lines added, removed, or
> modified in the diff, and the Intent / Background block MUST NOT expand that
> scope. Do NOT audit whether every intent item was delivered. **Do NOT generate
> findings for intent items not reflected in the diff** — the sole carve-out is
> item 18's description-accuracy check, whose finding targets the PR description
> rather than a code line and never asks for the missing change to be
> implemented. You MAY, however, flag
> where the diff appears to **contradict its own stated intent** — a changed line
> that does the opposite of, or undercuts, what the Intent / Background
> describes. This is NOT a new scope dimension; it sharpens item 4
> (architectural consistency) and item 18 (PR-description ↔ diff consistency),
> and such contradiction findings still target changed lines only. When no
> Intent / Background is supplied, proceed with the diff alone — this input is
> optional.
>
> "Review this code diff against the base branch for:
>
> 1. Security vulnerabilities (OWASP top 10, credential leaks, injection risks)
> 2. CLAUDE.md and coding standard violations. **For each modified file
>    path, enumerate every `.claude/rules/*.md` whose `paths:` glob
>    matches the path, then verify the diff satisfies each matching
>    rule's directives. Multiple rule files can apply to one path — for
>    example, any `.py` file matches both `lang.python.md` and
>    `brownfield_ai.python.md`, which glob `**/*.py` independently. Flag
>    any matching rule whose directives are not satisfied by the diff.**
> 3. Accidental file deletions or unintended modifications
> 4. Architectural consistency with existing patterns
> 5. Missing or degraded documentation (docstrings, type hints). Also enforce
>    the two comment standards indexed by `docs/coding_standards.md` §6 and §7:
>    (a) added comments that narrate change history — dates, deployment status,
>    evolution narrative, PR/ticket cross-references — instead of current-state
>    rationale, EXCEPT a dated or historical comment that another active rule
>    *requires* (e.g. the `-- mirrors schema of <table> as of YYYY-MM-DD` form
>    mandated by [`sql.queries.md`](../../rules/sql.queries.md) §Exceptions #4),
>    which is a forward-looking drift guard rather than narrative — see
>    [`comments.history.md`](../../rules/comments.history.md) §Exception;
>    (b) added comments that are redundant or agent-directed —
>    restating what the code, its base class, its type signature, or a linked
>    guide already says, or speculating about paths the code does not take.
>    Both are judged from the diff alone. Do **not** attempt to verify that
>    history *deleted* in this diff was relocated to the PR description or
>    ledger — you cannot see either, so you would be guessing in both
>    directions; that obligation rests with the author and the orchestrator.
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
> 12. Co-located mandate check: (Focused re-check of co-located
>     siblings already implicit in item 2 — duplication is intentional
>     for high-blast-radius conventions.) For each directory containing
>     modified files, enumerate sibling hygiene files such as
>     (non-exhaustive): `requirements.txt`, `package.json` and lockfiles,
>     `go.mod`/`go.sum`, version or manifest fields, `README.md`,
>     `CHANGELOG.md`, and version-pinned consumers — implied by the
>     directory's conventions or by any rule from item 2. For each
>     sibling, state whether it was updated and cite the rule requiring
>     (or permitting) the change — or justify in writing why it stays
>     unchanged. Missing co-located updates are findings; "the diff is
>     narrow" is not a defense when a convention requires a co-change.
> 13. Cross-file duplication / reuse: flag the same non-trivial block
>     duplicated across files — **≥2 workflow files** sharing a step, or
>     **≥3** copies of a code block elsewhere — and propose extraction to
>     a shared unit (a local composite action backed by a `ci/` script for
>     GitHub Actions per `ci.github-actions.md`; a shared function/module
>     for code). This is the inverse of item 9: extract genuine
>     duplication, but do not over-abstract a single use site. Duplication
>     intentionally mandated by a cited convention (cf. item 12) is exempt.
>     The diff shows only changed files, so apply this to duplication
>     introduced across the PR's own files, or to added code you recognize as
>     duplicating an existing repo pattern/convention. If the diff was split
>     (Step 1.4) you hold only part of the PR — this dimension is then carried by
>     the separate whole-PR added-lines pass described there, not by the
>     per-split reviewers.
> 14. Interpolation across the render/execute boundary (injection). Flag any
>     value spliced into a command / query / eval string that a templating
>     layer renders BEFORE the shell (or SQL engine) tokenizes it — e.g.
>     go-task `{{.Var}}` inside a `cmds:` line, an f-string/`.format()` built
>     into a `subprocess`/`os.system` argument, or string-concatenated SQL. A
>     value carrying `"`, `` ` ``, `$(…)`, `;`, or a quote can break out and
>     execute. This is a sharpened, mandatory instance of item 1: raise it
>     specifically whenever a change MOVES a value across that boundary — the
>     canonical miss is "fixed an empty-var bug by swapping shell expansion
>     `"$VAR"` for template interpolation `"{{.Var}}"`", which trades a
>     correctness footgun for an injection hole. For each such site, construct
>     the adversarial case explicitly (a value containing shell/SQL
>     metacharacters) and state whether it executes; propose the injection-safe
>     form — bind the value through the tool's env/parameter mechanism, then
>     expand with plain `"$VAR"` in the shell, never interpolate untrusted input
>     into the rendered string. **Verify the binding actually reaches the
>     consuming shell before calling it safe** — go-task scoping is non-uniform
>     (go-task 3.48): a task-level `env:` reaches `cmds:` shells but is INVISIBLE
>     to dynamic `sh:` var shells, which receive operator values from the exported
>     global `vars:`, not from a global `env:` entry (a global `env:` computed from
>     a var/input renders EMPTY there); `cmds:` shells see both global and
>     task-level `env:`. A binding placed where the consuming shell cannot see it
>     is inert (renders empty), which either reintroduces the empty-var bug or
>     silently changes the command — so an unverified binding-location claim
>     (including one asserted by a code comment) is itself a finding; confirm the
>     site with the runtime probe in item 17. When the interpolation being
>     replaced also carried a correctness guard (a `requires:` / default that
>     blocked an empty or wrong value — the intent of the bug the original fix
>     closed), the safe form MUST preserve that guard; do not trade one
>     regression for another. Blast radius (needs repo-write; reaches a job
>     holding cloud creds / `id-token: write`) informs severity but never
>     downgrades the site below a finding.
> 15. CI trigger / path-gate coverage — added/renamed files, gate-narrowing edits,
>     and bridging-construct edits. For every new
>     file the diff introduces, determine whether it falls under the repo's CI
>     path filters, workflow `paths:` / `on.push.paths` globs, affected-file
>     gates (e.g. `contains(env.AFFECTED_FILES, '<prefix>')`), or force-trigger
>     lists. A file that can influence built/tested/deployed behavior yet sits
>     OUTSIDE every gate is a finding — edits to it merge with no CI signal.
>     Symmetrically, flag any diff that NARROWS an existing gate (shrinks a
>     `paths:` glob, an `AFFECTED_FILES` prefix, or a force-trigger list) — it
>     de-gates previously-covered files with the same zero-signal outcome.
>     Pay special attention to a file added ABOVE a gated subtree (a repo-root
>     include-parent for a gated directory is the canonical escape). This also
>     covers a diff that MODIFIES the bridging construct of an already-merged,
>     out-of-gate file (a root Taskfile's `includes:` / `dir:`, a Makefile
>     `include`, a reusable-workflow `uses:`, or a wrapper that shells into a
>     gated subtree) — the same escape, even when the file is neither added,
>     renamed, nor gate-narrowing; scope strictly to edits touching the bridge
>     construct itself, and a prior "frozen/thin" invariant does not exempt it.
>     Reading CI/gate config to establish coverage is sanctioned context (per
>     the Step 2 scope note), not an out-of-scope audit; the finding targets the
>     in-diff file. Resolution is a `code-change` (extend the gate/glob) or a
>     `doc-or-todo` recording an explicit "this file stays frozen/thin"
>     invariant — never silent acceptance.
> 16. Referential integrity — a reference must not outlive its referent,
>     and no newly-added reference may point at a missing target. When the
>     diff DELETES or RENAMES a file, script, symbol, task/Make target, or
>     path, search the tree for surviving inbound references to the old
>     name — README / doc prose, `include:` / `import` / `source` / `uses:`
>     directives, `task` / `make` target callers, config keys, help text —
>     and flag every reference the deletion leaves dangling. Symmetrically,
>     for any path / file / target NEWLY REFERENCED in added lines (a README
>     pointing at `scripts/x.sh`, a doc citing a command, an `include:` of a
>     new file), verify the referent actually exists in the post-diff tree.
>     Item 3 catches *unintended* deletions or modifications and item 12
>     checks that a *changed* file's co-located siblings were updated; item
>     16 is the distinct reverse edge — verify that nothing still points at
>     what the diff intentionally removed, and that nothing the diff adds
>     points at a referent that is not there. The canonical miss: a fix
>     removes a transitional helper (e.g. a parity / validation script
>     slated for later deletion) but leaves the README sentence that points
>     at it, merging a dangling reference into the base branch. Reading
>     unchanged files to resolve a reference is sanctioned context (per the
>     Step 2 scope note), not an out-of-scope audit — the finding targets the
>     in-diff deletion or the in-diff added reference. Resolution is a
>     `code-change` (remove or re-point the dangling reference, or add the
>     missing referent) — never silent acceptance.
> 17. Tool-runtime-semantics claims — do not accept them from a static read.
>     Flag any code comment OR fix rationale that asserts runtime behavior of the
>     build / templating / container tooling that reading the diff cannot confirm:
>     go-task variable/env/template scoping (which shell sees which var — see
>     item 14), template comparison of an undefined var, shell word-splitting /
>     quoting, or docker flag semantics (e.g. valueless `-e VAR`). This is a
>     recurring miss — a parity/injection pass goes green while the *stated
>     mechanism* is wrong (the value actually arrives by a different path),
>     leaving a latent refactor trap and an inaccurate comment. The canonical
>     miss: a comment crediting a task-level `env:` with feeding a dynamic `sh:`
>     var (it does not — item 14). For each such claim emit an Experiment Request
>     with a minimal replica (a throwaway Taskfile, a one-line `docker run`) that
>     isolates it; the Orchestrator MUST dispatch it (Step 3 experimentation) and
>     reconcile the comment/fix to the observed behavior before the gate closes.
>     "Looks right" about tool internals is not verified.
> 18. PR-description ↔ diff consistency. Using the PR body supplied with the diff,
>     flag any narrative claim the diff contradicts — "preserved verbatim", "left
>     as-is", "no change to X", "mechanical migration only", "doc rot untouched" —
>     when the diff in fact changes those lines (or the converse: a claimed change
>     the diff omits). The description is the durable record (item 5 relocates
>     history INTO it), so a description that misdescribes its own diff is a
>     finding, resolved by a `doc-or-todo` correcting the description. That
>     correction MUST be applied through §"Per-Round PR Reconciliation" in
>     [pr_protocol.md](../../../docs/pr_protocol.md) — the procedure that actually
>     amends an existing PR body — before the diff is re-submitted. Capturing it
>     only as a post-gate TODO (Step 5) would leave the body unchanged, so fresh
>     reviewers would re-raise the identical finding every round until the
>     attempt limit. **This
>     dimension is the one exception to the changed-lines anchor, and it is
>     narrow:** the finding targets the PR description itself, not a code line,
>     so the converse case (a claimed change the diff omits) is in scope despite
>     having no line to point at. It does NOT license auditing intent
>     completeness — the resolution is always to correct the description, never
>     to implement the missing change; a genuinely undelivered item is the
>     author's and the Orchestrator's concern, not this gate's. If no PR
>     body was supplied to the review, state that this dimension could not be run.
> 19. Fix-the-class (not the instance) + ported-code correctness. When the diff
>     FIXES a defect, check whether the same defect class recurs, un-guarded,
>     elsewhere in the changed files — the canonical miss: a value corrected/pinned
>     in one file while the same value is duplicated across sibling files with no
>     drift guard (no lint, no single-source), so a future partial edit silently
>     re-breaks a path CI does not exercise. Flag the missing guard, not just the
>     one instance. Separately, code that is a **faithful port or a rewrite of
>     pre-existing behavior is NOT exempt** from correctness scrutiny: "preserves
>     the old behavior" / "mechanical migration" is a *parity* claim, not a
>     correctness proof — review ported or rewritten selection, matching, routing,
>     and enumeration logic for latent bugs the original also carried. Findings
>     still target changed lines (a rewritten loop, the newly-duplicated pins).
> 20. Data-dependent correctness — cross-reference the real inventory. For
>     selection / matching / enumeration / dispatch logic in the diff (substring
>     or prefix matches, glob enumeration, `=~`/`contains` tests, name-derived
>     routing), do NOT reason about the code shape in isolation — cross-reference
>     it against the actual inventory it runs over (sibling directory names,
>     shared prefixes, the set of task targets / modules / tables). Flag
>     collisions a shape-only read misses — the canonical case: an unanchored
>     substring match where two real entries share a prefix (a `test:scripts`
>     match also selecting `test:scripts:changed`), causing over-selection.
>     Reading the inventory (the sibling set, the referenced config) is
>     sanctioned context per the Step 2 scope note, not an out-of-scope audit;
>     the finding targets the in-diff matching/enumeration line.
> 21. **Test efficacy (mutation check).** For each added or changed test,
>     determine whether it would still pass if the implementation change under
>     review were reverted. A test that passes against the *old/unchanged* code
>     does not lock the *new* behavior and is a defect — flag it. Where the diff
>     adds both a fix and its test, confirm the test exercises the fixed path
>     (e.g. a case-fold fix must be tested with an input whose case actually
>     differs). Corollary — **normalization asymmetry**: flag logic that
>     matches/compares under one normalization but keys/stores under another
>     (case-insensitive match but case-sensitive key; trimmed compare but
>     untrimmed store). Where a revert-and-rerun would settle it, use the
>     Experiment Request mechanism.
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
checklist remains consistent. Item 12 (Co-located mandate check) has no
tdd-refactor analogue — it audits diff hygiene at review time, not
implementation refactoring; no `tdd-refactor.md` checklist update is
required. Item 13 (Cross-file duplication / reuse) maps to the existing
tdd-refactor "Code Reuse" constraint (Constraint 3), so it likewise needs
no separate `tdd-refactor.md` update. Items 14 (render/execute-boundary
injection), 15 (CI trigger/path-gate coverage), 16 (referential integrity),
17 (tool-runtime-semantics claims), and 18 (PR-description ↔ diff consistency)
are review-time gate dimensions with no tdd-refactor analogue — like item 12,
they are review-time diff-level audits (here: injection surface, CI topology,
reference consistency, tool-runtime claims, and PR-record accuracy), not
implementation refactoring; no `tdd-refactor.md` update is required. Items 19
(fix-the-class + ported-code correctness) and 20 (data-dependent correctness)
are likewise review-time diff-level gate dimensions with no tdd-refactor
analogue — they audit, at review time, defect-class recurrence across the
changed files and data-dependent selection/matching correctness against the
real inventory, not implementation refactoring; no `tdd-refactor.md` update is
required for either. Item 21 (test efficacy / mutation check) is the one new
dimension with a genuine tdd-refactor analogue — the TDD red-phase fail-first
invariant (a test must fail before the fix is written). No `tdd-refactor.md`
update is required: the mutation check enforces that same fail-first property at
review time (a test that still passes against the pre-change code never went
red), so the invariant is already covered on the implementation side and merely
gains a review-time guard. The optional **Intent / Background** input added to
the Step 2 prompt is likewise a review-time gate dimension with no tdd-refactor
analogue — it aids diff interpretation and sharpens items 4 and 18 at review
time, not during implementation refactoring; `tdd-refactor.md` needs no
checklist change.

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

> **Resolutions are new code — re-review them adversarially.** A `code-change`
> that resolves a finding is itself unreviewed code: on re-submission it MUST
> pass the full Step 2 prompt, not merely a confirmation that it satisfies the
> original finding. When a fix changes how a value is quoted, escaped, or
> interpolated (item 14), validating only the happy paths the fix targeted
> (e.g. "works on the env + CLI paths") is INSUFFICIENT — the resolution's
> validation MUST include the adversarial/negative case (a value with
> shell/SQL metacharacters). A fix that trades one failure mode for another is
> a recurring miss; treat every resolution as capable of introducing a new
> defect.
>
> **A concern-scoped re-review MUST still apply the FULL dimension set.** When a
> re-review is triggered by one specific concern (an injection class, a single
> finding, a rebase), it MUST re-run ALL Step 2 dimensions (1–21), not just the
> lens that motivated it. Narrowing the re-review to the motivating concern is
> how off-lens regressions slip through — a maintainability/drift finding
> (item 19) or a data-dependent correctness bug (item 20) is invisible to an
> injection- or parity-only pass. The gate's verdict is only valid against the
> full dimension set.
>
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
