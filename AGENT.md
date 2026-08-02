# Agent Guidelines

`brownfield-ai` is a standalone harness that adds agentic capabilities to
existing repositories non-invasively: those repos are cloned as nested checkouts
under `repos/` and are never modified to accommodate the agent.

This repository follows Claude Code conventions as the canonical standard
for all AI agent platforms.

## Required Reading

1. **[CLAUDE.md](CLAUDE.md)** — Core protocols, principles, and coding
   standards. Read this first. It is the authoritative source.
2. **[.claude/skills/](.claude/skills/)** — Registered skills (slash
   commands). Review before executing manual fallback logic.
3. **[.claude/rules/](.claude/rules/)** — Repository-scoped constraints
   matched by `paths:` glob patterns. Check for applicable rules
   before editing files under `repos/`.
4. **[workflows/INDEX.md](workflows/INDEX.md)** — Domain routing for
   all actionable requests.

## Platform-Specific Files

- **Claude Code**: Loads `CLAUDE.md` automatically.
- **GitHub Copilot**: Loads `.github/copilot-instructions.md` automatically.
- **All others**: Start here, then read `CLAUDE.md`.
