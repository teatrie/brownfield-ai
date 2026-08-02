---
name: docs-review
description: Audit, update, and clean repository documentation to extract learnings, remove redundancy, and keep CLAUDE.md strictly minimal.
---
# Documentation Review & Audit

You are a technical writer and systems auditor subagent. Your job is to extract new learnings, capture tech debt, deduplicate existing documentation, and tightly compress global context files.

**User hints:** $ARGUMENTS

---

## Step 0: Protocol Alignment

**Before taking any other action**, read and execute the instructions in
`.claude/skills/protocols/SKILL.md` to refresh your context and internalize the
core directives. This ensures you are fully aligned with the strict
repository standards while auditing the docs.

## Step 1: Harvest New Learnings & Tech Debt

**If invoked directly by the user**, ask:
"Did we encounter any new edge cases, prompt failures, or codebase hacks
recently that should be documented?"

**If invoked as part of an automated pipeline** (e.g., from `/auto-pr`
or `/ship`), skip the interactive prompt and proceed to scan recent git
diffs and conversation context for new learnings instead.

Based on any findings, categorize new information:

* **Learnings** ([docs/learnings.md](../../../../docs/learnings.md)): Technical implementation details, code-level edge cases, and bug resolutions.
* **Workflow Learnings** ([docs/workflow_learnings.md](../../../../docs/workflow_learnings.md)): Agent workflow gotchas, process hygiene, delegation, and CI pipeline quirks.
* **Tech Debt** ([docs/tech_debt.md](../../../../docs/tech_debt.md)): Codebase flaws, missing tests, organizational bad practices, structural hacks.

If the user mentions no new items, move forward.

## Step 1b: Prune Stale Learnings

Scan [docs/learnings.md](../../../../docs/learnings.md) and
[docs/workflow_learnings.md](../../../../docs/workflow_learnings.md) for
entries that should be removed. An entry is prunable when:

1. **Codified elsewhere**: The learning has been promoted to a rule in
   [CLAUDE.md](../../../../CLAUDE.md), a protocol doc (`docs/*.md`),
   `.claude/rules/`, `docs/container_security.md`, or
   `.claude/settings.json`. The rule supersedes the learning.
2. **Obsolete**: The tool, workflow, or constraint no longer exists
   (e.g., a removed skill, a deprecated Docker image, a one-time
   migration that is complete).
3. **Derivable from code**: The information can be determined by
   reading current source files (e.g., a Dockerfile entrypoint, a
   Taskfile target).

For each candidate, verify the codification target still contains the
rule before removing. Present the pruning list to the user for
approval before deleting (interactive mode). In headless mode
(`CI=true`), auto-prune entries meeting criteria 1 only (codified
elsewhere) — criteria 2 and 3 require judgment and are deferred.

## Step 2: Global Consistency & Redundancy Check

Scan the core documentation to ensure there is no state conflict or redundant bloating. Read through exactly these core layout files:

* [docs/learnings.md](../../../../docs/learnings.md)
* [docs/workflow_learnings.md](../../../../docs/workflow_learnings.md)
* [docs/delegation_protocol.md](../../../../docs/delegation_protocol.md)
* [docs/verification_protocol.md](../../../../docs/verification_protocol.md)
* [docs/planning_protocol.md](../../../../docs/planning_protocol.md)
* [docs/architecture.md](../../../../docs/architecture.md)
* [docs/tech_debt.md](../../../../docs/tech_debt.md)
* [docs/prompt_examples.md](../../../../docs/prompt_examples.md)
* Root [README.md](../../../../README.md)
* Any `README.md` files in subfolders
* All prompt templates in `workflows/*/prompts/` (e.g., `*.prompt.md`)
* Platform instruction files (e.g., `.github/copilot-instructions.md`,
  [CLAUDE.md](../../../../CLAUDE.md), `.gemini/` settings)

Perform the following audits:

1. **Contradictions**: Ensure no rules conflict (e.g., one doc allows something another doc prohibits).
1. **Redundancy**: Look for repeated rules across multiple files. Centralize rules into their single "source of truth". If a rule belongs in a specialized protocol doc, move it there and replace duplicates elsewhere with a link.
1. **Repository Links**: Ensure all references to repository files or folders use markdown links (e.g., `[docs/architecture.md](../../../../docs/architecture.md)`) instead of backtick-highlighted text (`` `docs/architecture.md` ``). Ignore variable names or external commands.
1. **Branch Links**: Ensure git branch names (e.g., `origin/main`, `ship/branch`) or untracked/transient files (e.g., `.gitignore`, `plan.md`) are represented strictly as inline backtick code blocks (e.g., `` `origin/main` ``) and NEVER hallucinated as markdown hyperlinks (e.g., ``origin/main``).
1. **Broken Links**: Scan for broken markdown links (e.g., hallucinated relative structures). Either 1) Fix the broken link if the *correct*, valid relative path is known and physically verified, or 2) Completely remove the broken link and revert it to an inline backtick reference if the proper path cannot be determined.
1. **Outdated Info**: Remove explicit mentions of deprecated processes, CLI toolings, or removed skill structures. Verify the "Directory Structure" section in [README.md](../../../../README.md) exactly maps to the actual current root and core subdirectories via `ls -la`.

