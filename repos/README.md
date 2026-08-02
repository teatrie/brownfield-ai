# Repositories

This directory holds clones of the repositories the agents work against, as
**nested checkouts**. This is what makes the harness non-invasive: your repos
keep their own history, tooling, and CI, and this workspace layers agent
capabilities on top without modifying them.

Everything matching `repos/*/` is gitignored, so nothing cloned here is ever
committed to this repository. The org and repo list are **user-supplied
configuration**, not hardcoded.

## Configuring which repositories to clone

There is **no built-in repository list** — the harness ships pointing at nothing, by
design. Supply your own via two variables:

| Variable | Meaning | Example |
|----------|---------|---------|
| `BROWNFIELD_ORG` | GitHub org or user that owns the repos | `acme` |
| `BROWNFIELD_REPOS` | Space-separated repo names | `api web scheduler` |

Set them inline for a one-off:

```bash
task repos:clone BROWNFIELD_ORG=acme BROWNFIELD_REPOS="api web"
```

…or export them in `.envrc` / `.env` to make them persistent. Add `DRY_RUN=1` to
print the plan without touching the network. With neither variable set,
`task repos:clone` fails with an explanatory message rather than doing nothing
silently.

`task repos:clone` clones a repo that is absent and fetches one that is already
present, so it is safe to re-run. To refresh checkouts to their default branch use
`task repos:reset`; to remove them all use `task repos:clean`.

## Usage

Agents may clone repositories here to:

1. Search for existing patterns or code.
2. Verify cross-repo dependencies.
3. Apply changes (e.g., Terraform updates).

## Sparse Checkout (Preferred)

When only a specific directory or file set is needed, prefer sparse checkout
over full clones to reduce disk usage and clone time:

```bash
task gh:sparse-clone -- <org>/<repo> <path/to/directory>
```

Full clones are acceptable when broad analysis across the entire repo is
required:

```bash
task gh:repo -- clone <org>/<repo>
```

## Generating a guide for a cloned repo

Run the `repos-research` prompt
(`workflows/repository-maintenance/prompts/repos-research.prompt.md`) against a
checkout to produce a curated guide under `docs/repo-guides/<repo>/`, plus the
matching `.claude/rules/` and `.github/instructions/` entries. The `repos-guide`
skill then surfaces that guide as Tier 1 discovery.

## Note

These are git repositories. Be careful when performing recursive operations.

## Important: Data Loss Warning

Do not `git add` any files or folders within this `repos/` directory. These are
external repositories managed by the agent.

If a repository here is dirty, the agent may switch to `main` (forcefully, if
required) to ensure a clean state. **Any uncommitted changes may be lost.**

If you have made manual changes that you wish to keep, you must take appropriate
action (e.g., commit/push or stash) before proceeding.
