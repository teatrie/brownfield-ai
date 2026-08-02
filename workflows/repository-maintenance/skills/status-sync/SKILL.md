---
name: status-sync
description: "Review project state, pause, and resume epics across machines by managing remote branches and the Execution Ledger. Triggered via `/status`, `/status pause`, or `/status resume <branch>`."
---

# `status-sync`

This skill handles seamlessly pausing an in-progress epic to be resumed later (often on another machine) by capturing the current state, and conversely, resuming a paused epic from a remote branch.

## Supported Commands

- `/status`: Queries the Execution Ledger (`execution-ledger index-epics`) to report current progress, active epics, and backlog items.
- `/status pause`: Captures the current active epic, creates a branch, forcefully adds the untracked `plan.md`, pushes the branch to remote, and checkpoints the pause to the Execution Ledger.
- `/status resume <branch>`: Fetches and checks out the specified remote branch, restoring `plan.md` and allowing the user/agent to pick up exactly where they left off.

## Execution Protocol

### When `/status` is invoked or a user asks for progress

1. The agent MUST immediately query the Execution Ledger (`execution-ledger index-epics`).
2. Report purely factual updates on current active epics, backlog, and completed iterations based on the ledger.
3. Check the environment variables in the terminal and accurately report their status along with the project status:

   **Environment Status:**
   - `AWS_PROFILE`: [value or 'Not Set']
   - `AWS_REDSHIFT_DB_USER`: [value or 'Not Set']
   - `USER_EMAIL`: [value or 'Not Set']
   - `GH_TOKEN`: [Set / Not Set] *(Do not display the actual token value)*

### When `/status pause` is invoked

1. Identify the current epic from `plan.md` or conversation context.
2. Ask the user for a branch name (e.g., `feature/epic-name`).
   - **Headless** (`CI=true`): Derive branch name from the epic ID
     (e.g., `pause/<epic-id>`). If the epic ID cannot be determined,
     fail-closed.
3. Run `git checkout -b <branch-name>`.
4. Run `git add -f plan.md` to ensure the current plan is tracked.
5. Ask the user for a commit message (or auto-generate a WIP commit).
   - **Headless** (`CI=true`): Auto-generate a WIP commit message
     (e.g., `"chore: pause epic <epic-id> — headless session"`).
6. Run `git commit -m "chore: pause epic and save plan.md state"`.
7. Run `git push -u origin <branch-name>`.
8. Checkpoint the pause to the Execution Ledger as a `design_decision` artifact with the branch name and context.
9. Inform the user the active progress has been paused and synced to origin.

### When `/status resume <branch>` is invoked

1. Run `git fetch origin`.
2. Run `git checkout <branch>`.
3. Run `git rm --cached plan.md` to stop tracking it in the branch (ensuring it doesn't accidentally get merged into main later), while leaving the local file intact for the current session.
4. Read the restored `plan.md` to understand the epic's context.
5. Query the Execution Ledger (`execution-ledger resume <epic-id>`) to realign with the epic's full context.
6. Provide a summary of the remaining tasks and ask the user to confirm starting the next step.
   - **Headless** (`CI=true`): Auto-proceed after presenting the summary.
     The caller is responsible for determining execution scope.
