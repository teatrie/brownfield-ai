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

### A hook edited without its test — or any settings change — routes to zero tests

- **Context**: `ci/test_staged.sh:72,96-102` and `ci/test_changed.sh:110,159-165` (byte-identical branches).
- **Description**: The `.claude/hooks/*` branch derives `tests/hooks/test_${basename}.py` from a dash-named hook without the `-`→`_` conversion its sibling branches perform, so `[ -f ]` never matches. Adding the conversion is insufficient: the real test files carry a `_hook` suffix and `block-container-escape.sh` / `test_block_container_hook.py` share no stem, so zero of five hooks resolve under any derivation rule. **Scope precisely**: a diff that touches a hook *and* its `tests/hooks/*.py` file still routes, because the test file matches the `tests/hooks/*` branch at line 77 and is added directly. The hole is a hook edited **alone** — exactly the shape of a logic-only change to security-boundary code — which silently runs nothing. Separately, `.claude/settings.json` appears in neither routing grep, so `test_settings_permission_baseline.py` and `test_settings_hook_registration_integrity.py` never fire on the file they exist to guard, in any diff shape. `test_changed.sh` is the pre-push gate for `auto-pr` and `ship`, so this reaches the PR path too. Observed 2026-08-03: staging a new hook plus a `settings.json` edit, with no test file yet, produced `No testable scripts found`.
- **Proposed Fix**: Route `.claude/hooks/*` and `.claude/settings*.json` to the `tests/hooks/` **directory** rather than a derived filename — matching the existing fallback idiom at `ci/test_staged.sh:148-151`. Ready-to-apply operator patch (both files) was written to `tmp/operator-patch-hook-routing/APPLY.md`; re-derive from this entry if that scratch directory is gone. Both files are `.sh`, so this is operator-applied.

---

### `docker/agent-cli/` routing asymmetry between the two gates

- **Context**: `ci/test_changed.sh:110` vs `ci/test_staged.sh:72`.
- **Description**: The `changed` grep covers `docker/agent-cli/`; the `staged` grep does not. A change under `docker/agent-cli/` is therefore gated pre-push but not at the per-step `test:staged` checkpoint, so the failure surfaces later than it should.
- **Proposed Fix**: Reconcile the two greps. Confirm which other prefixes diverge while doing so — this was found incidentally, so the audit is not exhaustive.

---

## Upstream repositories

Debt discovered inside the repositories you clone under `repos/` belongs here
too — group it under a `## <repo>` heading so harness debt and upstream debt stay
distinguishable. This section is intentionally empty in a fresh checkout.

---
