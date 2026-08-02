# TDD Protocol — Red-Green-Refactor with Git Safety Net

This protocol is referenced by both the `tdd-execute` and `feature-epic` skills for the strict TDD loop.

## The 6-Step TDD Loop

### Step 1 — PRE: Record domain start SHA

```bash
DOMAIN_START_SHA=$(git rev-parse HEAD)
touch .tdd-active
```

### Step 2 — RED: Write failing tests & Verify Spec Coverage

- **Step 2.1: Test Generation**: Spawn `tdd-red` subagent with the domain plan.
  - The agent writes exhaustive tests.
  - **Traceability Requirement**: Every test function's docstring MUST explicitly cite the specific Requirement ID (e.g., `[Req-001]`) it covers from the `plan.md`.
- **Step 2.2: Execution Verification**: The Orchestrator spawns an `Executor` agent to run the tests. They MUST fail for the **RIGHT reason** (missing implementation/assertion failure, not syntax errors).
- **Step 2.3: Specification Traceability (Review)**: The Orchestrator spawns a `code-review` agent to perform a deterministic "Spec-to-Test" trace.
  - The Reviewer extracts all `[Req-XXX]` markers from the domain plan.
  - The Reviewer scans the written test file and maps the IDs mentioned in the docstrings.
  - If any ID from the plan is missing in the tests, or if a test contains tautological assertions (e.g., `assert True`), the Reviewer flags a FAIL.
- **Step 2.4: Resolution**: If the Reviewer issues a FAIL, the Orchestrator spawns a **new** `tdd-red` subagent. It provides the current test code and the exact missing `[Req-XXX]` IDs, instructing the agent to patch the gaps until the Reviewer confirms a 1:1 match.

**Ledger Checkpoint:** After the Reviewer confirms RED (tests fail for the right reason and spec traceability passes), the Orchestrator MUST checkpoint a `step_result` artifact to the Execution Ledger with `{"step": "RED", "verdict": "pass"}` and the Reviewer's confirmation summary.

### Step 3 — GREEN: Make tests pass with minimal code

- Spawn `tdd-green` subagent with failing tests + target files
- Agent writes **minimum code** to pass ALL tests.
  - **CRITICAL DEFINITION**: "Minimum code" strictly applies to functional logic. It does NOT mean removing or modifying required components like docstrings, typing hints, or internal comments. You MUST explicitly instruct the subagent to preserve all existing documentation blocks and `Args:` definitions during implementation.
- **Verification Protocol (Strict 3-Agent Boundary)**:
  To prevent confirmation bias, context drift, and "faked" success, the execution loop MUST be handled by **THREE STRICTLY ISOLATED AGENTS**:
  1. **Executor Agent (`task`)**: Exclusively runs the test runner (`pytest`, `make test`, `task test:staged`) and outputs the raw console logs. It does nothing else.
  2. **Reviewer Agent (`code-review`)**: Exclusively reads the raw logs provided by the Executor to confirm ALL tests genuinely pass. It does not run the tests or edit code.
  3. **Implementation Agent (`tdd-green` / `tdd-refactor`)**: If the Reviewer declares a FAIL, the Orchestrator passes the failure logs *back* to the Implementation Agent to fix the code. The Implementation Agent NEVER runs the tests directly.
- NEVER use inline linter bypasses (`# noqa`, `# type: ignore`, `# shellcheck disable`, `eslint-disable`, etc.) to "solve" linting errors. This is a severe protocol violation and will fail the CI gate. You must fix the underlying structural or type issue.
- Run the repository's lint auto-fix command (e.g., `task lint:fix` or `make fmt`) to auto-fix formatting and import ordering
- Run the repository's standard lint command (e.g., `task lint` or `make lint`) to confirm no remaining violations
  - If lint violations remain, fix them manually (using the same 3-Agent Boundary above: Executor runs lint, Reviewer checks logs, Implementer fixes code).
  - Type errors and security vulnerabilities are correctness issues

