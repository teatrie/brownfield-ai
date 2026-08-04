---
description: Code Comment History Constraints
applyTo: "**/*.py,**/*.sql,**/*.sql.j2,**/*.sh,**/*.yaml,**/*.yml,**/*.tf,**/*.ts,**/*.tsx,**/*.js,**/*.ipynb"
---

# Code Comment History Constraints

## Core Rule

This file is a **mirror**. The authoritative source is `.claude/rules/comments.history.md`; when the two diverge, that file wins. Both are indexed by `docs/coding_standards.md` section 6 ("No Historical / Tracking Comments in Code").

Comments explain the code's **current-state rationale** -- why it is shaped this way, for a reader who has only the current tree. They MUST NOT narrate the change history that produced it. Strip dates ("added 2026-06"), deployment status ("already applied to prod"), evolution narrative ("Wave-2 was X, now Y"), and PR / ticket / forensic cross-references. `git blame`, the PR description, and the Execution Ledger already record this; in code it rots (the "now" stops being now) and adds noise to every future read.

For example, a migration comment that narrates which wave first set a column nullable, which backfill flipped it, which PR carried the change, and that it is already applied to production is all tracking narrative. The same line rewritten to state only why the column is NOT NULL today -- the value is guaranteed present downstream, and the constraint lets the planner prune a hash join -- carries every fact a future reader needs.

**Keep test**: would the comment still be true and useful if the introducing PR were the *only* thing in the file's history? If it only makes sense relative to a past state, it is tracking narrative -- relocate it (subject to the Exception below).

## Exception -- Rule-Mandated Dated Comments

A dated or historical comment that *another active rule requires* is a forward-looking drift guard, not change-history narrative -- KEEP it. The canonical case is the `-- mirrors schema of <source_table> as of YYYY-MM-DD` comment mandated by the SQL query standard's schema-mirroring exception (`sql.queries.md`), whose date deliberately makes a stale schema assumption visible on drift. The Keep test yields to any rule that explicitly requires the comment.

## Relocation Is Mandatory -- Never Delete Silently

This binds **every code-modifying agent**, not just the TDD agents. When you strip -- or decline to write -- a change-history detail that is worth preserving:

- **Subagent reporting to an orchestrator**: surface it at the end of your response under a level-3 Markdown heading written exactly as `### PR-Narrative`, followed by a plain-prose bullet list with one bullet per history detail and no code. The orchestrator is then responsible for persisting it — to the Execution Ledger, the PR description, or both — before your context is discarded. **There is no automated harvesting step yet**, so treat an unpersisted block as lost.
- **Operating directly (no orchestrator)**: write it straight into the PR description or the plan / ledger artifact.

Either way the history MUST land somewhere durable. Note the limit of the automated backstop: the Code Diff Review Gate enforces this standard against comments **added** in a diff, but it cannot confirm that history *deleted* in a diff was relocated — reviewers receive only the diff, not the PR description or the ledger. Relocation is an author-and-orchestrator obligation with no mechanical check behind it.
