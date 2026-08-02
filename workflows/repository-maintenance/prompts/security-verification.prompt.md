---
name: Security Verification
description: >-
  Audit Claude Code security settings across all three layers (global,
  project-shared, project-local), run verification checks against the
  sandbox and permission boundaries, and advise on gaps using the
  reference settings as a baseline.
---

# Security Verification Prompt

> **Agent Instructions:**
>
> - No required arguments. All inputs are discovered from the
>   environment.
> - Optional arguments: `<FOCUS_AREA>` to limit the audit to a specific
>   layer or concern.
> - This prompt **executes verification** — it reads settings, runs
>   checks, and produces a pass/fail report with recommendations.

## Arguments

| Argument | Required | Description | Example |
|----------|----------|-------------|---------|
| `<FOCUS_AREA>` | No | Limit audit to a specific area | `sandbox`, `permissions`, `hooks`, `docker` |

## Execution

### Phase 1 — Settings Inventory

Read all three settings layers and the reference settings. Run these
reads in parallel:

1. **Global settings**: `~/.claude/settings.json`
2. **Project shared settings**: `.claude/settings.json`
3. **Project local settings**: `.claude/settings.local.json`
4. **Reference — global**: `docs/reference-settings/global-settings.reference.json`
5. **Reference — project local**: `docs/reference-settings/project-settings-local.reference.json`
6. **Reference — README**: `docs/reference-settings/README.md`

If any of the three active settings files (1-3) do not exist, note the
absence as a finding — a missing layer means its protections are not
applied.

### Phase 2 — Static Analysis

Compare the active settings against the reference settings. For each
category below, identify **present**, **missing**, and **divergent**
entries. Do not flag intentional project-specific additions (e.g., extra
WebFetch domains) as gaps — only flag missing security-critical entries.

#### 2.1 — Three-Tier Permission Model

Claude Code permissions have three effective tiers:

| Tier | In allow? | In deny? | Behavior |
|------|-----------|----------|----------|
| **Allow** | Yes | No | Auto-approved, no prompt |
| **Deny** | — | Yes | Blocked, agent cannot proceed |
| **Ask** | No | No | User prompted for approval |

Verify that `settings.local.json` uses **scoped allows** (per-directory)
rather than blanket `Edit(**)` / `Write(**)`. Blanket allows defeat the
ask tier entirely — every path not denied becomes auto-approved,
eliminating the human-in-the-loop for infrastructure changes.

Check the following tier assignments:

**Deny tier** (must be present across merged settings):

| Category | Expected deny patterns | Layer |
|----------|----------------------|-------|
| Self-modification | `Edit/Write(.claude/settings.json)` | Project shared |
| Self-modification | `Edit/Write(.claude/settings.local.json)` | Project local |
| Hook protection | `Edit/Write(.claude/hooks/**)` | Project shared |
| Shell scripts | `Edit/Write(**/*.sh)` | Project shared |
| Docker security | `Edit/Write(docker/**/Dockerfile)`, `Edit/Write(docker/**/*.sh)` | Project shared |
| Compose file | `Edit/Write(docker-compose.yml)` | Project shared |
| Agent credentials | `Read/Edit/Write(~/.claude/sessions/**)` | Global |
| Agent credentials | `Read/Edit/Write(~/.claude/history.jsonl)` | Global |
| Cross-tool credentials | `Read(~/.codex/auth.json)`, `Read(~/.gemini/oauth_creds.json)` | Global |
| AWS credentials | filesystem denyList `**/tmp/.aws-credentials.env` | Project local |

**Ask tier** (must NOT appear in allow lists):

| Path | Why |
|------|-----|
| `Taskfile.yml`, `taskfiles/*` | Task runner definitions — agent's own execution boundary |
| `CLAUDE.md`, `AGENT.md`, `GEMINI.md` | Protocol docs — changes alter agent behavior |
| `.github/**` | CI workflows, CODEOWNERS |
| `tsconfig.json` | Build configuration |
| `.claude/agents/**` | Agent definitions — changes alter review gates and delegation behavior |

