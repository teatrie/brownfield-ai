# Workflow & Operational Learnings

This document captures process, workflow, and operational learnings that are not specific to code implementation. Use this file for agentic protocols, hygiene, delegation, container orchestration, and bulk import procedures.

## Hygiene & Maintenance Protocols

- **Mandatory `task repos:reset`**: Always ask the user for explicit permission before running `task repos:reset`, as it destroys uncommitted changes. Suggest options for saving changes (e.g., `git stash`, new branch, move files), and require the user to type "PROCEED WITH RESET" to confirm.
- **Temporary Artifacts**: All temporary files (scripts, logs, PR bodies) must be created in `tmp/<context>/` and deleted after use. Never create temp files in root or source directories.
- **Never run two gated `task` targets concurrently**: Every containerised target that passes the Python security gate writes the *same* fixed host-side token, `tmp/.python-gate-pass`, and each call site pairs it with an unconditional `- defer: rm -f tmp/.python-gate-pass`. Roughly fifty such sites span `lint:*`, `test:*`, `ledger:*`, `todo:*`, `findings:*`, `chromadb:*` and `tools:*` — so this is not a lint-versus-test problem, it is any two of them. Whichever container starts after the other's `defer` dies with `ERROR: Security gate artifact not found.` — which reads exactly like a genuine gate bypass. Run gated targets sequentially, and when handing work to a subagent or a background runner, say explicitly whether one is already in flight. The underlying flaw is recorded in [tech_debt.md](tech_debt.md).

## Workflow Separation

- **Development vs Operational Learnings**: Keep development/coding learnings in [learnings.md](learnings.md). Move operational/process learnings to [workflow_learnings.md](workflow_learnings.md).
