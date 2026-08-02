---
name: claude-review
description: Reviews the .claude folder (skills and agents) for consistency, correctness, and redundancy against repository protocols.
---

# 🤖 Claude Meta-Review

This skill reviews the [.claude/](../..) directory to ensure all custom agents and skills are consistent, correct, strictly aligned with repository protocols, and free of redundancy.

## Execution Steps

0. **Protocol Alignment**: Read and execute the instructions in
   `.claude/skills/protocols/SKILL.md` as your very first step. This ensures
   you have refreshed your context on the repository's strict
   operational rules before beginning your review.
1. **Scan the Landscape**: Read and analyze the contents of
   [.claude/skills/](../../../../.claude/skills),
   [.claude/agents/](../../../../.claude/agents), and
   [.claude/rules/](../../../../.claude/rules). Also scan
   `.github/instructions/` for the Copilot counterparts.
2. **Align with Protocols**: Cross-reference the skills and agents against [CLAUDE.md](../../../../CLAUDE.md) and the auxiliary protocols in [docs/](../../../../docs) (e.g., `delegation_protocol.md`, `verification_protocol.md`).
3. **Identify Third-Party vs. Internal**:
   - Check if the skill resides under a `third-party/` intermediate directory (e.g., `workflows/<domain>/skills/third-party/<skill>`).
   - Alternatively, check the directory of each skill for any file matching `*LICENSE*` or `*NOTICE*` (case-insensitive, e.g., `LICENSE`, `LICENSE.txt`, `license.md`).
   - If either condition is met, treat the skill as a **Third-Party Skill**.
   - Otherwise, treat it as an **Internal Skill**.
4. **Enforce and Update**:
   - **Internal Skills**: Automatically fix identified inconsistencies, stylistic errors, and structural redundancies. You MUST enforce the following rules:
     - **AWS Authentication Compliance**: Scan all skills that interact with AWS (e.g., executing AWS CLI commands or running AWS-dependent Docker containers).
       - **Enforce Pre-flight Auth**: Ensure the skill explicitly mandates the **Pre-flight Authentication** directive (invoking the `aws-vault-auth` skill to extract `AWS_ACCESS_KEY_ID`, etc., and injecting those variables directly into the sub-agent or Docker command). Update the skill's instructions to strictly adhere to this if it is missing.
       - **Lazy Auth Enforcement**: Ensure skills rely on the Lazy Auth loop (catching `ExpiredToken` or `AccessDenied` from subagents and re-invoking `aws-vault-auth` to retry) rather than eagerly fetching credentials on every single execution.
     - **Repository Links**: Ensure all references to repository files or folders use markdown links with valid relative paths (e.g., `[docs/architecture.md](../../../../docs/architecture.md)`). Ignore variable names or external commands.
     - **Branch Links**: Ensure git branch names (e.g., `origin/main`, `ship/branch`) or untracked/transient files (e.g., `.gitignore`, `plan.md`) are represented strictly as inline backtick code blocks and NEVER hallucinated as markdown hyperlinks.
     - **Broken Links**: Scan for broken markdown links (e.g., hallucinated relative structures). Either 1) Fix the broken link if the *correct*, valid relative path is known and physically verified, or 2) Completely remove the broken link and revert it to an inline backtick reference if the proper path cannot be determined.

   - **Platform Rule File Consistency**: Scan `.claude/rules/` and
     `.github/instructions/` to verify:
     - **Pairing**: Every `.claude/rules/<name>.md` must have a
       corresponding `.github/instructions/<name>.instructions.md`
       (and vice versa). Flag unpaired files. Language rules (e.g.,
       `lang.python.md`) are exempt from requiring a Copilot counterpart
       when the `paths:` glob provides sufficient scoping — do NOT flag
       these as unpaired.
     - **Naming convention**: Rule files use a namespaced prefix:
       `repos.<repo>.<scope>.md` / `repos.<repo>.<scope>.instructions.md`
       for repository-scoped constraints (e.g.,
       `repos.analytics.datalake.md`), and `lang.<language>.md` for
       cross-cutting language standards (e.g., `lang.python.md`).
     - **Pattern alignment**: The `paths:` YAML list in
       `.claude/rules/` must be functionally equivalent to the
       comma-separated `applyTo` glob string in the corresponding
       `.github/instructions/` file.
     - **Content parity**: Substantive rules (constraints, lint/test
       commands, conventions) must be equivalent across both files.
     - **Validation routing**: Custom lint/test commands in rules
       must be consistent with `taskfiles/repos/<repo>.yml` definitions.

   - **Redundancy & Conflict Checks**: Identify if multiple skills are trying to perform the exact same task, or if new skills conflict with existing ones.
   - **Protocol Enforcement (`CLAUDE.md`)**: Ensure skills don't violate core rules like formatting, delegation constraints, or sandbox boundaries.
   - **Headless Session Compliance**: Scan all skills for interactive
     gates — user prompts, approval waits, flag-to-user steps, browser/
     display interactions, or feedback collection loops. For each gate
     found, verify that the skill includes an explicit headless/non-
     interactive fallback directive. If no fallback is defined for a
     gate, the skill MUST **FAIL execution** in headless mode — never
     silently proceed or "pass with caveats." Acceptable fallbacks must
     be explicitly defined per gate and align with the pattern in
     [docs/verification_protocol.md](../../../../docs/verification_protocol.md)
     and the full convention in
     [docs/delegation_protocol.md §5](../../../../docs/delegation_protocol.md):
     detect headless mode, derive context from git diffs or conversation
     history, checkpoint results to the Execution Ledger, and halt on
     unresolvable blockers. Headless detection uses a two-layer
     convention: the `CI` environment variable at the infrastructure
     layer, and a prompt-level signal at the skill layer (e.g., the
     calling orchestrator includes headless context in the delegation
     prompt, or the skill detects pipeline invocation like `/auto-pr`).
     The default mode is interactive — headless mode is only active when
     explicitly signaled. Additionally, verify that any skill which
     delegates to subagents propagates the headless signal into every
     delegation prompt — the `CI` env var propagates automatically
     within the process tree but must be explicitly passed to Docker
     containers via `--env CI=true`. Flag any skill that lacks fail-
     closed headless handling for its interactive gates when operating
     under headless signals, or that delegates without propagating the
     headless signal.
     - **New Skill Evaluation** (defense-in-depth): When reviewing a
       newly created skill, additionally evaluate whether the skill is
       likely to be invoked in headless sessions (e.g., subagent
       delegation, `claude -p`, automated pipelines). If headless
       likelihood is ambiguous, flag the skill and present the User
       with options: (1) add a fail-closed halt at each gate, (2) add
       explicit fallback logic per gate (checkpoint to ledger, derive
       from context), or (3) mark the skill as interactive-only. Never
       silently assume interactive-only. Note: this is a downstream
       safety net — the primary creation-time gate is in the `skill-creator` skill.

   - *Exception*: If a fix requires a severe conceptual change or is a major violation of protocols, **DO NOT** update it automatically. Flag it to the User.
   - **Third-Party Skills**: **DO NOT** make automatic updates under any circumstances. Identify issues and flag them to the User for review and consent.
5. **Summarize**: Output a structured report detailing:
   - Skills/Agents automatically updated.
   - Third-Party Skills reviewed (with flagged issues).
   - Any severe violations requiring user intervention.