If any of these paths appear in an allow list, flag it — the agent can
silently modify its own execution environment or protocol docs without
human review.

**Allow tier** (should be scoped, not blanket):

Verify that allow entries use directory-scoped patterns (e.g.,
`Edit(src/**)`, `Write(tests/**)`) rather than `Edit(**)` / `Write(**)`.
The reference settings list the recommended scoped allows.

#### 2.2 — Sandbox Configuration

Verify the sandbox block in global settings includes:

- `enabled: true`
- `enforceReadOnlyRoot: true`
- `preventSelfModification: true`
- `enableWeakerNetworkIsolation: true` (required for Docker socket
  access)
- `network.allowUnixSockets` includes Docker socket paths
- `network.allowedDomains` is limited to localhost/loopback
- `filesystem.denyRead` covers `~/.claude`, `~/.codex`, `~/.gemini`
- `filesystem.allowRead` carves out only necessary paths (projects,
  chroma_db, debug, tool configs)
- `filesystem.allowWrite` includes `~/.claude/projects` and
  `~/.docker/buildx/` (required for Docker builds)
- `restrictedCommands` includes destructive commands (`rm -rf /`,
  `sudo *`, `mkfs *`, etc.)

#### 2.3 — PreToolUse Hooks

Verify that `.claude/settings.json` defines PreToolUse hooks on the
`Bash` matcher. For each hook command referenced, verify the script file
exists on disk.

#### 2.4 — Bash AllowList

Verify the bash allowlist across layers:

- **Global**: should include safe read-only commands (`ls`, `tree`,
  `wc`, `mkdir`), git subcommands, gh CLI subcommands, docker
  read-only commands (`info`, `ps`, `compose`).
- **Project local**: should include the project's task runner
  (`task *`) if the project uses Taskfile.

Flag any allowlist entry that grants write access to external systems
(e.g., `gh pr merge`, `terraform apply`, `kubectl delete`) without a
corresponding hook guard.

#### 2.5 — Filesystem DenyList

Verify the filesystem denyList covers:

- Version control internals: `**/.git/**`
- SSH keys: `~/.ssh/**`
- Environment files: `**/.env`, `**/.env.*`
- OS artifacts: `**/.DS_Store`
- Dependency caches: `**/node_modules/**`
- Infrastructure state: `**/.terraform/**`, `**/*.tfstate`,
  `**/*.tfstate.backup`

### Phase 3 — Runtime Verification Checks

Run the following checks to validate that settings are enforced at
runtime. Execute independent checks in parallel where possible.

#### 3.1 — Docker Build Chain (sandbox write boundary)

```bash
task lint
```

This exercises the Docker build chain, which writes to
`~/.docker/buildx/`. If this fails with a sandbox write error, the
`sandbox.filesystem.allowWrite` entry for `~/.docker/buildx/` is
missing.

#### 3.2 — Containerized Test Execution

```bash
task test:brownfield_ai
```

Validates that Docker socket access and container execution work
end-to-end through the sandbox.

#### 3.3 — Docker Socket Access

```bash
docker compose ps
```

Validates that the Unix socket allowlist in the sandbox permits Docker
daemon communication.

#### 3.4 — Bash AllowList Enforcement

```bash
git status
```

Validates that the global bash allowlist permits standard git operations.

#### 3.5 — Dedicated Tool Access

Use the `Read` tool to read `CLAUDE.md`. This validates that dedicated
tools (Read, Edit, Grep, Glob) operate outside the bash allowlist and
are governed by permissions and filesystem rules instead.

#### 3.6 — Deny Rule Enforcement

Attempt to `Edit` `.claude/settings.local.json` (e.g., replace `{}`
with `{"test": true}`). This MUST be denied by the project-local
self-protection deny rule. If the edit succeeds, the deny rule is
missing or misconfigured — **immediately revert the file** by
restoring its original content with the Edit tool, then report the
deny rule as MISSING.

