# Container Security Model

## Threat Model

The agent is the adversary. Human operators are trusted and may bypass gates
in emergencies. The 3-layer model enforces defense-in-depth: any single layer
can be bypassed by a determined attacker with host access, but the combination
raises the bar for accidental or automated misuse.

The primary concern is an agent (Claude Code) running arbitrary code in
production containers, exfiltrating credentials, or escaping to the host
filesystem via Docker bind mounts.

## Architecture: Four Layers (Layer 0 + Three Enforcement Layers)

```text
Claude Code (Bash tool call)
        |
        v
[Layer 0] Permission Allowlist    <- fail-closed-by-environment
        |  .claude/settings.json  permissions.allow / deny
        |  Denies a call without reaching any hook
        |
        v
[Layer 1] PreToolUse Hook         <- primary enforcement boundary
        |  block-container-escape.sh
        |  block-terraform-escape.sh
        |  exit 2 = deny, exit 0 = allow
        |
        v
[Layer 2] Host-Side Gate Script   <- defense-in-depth
        |  docker/shared/python-security-gate.sh  (Python containers)
        |  tf-safe.sh via task              (Terraform container)
        |  Writes gate artifact to tmp/
        |
        v
[Layer 3] Container Entrypoint    <- defense-in-depth
           docker/shared/python-gate-entrypoint.sh  (Python containers)
           sudo + hidden binary (_tf_exec_internal)  (Terraform container)
```

Layer 1 is the primary enforcement boundary. Layer 0 narrows the
matcher surface so disallowed calls never reach a hook. Layers 2 and 3
are defense-in-depth.

## Layer 0: Permission Allowlist (fail-closed-by-environment)

`.claude/settings.json` `permissions.allow` and `permissions.deny` form
the outermost gate — Claude Code consults them before invoking any
PreToolUse hook. A denied match short-circuits the decision and no hook
runs; an unmatched match in headless mode (`CI=true`) fails closed
(the call is denied without prompting); an unmatched match in
interactive mode surfaces an Ask-tier prompt that the human operator
approves or rejects.

**Fail-closed-by-environment** is the design invariant: narrowing the
allowlist on the production baseline relies on the interactive operator
to approve the occasional legitimate case that falls through. Headless
runs cannot prompt, so any headless invocation that falls outside the
allowlist is a hard denial — this is intentional. Agents MUST never
attempt to broaden the allowlist to "fix" a headless denial; the
correct response is either (a) rewrite the call to match an existing
allow entry, or (b) add an explicit enumerated allow entry to the
baseline via a reviewed PR.

**Variant-specific nuance for `agent:*:local`**: the `:local` reviewer
tasks (e.g. `task agent:review:codex:local`, `task agent:review:gemini:local`)
bypass the container-mode entrypoint and run the vendor CLI against the
host user's OAuth session. These are allow-listed on the production
baseline because they are load-bearing for the tri-family review gate,
but they are **not** intended for headless execution — a headless
`agent:*:local` invocation will hang on the vendor CLI's interactive
OAuth prompt or produce a misleading auth error. The CI path uses the
container variant (`task agent:review:<family>`) with API keys sourced
from the environment.

### Rollback recipe — re-admitting a dropped namespace

When a narrowing PR drops a namespace that later proves load-bearing,
apply this recipe rather than reverting the whole PR:

1. Reproduce the failure. Note the exact `task <target>` string and the
   stderr ("Claude requested permissions to use Bash …" for Ask-tier,
   or a headless hard-deny).
2. Confirm the task target is one Claude should be allowed to invoke
   directly. If the failure is a transitively-nested task that *should*
   have matched through a parent allow entry, the fix is usually in the
   Taskfile (rename the nested target, hoist the dependency) rather
   than the settings.
3. Add the minimal enumerated allow entry to `.claude/settings.json`,
   matching the style of existing baseline entries (`Bash(task <ns>:*)`
   — no trailing `*`, no bare `<ns>` without colon):

   ```json
   { "allow": ["Bash(task <namespace>:*)"] }
   ```

