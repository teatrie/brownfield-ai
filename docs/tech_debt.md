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

### `docker/agent-cli/` routing asymmetry between the two gates

- **Context**: `ci/test_changed.sh:110` vs `ci/test_staged.sh:72`.
- **Description**: The `changed` grep covers `docker/agent-cli/`; the `staged` grep does not. A change under `docker/agent-cli/` is therefore gated pre-push but not at the per-step `test:staged` checkpoint, so the failure surfaces later than it should. The current behaviour is pinned on both sides — `TestStagedRouter::test_agent_cli_paths_are_not_routed` and `TestChangedRouter::test_agent_cli_path_routes_to_prefixed_test` — so reconciling the greps means updating those two tests deliberately rather than discovering the divergence again.
- **Proposed Fix**: Reconcile the two greps. Confirm which other prefixes diverge while doing so — this was found incidentally, so the audit is not exhaustive.

---

### CI `lint` job rebuilds the infra-lint image uncached, with no retry

- **Context**: `.github/workflows/ci.yml` (`lint` job, `Build Infra Lint Image` step) → `taskfiles/builders.yml:infra-lint` → `docker/builders/Dockerfile.infra-lint`.
- **Description**: The build is a bare `docker compose --profile tools build infra-lint` — no `--cache-from`, no registry or GHA layer cache, no retry wrapper. Every CI run starts from a cold runner and rebuilds all twelve BuildKit steps, each reaching a different remote: Docker Hub (`python:3.12-slim`), Debian apt, nodesource, PyPI, npm, and three archive downloads — two from GitHub releases (kubeconform, hadolint) and one from the Helm CDN (`get.helm.sh`). Any one of those timing out fails the `lint` job with a red check that is indistinguishable from a genuine lint violation, so a transient network fault reads as a code defect until someone opens the log. Diagnosing exactly that on PR #14 cost a full cycle.
- **Proposed Fix**: Cache and retry are separable, and either alone reduces the failure rate. Cache: switch the step to `docker/build-push-action` with `cache-from: type=gha` / `cache-to: type=gha,mode=max`, or publish the image to GHCR on `main` and pull it as `--cache-from`. Retry: wrap the build in a bounded retry so a single registry timeout does not fail the job. Whichever lands, the job should distinguish infrastructure failure from lint failure in its exit surface — a build-stage failure is not a lint result.

---

### Python security-gate token is a fixed path, so concurrent gated tasks race

- **Context**: `docker/shared/python-security-gate.sh` (writes `$WORKSPACE_ROOT/tmp/.python-gate-pass` at two sites), `docker/shared/python-gate-entrypoint.sh` (`GATE_FILE="/tmp/.python-gate-pass"`), and the ~50 gated call sites across `taskfiles/ledger.yml`, `lint.yml`, `findings.yml`, `todo.yml`, `test.yml`, `chromadb.yml` and `tools.yml`.
- **Description**: The token path is a single hardcoded constant with no per-invocation component, and every call site pairs the gate invocation with an unconditional `- defer: rm -f tmp/.python-gate-pass`. Two gated targets in flight at once — the ordinary case when one agent runs `task lint:staged` while another runs `task test:staged`, or when a `task todo:list` lands mid-suite — therefore share one token and each deletes it on completion. The container that starts after the other's `defer` exits 1 with `ERROR: Security gate artifact not found.` That message is indistinguishable from a genuine attempt to bypass the gate, which is the worst available confusion for a security control: the operator learns to treat a real bypass signal as a benign race. The cleanup being duplicated verbatim at every site rather than owned by the gate itself is what makes the invariant unenforceable — a new target can omit the `defer` and nothing catches it.
- **Proposed Fix**: Give the token a per-invocation identity (e.g. a `mktemp` path threaded through both the `-v` mount and an env var the entrypoint reads) so concurrent runs cannot collide, and move the cleanup into a single owner instead of repeating `defer` at each site. If the fixed path must stay, at minimum distinguish "token absent" from "token deleted by a concurrent run" in the entrypoint's exit surface. Until this lands the constraint is operational only, recorded in [workflow_learnings.md](workflow_learnings.md).

---

## Upstream repositories

Debt discovered inside the repositories you clone under `repos/` belongs here
too — group it under a `## <repo>` heading so harness debt and upstream debt stay
distinguishable. This section is intentionally empty in a fresh checkout.

---
