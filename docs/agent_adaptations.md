# Agent Platform Adaptations

This document describes how each supported agent platform maps to
the repository's core protocols (`agent-team`, `feature-epic`,
`tdd-execute`, `bug-fix`) and their specific capabilities.

## 1. Claude Code (Primary)

**Claude Code** is the primary agent platform for this repository.
All skills, agents, and protocols are designed and tested here first.

- **Orchestration**: Full subagent delegation with per-subagent
  model selection (`haiku`/`sonnet`/`opus` via the `model`
  parameter). Supports parallel subagent spawning (multiple Agent
  calls in a single message).
- **Subagent Types**: Enforces least-privilege via `subagent_type`
  (e.g., `tdd-red`, `qa-lint`, `code-review`, `explore`).
- **TDD Loops**: Best suited for Red-Green-Refactor loops due to
  native subagent specialization and cost-tiered model assignment.
- **Agent Teams**: Supports multi-session coordination via
  [Agent Teams](https://code.claude.com/docs/en/agent-teams) with
  tmux split panes, shared task lists, and inter-agent messaging.
- **Tool Execution**: Deeply integrated with the local terminal,
  automatically executing `task`, `make`, `git`, and `gh` commands.
- **Rules**: `.claude/rules/*.md` files are auto-matched by
  `paths:` glob patterns when editing repo-specific files.
- **Skills**: `.claude/skills/` are registered and invokable via
  `/skill-name`. Workflow skills under `workflows/` are deferred
  and loaded on-demand via `@` file picker.
- **Permissions**: Set `mode: "bypassPermissions"` on subagents to
  prevent breaking autonomous loops with interactive prompts.

## 2. GitHub Copilot (Supported)

**GitHub Copilot** (VS Code Chat and CLI) provides deep GitHub
integration and multi-family model access.

- **GitHub Context**: Native PR creation, code review diffs, and
  workspace search via the GitHub ecosystem.
- **Model Selection**: Session-level model picker with access to
  multiple model families (Anthropic, OpenAI, Google). Cannot set
  model per-subagent — all subagents inherit the session model.
- **Parallel Subagents**: Not supported. Wave members execute
  sequentially.
- **Rules**: `.github/instructions/*.instructions.md` files are
  auto-matched by `applyTo` YAML frontmatter globs.
- **Skills**: Copilot scans `workflows/` natively for skill
  discovery. `.claude/skills/` are not auto-discovered but can be
  read on demand.
- **Delegation**: Uses `runSubagent` tool. Skills reference
  delegation generically ("delegate to a subagent") for
  cross-platform compatibility.

## 3. Gemini CLI (Supported)

**Gemini CLI** provides large-context research and auto-routing
capabilities.

- **Auto Model Routing**: The `auto` mode routes between models by
  task complexity. Manual override via `--model` or `GEMINI_MODEL`.
- **Large Context**: Gemini Pro models support massive context
  windows (1M+ tokens) with prompt caching that reduces follow-up
  costs by ~90%. Preferred for deep research tasks.
- **Parallel Subagents**: Not supported. Sequential execution only.
- **Silent Fallback**: Built-in fallback chain
  (`flash-lite` → `flash` → `pro`) handles model unavailability
  without user intervention.
- **Skills**: No native skill discovery. Workflow skills are
  loaded by reading the file path directly.

## Cross-Platform Design Principles

The repository's skills and protocols are written to be
platform-neutral:

- **Tier-based model selection**: Skills reference abstract tiers
  (`fast-*`, `medium`, `high-reasoning`) instead of concrete model
  names. Each platform resolves tiers at runtime. See the
  [agent-team skill](../.claude/skills/agent-team/SKILL.md).
- **File-path references**: Workflow skills are referenced by path
  (e.g., `workflows/.../SKILL.md`) rather than slash-command
  invocation, ensuring any platform can load them via file read.
- **Generic delegation**: Skills say "delegate to a subagent"
  without naming platform-specific tools (`runSubagent`, `Agent`).
- **Rule parity**: `.claude/rules/` and `.github/instructions/`
  contain equivalent rules with matching glob patterns. The
  `claude-review` skill enforces this consistency.
- **Build tool discovery**: Sub-agents detect build targets
  dynamically in `repos/` using platform rule files, root
  `taskfiles/`, or the repo's native build tools.
