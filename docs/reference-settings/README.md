# Claude Code Security Settings Reference

This directory contains **suggestive** (reference) settings files for
hardening a Claude Code workspace. They are not applied directly — copy
the relevant sections into your actual settings files and adapt paths,
domains, and allowlists to your project.

## Settings Architecture

Claude Code uses a three-layer settings hierarchy. Each layer can define
permissions, filesystem rules, bash allowlists, hooks, and sandbox
configuration. Layers are merged top-down — **deny rules are
cumulative** (a deny at any layer blocks the action), while allow rules
at a lower layer cannot override a deny at a higher layer.

### Bash allowlist schema

Bash allowlist entries live under `permissions.allow` using the
permission-rule syntax `Bash(<command-pattern>)` — e.g.,
`"Bash(task *)"` auto-approves any `task <name>` invocation. The
legacy-looking `tools.bash.allowList` key is **not recognized** by
Claude Code and has no effect. Always express allowlists as
`permissions.allow` entries.

| Layer | File | Scope | Checked into git? |
|-------|------|-------|--------------------|
| Global (user) | `~/.claude/settings.json` | All projects on this machine | No |
| Project (shared) | `.claude/settings.json` | This project, all contributors | Yes |
| Project (local) | `.claude/settings.local.json` | This project, this machine only | No (gitignored) |

### Production vs Local Development

The two project-layer files serve different operational contexts, and
this distinction is load-bearing for the security model:

- **`.claude/settings.json` is the production/headless baseline.** It
  is checked in and ships with the repo, so it applies unchanged when
  the repo runs on a production server, in headless CI, or anywhere
  `settings.local.json` is absent. Keep its `permissions.allow` list
  minimal — the current baseline is an enumerated set of nine
  `Bash(task <ns>:*)` entries rather than a `Bash(task *)` wildcard,
  with each allowed namespace justified in
  [CLAUDE.md §17](../../CLAUDE.md) and
  [tool_chain.md §Task Permission Baseline](../tool_chain.md). Every
  file write that is not explicitly allowed falls through to the
  default, which per the Headless Session Protocol
  ([CLAUDE.md §16](../../CLAUDE.md)) fails closed in headless mode.
  Minimal allow equals minimal attack surface in prod.
- **`.claude/settings.local.json` is developer ergonomics.** It is
  gitignored and excluded from prod deployments. Broad `Edit`/`Write`
  grants for project trees (e.g., `src/**`, `tests/**`, `docs/**`)
  unlock interactive workflows on a developer laptop where a human is
  present to review diffs before commit.

This split is defense-in-depth: restrictive prod, permissive dev, same
deny perimeter enforced in both.

**Operational rule: do not promote developer conveniences from
`settings.local.json` into `settings.json`.** A compromised or
prompt-injected headless agent running in prod would inherit any
`allow` entry in the shared file, expanding its write surface beyond
what's intended. The broad per-directory `Edit`/`Write` grants belong
in the local file precisely because they should disappear when the
repo is deployed to a server with no human-in-the-loop.

### What goes where

**Global** (`~/.claude/settings.json`):

- Sandbox configuration (filesystem read/write boundaries, network, restricted commands)
- Cross-project bash allowlist (git, docker, ls, tree, etc.)
- Agent tool credentials deny rules (sessions, history, OAuth tokens)
- Plugins (LSP servers, etc.)

**Project shared** (`.claude/settings.json`):

- Security-critical file deny rules (Dockerfiles, shell scripts, hooks, settings itself)
- PreToolUse hooks (container escape blockers, terraform guards)
- Infrastructure-specific deny rules

**Project local** (`.claude/settings.local.json`):

- Self-protection deny rule (prevents agent from editing this file)
- Scoped permission allows (Edit, Write per directory — see three-tier model below)
- Per-user bash allowlist overrides (e.g., `task *` for task-runner workflows)
- Credential file deny rules (`tmp/.aws-credentials.env`)
- WebFetch domain allowlist
- Plugins specific to this user's workflow

### Three-tier permission model

Claude Code permissions have three effective tiers based on allow/deny
list membership:

| Tier | In allow? | In deny? | Behavior |
|------|-----------|----------|----------|
| **Allow** | Yes | No | Auto-approved, no prompt |
| **Deny** | — | Yes | Blocked, agent cannot proceed |
| **Ask** | No | No | User prompted for approval |

The **ask** tier is the key security design tool. Paths that straddle
the boundary between routine work and infrastructure (e.g., Taskfiles,
protocol docs, CI config) should be placed in neither list. This gives
the agent the ability to propose changes while requiring human approval
for each one.

**Recommended tier assignments:**

| Tier | Paths | Rationale |
|------|-------|-----------|
| Allow | `src/`, `scripts/`, `tests/`, `docs/`, `services/`, `workflows/`, `ci/`, `repos/`, `tmp/`, `agent-review/`, `.claude/rules/`, `.claude/skills/`, `plan.md`, `todo-plan.md`, `README.md` | Core agent work — code, tests, docs, planning |
| Ask | `Taskfile.yml`, `taskfiles/*`, `CLAUDE.md`, `AGENT.md`, `GEMINI.md`, `.github/**`, `tsconfig.json`, `.claude/agents/**` | Infrastructure, protocol docs, and agent definitions — human approval required |
| Deny | `.claude/settings*`, `.claude/hooks/**`, `docker/**/Dockerfile`, `docker/**/*.sh`, `docker-compose.yml`, `**/*.sh` | Security boundary — blocked at project-shared layer |

## Reference Files

| File | Maps to | Purpose |
|------|---------|---------|
| [`global-settings.reference.json`](global-settings.reference.json) | `~/.claude/settings.json` | Machine-level sandbox, bash allowlist, credential protection |
| [`project-settings-local.reference.json`](project-settings-local.reference.json) | `.claude/settings.local.json` | Per-user permissions, domain allowlists, task runner access |

The project shared settings (`.claude/settings.json`) are not provided as
a reference because they are repository-specific — hooks reference
project-local scripts, and deny rules target project-specific
Dockerfiles and security gates. See the existing `.claude/settings.json`
in this repository for a working example.

## Related Documentation

- **[Container Security Model](../container_security.md)** — the
  3-layer defense-in-depth architecture (PreToolUse hooks, host-side
  gate scripts, container entrypoint validation) that enforces
  execution isolation. The settings documented here are **Layer 0** —
  they gate which tool calls reach the hook layer at all. Together,
  the four layers form the complete agent security boundary:

  ```text
  Layer 0  Claude Code settings   (permissions, sandbox, bash allowlist)
  Layer 1  PreToolUse hooks       (block-container-escape.sh, etc.)
  Layer 2  Host-side gate scripts (python-security-gate.sh, etc.)
  Layer 3  Container entrypoint   (validates gate artifact at runtime)
  ```

  Changes to settings (Layer 0) can weaken or bypass Layers 1-3. For
  example, removing `Edit(**/*.sh)` from the deny list lets the agent
  modify hook scripts, which disables Layer 1. The security
  verification prompt checks for these cross-layer dependencies.

## Verification

After applying settings changes, run the security verification prompt:

```text
@workflows/repository-maintenance/prompts/security-verification.prompt.md
```

This runs a structured pass/fail audit across all three layers and
reports gaps against these reference settings.
