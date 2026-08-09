# Workflow Requirement

**CRITICAL CONSTRAINT: Artifacts & Logs**
NEVER use the OS absolute `/tmp/` directory for scratch files, bash redirections, or terminal outputs. ALWAYS route these strictly to the workspace-relative `tmp/` directory (e.g., `> tmp/output.log`). **If a system tool or API throws a "Permission Denied" or "User Approval Required" error for modifying files outside the workspace, you MUST treat it as a hard failure of context drift.** Immediately abort, read [docs/learnings.md](../docs/learnings.md), refocus via the [protocols skill](../.claude/skills/protocols/SKILL.md), and then rewrite your paths to be exclusively relative to `$PWD`. Using `/tmp/` causes permission blocks that break the autopilot execution loop.

**Error Recovery & Context Drift:**
If you find yourself stuck in a loop, encountering repetitive errors, or losing context of the architectural constraints, you MUST stop execution, physically read [docs/learnings.md](../docs/learnings.md), and completely review the [protocols skill](../.claude/skills/protocols/SKILL.md) to violently realign and refocus before attempting another fix.

**No Linter Bypasses**: The use of `# noqa`, `# type: ignore`, `# shellcheck disable`, `eslint-disable`, or any other inline linter suppression comment is STRICTLY FORBIDDEN. You must actually fix the issue.

At the end of every task or plan step, you MUST independently stop to:

1. Read the `plan.md` to update progress.
2. Read [CLAUDE.md](../CLAUDE.md) to verify all coding standards and core protocols.
3. **Verify Pipeline State:**
   - **If the step was executed via a formal skill** (e.g., the [tdd-execute skill](../.claude/skills/tdd-execute/SKILL.md)) that already completed its mandated QA Phase, simply review and confirm those results.
   - **For all other ad-hoc coding tasks**, you MUST stage the specific files you modified (`git add <files>`), then **delegate** execution of `task lint:staged` and `task test:staged` to an isolated sub-agent (e.g., `qa-lint` or `test` runner). **NEVER** run tests, lints, or builds directly. You must verify the sub-agent passed the pipeline gates before declaring the step complete. Pre-push gates in `auto-pr` and `ship` use `task lint:changed` / `task test:changed` (branch diff vs main) for broader coverage. **Exception:** You may omit `task test:staged` **only** when modifications are strictly limited to Markdown/Documentation files **and** no routing branch in `ci/test_staged.sh` maps any staged path to a test target — Markdown is not self-evidently untested (reviewer prompts, rubrics, and agent definitions all route to tests), so confirm the routing before skipping rather than inferring it from file extensions. Either way, ensure any temporary scratch files (like Python builder scripts) are deleted before running `task lint:staged` to prevent unrelated pipeline checks.
   - **Ad-Hoc Scripts (Anti-Monolith Guard):** If you (the Orchestrator) generated a temporary Python or bash script to modify files, fix lint errors, or bypass tests on your own, you are in violation of protocol. You MUST delegate the creation and execution of that script to an implementer subagent. Any such script MUST be reviewed by a `code-review` subagent, who is instructed to specifically reject the script if the Orchestrator wrote it instead of an implementer.
4. **Execution Ledger Checkpoint:** After lint/test verification passes, checkpoint a `step_result` artifact to the Execution Ledger with the raw stdout and verdict (`pass`/`fail`). When resuming work on an in-progress epic, query the ledger to bootstrap context. See the [execution-ledger SKILL.md](../workflows/agent-memory/skills/execution-ledger/SKILL.md) for canonical CLI commands.
5. **Structural Conformance (Skills & Routing):**
   - If the task involved modifying, creating, or deleting files in `.claude/skills/` or `workflows/`, you MUST trigger the `docs-review` and `claude-review` skills BEFORE completing the session to ensure master routers, constraints, and dependencies are mathematically aligned.

## Execution Ledger

The Execution Ledger is the authoritative, persistent project registry backed by ChromaDB. It records plans, design decisions, gate verdicts, step results, wave summaries, and PR lifecycle events for every epic. `plan.md` remains the ephemeral session scratchpad, but the ledger is the source of truth for cross-session resumability and audit.

**Mandatory interactions:**

- **Session Start**: Query the ledger (`task ledger:index` and `task ledger:resume`) to align with current epics before starting work.
- **Step Completion**: After each step's lint/test verification passes, checkpoint a `step_result` artifact.
- **Gate Verdicts**: After Dual-Model Review Gate verdicts, checkpoint `gate_verdict` artifacts (one per reviewer).
- **Wave/Epic Completion**: Checkpoint `wave_summary` artifacts after each wave; update epic status to `completed` at epic end.
- **PR Lifecycle**: After PR creation, checkpoint `pr_created`; after merge, checkpoint `pr_merged`.

See [docs/planning_protocol.md](../docs/planning_protocol.md) and [docs/verification_protocol.md](../docs/verification_protocol.md) for full ledger checkpoint protocols. See [execution-ledger SKILL.md](../workflows/agent-memory/skills/execution-ledger/SKILL.md) for CLI commands and artifact schemas.
