---
paths:
  - "**/.github/workflows/*.yml"
  - "**/.github/workflows/*.yaml"
  - "**/.github/actions/**"
  - "**/ci/*.sh"
---

# GitHub Actions CI Conventions

Conventions for authoring GitHub Actions workflows and their supporting
scripts, in this repo and in cloned upstream repos (`repos/<repo>/.github/`).
These encode patterns validated in production; follow them when adding or
modifying CI so reviewers and implementers share one source of truth.

> **Note**: The fenced YAML/bash examples below are deliberately omitted from
> the `.github/instructions/` mirror per the established repository convention
> for those mirrors (code/example blocks are described inline there instead).
> Do not "helpfully" sync them.

## 1. No duplicated steps across workflows (MANDATORY)

Do **not** copy the same non-trivial step (or `run:` script) into more than
one workflow file. The moment a step is needed by **≥2 workflows**, extract it
into a **local composite action** under `.github/actions/<name>/action.yml`
(`runs.using: composite`) and have each workflow call it via a single
`- uses: ./.github/actions/<name>` step.

This is a deliberate exception to the general repository rule against
introducing patterns unprompted ([CLAUDE.md](../../CLAUDE.md) §8 "Code
Consistency"): a shared composite action **is** the requested pattern for
repeated workflow steps, so implementers should reach for it up front rather
than duplicate. The threshold is lower than the general rule-of-three because
workflow files accrete copy-pasted boilerplate quickly and drift silently.

This is the inverse of premature abstraction: extract genuine duplication
across files; do **not** wrap a single use site in an action.

### Where shared bash lives

When the shared step is more than a couple of lines of bash, put the logic in a
script under `ci/` (matching the repo's existing `ci/*.sh` convention, e.g.
`ci/lint_changed.sh`) and have the composite action invoke it:

```yaml
# .github/actions/<name>/action.yml
runs:
  using: composite
  steps:
    - shell: bash
      env:
        SOME_INPUT: ${{ github.event_name }}
      run: bash "$GITHUB_WORKSPACE/ci/<name>.sh"
```

Invoke the script as `bash "$GITHUB_WORKSPACE/ci/<name>.sh"` — the absolute
`$GITHUB_WORKSPACE` anchor is cwd-independent, and the `bash <path>` form means
the script's executable bit is irrelevant (committed `100644` is fine). Keep
`set -euo pipefail` inside the script. **NOTE:** `actions/checkout` MUST run
before any local `uses: ./...` step — the runner resolves local actions and
`ci/` scripts from the checked-out workspace.

## 2. Exporting values from a composite action

A composite action step that appends `KEY=value` to `$GITHUB_ENV` makes `KEY`
available to **subsequent steps of the calling job** (it crosses the
composite-action boundary). Use this to share computed values (e.g. an
affected-files set) so downstream job steps can gate on
`if: contains(env.KEY, '...')` without changes. For a single discrete return
value, an action `outputs:` mapped from a step output is the alternative; pick
`$GITHUB_ENV` when multiple later steps consume the value as an env var.

Multi-line values corrupt `$GITHUB_ENV` via the `KEY=value` append form —
collapse to a single line (`tr '\n' ' '`) or use the `KEY<<EOF` heredoc form.

## 3. Job gating: always-run job + internal step gate

Prefer an **always-run job with an internal `if:` step gate** over native
`paths:` triggers. A workflow skipped by a `paths:` trigger filter never posts
its checks at all, which blocks a merge when one is a required status check (a
*job*-level `if:` skip, by contrast, posts a `skipped` conclusion).
An always-run job whose steps short-circuit via `if:` always reports `success`,
so it never wedges branch protection.

## 4. OIDC, secrets, and permissions

- Map the secrets a workflow needs at the **workflow-level `env:`** block
  (e.g. `AWS_ROLE`, `AWS_REGION`, and any PAT the shared setup action
  consumes). A job that assumes an AWS role via OIDC needs these present.
- Declaring **any** `permissions:` key resets all others to `none`. A workflow
  using OIDC needs **both** `id-token: write` **and** `contents: read`
  (the latter for `actions/checkout`). A lint-only job that touches no cloud
  needs only `contents: read`.

## 5. Computing a changed-file set

When a job must diff the changed files, fetch the base ref explicitly before
diffing so the fallback resolves on new-branch / zero-SHA pushes:
`git fetch --no-tags origin <base>:refs/remotes/origin/<base>` (a bare
`git fetch origin <base>` only updates `FETCH_HEAD`, not the remote-tracking
ref the fallback diff reads). Guard the all-zeros `github.event.before` SHA and
fall back to `origin/<base>...HEAD`. This mirrors the repo's
`ci/lint_changed.sh` / `ci/test_changed.sh`.

## Enforcement

The Code Diff Review Gate ([diff-review](../skills/diff-review/SKILL.md))
checks cross-file duplication as a review criterion. New CI authored without
these conventions should be flagged and revised before merge.
