---
description: GitHub Actions CI conventions — shared composite actions, OIDC/permissions, job gating, changed-file detection
applyTo: "**/.github/workflows/*.yml,**/.github/workflows/*.yaml,**/.github/actions/**,**/ci/*.sh"
---

# GitHub Actions CI Conventions

Conventions for authoring GitHub Actions workflows and their supporting scripts, in this repo and in cloned upstream repos (`repos/<repo>/.github/`). These encode patterns validated in production.

## 1. No duplicated steps across workflows (MANDATORY)

Do not copy the same non-trivial step (or `run:` script) into more than one workflow file. When a step is needed by two or more workflows, extract it into a local composite action under `.github/actions/<name>/action.yml` (composite `runs.using`) and have each workflow call it via a single `uses: ./.github/actions/<name>` step. This is a deliberate exception to the general rule against unprompted new patterns — a shared composite action is the requested pattern for repeated workflow steps. The threshold is lower than the general rule-of-three because workflow boilerplate accretes and drifts silently. This is the inverse of premature abstraction: extract genuine duplication across files; do not wrap a single use site.

When the shared step is more than a couple of lines of bash, put the logic in a script under `ci/` (matching the existing `ci/*.sh` convention) and have the composite action invoke it as `bash "$GITHUB_WORKSPACE/ci/<name>.sh"` — the absolute workspace anchor is cwd-independent and the `bash <path>` form makes the executable bit irrelevant. Keep `set -euo pipefail` inside the script. `actions/checkout` MUST run before any local `uses: ./...` step, because the runner resolves local actions and `ci/` scripts from the checked-out workspace.

## 2. Exporting values from a composite action

A composite action step that appends `KEY=value` to the `GITHUB_ENV` file makes `KEY` available to subsequent steps of the calling job, crossing the composite-action boundary. Use this to share computed values so downstream job steps can gate on a `contains(env.KEY, ...)` condition without changes. For a single discrete value, an action output mapped from a step output is the alternative; pick the env file when multiple later steps consume the value as an env var. Multi-line values corrupt the env file via the append form — collapse to a single line (translate newlines to spaces) or use the heredoc append form.

## 3. Job gating: always-run job + internal step gate

Prefer an always-run job with internal `if:` step gates over native `paths:` triggers. A workflow skipped by a `paths:` trigger filter never posts its required checks, blocking merges (a job-level `if:` skip instead posts a `skipped` conclusion); an always-run job whose steps short-circuit via `if:` always reports success and never wedges branch protection.

## 4. OIDC, secrets, and permissions

Map the values a workflow needs at the workflow-level `env:` block (for example the AWS role and region), because a job that assumes an AWS role via OIDC needs them present. Scope secrets to their consumer: the `secrets` context is available in workflow-level `env:`, so mapping one there parses, but the value is then readable by every job and step including third-party actions — map a PAT or other long-lived token at the job- or step-level `env:` that consumes it, and reserve workflow-level `env:` for non-sensitive identifiers such as a role ARN or a region.

Declaring any `permissions:` key resets all others to `none`: a workflow using OIDC needs both `id-token: write` and `contents: read` (the latter for checkout); a lint-only job that touches no cloud needs only `contents: read`.

## 5. Computing a changed-file set

Fetch the base ref explicitly before diffing so the fallback resolves on new-branch / zero-SHA pushes, using a `--no-tags` destination refspec (`<base>:refs/remotes/origin/<base>`) that updates the remote-tracking ref (a bare fetch of the branch only updates `FETCH_HEAD`). Guard the all-zeros `github.event.before` SHA and fall back to a `origin/<base>...HEAD` diff. This mirrors the repo's `ci/lint_changed.sh` / `ci/test_changed.sh`.

## Enforcement

The Code Diff Review Gate checks cross-file duplication as a review criterion. New CI authored without these conventions should be flagged and revised before merge.