#### 3.7 — Ask Tier Enforcement

Test each of the following ask-tier files by attempting a no-op `Edit`
(e.g., add a trailing newline or a comment, then revert). For each
file, record whether the edit:

- **Prompted the user** (PASS — ask tier working)
- **Auto-approved silently** (FAIL — file is covered by a blanket
  allow like `Edit(**)`)
- **Was denied** (MISCONFIGURED — file landed in the deny tier
  instead of the ask tier)

Files to test:

| File | Expected |
|------|----------|
| `Taskfile.yml` | User prompted |
| `CLAUDE.md` | User prompted |
| `.github/copilot-instructions.md` | User prompted |

If any file auto-approves, report it as a gap — the ask tier is not
functioning for that path. The most common root cause is a blanket
`Edit(**)` or `Write(**)` in the project-local allow list.

**Important:** After each test, revert the edit so the verification
leaves no residual changes. If the user denies the prompt, that
counts as PASS (the prompt fired, which is the expected behavior).

#### 3.8 — Hook Execution

Run a command that should be intercepted by a PreToolUse hook (e.g.,
`python3 --version` for a Python execution blocker, or `terraform init`
for a Terraform escape blocker). Verify the hook fires and blocks the
command. Skip this check if no hooks are configured.

#### 3.9 — Cross-Family Reviewer Preflight (Optional)

Run the three bridge reviewer preflight checks in parallel:

```bash
task agent:preflight:gemini
task agent:preflight:codex
task agent:preflight:copilot
```

Record CLI availability, authentication status, and auth mode for
each reviewer. Present results as:

| Reviewer | CLI | API key | Mode | Status |
|----------|-----|---------|------|--------|
| Gemini | installed/missing | set/unset | local/container/none | AVAILABLE/UNAVAILABLE |
| Codex | installed/missing | set/unset | local/container/none | AVAILABLE/UNAVAILABLE |
| Copilot | installed/missing | set/unset | container/none | AVAILABLE/UNAVAILABLE |

Status mapping:

- **AVAILABLE**: preflight returned `local` or `container`. Auth is
  not verified by preflight — failures surface at execution time.
- **UNAVAILABLE**: preflight returned `none` (no local CLI and no
  API key).

This check is informational — reviewer unavailability does not
constitute a security gap but degrades the diff-review gate from
3-of-3 to 2-of-3 or fewer cross-family reviewers.

#### 3.10 — Cross-Family Reviewer Smoke Test (Optional, CLI-dependent)

Preflight only confirms that the CLI binary responds and that auth
credentials exist. It does **not** exercise the review path
end-to-end. Two historically-observed failure modes pass preflight
but break at invocation:

- **Sandbox write denials** for the CLI's cache/session directory
  (`~/.gemini/tmp/`, `~/.codex/sessions/`). The CLI hangs with
  empty stderr until the script timeout fires.
- **Nested-sandbox deadlock** on macOS: the CLI tries to apply
  its own `sandbox-exec` profile inside Claude Code's outer
  sandbox and fails with `sandbox_apply: Operation not permitted`,
  returning an empty verdict.

Both require live invocation to catch. This phase runs a short
review against a synthetic diff and validates output shape.

**Skip rule**: For each reviewer whose 3.9 status is `UNAVAILABLE`,
skip its smoke test and record `SKIPPED (CLI unavailable)` in the
report. Do **not** skip on `DEGRADED` — downgraded auth tiers
still exercise the invocation path.

**Procedure (per AVAILABLE reviewer)**:

1. Construct a synthetic diff using the Write tool (not bash
   redirection — the redirect-block hook denies it):
   - `tmp/smoke-diff-r0.patch`: a 1-line `README.md` change like
     `+<!-- security-verification smoke test -->`.
