# Tool Chain

- **Task (Go-Task)**: Build tool used for linting, building, and orchestration (`task` command). Ensure it is installed.
- **Terraform**: Used for infrastructure changes (e.g., DMS tasks).
- **GitHub CLI (`gh`)**: Used for cloning repos, managing PRs/issues. Agents must use `task gh:*` aliases (`task gh:search`, `task gh:api`, `task gh:repo`, `task gh:sparse-clone`) instead of invoking `gh` directly (see CLAUDE.md Principle 12).
- **Git**: Agents must use `task git:*` aliases instead of invoking `git` directly for sandbox compatibility and to eliminate `git` as a host dependency (see CLAUDE.md Principle 12). Named aliases: `clone`, `push`, `commit`, `rebase`, `pull`, `add`, `status`, `checkout`, `fetch`, `diff`, `log`. Catch-all: `task git:run -- <subcommand> [args]`. For GitHub-specific clone operations, `task gh:repo` and `task gh:sparse-clone` are also available.
- **aws-vault**: Used to securely manage AWS SSO credentials. We use the `task aws:auth` task wrapper and our `aws-vault-auth` agent capability to securely extract temporary tokens into a local, git-ignored file (`tmp/.aws-credentials.env`), preventing STS secrets from bleeding into the LLM context limits or persisting permanently.
- **uv** (Optional): Astral's Rust-based Python package manager.
Used by `task test:setup` to create the host `.venv/` with Python
3.12 for host-run tests — primarily `test:skills:staged`, which
cannot run in a container per [CLAUDE.md](../CLAUDE.md) §11. Only
developers who run the test suite locally need `uv`. CI installs
it explicitly via `.github/workflows/test.yml` (official Astral curl installer).
Install locally via `task setup:env` (offers brew install on
macOS) or manually: `brew install uv` (macOS) / `pip install uv`
(any platform) / `curl -LsSf https://astral.sh/uv/install.sh | sh`
(any platform).
- **jq**: Lightweight command-line JSON processor. Used by PreToolUse
security hooks (`.claude/hooks/`) for robust extraction of fields from
JSON payloads, and by agent CLI scripts (`scripts/agent-cli/`) for
safe JSON construction and parsing. Installed as a host prerequisite
via `brew install jq` (see `scripts/setup_env.sh`).
- **Execution Ledger**: ChromaDB-backed audit trail for execution artifacts.
Invoked via the `execution-ledger` skill in `workflows/agent-memory/`. See:
[SKILL.md](../workflows/agent-memory/skills/execution-ledger/SKILL.md)
- **repo-cli**: Isolated container for all `git` and `gh` operations. Only
`git`, `gh`, and `sparse-clone.sh` are permitted — any other command is
denied at the entrypoint. The entrypoint applies git environment hardening
(overrides `core.hooksPath`, `core.pager`, `GIT_TERMINAL_PROMPT`, etc.) to
close the shared-workspace hook/config/pager RCE vector, and scans all
arguments for dangerous flags (`-c`, `--config-env`, `--exec-path`, etc.)
on both `git` and `gh` invocations. All `task gh:*` and `task git:*`
aliases in the Taskfile route through this container — agents MUST use
those aliases instead of invoking `gh` or `git` directly on the host (see
CLAUDE.md Principle 12).
- **Python Security Gate**: Three-layer security enforcement for Python
execution in `python-cli` and `pytest-cli` containers. Layer 1: Claude Code
PreToolUse hooks block direct Docker access. Layer 2: Host-side gate script
(`docker/shared/python-security-gate.sh`) validates paths, flags, and
git-tracking. Layer 3: Container entrypoint validates a time-limited gate
artifact. All existing
taskfile tasks (`ledger:*`, `chromadb:*`, `todo:*`, `test:*`, `lint:*`)
route through the gate automatically. See
[docs/container_security.md](container_security.md) for the full security
model, deny rules, Docker build auditing, and contributor onboarding.
- **CLI Invocation Discipline**: Many `task` aliases (`ledger:*`,
`chromadb:*`, `todo:*`) wrap `defopt`-based Python CLIs where parameter
names are derived from Python function signatures, not from the task alias.
Keyword-only parameters (those after a bare `*` separator) require explicit
`--flag` syntax — positional passing silently misroutes arguments. Before
constructing a CLI invocation, read the target function signature or run
`<command> --help` to confirm exact flag names. See
[learnings.md](learnings.md) §Python CLI & Environment for `defopt` naming
gotchas and [delegation_protocol.md](delegation_protocol.md) §3 for the
mandatory CLI Syntax Verification guard rail.
- **Codex CLI** (`@openai/codex`): OpenAI's code review CLI. Used by the
  `codex-reviewer` bridge agent for cross-family model verification.
  Invoked via `task agent:review:codex` (container) or
  `task agent:review:codex:local` (host OAuth). Agents must use the task
  aliases — never invoke `codex` directly on the host.

