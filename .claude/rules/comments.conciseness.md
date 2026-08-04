---
paths:
  - "**/*.py"
  - "**/*.sql"
  - "**/*.sql.j2"
  - "**/*.sh"
  - "**/*.yaml"
  - "**/*.yml"
  - "**/*.tf"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.ipynb"
---

# Code Comment & Docstring Conciseness Constraints

> **Note**: The WRONG/RIGHT code examples below are deliberately omitted from the `.github/instructions/` mirror per the established repository convention for `.github/instructions/` mirrors (code/example blocks are described inline there instead). Do not "helpfully" sync them.

## Core Rule

This is the authoritative source for the standard that [`docs/coding_standards.md`](../../docs/coding_standards.md) §7 ("Minimal, Reader-Directed Comments & Docstrings") indexes. It is the *audience/redundancy* companion to the *temporal* rule in [`comments.history.md`](comments.history.md) (§6): §6 forbids narrating **when** the code changed; this rule forbids explaining **what a competent reader already knows**.

Comment only the non-obvious rationale that is specific to *this* code and cannot be recovered by reading the code itself, its base class / type signature, or a linked guide. Write for a competent engineer reading the current tree — **never** as scaffolding that narrates the agent's own reasoning or restates a generic contract "for completeness". Prefer deleting or condensing over explaining. Verbosity is not free: every redundant line dilutes the signal of the one comment that actually mattered.

The three failure modes this rule targets:

1. **Generic / non-local** — restates a base-class contract, a framework convention, or a repo-guide rule that is identical for every sibling and carries nothing specific to this file. If it would read the same pasted into any other subclass, delete it (the base class or the guide is its home).
2. **Agent-directed** — reads as scaffolding that narrates the author's or agent's decision process ("we cast this because the task asks for…", step-by-step reasoning) rather than the code's current-state rationale for a future human reader.
3. **Speculative / over-explained** — length spent hedging about code paths that are not taken, alternatives that were rejected, or coercions that cannot occur given the declared types. State what the code does and why; do not litigate what it does not do.

**Delete test** (the companion to §6's Keep test):

- (a) Would a competent engineer already know this from the code, its base class / type signature, or a linked guide? → **delete**.
- (b) Does it explain the *author's / agent's decision process* rather than the code's current-state rationale? → **delete or rewrite** as terse rationale.
- (c) Does it speculate about paths the code does not take? → **delete**.

**Keep** only what is locally specific and non-obvious — the comment that stops a future reader from "simplifying" a load-bearing line. Canonical keeper: an inert-looking `min_size = 0` that silently disables a `final_size > min_size` empty-snapshot assertion. Nothing in the assignment reveals that; the comment earns its line.

```python
# WRONG — generic base-class contract; identical for every sibling task
# `table` is the fully-qualified catalog table this task reads from. The
# base class uses it to build the object-store path and to construct the
# logging context for the run, per the framework.
table = "unprocessed_events_snapshot"

# RIGHT — the contract lives on the base class / guide; the value stands alone
table = "unprocessed_events_snapshot"
```

```python
# WRONG — agent-directed + speculative; narrates reasoning and a non-taken path
# We add validate_nulls here because CDC can null-corrupt timestamp
# columns, and we cast reported_count to IntegerType because if it stayed a
# long it might overflow or the query engine might coerce the string form, so
# to be safe we handle both the string case and the long case defensively.
df = validate_nulls(df, ts_list=["created_ts"])
df = df.withColumn("reported_count", F.col("reported_count").cast(T.IntegerType()))

# RIGHT — current-state rationale, locally specific, no speculation
# CDC can emit null timestamps; guard before downstream use.
df = validate_nulls(df, ts_list=["created_ts"])
# Source emits INT UNSIGNED as long; output contract is integer.
df = df.withColumn("reported_count", F.col("reported_count").cast(T.IntegerType()))
```

## Docstrings

Docstrings state the **contract** (params, returns, raises) plus any non-obvious behaviour — nothing more:

- Do not restate the type signature in prose (`param x: an int` above `x: int` is noise).
- Do not speculate about inputs the signature already excludes or paths the body does not take.
- Legacy-file upgrades under the Boy Scout Rule ([`lang.python.md`](lang.python.md)) add the *minimal* PEP-257 contract, not a narrative.
- The presence requirements in [`docs/coding_standards.md`](../../docs/coding_standards.md) §"Documentation Standards" (modules/classes/public functions always; private helpers only when complex; tests omitted) still govern *whether* a docstring exists; this rule governs *how terse* it is when it does.

## Relationship to §6

§6 ([`comments.history.md`](comments.history.md)) requires relocating stripped **history** to a durable home (PR description / ledger) via the `### PR-Narrative` mechanism. This rule differs: verbosity stripped under the Delete test is **redundant by definition** — it is recoverable from the code, base class, or guide — so it needs no relocation. Relocate only if a stripped line contained genuinely non-obvious rationale, in which case the fix is to *condense* it in place, not delete it.

## Enforcement

Not lint-detectable — "too generic / for-the-agent / speculative" is a human-reviewer judgment, and a linter would produce noise. The Code Diff Review Gate ([`diff-review`](../skills/diff-review/SKILL.md) reviewer prompt item 5) is the backstop.
