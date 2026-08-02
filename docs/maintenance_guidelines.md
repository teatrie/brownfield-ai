# Repository Maintenance Guidelines

## 1. Clean Environment Protocol

**Prevent "Dirty State" Errors**

Before starting *any* new task or skill execution, you MUST verify the state of the repository.

- **Check**: Run `git status` and `task repos:status` (if available) or check [repos/](../repos) content.
- **Reset**: If [repos/](../repos) contains checked-out repositories from a previous session, you MUST run:

  ```bash
  task repos:reset
  ```

  *Exception*: If the user explicitly asks to continue from the previous state.

  **CRITICAL:** Because `task repos:reset` destroys uncommitted changes, **you MUST explicitly ask the user for permission** before running it. To do this safely, you must: 1) Suggest options for the user to save their changes (e.g., `git stash`, create a new branch, or move files to a different location), and 2) Ask the user to type the exact phrase "PROCEED WITH RESET" to confirm. Once confirmed, this task resets the target repo to the remote default branch (e.g. `main`) and wipes out other local branches.

**Why?**

Agents often leave repositories in detached HEAD states, with uncommitted changes, or on feature branches. Starting a new task on top of this unpredictable state leads to:

- Missing files (e.g., `iam.tf` not generated because the skill thought it existed).
- Merge conflicts.
- Committing unrelated changes.

## 2. Temporary File Protocol

**Prevent Accidental Commits**

All temporary files created for intermediate steps (PR bodies, logs, diffs, plans) MUST be scoped strictly to contexts within `tmp/<feature_branch>/`.

- **Bad**: `echo "desc" > pr_body.md` (Risks `git add .` picking it up)
- **Good**: `mkdir -p tmp/my_feature && echo "desc" > tmp/my_feature/pr_body.md`

**Rule**:

- ALWAYS create temp files in a branch-specific folder like `tmp/<feature_branch>/`.
- NEVER create temp files in the root or [src/](../src) directories.
- The `tmp/` directory is git-ignored by default.

## 3. Workspace Cleanup Protocol

**Managing Cache and Remote Clones**

To prevent the workspace from becoming bloated over time or to fully reset local Git states, utilize the built-in clean tasks:

- **`task clean`**: Removes local temporary artifacts, IDE cache (`.pytest_cache/`, `logs/`), Git worktrees (`worktrees/`), and clears the general `tmp/` directory. Suitable for day-to-day resets without losing previously cloned target repos.
- **`task repos:clean`**: Destructively removes all locally cloned repositories currently mapped inside [repos/](../repos). This mandates a fresh fetch over the network the next time a repository is needed. Use this when the local repository environment experiences irrecoverable git corruption.