## `task` Invocation Convention: CLI_ARGS over Env-Var Prefix

Agents MUST pass caller-supplied values to `task` targets as `KEY=value`
tokens after `--`, not as inline env-var prefixes. The block hook
(`.claude/hooks/block-sandbox-prompt-patterns.sh`) denies the env-var-prefix
form because it creates a per-invocation permission matcher token distinct
from the `Bash(task <ns>:*)` entries in the baseline allow list, which
defeats the workspace's headless-safe allowlist.

**Correct — values travel through `CLI_ARGS`:**

```bash
task agent:review:gemini:local -- ROUND=3 EFFORT=high GEMINI_MODEL=gemini-3.1-pro-high
task agent:review:codex -- ROUND=3 EFFORT=high MODEL=o3-mini
task agent:review:copilot -- ROUND=3
```

**Denied — inline env-var prefix:**

```bash
# BLOCKED by block-sandbox-prompt-patterns.sh
ROUND=3 EFFORT=high task agent:review:gemini:local
```

### How recipes consume `CLI_ARGS`

Task exposes everything after `--` as the `{{.CLI_ARGS}}` template variable.
The recipe routes that string through
[`scripts/agent-cli/cli-args-to-env.sh`](../scripts/agent-cli/cli-args-to-env.sh),
which takes the **target script path as its first positional argument**
followed by the caller's `KEY=value` tokens. There is no `--` separator —
any token that is not `KEY=value` form (including a stray `--`) is
rejected. Dropping the separator closes the smuggling path where a
caller-supplied `--` inside `{{.CLI_ARGS}}` could prematurely terminate
the key-parse loop and promote the remaining tokens into
caller-controlled argv that `exec env` would run as a command.

The shim:

1. Captures the target script path from argv[1].
2. Splits each remaining token on the first `=`.
3. Rejects any token that does not contain `=` (flag-like tokens such
   as `-u`, `--env`, and a stray `--` all fail this check).
4. Validates the key against `ALLOWED_KEYS_REGEX` (currently `ROUND`,
   `EFFORT`, `REVIEW_SESSION_ID`, `WORKSPACE`, `REVIEW_TYPE`,
   `GEMINI_MODEL`, `GEMINI_TIMEOUT`, `MODEL`, `DIFF_FILE`). The legacy
   `PROMPT_FILE`, `REVIEW_PROMPT_FILE`, and `REVIEW_DIFF_FILE` keys
   were removed in TODO-0092 Phase A — the template-driven wrapper
   contract carries the reviewer subject via `DIFF_FILE` and selects
   the template via `REVIEW_TYPE`.
5. Validates the value against `VALUE_REGEX` (`[A-Za-z0-9._/:@+=-]*` — no
   whitespace, no shell metacharacters, no expansion tokens). This closes
   the `$(...)` injection surface that the previous Go-template `env:` map
   guarded against.
6. `exec`s the target script with `env KEY=value ...` prepended so the
   values land in the child process environment exactly like the
   previous inline-prefix form did.

Recipe skeleton:

```yaml
my-target:
  cmds:
    - >-
      scripts/agent-cli/cli-args-to-env.sh
      scripts/agent-cli/my-target.sh {{.CLI_ARGS}}
```

The underlying script reads values from `$ROUND`, `$EFFORT`, etc. — no
changes required to existing env-var-based scripts.

### Adding a new allowlisted key

1. Edit `scripts/agent-cli/cli-args-to-env.sh` and extend
   `ALLOWED_KEYS_REGEX` with the new key name.
2. Update the `desc:` block of every `task` target that accepts the new
   key so `task --list-all` advertises it.
3. If the value may contain characters outside `[A-Za-z0-9._/:@+=-]`,
   widen `VALUE_REGEX` with explicit justification — do not weaken the
   regex for convenience. Whitespace and shell-metacharacter admission
   reopens injection paths and must be paired with downstream
   argv-quoting guarantees.

### Adding a new target

Follow the recipe skeleton above. The shim executes a **single target
script path** — multi-word commands (e.g. `docker compose run ...`)
always require a wrapper script under `scripts/agent-cli/` that reads
values from env and exec's the real command. See
`copilot-review-container.sh`, `gemini-review-container.sh`, and
`codex-review-container.sh` for the pattern.

This is also where caller-derived flags (e.g. `--prompt-file
tmp/foo-r${ROUND}.txt`) belong. Do not inline shell parameter expansion
in the Taskfile recipe — Task renders the cmd string before the shim
sets env, so `${ROUND:-1}` would resolve against the parent shell's
(empty) env. Perform the expansion inside the wrapper script, after the
shim has exec'd it with the validated values injected.

## Subject Sanitization (reviewer wrappers)

When a bridge reviewer (`gemini-reviewer`, `codex-reviewer`,
`copilot-reviewer`) invokes `task agent:review:<family>[:local]`, the
caller-supplied diff or plan subject (`DIFF_FILE`) is sanitized by
`scripts/agent-cli/_review-common.sh` before the reviewer sees it. This
section is the authoritative description of that contract.

