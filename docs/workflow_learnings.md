# Workflow & Operational Learnings

This document captures process, workflow, and operational learnings that are not specific to code implementation. Use this file for agentic protocols, hygiene, delegation, container orchestration, and bulk import procedures.

## Hygiene & Maintenance Protocols

- **Mandatory `task repos:reset`**: Always ask the user for explicit permission before running `task repos:reset`, as it destroys uncommitted changes. Suggest options for saving changes (e.g., `git stash`, new branch, move files), and require the user to type "PROCEED WITH RESET" to confirm.
- **Temporary Artifacts**: All temporary files (scripts, logs, PR bodies) must be created in `tmp/<context>/` and deleted after use. Never create temp files in root or source directories.

## Workflow Separation

- **Development vs Operational Learnings**: Keep development/coding learnings in [learnings.md](learnings.md). Move operational/process learnings to [workflow_learnings.md](workflow_learnings.md).