2. Construct a minimal review prompt:
   - `tmp/{reviewer}-review-prompt-r0.txt`: brief instruction
     referencing `tmp/smoke-diff-r0.patch`, no real review
     criteria required — the goal is to confirm the CLI
     completes, not to evaluate the diff.
3. Invoke the reviewer with a short timeout:

   ```bash
   task agent:review:gemini:local -- ROUND=0 GEMINI_TIMEOUT=120 REVIEW_TYPE=spec-req-verification DIFF_FILE=tmp/<epic_id>-spec.md
   task agent:review:codex:local  -- ROUND=0 REVIEW_TYPE=spec-req-verification DIFF_FILE=tmp/<epic_id>-spec.md
   ```

4. Validate outputs:

   | Artifact | Check |
   |----------|-------|
   | `tmp/{reviewer}-review-output-0.md` | File exists, size > 0 |
   | `tmp/{reviewer}-exit.json` | Valid JSON; `signal` is `OK` or `APPROVED`; not `*_ERROR` or `*_FALLBACK` |
   | `tmp/{reviewer}-review-err.txt` | Stderr is empty or benign (no `sandbox_apply`, `Operation not permitted`, or `timeout`) |

5. Record results:

   | Reviewer | Output size | Exit signal | Latency | Status |
   |----------|-------------|-------------|---------|--------|
   | Gemini | ... bytes | ... | ...s | PASS/FAIL/SKIPPED |
   | Codex | ... bytes | ... | ...s | PASS/FAIL/SKIPPED |

**Failure triage**:

- Empty output + empty stderr → suspect sandbox `denyWrite` on the
  CLI's session/cache directory. Check `Edit(~/.gemini/**)` or
  `Edit(~/.codex/**)` deny entries (both `Edit(...)` and
  `Write(...)` deny rules merge into sandbox `denyWrite`).
- `sandbox_apply: Operation not permitted` in stderr → nested
  sandbox deadlock. Verify the reviewer script passes a
  sandbox-disable flag (Codex: `--sandbox danger-full-access`) or
  set `sandbox.enableWeakerNestedSandbox: true` at the layer the
  CLI can reach.
- `token_missing` / auth error → credentials expired or
  `allowRead` is missing the OAuth file path.

**Cleanup**: Remove `tmp/smoke-diff-r0.patch`,
`tmp/{reviewer}-review-prompt-r0.txt`,
`tmp/{reviewer}-review-output-0.md`, `tmp/{reviewer}-review-err.txt`,
and `tmp/{reviewer}-exit.json` after recording results, so the
smoke-test run leaves no residual artifacts.

This phase remains informational: a failed smoke test does not
block the security audit, but it does flag an operability gap
that preflight cannot surface.

### Phase 4 — Report

Produce a report with the following structure:

#### Summary Table

| # | Check | Category | Result | Notes |
|---|-------|----------|--------|-------|
| 1 | Docker build chain | Sandbox write | PASS/FAIL | ... |
| 2 | Containerized tests | Docker socket | PASS/FAIL | ... |
| ... | ... | ... | ... | ... |

#### Gap Analysis

For each gap found in Phase 2, produce a recommendation:

```text
GAP: <what is missing>
RISK: <what could happen without this protection>
FIX: <exact JSON path and value to add>
LAYER: <which settings file to modify>
```

#### Recommended Actions

List concrete steps to close each gap, ordered by risk severity
(credential exposure > self-modification > write boundary > convenience).

If no gaps are found, state: "All settings match reference baselines.
No changes recommended."

## Reference Settings

The reference settings used as baselines for this audit are maintained
at:

- `docs/reference-settings/global-settings.reference.json` — global
  (user-level) sandbox, permissions, and bash allowlist
- `docs/reference-settings/project-settings-local.reference.json` —
  project-local permissions and task runner access
- `docs/reference-settings/README.md` — settings architecture and
  layer merge semantics

These files are suggestive, not prescriptive. Project-specific additions
(extra WebFetch domains, additional plugins, custom hooks) are expected
and should not be flagged as divergences.
