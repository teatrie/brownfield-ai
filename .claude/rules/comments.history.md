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

# Code Comment History Constraints

> **Note**: The WRONG/RIGHT code example and the `### PR-Narrative` fenced template below are deliberately omitted from the `.github/instructions/` mirror per the established repository convention for `.github/instructions/` mirrors. Do not "helpfully" sync them.

## Core Rule

This is the authoritative source for the standard that [`docs/coding_standards.md`](../../docs/coding_standards.md) §6 ("No Historical / Tracking Comments in Code") indexes.

Comments explain the code's **current-state rationale** — why it is shaped this way, for a reader who has only the current tree. They MUST NOT narrate the change history that produced it. Strip dates ("added 2026-06"), deployment status ("already applied to prod"), evolution narrative ("Wave-2 was X, now Y"), and PR / ticket / forensic cross-references. `git blame`, the PR description, and the Execution Ledger already record this; in code it rots (the "now" stops being now) and adds noise to every future read.

```python
# WRONG — change-history narrative belongs in the PR, not the migration
# Wave-2 originally set this nullable; flipped to NOT NULL after the
# 2026-05 backfill (see PR #381). Already applied to prod on 2026-06-01.
op.alter_column("events", "user_id", nullable=False)

# RIGHT — current-state rationale only
# user_id is guaranteed present downstream; NOT NULL lets the planner
# use the column for hash-join pruning.
op.alter_column("events", "user_id", nullable=False)
```

**Keep test**: would the comment still be true and useful if the introducing PR were the *only* thing in the file's history? If it only makes sense relative to a past state, it is tracking narrative — relocate it (subject to the Exception below).

## Exception — Rule-Mandated Dated Comments

A dated or historical comment that *another active rule requires* is a forward-looking drift guard, not change-history narrative — KEEP it. The canonical case is the `-- mirrors schema of <source_table> as of YYYY-MM-DD` comment mandated by [`sql.queries.md`](sql.queries.md) §Exceptions #4, whose date deliberately makes a stale schema assumption visible on drift. The Keep test yields to any rule that explicitly requires the comment.

## Relocation Is Mandatory — Never Delete Silently

This binds **every code-modifying agent**, not just the TDD agents. When you strip — or decline to write — a change-history detail that is worth preserving:

- **Subagent reporting to an orchestrator**: surface it under a `### PR-Narrative` heading at the end of your response. The orchestrator is then responsible for persisting it — to the Execution Ledger, the PR description, or both — before the subagent's context is discarded. **There is no automated harvesting step yet**: [`docs/pr_protocol.md`](../../docs/pr_protocol.md) does not currently define one, so the relocation depends on the orchestrator acting on the block it receives. Treat an unpersisted `### PR-Narrative` as lost.

  ```text
  ### PR-Narrative
  - <one bullet per history detail; plain prose, no code>
  ```

- **Operating directly (no orchestrator)**: write it straight into the PR description or the plan / ledger artifact.

Either way the history MUST land somewhere durable. Note the limit of the automated backstop: the Code Diff Review Gate ([`diff-review`](../skills/diff-review/SKILL.md) reviewer prompt item 5) enforces §6 and §7 against comments **added** in a diff, but it cannot confirm that history *deleted* in a diff was relocated — reviewers receive only the diff, not the PR description or the ledger. Relocation is therefore an author-and-orchestrator obligation with no mechanical check behind it. Treat an unpersisted `### PR-Narrative` as lost.