4. Update `tests/hooks/test_settings_permission_baseline.py`:
   add the new entry to `EXPECTED_ALLOW_SET`, remove it from
   `EXCLUDED_NAMESPACES` if it was listed there, and confirm the
   composite-vulnerability guard still trips on unrelated adjacent
   namespaces.
5. Include the reproduction command + decision rationale in the PR body
   so a future reviewer can audit whether the namespace should remain
   enumerated or be removed again as the Taskfile evolves.

## Layer 1: PreToolUse Hooks

Claude Code invokes registered PreToolUse hooks before executing any `Bash`
tool call. The hook receives the full tool input as JSON on stdin. The hook
exits with:

- `exit 0` and no stderr output — allow the tool call.
- `exit 2` and a message to stderr — deny the tool call; Claude Code surfaces
  the stderr message as an error.

Any unexpected error inside the hook triggers the `ERR` trap, which prints a
denial message and exits 2 (fail-closed). Malformed (non-JSON) input is
rejected with exit 2 — the hook never silently passes bad input.

**Registration** is in [`.claude/settings.json`](../.claude/settings.json)
under `hooks.PreToolUse`. All three hooks are registered as `Bash` matchers
and run in sequence on every tool call:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/block-terraform-escape.sh"
          },
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/block-container-escape.sh"
          },
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/block-docker-build-escape.sh"
          }
        ]
      }
    ]
  }
}
```

**Normalization pattern** used in all hooks: the raw JSON is read from stdin,
the command string is extracted via `jq -r` from the JSON payload, then
pattern-specific normalization (e.g., `tr '\n' ' '`) prevents multiline bypass
of single-line `grep` patterns.

**Python hook**
([`.claude/hooks/block-container-escape.sh`](../.claude/hooks/block-container-escape.sh)):
Blocks `docker [compose] run/exec` targeting the Python execution containers,
any `--entrypoint` override on those containers, legacy `docker-compose`
access, and interactive shell tasks (`task sh:python-cli`, `task sh:pytest-cli`).
It also blocks direct `pytest` and `py.test` invocations on the host (the legitimate paths are the host-side targets enumerated in [CLAUDE.md](../CLAUDE.md) §11 — `task test:skills`, `task test:container-integration` and `task test:routing` — each of which invokes pytest internally and is invisible to the hook).

**Docker build hook**
([`.claude/hooks/block-docker-build-escape.sh`](../.claude/hooks/block-docker-build-escape.sh)):
Intercepts `docker build`, `docker compose build`, and `docker buildx build`
commands. Three gates: (1) blocks builds from untracked Dockerfiles (`-f`
flag pointing to a non-git-tracked file), (2) blocks builds when untracked
Dockerfiles exist anywhere in the working tree, (3) audits uncommitted changes to
security-critical files for security-weakening patterns (entrypoint removal,
USER removal, permission loosening, gate bypass). Clean builds from tracked,
committed files pass through.

**Terraform hook**
([`.claude/hooks/block-terraform-escape.sh`](../.claude/hooks/block-terraform-escape.sh)):
Blocks direct access to `_tf_exec_internal` (the hidden Terraform binary),
`--entrypoint` override on `infra-terraform`, and `--user/-u` values other
than `agent` or `agent:agent` on `infra-terraform`. The `--user` check
tokenizes the full command to handle all flag forms (`--user VAL`,
`--user=VAL`, `-u VAL`, `-uVAL`) and rejects numeric UIDs, root, and
unknown names.

## Layer 2: Host-Side Gate Scripts

### Python containers — `docker/shared/python-security-gate.sh`

[`docker/shared/python-security-gate.sh`](../docker/shared/python-security-gate.sh)
is the host-side validation gate for the Python execution containers. It runs
before Docker execution and validates paths, flags, and (where applicable)
git-tracking of the target files.

**Modes**: `run`, `test`, `lint`.

**Gate artifact**: On success, the script writes a gate artifact to
`tmp/.python-gate-pass` with the format:

```text
GATE_PASS=<unix_timestamp>:<sha256_of_paths>
```

The timestamp has a 120-second TTL enforced by Layer 3. The SHA-256 hash is
included for audit trail purposes; Layer 3 does not re-verify it (command
binding is enforced at Layer 2).

Taskfile tasks that run Python through the `pytest-cli` / `python-cli`
entrypoint route through this gate automatically, and a `defer` cleanup step
removes the artifact after each task completes. The rule for the exceptions is
structural rather than a list: any path that overrides the entrypoint
(`docker compose run --entrypoint ""`) bypasses the gate, and any target that
runs pytest host-side is outside its scope by construction — the gate exists to
validate paths and flags before Python runs *in a container*. See
[CLAUDE.md](../CLAUDE.md) §11 for the host-side targets.

### Terraform container — `tf-safe.sh` via task

The `infra-terraform` container uses a different pattern. The `tf-safe` wrapper
(copied into the container at `/usr/local/bin/tf-safe` and owned by root) is
the container entrypoint. It enforces a subcommand allowlist (`init`, `fmt`,
`plan`, `show`) and delegates to `_tf_exec_internal` via `sudo`. There is no
host-side gate artifact for Terraform; the task wrapper itself is the gate.

### Lint container — `docker/shared/lint-security-gate.sh`

[`docker/shared/lint-security-gate.sh`](../docker/shared/lint-security-gate.sh)
is the host-side validation gate for the `infra-lint` container. It supports
`lint` (read-only) and `fix` (read-write) modes with separate gate artifacts:

- `lint` mode: Writes `tmp/.lint-gate-pass` — read-only operations
- `fix` mode: Writes `tmp/.lint-fix-gate-pass` — write operations (e.g., `ruff --fix`)

The `infra-lint` container uses `/workspace` (not `/app`) as its working
directory, inherited from the existing `Dockerfile.infra-lint`.

## Layer 3: Container Entrypoints

### Python containers — `docker/shared/python-gate-entrypoint.sh`

[`docker/shared/python-gate-entrypoint.sh`](../docker/shared/python-gate-entrypoint.sh)
is the entrypoint for the Python execution containers. It is owned by root
inside the container; the `agent` user (non-root) cannot overwrite it.

On startup it:

1. Checks for `PYTHON_GATE_DISABLED=1` — if set, emits a WARNING to stderr
   and passes control directly to the command (`exec "$@"`).
2. Verifies `/tmp/.python-gate-pass` exists. All commands (including
   `python3`, `python`, `pytest`, and any unlisted binary) are blocked if
   the artifact is missing.
3. Extracts the timestamp from the artifact and validates it is not older
   than 120 seconds. Expired or malformed artifacts cause `exit 1`.
4. If the command is `python3 <script>` and the script file exists, runs
   `ruff check --select S --no-cache` on it. This catches
   dangerous patterns (eval, exec, subprocess shell injection, hardcoded
   secrets, insecure temp files) before execution. Failures block the
   script with `exit 1`.
5. Execs the requested command.

The gate file path inside the container is `/tmp/.python-gate-pass`, which
maps to the bind-mounted `tmp/.python-gate-pass` on the host.

### Terraform container — sudo + hidden binary

The `infra-terraform` container
([`docker/builders/Dockerfile.infra-terraform`](../docker/builders/Dockerfile.infra-terraform))
uses a different mechanism:

- The real Terraform binary is moved to `/bin/_tf_exec_internal` and set to
  `chmod 0700` (root-only execute).
- A scoped `sudoers` rule allows the `agent` user to run
  `/bin/_tf_exec_internal` only for the four permitted subcommands
  (`init`, `fmt`, `plan`, `show`) via `sudo`.
- The container runs as the `agent` user. Any attempt to call
  `_tf_exec_internal` directly (without `sudo`) fails with permission denied.
- The Layer 1 hook blocks agent attempts to reference `_tf_exec_internal`
  from outside the container.

### agent-cli — `docker/agent-cli/entrypoint.sh`

The `agent-cli` container uses a command allowlist entrypoint. Only three
commands are permitted: `copilot-review`, `gemini-review`, and `preflight`.
The entrypoint validates `--prompt-file` arguments with `realpath` to prevent
symlink traversal outside `tmp/`. There is no gate artifact and no bypass
variable — this is intentional since the commands are fixed.

### Lint container — `docker/shared/lint-gate-entrypoint.sh`

[`docker/shared/lint-gate-entrypoint.sh`](../docker/shared/lint-gate-entrypoint.sh)
is the entrypoint for `infra-lint`. It validates the gate artifact TTL (checks
both lint and fix artifacts), enforces a command allowlist (8 linting tools +
`helm template`/`helm lint`), and blocks `bash`, `sh`, and `python3`.

**Bypass**: Set `LINT_GATE_DISABLED=1` to bypass Layer 3. Blocked by Layer 1
hook for agent invocations.

**Fix mode volume override**: The `fix` task in `taskfiles/lint.yml`
overrides the compose-level `:ro` mount with a read-write bind mount
(`-v {{.ROOT_DIR}}:/workspace`) to allow tools like `markdownlint-cli2
--fix` to write changes. This override is gated by the
`lint-fix-gate-pass` artifact — only the host-side gate script can
authorize write access.

## File-Level Deny Rules

Security-critical files are protected from agent modification via `deny` rules
in [`.claude/settings.json`](../.claude/settings.json) (project-level, checked
in) and `.claude/settings.local.json` (user-level, gitignored). Both locations
must carry the same deny rules: the project file protects contributors who lack
local overrides; the local file overrides any blanket `allow Edit(*)` rules.

Protected files:

| Path | Rationale |
|------|-----------|
| `.claude/settings.json` | Self-protection — prevents agent from removing deny rules |
| `.claude/hooks/**` | Hook scripts are the primary enforcement boundary |
| `docker/shared/python-gate-entrypoint.sh` | Layer 3 container entrypoint |
| `docker/shared/python-security-gate.sh` | Layer 2 host-side gate |
| `docker/python-cli/Dockerfile` | Defines entrypoint and USER for python-cli |
| `docker/pytest-cli/Dockerfile` | Defines entrypoint and USER for pytest-cli |
| `docker/repo-cli/Dockerfile` | Defines entrypoint and USER for repo-cli |
| `docker-compose.yml` | Service definitions, entrypoint mappings, volumes |
| `docker/agent-cli/Dockerfile` | Defines entrypoint and USER for agent-cli |
| `docker/agent-cli/entrypoint.sh` | Layer 3 command allowlist for agent-cli |
| `docker/builders/Dockerfile.infra-lint` | Defines entrypoint and USER for infra-lint |
| `docker/shared/lint-security-gate.sh` | Layer 2 host-side gate for infra-lint |
| `docker/shared/lint-gate-entrypoint.sh` | Layer 3 container entrypoint for infra-lint |
| `docker/shared/jsonlint-batch.sh` | In-container jsonlint wrapper for infra-lint |
| `docker/builders/Dockerfile.infra-terraform` | Defines entrypoint and USER for infra-terraform |
| `docker/builders/tf-safe.sh` | Layer 2/3 Terraform subcommand allowlist |

When the agent attempts to edit a denied file, Claude Code prompts the user
for explicit approval. The agent cannot self-approve — a rogue (prompt-injected)
agent is blocked without human intervention.

### Settings Precedence

Claude Code evaluates permission rules in scope order (highest wins):

1. **Managed settings** (org-level, if present)
2. **`.claude/settings.local.json`** (project, gitignored)
3. **`.claude/settings.json`** (project, checked in)
4. **`~/.claude/settings.json`** (user global)

A higher-precedence `allow` overrides a lower-precedence `deny`. Within the
**same** file, `deny` is evaluated before `allow` and takes priority.

This means blanket `allow Edit(*)` or `allow Write(*)` rules in
`settings.local.json` (#2) override the project deny rules in
`settings.json` (#3). Contributors with blanket allows MUST copy the deny
rules into their `settings.local.json` to restore protection.

### New Contributor Onboarding

If your `.claude/settings.local.json` contains `allow Edit(*)` or
`allow Write(*)`, copy the `deny` array from `.claude/settings.json` into
your local file's `permissions` block. Without this, the local allows
override the project deny rules and security-critical files are unprotected.

### Making Legitimate Changes to Protected Files

Protected files can be modified through three paths:

1. **Edit directly in your IDE or terminal** — deny rules only apply to
   Claude Code's `Edit`/`Write` tools. Your editor, `vim`, `sed`, and
   manual `git` commands are unaffected.

2. **Approve per-edit when prompted** — if you ask the agent to modify a
   protected file, Claude Code will prompt you for approval on each edit.
   Approve individually. This is suitable for small, targeted changes.

3. **Temporarily remove deny rules for agent-driven workflows** — when
   you want the agent to edit, test, and iterate on protected files
   (e.g., updating a Dockerfile and fixing build failures), remove the
   relevant deny rules from your `settings.local.json` for the session.
   **Re-add them when done.** The project-level deny rules in
   `settings.json` remain in place for other contributors. Note: even
   with deny rules removed, the Docker build hook still audits diffs
   for security-weakening patterns as an independent safety layer.

## Container Coverage

| Container | Layer 1 Hook | Layer 2 Gate | Layer 3 Entrypoint | Notes |
|-----------|-------------|--------------|-------------------|-------|
| `python-cli` | `block-container-escape.sh` | `python-security-gate.sh` | `python-gate-entrypoint.sh` | Non-root `agent` user; `:ro` mount + `tmp/:rw` |
| `pytest-cli` | `block-container-escape.sh` | `python-security-gate.sh` | `python-gate-entrypoint.sh` | `agent` user with GID 0 for `docker.sock` access; `:ro` mount + `tmp/:rw` |
| `repo-cli` | `block-container-escape.sh` | — | `entrypoint.sh` (command allowlist + git/gh flag filtering + git env hardening) | Non-root `agent` user; no gate artifact; git/gh/sparse-clone.sh only |
| `infra-terraform` | `block-terraform-escape.sh` | `tf-safe.sh` (via task) | sudo + chmod 0700 binary | Non-root `agent` user; no gate artifact |
| `agent-cli` | `block-container-escape.sh` | — | `entrypoint.sh` (command allowlist + `--prompt-file` validation) | Non-root `agent` user; `:ro` mount + `tmp/:rw`; no gate artifact; no bypass variable (intentional) |
| `infra-lint` | `block-container-escape.sh` | `lint-security-gate.sh` | `lint-gate-entrypoint.sh` | Non-root `agent` user; `:ro` mount (uses `/workspace`) + `tmp/:rw`; lint/fix mode split |
| `ledger-dashboard` | `block-container-escape.sh` | -- | `entrypoint.sh` (command allowlist: uvicorn only) | Non-root `agent` user; `~/.brownfield-ai:/brownfield-ai` r/w (writes `ledger_index.db`); no bypass variable |

## Mandatory Protocol: New Dockerfiles

**Any new Dockerfile added to this repository MUST be evaluated against this
security model before merge.** This is not optional — ungated containers are
attack surface.

When adding a new container:

1. **Assess**: Does the agent invoke this container via task wrappers or
   directly? If the agent can reach it via `docker compose run`, it needs
   a hook.
2. **Gate**: Create a PreToolUse hook (Layer 1) following the Hook Authoring
   Guide below. Add Layer 2 and Layer 3 if the container executes
   user-supplied scripts or code.
3. **Document**: Add the container to the Coverage table above with its
   layer assignments.
4. **Test**: Write hook tests and verify live per the authoring guide.

Pull requests that add or modify Dockerfiles without addressing container
security will be flagged during code review.

## Hook Authoring Guide

When adding security hooks for a new container, follow this pattern.

### 1. Create the hook script

File: `.claude/hooks/block-<name>-escape.sh`

Required structure:

```bash
#!/usr/bin/env bash
# Brief description of what is blocked.
set -uo pipefail

# Failure-closed ERR trap.
trap 'echo "DENIED: hook error — failing closed." >&2; exit 2' ERR

# Read and extract command from Claude Code's JSON hook input via sed.
# No external dependencies (jq not required).
INPUT=$(cat)
[[ -z "$INPUT" ]] && exit 0
if ! printf '%s' "$INPUT" | grep -q '{'; then
  echo "DENIED: malformed hook input — failing closed." >&2
  exit 2
fi
COMMAND=$(printf '%s' "$INPUT" | tr '\n' ' ' | sed 's/.*"command":"//; s/"[}]*$//' | sed 's/\\n/ /g; s/\\"/"/g; s/\\\\/\\/g')
[[ -z "$COMMAND" ]] && exit 0

# Pattern checks — exit 2 to deny, exit 0 to allow.
if printf '%s' "$COMMAND" | grep -qE '<dangerous-pattern>'; then
  echo "DENIED: <reason>." >&2
  exit 2
fi

exit 0
```

Key requirements:

- `set -uo pipefail` — strict mode.
- `ERR` trap — fail-closed on unexpected errors.
- Malformed-input guard — rejects non-JSON input with exit 2.
- Extract command from stdin via `sed` (no `jq` dependency).
- Normalize newlines before pattern matching.
- Use `printf '%s' "$COMMAND" | grep` rather than `echo` or `[[ =~ ]]`
  to avoid quoting edge cases.
- `exit 2` to deny; `exit 0` to allow.

### 2. Register in settings.json

Add the hook to `.claude/settings.json` under `hooks.PreToolUse`:

```json
{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/block-<name>-escape.sh" }
```

### 3. Write tests

File: `tests/hooks/test_block_<name>_hook.py`

Use the `_run_hook` helper pattern established in the existing test files.
The helper invokes the bash script with a JSON payload on stdin and returns
the `subprocess.CompletedProcess` result. Organize tests into three classes:

- `TestBlocked` — parametrize with commands that must be denied (assert
  `returncode == 2` and `"DENIED" in result.stderr`).
- `TestAllowed` — parametrize with commands that must be allowed (assert
  `returncode == 0`).
- `TestEdgeCases` — multiline bypass attempts, extra whitespace, empty
  command input, and malformed (non-JSON) input.

### 4. Verify live

After registering the hook, confirm Claude Code invokes it by issuing a
command that matches the block pattern within the session. The session should
surface the `DENIED:` message as a tool error without executing the command.

## Emergency Bypass

### Python containers

Set `PYTHON_GATE_DISABLED=1` as an environment variable on the Docker command.
This bypasses Layer 3 only — the container entrypoint emits a WARNING to
stderr and passes control directly to the requested command.

Layer 1 (hook) remains active. To bypass it, the hook registration must be
temporarily removed from `.claude/settings.json`. This is a manual step
intentionally requiring human action.

The `PYTHON_GATE_DISABLED` bypass is for human operator debugging and recovery
only. Never set it in automated pipelines or CI environments.

### Terraform containers

There is no runtime bypass flag for `infra-terraform`. The `tf-safe` wrapper
enforces the subcommand allowlist unconditionally. If a subcommand outside the
allowlist (e.g., `apply`) is required, a human operator must exec into the
container directly on the host and invoke `sudo /bin/_tf_exec_internal`
manually — this requires host-level Docker access that the agent does not have.

### Datalake container

Set `DATALAKE_GATE_DISABLED=1` as an environment variable on the Docker command.
This bypasses Layer 3 only — the container entrypoint emits a WARNING and
passes control to the command.

Layer 1 (hook) blocks agent use of `DATALAKE_GATE_DISABLED=1` via the
`-e.*_GATE_DISABLED` pattern match. Only human operators running commands
directly in their terminal can use this bypass.

### Redshift container

Set `REDSHIFT_GATE_DISABLED=1` as an environment variable on the Docker command.
This bypasses Layer 3 only — the container entrypoint emits a WARNING and
passes control to the command.

Layer 1 (hook) blocks agent use of `REDSHIFT_GATE_DISABLED=1` via the
`-e.*_GATE_DISABLED` pattern match. Only human operators running commands
directly in their terminal can use this bypass.

### Lint container

Set `LINT_GATE_DISABLED=1` as an environment variable. Same behavior and
hook protection as `DATALAKE_GATE_DISABLED`.

### agent-cli

There is no emergency bypass variable for `agent-cli`. This is intentional —
the container runs exactly 3 predefined commands. If a different command is
needed, a human operator must exec into the container directly.

## Testing

### Unit tests (run inside Docker via `task test:scripts`)

Hook and gate script tests run inside the `pytest-cli` container:

```bash
task test:scripts
```

These cover: PreToolUse hook enforcement, gate script validation, entrypoint
command allowlists, gate artifact format/expiry, conftest.py scanning, and
tox.ini integrity checking.

### Integration tests (run on the host)

Integration tests validate actual container behavior — `:ro` mounts, non-root
user enforcement, entrypoint immutability, gate bypass blocking, and helm
subcommand restriction. They require Docker images to be pre-built and run
**on the host** (not inside a container):

```bash
docker compose --profile tools build
pytest tests/integration/test_container_hardening.py -v
```

Run via the dedicated task (uses `.venv/` automatically):

```bash
task test:integration
```

Integration tests are excluded from `task test:scripts` via `norecursedirs` in
`pytest.ini` and carry `@pytest.mark.integration`. They use
`subprocess.run(["docker", "compose", ...])` to start real containers and
assert security properties.

## Design Decisions

### Why not sudo/chmod for Python containers

The `infra-terraform` container uses `sudo` to elevate to root for binary
execution. This works because Terraform writes its state and lock files to
`/workspace` inside the container, not to a bind-mounted host directory.

Python containers bind-mount the workspace into `/app`. If the agent user were
root (or used `sudo` to write as root), all artifacts — `__pycache__`,
`.pytest_cache`, `coverage.xml`, generated files — would be owned by UID 0 on
the host. This breaks local development workflows for human developers running
the same containers. The non-root `agent` user avoids this bind-mount file
ownership problem.

### Why hooks over static deny rules

Claude Code's sandbox supports static `Bash(docker run ...)` deny patterns via
glob matching. Glob matching has subtle spacing issues: a pattern anchored to a
single space between tokens does not match double-space or tab-separated
variants, and multiline continuations (via `\`) can bypass single-line globs.

Hooks provide:

- Tokenized command parsing for `--user`/`-u` flag variants.
- Newline normalization to close multiline bypass.
- Fail-closed ERR traps for unexpected errors.
- Structured JSON input from Claude Code's tool invocation context.

### Gate artifact is a speed bump, not a wall

The agent has write access to `tmp/` and could theoretically write a forged
gate artifact directly, bypassing Layer 2's path and flag validation. Layer 1
hooks are the real enforcement boundary. The gate artifact ensures that even
if Layer 1 is misconfigured or a new container is added without a hook,
Layer 3 provides a backstop requiring an explicit host-side action before
the container runs. The 120-second TTL prevents a stale artifact from
authorizing a later, unrelated invocation.
