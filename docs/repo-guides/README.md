# Repository Guides

Curated, per-repository reference documentation for the repos you clone into
`repos/`. These guides are **Tier 1 discovery** (see `CLAUDE.md` Protocol 12):
agents read them before making any remote call, because they are authoritative
and zero-cost.

This directory ships empty by design — the guides describe *your* repositories,
so they are generated rather than vendored.

## Generating a guide

Run the `repos-research` prompt at
`workflows/repository-maintenance/prompts/repos-research.prompt.md` against a
checkout under `repos/`. It produces:

+ `docs/repo-guides/<repo>/` — the guide itself, including the **AI Coding
  Readiness Assessment** for that codebase.
+ `.claude/rules/repos.<repo>.md` — agent constraints scoped to that repo.
+ `.github/instructions/repos.<repo>.instructions.md` — the Copilot mirror.

## Reading a guide

Use the `repos-guide` skill rather than searching this directory by hand; it
routes a domain or repo question to the right guide.