**Preserved bytes**: TAB (`0x09`), LF (`0x0A`), CR (`0x0D`). Whitespace
fidelity matters for diff readability and context windows.

**Stripped byte classes**:

1. **C0 control codes** other than TAB/LF/CR — NUL through US, plus DEL
   (`0x7F`). Removed by a single `tr` pass.
2. **ANSI CSI sequences** — byte pattern `ESC [ <parameter bytes>
   <intermediate bytes> <final byte>`, where the final byte is
   `[a-zA-Z]`. Removed by the `sed` pass that precedes the `tr` pass.

**Pipe order is load-bearing**: `sed` runs first so that each ESC that
introduces a CSI is consumed together with its trailing final-byte; the
`tr` pass then sweeps the remaining orphan ESCs and other C0 controls.
Reversing the order would strip ESCs before `sed` could match the CSI
body, leaving numeric parameter bytes and the final letter in the
output as visible garbage. See commit `c5d581f` for the historical fix.

**Known limitation — OSC/DCS bodies**: the sanitizer's CSI regex does
not match OSC (`ESC ]`) or DCS (`ESC P`) introducers. An OSC/DCS escape
therefore loses only its leading ESC (stripped as an orphan C0 byte by
`tr`); the body and terminator bytes pass through. For a BEL-terminated
OSC this means the intervening payload plus `0x07` appear in the
sanitized subject; for an ST-terminated DCS/OSC the payload plus the
trailing `\` appears. The reviewer still sees an obviously-malformed
subject (no preserved cursor-control side effects), but the payload is
not scrubbed. Extending the regex to include `ESC ][^\x07]*\x07` /
`ESC P[^\x1b]*\x1b\\` is tracked as TODO-0092k and has not shipped —
the threat model today is log-noise and terminal-garbling, not
injection, because the downstream consumer (a reviewer LLM) does not
interpret OSC/DCS sequences as control. Callers that need a hard
stripping guarantee should apply a pre-filter upstream of the task
wrapper.

**Path containment**: the wrapper enforces that any `DIFF_FILE` value
resolves (via `realpath`) under `tmp/` or the workspace's
`~/.brownfield-ai/agent-review/` scratch directory. Absolute paths outside
either root are rejected at the `_review-common.sh` entry point before
sanitization runs.

## Task Permission Baseline

Claude Code's Bash allowlist in `.claude/settings.json` is an
**enumerated set of eight `Bash(task <ns>:*)` entries**:

```text
Bash(task agent:*)      Bash(task findings:*)    Bash(task gh:*)
Bash(task git:*)        Bash(task ledger:*)      Bash(task lint:*)
Bash(task test:*)       Bash(task todo:*)
```

Every other `task` namespace is **excluded by default** and prompts
the user on invocation. Destructive or code-executing namespaces
(`run:*`, `repos:*`, `aws:*`, `ralph:*`) are kept out
of the baseline by exclusion, not by per-task deny matchers.
Per-target content rules that need finer granularity than a namespace
(e.g., `sh:<gated>`, `CI=`-prefixed invocations) live in PreToolUse hooks at
`.claude/hooks/` rather than the permission matcher — see
`docs/container_security.md` Layer 0 for the architectural rationale
and the rollback recipe if a future allow-list change must
temporarily re-admit a namespace.

**Transitive-nesting verification**: authors of new task targets
must confirm that when Claude invokes `task X` and `X`'s `deps:` or
`cmds:` chain eventually runs `task Y`, the outer invocation
(`task X`) is what the permission matcher sees — inner `task Y` calls
are subprocesses, not separate permission checks. This means the
allow list governs which top-level targets Claude may directly issue;
chained inner calls inherit the outer authorization. The consequence
for agents: any new leaf task authored under an allowed namespace
ships without permission drift, but authoring an entirely new
top-level namespace requires an addition to the allow list above.

**Operator-authorized destructive subtarget**:
`task ledger:check-reviews` is reachable via the `ledger:*` allow by
design. It closes PRs and deletes branches when it transitions
`in_review` epics — destructive under the usual definition — but its
three legitimate callers (ralph autonomous loop runner, the user in
their terminal, the user asking a Claude session to sweep review
states) all carry operator intent as the authorization boundary. The
permission matcher is not the gate; the caller's request is. This
exception is pinned in
`tests/hooks/test_settings_permission_baseline.py` via the
`OPERATOR_AUTHORIZED_DESTRUCTIVE` set and must not be extended
without an explicit trust-model review.

Note on subagent inheritance: a subagent spawned from an
operator-initiated Claude session inherits the parent's ceiling and
can invoke `task ledger:check-reviews` without a fresh prompt. This is
acceptable under the current delegation model — the parent's
operator-intent carries transitively — but delegating agents MUST NOT
construct subagent prompts that instruct the subagent to invoke this
task absent a caller request. Put differently: operator intent is
inherited, not manufactured.
