# Architecture

## Overview

This repository is an agent-orchestration harness. It does not host the systems it
works on — it sits alongside them. Target repositories are cloned as nested
checkouts under `repos/`, and the harness layers agentic capability on top of them
**non-invasively**: your repos keep their own history, build tooling, and CI, and
nothing here is committed back into them.

That separation is the core design constraint. Everything below follows from it.

## Harness Topology

### Workspace layout

- **`repos/`** — nested checkouts of the repositories under study. Gitignored
  (`repos/*/`), so cloned code never enters this repository's history. See
  [repos/README.md](../repos/README.md).
- **`docs/repo-guides/`** — generated, curated documentation about those repos. This
  is the agent's Tier 1 reference (Protocol 12): guides answer questions without a
  remote call or a re-read of the source.
- **`.claude/rules/`** and **`.github/instructions/`** — per-repo agent constraints,
  mirrored for Claude and Copilot respectively.
- **`src/`**, **`scripts/`**, **`ci/`**, **`services/`** — the harness's own Python:
  the execution ledger, the autonomous runner, CI gates, and the dashboard.
- **`workflows/`** — domain-driven skill and prompt routing (see
  [workflows/INDEX.md](../workflows/INDEX.md)).

### Execution isolation

Agent-executed code runs in Docker, never on the host. A 3-layer security gate
(PreToolUse hooks → host-side validation → container entrypoint allowlist) enforces
this. See [container_security.md](container_security.md) for the full model and
[tool_chain.md](tool_chain.md) for the task-permission baseline.

### Discovery tiers

Agents resolve questions about a target repo in cost order — local guides first,
remote search second, cloning last. See `CLAUDE.md` Protocol 12.

## Describing Your Own Topology

The harness is deliberately agnostic about what your systems look like. Rather than
hardcoding an inventory here, generate it:

1. Clone the repositories you care about into `repos/`.
2. Run the `repos-research` prompt
   (`workflows/repository-maintenance/prompts/repos-research.prompt.md`) against
   each one. It produces the repo guide, the rules file, the Copilot mirror, and an
   **AI Coding Readiness Assessment** scoring how amenable that codebase is to agent
   work — with prioritized, evidence-backed recommendations for improving it.
3. Record cross-repo relationships (who calls whom, who consumes whose data) in the
   generated guides, where they stay close to the evidence that supports them.

Use this section to note anything that spans repositories and therefore has no
single guide to live in — the org name, the deployment substrate, shared
infrastructure, or the boundary between operational and analytical systems.
