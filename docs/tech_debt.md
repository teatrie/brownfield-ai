# Technical Debt & TODOs

This document tracks technical debt, refactoring opportunities, and known shortcuts taken by agents or developers. It serves as a backlog for future improvements to ensure code quality and maintainability.

Agents MUST proactively document any codebase flaws, confusing conventions, or required refactorings they encounter during their work in this file.

## Guidelines

- **When to add**:
  - You encounter bad quality code, confusing legacy patterns, or anti-patterns requiring refactoring.
  - You took a shortcut to get a task to "Green" (working) but couldn't "Refactor" to an optimal state.
  - You identify a pattern that deviates from established best practices but fixing it is out of scope for the current task.
  - An established pattern in the codebase forced you to write sub-optimal code to maintain consistency.
- **Where NOT to add**:
  - Do not add codebase flaws or refactoring ideas to [docs/learnings.md](learnings.md). That file is for agent execution issues and tooling environment gotchas.
- **Format**:
  - **Item**: Brief title.
  - **Context**: Where is it? (Repo, file, service).
  - **Description**: What is the issue? Why is it debt?
  - **Proposed Fix**: How should it be resolved?

## Backlog

### [Example] Hardcoded ARN in IAM Policy

- **Context**: `repos/infra`, `writer-labels` service.
- **Description**: IAM policy uses a hardcoded ARN string instead of a dynamic reference.
- **Proposed Fix**: Use `data.aws_secretsmanager_secret.name.arn`.

---

### Duplicated CASE sort block in `list_epics` + empty-string sentinel

- **Context**: `workflows/agent-memory/skills/execution-ledger/scripts/chromadb_ledger.py`, `list_epics()`.
- **Description**: The status-priority CASE expression is duplicated verbatim in both the filtered and unfiltered branches. The `status_filter` parameter uses an empty-string sentinel (`""`) instead of `Optional[str] = None`, which is an implicit convention that is easy to misuse. Tracked as diff-review findings S-003, S-004, S-005.
- **Proposed Fix**: Extract the CASE SQL to a module-level constant; change the parameter signature to `status_filter: Optional[str] = None` and update all callers. Ticket: ACME-2931.

---

## Upstream repositories

Debt discovered inside the repositories you clone under `repos/` belongs here
too — group it under a `## <repo>` heading so harness debt and upstream debt stay
distinguishable. This section is intentionally empty in a fresh checkout.

---