**Git checkpoint (unconditional):**

```bash
git add -A && git commit -m "chore: GREEN checkpoint — <domain>"
```

**Ledger Checkpoint:** After the GREEN git checkpoint, the Orchestrator MUST checkpoint a `step_result` artifact to the Execution Ledger with `{"step": "GREEN", "verdict": "pass"}` and the raw test output.

### Step 4 — REFACTOR: Clean the code (guarded by checkpoint)

**Refactor scope (priority order):**

1. Standards & conventions — match project patterns, language idioms
2. Simplicity — remove unnecessary complexity, dead code, premature abstractions
3. Readability & maintainability — clear naming, obvious flow
4. Performance — only for obvious inefficiencies, not speculative

**Constraints:**

- ONLY touch files written/modified in this domain
- Do NOT add abstractions, helpers, or "improvements" beyond scope
- Do NOT touch unrelated files

**Verification**: After refactoring, use the **Double-Check Verification Protocol** (Executor runs tests, Reviewer confirms pass) to ensure no regressions.

**Ledger Checkpoint:** After the Reviewer confirms REFACTOR tests still pass, the Orchestrator MUST checkpoint a `step_result` artifact to the Execution Ledger with `{"step": "REFACTOR", "verdict": "pass"}` and the raw test output.

### Step 5 — QUALITY ASSURANCE PHASE (QA Phase)

After the Refactor phase, the orchestrator MUST delegate to subagents to perform the following Quality Gates:

1. **Code Standards Review (`qa-standards` subagent)**: Analyze code changes against [docs/coding_standards.md](../../../docs/coding_standards.md) and `CLAUDE.md`. The subagent fixes/refactors code to ensure strict adherence. It reports back to the Orchestrator what changes were made.
2. **Lint Validation (`qa-lint` subagent)**: The Orchestrator explicitly stages modified files (`git add`) and delegates to a new subagent to cleanly run the repository's lint auto-fix command (e.g., `task lint` / `task lint:staged`). The subagent must resolve all lint issues and report back to the Orchestrator.
3. **Test Verification Loop (`qa-test` subagent)**: If changes were made in Step 1 or Step 2, the Orchestrator ensures files are staged and delegates to a new subagent to run all tests (`task test` / `task test:staged`).
   - The subagent attempts to resolve all test failures.
   - **CRITICAL**: If the subagent fails to resolve a test failure after 3 turns (attempts), it MUST stop and move on to the next test.
   - Once all tests have been run, the subagent reports back to the Orchestrator with any remaining test failures.
4. **Escalation / Handoff**:
   - If there are test failures remaining, the Orchestrator evaluates if another attempt by a higher-tier subagent (e.g., `qa-test-escalation`) is warranted.
   - If yes, repeat Step 3 with the new subagent and the list of test failures.
   - If the escalated subagent also fails, the Orchestrator MUST stop and notify the User of unresolved test failures.
5. **Proceed**: If all tests have passed (GREEN), proceed to the next phase (POST).

### Step 6 — POST: Soft reset and domain commit

```bash
rm .tdd-active
git reset --soft $DOMAIN_START_SHA
# All domain changes now staged (no checkpoint clutter)
git commit -m "feat(<domain>): <description>"
```

**Step Verification Requirement:** After finishing this 6-step loop for a domain, you MUST independently stop to read `plan.md` to update progress, parse [CLAUDE.md](../../../CLAUDE.md) to verify all coding standards and protocols, and re-run all pipeline gates (`task test` and `task lint`) before moving to the next task. After gates pass, checkpoint a `step_result` artifact to the Execution Ledger with the domain name, raw stdout, and verdict (`pass`/`fail`).

## Rules

- GREEN checkpoint is **UNCONDITIONAL** — always commit before refactor
- Never `--amend` the checkpoint — it's immutable until soft reset
- Escalated agent gets clean slate (GREEN code), not the failed attempt's diff
- If all 3 refactor attempts fail, ship the GREEN code — working beats perfect