## Step 3: Workflow Domain Conformance

With the introduction of Domain-Driven Design (DDD) in the `workflows/` directory, perform the following structural consistency checks:

1. Validate every `workflows/<domain-name>/CONTEXT.md`:
   * Ensure it contains a detailed description of the domain's purpose.
   * Verify it includes the `## Available Skills` index listing all skills actually present in that domain's `skills/` folder.
2. Review the skills within `workflows/<domain-name>/skills/`:
   * Is each skill physically located in the most appropriate logical domain?
   * Do they adhere strictly to formatting standards and `skill-creator` layout conventions?
3. Verify `workflows/INDEX.md` routes to all active domains correctly.
4. **Headless Session Handling**: Verify that every skill and protocol
   containing interactive gates — user prompts, approval waits,
   flag-to-user steps, browser/display interactions, or feedback
   collection — includes an explicit headless/non-interactive
   fallback. The fallback must follow the pattern established in
   [docs/verification_protocol.md](../../../../docs/verification_protocol.md)
   and the full convention in
   [docs/delegation_protocol.md §5](../../../../docs/delegation_protocol.md):
   detect headless mode and, if no explicit fallback is defined for
   the gate, **FAIL execution immediately** — never silently proceed
   or "pass with caveats." Acceptable fallbacks (checkpoint to the
   Execution Ledger, derive context from git diffs) must be explicitly
   defined per gate; the absence of a fallback is a hard failure.
   Headless detection uses a two-layer convention: (1) the `CI`
   environment variable at the infrastructure layer (set automatically
   in GitHub Actions, must be set by local callers for headless
   sessions), and (2) a prompt-level signal from the calling
   orchestrator or pipeline context at the skill layer. The default
   mode is interactive — headless mode is only active when explicitly
   signaled. Additionally, verify that any skill which delegates to
   subagents propagates the headless signal into every delegation
   prompt — the `CI` env var propagates automatically within the
   process tree but must be explicitly passed to Docker containers
   via `--env CI=true`. Flag any skill that lacks a fail-closed
   headless code path for its interactive gates when operating under
   headless signals, or that delegates without propagating the
   headless signal. Note: `docs-review`
   Step 1 already implements this pattern (interactive vs. automated
   pipeline branch) and serves as the canonical exemplar.

## Step 4: CLAUDE.md Minimization (CRITICAL)

[CLAUDE.md](../../../../CLAUDE.md) is loaded into every initial prompt context automatically. It MUST be extremely lean to preserve global token budget.

1. Read [CLAUDE.md](../../../../CLAUDE.md).
1. Identify verbose prose, specific edge-cases, or long lists of rules that can be offloaded.
1. Relocate heavy instructional sections into dedicated `docs/*.md` files and link to them centrally.
1. Strip conversational "fluff". Keep only absolute core invariants, architectural indexing, and top-level repository routing.

## Step 5: User-Facing Prompts Sync (`prompt_examples.md`)

1. Read [docs/prompt_examples.md](../../../../docs/prompt_examples.md) and compare it against the active `.claude/skills/` and `workflows/` directory tree.
1. The objective of `prompt_examples.md` is to teach humans how to interact with the AI via Natural Language.
1. Ensure all new or modified capabilities are properly categorized.
1. Write exact, practical "**English Prompt Examples**" for every skill, showing a developer exactly what conversational text they should type to trigger it effectively.

## Step 6: Propose & Implement

Present a concise Markdown plan of additions, relocations, and deletions to the user.
Wait for **explicit User Approval**.

**Headless mode** (`CI=true` or explicit pipeline signal): Auto-approve
the proposed changes. Checkpoint a `step_result` artifact to the
Execution Ledger with `{"step": "docs-review-approval", "verdict":
"auto-headless"}`. If the proposed changes include deletions of files
containing non-redundant content, fail-closed: checkpoint
`{"verdict": "fail", "reason": "destructive docs changes require
interactive approval"}` and halt.

Once approved:

1. Apply the file changes exactly as discussed (use edit capabilities or script writing).
1. Run standard local text validation checks.

```bash
task lint:markdown FILES="<changed_files>"
```

1. If linting fails (e.g. trailing whitespaces or list-indent issues), explicitly fix the errors and re-run the lint gate.

## Step 7: Finalize

Once all format gates pass cleanly, report completion to the user and
remind them they can use the `auto-pr` or `ship` skills to track and
deploy the documentation updates.
