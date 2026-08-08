# Double-Check Verification Protocol

To prevent bias, context corruption, and hallucinations, the Orchestrator (Execution Lead) must **NEVER** directly run or self-validate tests, linters, or critical checks. Instead, strict separation of duties is enforced.

See [CLAUDE.md](../CLAUDE.md) for core principles and architectural index. For term definitions (Executor, Reviewer, Regression gate, etc.), see the [Glossary](glossary.md).

## No Faking / Hallucinated Success

Never fake schemas, dummy data, bypass critical dependency checks, or artificially force a command to pass. If an underlying tool, API, directory (e.g. missing target repo in [repos/](../repos)), or requirement is absent, diagnose the *root cause* or halt and ask for help. A "fake pass" or "fallback hallucination" (where an agent looks at the wrong directory to salvage an answer) introduces catastrophic tech debt.

- **Prohibition on Semantic Overrides**: You must never inject meaningless, generic placeholder strings (e.g., `"""Module doc."""` or `"""Process data."""`) globally or ad-hoc just to satisfy Pydocstyle, typing, or linting constraints. Context must always be preserved.
- **Review of Ad-Hoc Scripts (Anti-Monolith Guard)**: If any scratch script (Python, Bash, etc.) is written to "bulk fix" an issue or blindly bypass a pipeline gate within the `./tmp/` directory, a `code-review` agent MUST verify the contents of that script before the Orchestrator pipes it to the terminal. **CRITICALLY**: The `code-review` agent must verify *who* wrote the script. If the Orchestrator generated the script itself instead of delegating the script-writing to an implementer sub-agent, the `code-review` agent MUST flag this as a critical violation of the delegation protocol, reject the script, and force the Orchestrator to delete it and delegate appropriately.

## Review Finding Resolution Mandate

**All review findings must be resolved — no exceptions.** This directive
applies universally to every code review, regardless of how it is
invoked: the `/diff-review` skill, ad-hoc `code-review` agents, post-wave
quality reviews, or any other reviewer delegation.

- The Orchestrator MUST NOT silently dismiss, defer, or downgrade any
  finding. Findings requiring code changes MUST be delegated to an
  implementer subagent. Findings the Orchestrator believes require no
  action MUST go through the
  [Finding Resolution Review](#finding-resolution-review) for
  independent validation.
- Findings resolved via documentation updates or TODO capture (`doc-or-todo`)
  are real resolutions — but they still require reviewer consensus via
  the Finding Resolution Review. The Orchestrator MUST NOT self-declare
  that a TODO or doc update suffices; reviewers must independently agree
  that the tracking mechanism adequately captures the issue and that
  deferral does not create unacceptable risk.
- "Non-blocking", "informational", and "minor" severity labels do not
  exempt a finding from resolution. Every finding is resolved or
  validated — none are dropped.
- Self-dismissal of findings collapses the 3-agent verification
  boundary and is a protocol violation equivalent to the Orchestrator
  writing code directly.

## Step Verification Protocol

At the end of every individual step in a multi-step plan, the Lead Agent/Orchestrator MUST independently stop to read `plan.md` to update progress. Then, the Orchestrator MUST explicitly stage modified files (`task git:add`) and invoke the `task` subagent to run `task lint:staged` and `task test:staged` to verify ONLY the staged files against pipeline gates before declaring the step complete. `task test:staged` may be omitted **only** when the change is docs-only **and** no routing branch in `ci/test_staged.sh` maps any staged path to a test target — Markdown is not self-evidently untested (reviewer prompts, rubrics, and agent definitions all route to tests), so confirm the routing before skipping rather than inferring it from file extensions. *The Orchestrator must NEVER run these commands directly in its own interactive terminal.*

### Infrastructure Failure Handling

If `task lint:staged`, `task test:staged`, or any pipeline gate command
(including repo-specific equivalents such as `task <repo>:lint`
and pre-push gates like `task lint:changed` / `task test:changed`) fails due
to infrastructure issues rather than code quality violations, the QA gate MUST
be marked as **FAIL** — not silently passed or ignored. The Orchestrator MUST
NOT treat infrastructure failures as "pass with caveats."

Infrastructure failure signals include: non-zero exit from Docker with no
lint/test output, TLS/SSL handshake errors in stderr, `docker compose`
`ContainerNotFound` or image build failures, and network timeouts during
dependency pulls.

**Interactive sessions** (user present): The Orchestrator MUST present the
user with two options:

1. **Address and re-run**: The user resolves the infrastructure issue (e.g.,
   rebuilds Docker images, fixes network configuration) and instructs the
   Orchestrator to re-run the QA gate from the beginning.
2. **Manual QA approval**: The user performs the necessary QA steps manually
   outside the agent session. The Orchestrator MUST present the exact commands
   the user needs to run (e.g., `task lint:staged`, `task test:staged`, or
   the full `task lint` / `task test` equivalents). The user confirms the
   commands passed and explicitly approves the QA gate. The Orchestrator
   records the gate as "PASS (manual — user-approved)" in any ledger
   checkpoint. This approval path is a weakened gate and MUST NOT become a
   routine bypass for failing pipelines.

**Headless sessions** (no user present, e.g., `claude -p` or bot-driven
execution): The Orchestrator MUST retry the failing command once after a
10-second pause. If the retry also fails, the Orchestrator MUST:

1. Checkpoint a `step_result` artifact to the Execution Ledger with
   `verdict: fail` and the full infrastructure error output in the body.
2. Halt execution. Do NOT proceed past the QA gate.
3. The next session (human or bot) resumes via `execution-ledger resume`
   and sees the infrastructure failure context for diagnosis.

The Orchestrator MUST NOT proceed past the QA gate without resolution in
either mode. Skipping the gate or treating the failure as a soft warning
violates the No Faking protocol (Principle 7).

## Repository Context Discovery (Important)

Because this `brownfield-ai` repository clones other target repositories under `repos/*`, **the Executor must first examine the specific repository it is working in to determine what build tool is being used.**

Many repositories will use **Make** (`Makefile`, `makefile.defs`) or **Task** ([Taskfile.yml](../Taskfile.yml)), or have specific CI scripts. The agent **must determine** what test, lint, and build targets are supported by the build tool in the repository and call them appropriately (e.g., `task lint`, `make test`, `make fmt`, etc.) rather than assuming a universal command.

## Roles

1. **Orchestrator (Execution Lead)**:
    - **Role**: Delegator and Verification Manager.
    - **Prohibited**: Writing code (implementation) or running validation commands directly.
    - **Responsibility**: Manages the verification tasks, delegates implementation, grants/revokes permissions, and acts on consensus between Executor and Reviewer.

2. **Executor (Agent A)**:
    - **Type**: `task` (or `general-purpose` for complex setups).
    - **Role**: Discovers the correct build tool/commands for the target repo, and executes the validation command.
    - **Output**: Returns raw stdout/stderr and a preliminary status (Pass/Fail).

3. **Reviewer (Agent B)**:
    - **Type**: `code-review` (or `explore`).
    - **Role**: Analyzes the **output** produced by the Executor, but MUST NOT trust the Executor's summary blindly.
    - **Anti-Faking Duty**: The Reviewer MUST inspect the actual artifacts produced (e.g., the actual file diffs, the contents of generated sql files, the raw JSON outputs) to check for "hallucinated success"—such as hardcoded dummy schemas (`CREATE TABLE dummy`), faked configurations, or artificially skipped steps.
    - **Delegation Enforcement**: If asked to review an ad-hoc helper script, the Reviewer MUST identify who wrote it. If the Orchestrator/Primary Agent wrote it directly, the Reviewer MUST actively reject the request, citing a violation of the Mandatory Delegation rule, and instruct the Orchestrator to delegate the drafting of the script to a worker agent.
    - **Source Verification**: If reviewing research, the Reviewer MUST enforce that the Executor cites precise, verifiable file paths. If the task required checking `repo A` but the Executor cites files from `repo B` (a common fallback hallucination when a directory is missing), the Reviewer MUST reject it.
    - **Goal**: Detects "false positives" (e.g., exit code 0 but error logs present), skipped validation/endpoints, "fake/bypassed" generated files, and context substitutions.

## Workflow (Strict 3-Agent Boundary)

To prevent code corruption and cheating, the lifecycle of execution, review, and resolution MUST be isolated across **THREE DISTINCT AGENTS**:

1. **Delegate Execution (Agent 1: Executor)**:
    The Orchestrator calls the **Executor** agent (`task`) to run the command. The Executor NEVER writes code.
    > "Examine the repo build configuration to find the lint command, then run it and report the raw output."

2. **Delegate Review (Agent 2: Reviewer)**:
    The Orchestrator takes the output from the Executor **and points to the generated file artifacts** and passes it to the **Reviewer** agent (`code-review`).
    > "Analyze this build output and the git diff for these specific generated files. Are there any errors, warnings, or ignored failures? Look intensely for faked data (e.g., dummy variables, mocked schemas) instead of actual generated values. Does it meet the criteria for a PASS?"

3. **Consensus Check & Resolution (Agent 3: Implementer)**:
    - **PASS**: Both Executor and Reviewer confirm success.
    - **FAIL**: If the Reviewer reports an issue, the task is considered failed. The Orchestrator MUST pass the failure logs to a **THIRD** entirely separate agent (`tdd-green`, `tdd-refactor`, or `bug-fix`) to write the code fix. The Implementer Agent must NEVER run the test itself.

4. **End-to-End Pipeline Verification**:
    After unit tests pass, the Executor MUST run the broader integration or CI wrapper commands (e.g., `task test`, `task test:skills:changed`) to ensure the changes did not break the downstream CI environment or trigger multi-file/integration bugs.

## QA Phase Orchestration Loop

Once functionality is deemed feature-complete, the Orchestrator must enforce a strict QA orchestration loop before finalizing the branch or artifact:

1. **Pipeline Gate Execution**: The Orchestrator delegates a forced baseline CI execution (e.g., `task lint` and `task test`) to a subagent to ensure zero regressions in isolated Docker environments.
2. **Hard Assert Review**: A `code-review` agent ensures that sandbox test validations assert real state changes (e.g., network hits or DB mutations) and have not hard-coded positive mock assertions (e.g., skipping tests with `assert True`).
3. **Drift and State Verification**: If infrastructure (Terraform) or database schemas are modified, the Orchestrator designates a `task` agent to run dry-run plans (`terraform plan`) and validates against any unmerged concurrent PR deployments.
4. **Resolution Cycling**: Any test failure, explicit linter warning, or coverage drop loops immediately back to the Implementer agent for rectification until a clean pass occurs cleanly across all checks.

## Structural Review Finding Enforcement

When `docs-review` or `claude-review` agents produce findings, the
Orchestrator MUST NOT self-assess those findings as "acceptable" or "design
trade-offs" and proceed. Self-dismissal collapses the 3-agent verification
boundary
([Workflow (Strict 3-Agent Boundary)](#workflow-strict-3-agent-boundary)
above) by having the Orchestrator act as both delegator and reviewer.

- **Interactive mode**: Present ALL findings to the user with the
  reviewer's original severity classification. The Orchestrator may add
  context but MUST NOT downgrade severity or recommend dismissal.
- **Headless mode**: Apply the
  [Finding Resolution Review](#finding-resolution-review) process.
  Findings requiring code changes MUST be delegated to an implementer
  subagent per the [Delegation Protocol](delegation_protocol.md) —
  the Orchestrator MUST NOT apply fixes directly, even for minor
  changes. Findings the Orchestrator believes require no action are
  submitted to the resolution review for independent validation.

  **Escalating resolution for code-change findings**: The Orchestrator
  selects the starting model tier based on the complexity of the
  finding (e.g., a simple formatting fix starts at `fast-*`; a
  multi-file security fix starts at `medium` or `high-reasoning`).
  Escalation follows the 1-per-matrix-point rule defined in the
  [Failure Escalation Protocol](../.claude/skills/agent-team/SKILL.md#failure-escalation-protocol):
  each unique (model tier, effort variant) combination gets exactly
  1 attempt. The Orchestrator may skip lower matrix points when the
  finding clearly exceeds their capability. Skipped points do not
  count toward the attempt budget. Only after the highest matrix
  point is exhausted does the gate fail. Checkpoint a `step_result`
  artifact with `verdict: fail`, the full findings, and the exhausted
  matrix path, then halt.

## Execution Ledger Checkpoints

After each Dual-Model Review Gate verdict is rendered → the Orchestrator MUST
checkpoint a `gate_verdict` artifact to the execution ledger per reviewer (two
documents total) with the verdict (APPROVED, APPROVED WITH NOTES, or BLOCKED),
`agent_model` identifier, and full reasoning in the artifact body.

After each step's verification completes (lint/test execution) → checkpoint a
`step_result` artifact with the raw lint/test stdout in the body and
`verdict` set to `pass` or `fail`.

After each wave completes execution → checkpoint a `wave_summary` artifact
documenting all domains executed in the wave, overall status, and elapsed
duration.

After the per-wave code quality review completes → checkpoint a
`gate_verdict` artifact with `step` set to `wave-N-quality-review`,
the single reviewer's verdict, and findings summary in the body.

After the regression gate verdict is finalized → checkpoint `gate_verdict`
artifacts (two documents, one per reviewer) to record the final verdict and
reasoning for the full test suite run.

After a PR is created via the `auto-pr` or `ship` skill → checkpoint a
`pr_created` artifact with metadata: `pr_url`, `branch`, `jira_ticket`.

After a PR is merged → checkpoint a `pr_merged` artifact with metadata:
`pr_number`, `merge_sha`.

After the Code Diff Review Gate verdict is finalized (when `epic_id` is
present) → checkpoint `gate_verdict` artifacts (two documents, one per reviewer)
keyed on `epic_id`, recording the final code-quality verdict and reasoning for
the full diff review. When the Cross-Family Review Extension is active, checkpoint
one `gate_verdict` artifact per active reviewer (N total — one per Claude reviewer
plus one per active bridge agent). Bridge agent artifacts MUST include the
appropriate `reviewer_platform` metadata (`copilot-bridge`, `gemini-bridge`, or `codex-bridge`).

### Canonical Artifact Schemas

All artifacts accumulate by default (each checkpoint creates a new document).
The exceptions are `plan_snapshot` and `requirement_map`, which supersede
previous versions.

| Artifact Type | Required Metadata | Accumulates/Supersedes |
|---|---|---|
| `step_result` | `verdict` (`pass`/`fail`), raw stdout in body | Accumulates |
| `gate_verdict` | `verdict` (see [§Dual-Model Review Gate](#dual-model-review-gate)), `agent_model`, `epic_id` (optional), `reviewer_platform` (optional), `step` (optional — e.g., `wave-N-quality-review`, `spec-verification`) | Accumulates |
| `wave_summary` | domains executed, overall status, elapsed duration | Accumulates |
| `plan_snapshot` | `version` (incremented on mutation) | Supersedes |
| `requirement_map` | Req-ID to description mapping | Supersedes |
| `design_decision` | rationale in body | Accumulates |
| `pr_created` | `pr_url`, `branch`, `jira_ticket` | Accumulates |
| `pr_merged` | `pr_number`, `merge_sha` | Accumulates |
| `ci_resolution` | `verdict` (`pass`/`fail`), `pr_ref`. Body contains CI Gate Resolution Log. | Accumulates |
| `pr_changes_required` | `epic_id`. Body contains per-repo summary (repo, PR ref, reviewer names, status). | Accumulates |

`gate_verdict` body contains full reviewer reasoning and may include
extended review criteria (performance, readability, Boy Scout Rule) per
the diff-review prompt. Checkpoints pre-PR #127 lack these categories.

**Envelope embedding (post-W4)**: when the reviewer is in the active
per-wave migration allowlist (i.e., emits an Output Envelope), the
`gate_verdict` body MAY embed the parsed `Envelope` JSON alongside the
prose reasoning. Embedding is OPTIONAL but RECOMMENDED — it lets
resumed sessions and post-hoc auditors see the exact discrete fields
that drove the merge decision (next_action, recommended_next_tier,
halt_trigger, per-finding severity/blocking) without re-parsing the
original LLM output. The full `MergeDecision` (action, feedback list,
audit_note, cross_family_dissent reference) MAY also be embedded for
the same reason.

## Dual-Model Review Gate

Applies to: plan reviews, post-wave verification gates, and final regression gates. Two independent reviewers must both pass GREEN before the gate clears.

### Reviewer Model Selection (platform-aware)

The Planner or Orchestrator selects the two best available models on the platform — or more when the Cross-Family Review
Extension is active (see below) — the highest-tier and the second-highest-tier. When cross-family models are available,
one reviewer MUST be cross-family.

| Platform | Reviewer 1 | Reviewer 2 | Additional Reviewers |
|---|---|---|---|
| Cross-family available (e.g., Copilot session) | Highest-tier available | Highest-tier cross-family model | — |
| Single-family only (e.g., Claude Code) | `high-reasoning` tier | `medium` tier | — |
| Claude Code + one bridge agent available | Opus (`high-reasoning`) | Sonnet (`medium`) | Bridge agent (3-of-3) |
| Claude Code + multiple bridge agents available | Opus (`high-reasoning`) | Sonnet (`medium`) | Each active bridge agent (N-of-N) |
| Single model only | Same model, two separate agents | Same model, two separate agents | — |

Examples: On Claude Code — Opus + Sonnet. On Copilot — Opus + GPT, or Opus + Gemini Pro. The Planner/Orchestrator decides
the best combination at runtime.

**Reviewer effort (S-4 R2 — planner-pin authoritative above the floor)**:
Spawn two independent `code-review-{tier}` agents where `{tier}` is the
planner-pinned `reviewer_effort_tier` from `plan.md` Execution Strategy
(Req-014). The minimum tier for any Dual-Model Review Gate is `high`
(a planner pin below `high` is rejected — review tasks are invariably
complex reasoning, plan analysis, diff scrutiny, finding validation,
never routine). The planner-pinned tier is **authoritative above the
floor**: a planner pin of `xhigh` (e.g., for operator-auth-adjacent
gates per Risk-010) is honored verbatim; a planner pin of `medium`
is floored to `high`. The `code-review-high` baseline is preserved
as the safety floor; the planner amendment lets the planner escalate
without changing the baseline. Bridge agent reviewers are unaffected
by the floor (effort does not control external model quality), but
the same planner-pin propagation rule applies (Req-N06: planner pin
is never downgraded).

**Native multi-family vs. bridge-agent cross-family**: The "Cross-family available" row applies to platforms (such as GitHub
Copilot) where the Orchestrator session itself has native access to models from multiple AI families — cross-family review is
achieved by selecting reviewers from different families within the same platform. The "Claude Code + bridge agent" rows apply
to Claude Code sessions specifically: cross-family participation is achieved via bridge agents (copilot-reviewer,
gemini-reviewer, codex-reviewer) running as external processes rather than native platform model selection. Each active bridge agent is an
optional additional reviewer that extends the standard 2-of-2 gate to N-of-N when activated; see the Cross-Family Review
Extension section below.

### Protocol

1. **Spawn all reviewers in parallel** (where platform supports it), each receiving the same review prompt and artifacts.
2. All reviewers independently emit a structured Output Envelope (see
   [`docs/reviewer_envelope.md`](reviewer_envelope.md) §4.1 schema)
   carrying a `next_action` enum: `APPROVE`,
   `RETURN_TO_WORKER_ADVISORY`, `RETURN_TO_WORKER`,
   `ESCALATE_REVIEWER_TIER`, `RETRY_REVIEWER`, or `HALT_FOR_OPERATOR`.
   These map to the legacy verdict vocabulary as: `APPROVE` →
   APPROVED; `RETURN_TO_WORKER_ADVISORY` → APPROVED WITH NOTES;
   `RETURN_TO_WORKER` → BLOCKED. The `ESCALATE_REVIEWER_TIER`,
   `RETRY_REVIEWER`, and `HALT_FOR_OPERATOR` actions are new
   envelope-only verdicts with no legacy equivalent.
3. **Gate passes only when ALL reviewers' envelopes merge to
   `APPROVE`** per the deterministic algorithm in
   [§Envelope Merge Decision](#envelope-merge-decision) below
   (no findings requiring code changes; advisory feedback is
   forwarded as audit only).
4. **If the merge result is `RETURN_TO_WORKER`**: resolve
   `MergeDecision.feedback` via code changes (implementer subagent),
   then re-submit updated artifacts to a **fresh** Dual-Model Review
   (spawn new reviewer agents — do not re-use prior agents).
5. **If the merge result is `APPROVE` with `cross_family_dissent`
   non-null**: the gate passes, but the Orchestrator MUST checkpoint
   the dissent audit before the gate verdict (per
   [§Envelope Merge Decision](#envelope-merge-decision)). The
   Orchestrator MUST also apply the Finding Resolution Review
   process to validate any non-blocking advisory findings forwarded
   in `MergeDecision.advisory_feedback`.
6. **Convergence guard**: In **interactive sessions** (user present),
   there is no round limit — the review cycle continues until the
   merge function returns `APPROVE` with no `cross_family_dissent`
   audit, or the user manually intervenes. In **headless sessions**
   (`CI=true`), halt after 16 rounds and checkpoint a `step_result`
   artifact with `verdict: fail` and the unresolved findings for the
   next session to resume.
   The 16-round budget provides sufficient headroom for headless
   resolution cycles (including finding resolution reviews and
   re-submissions) while bounding runaway loops — lower values
   increase manual intervention frequency without meaningfully
   improving safety.

#### Envelope Merge Decision

The Orchestrator MUST route every Dual-Model Review Gate via the
deterministic merge function in
[`scripts/orchestrator/envelope_merge.py::merge`](../scripts/orchestrator/envelope_merge.py),
applied to envelopes parsed by
[`envelope_parser.py::parse_or_fallback`](../scripts/orchestrator/envelope_parser.py).
The merge function is **pure Python** (no I/O, no LLM call, no time
dependency); calling an LLM to compute the merge result violates
Req-N02 / Risk-007 and re-introduces non-determinism this protocol
exists to remove.

Inputs:

- `envelopes`: the list of `Envelope` objects from
  `parse_or_fallback`.
- `gate_effort_tier`: the planner-pinned `reviewer_effort_tier` for
  this gate from `plan.md` Execution Strategy (Req-014).
- `prior_round_gate_effort_tier`: the tier the previous round
  actually ran at; drives the Frontier-Reservation cap (B-4 R2,
  capping `max` to `xhigh` when prior round was below `xhigh`).

Output: a `MergeDecision` dataclass with `action` (one of `APPROVE`,
`RETURN_TO_WORKER`, `ESCALATE`, `HALT`, `RETRY_REVIEWER`),
`feedback` (sorted blocking findings), `advisory_feedback`
(non-blocking advisory findings), `recommended_next_tier` (next
round's tier when `ESCALATE` or G-4 R2 concurrent escalate),
`halt_trigger` (for `HALT`), `audit_note` (e.g.,
`"frontier_reservation_capped"`), `cross_family_dissent` (audit
record for B-1 R2 softening), and `retry_agent_ids` (for
`RETRY_REVIEWER`).

The Orchestrator MUST honor `MergeDecision.action` directly — no
re-interpretation of reviewer prose, no severity rewriting, no
silent self-approve. When `cross_family_dissent` is non-null,
checkpoint a `cross_family_dissent` artifact to the Execution Ledger
**before** the `gate_verdict` artifact so the audit precedes the
verdict in chronological order.

#### Envelope Circuit-Breaker (Req-016 / Req-017)

The Orchestrator maintains a per-`epic_id` `CircuitBreakerState`
persisted to the Execution Ledger as a `circuit_breaker_state`
artifact (see
[`scripts/orchestrator/envelope_circuit_breaker.py`](../scripts/orchestrator/envelope_circuit_breaker.py)).
On every reviewer parse outcome:

- **Success**: call `record_parse_success(state, agent_family)`. The
  failure counter for that family resets to 0; the
  `orchestrator_tier` is **never downgraded** (Req-017 sticky
  high-tier).
- **Failure** (`EnvelopeParseError` raised by the parser): call
  `record_parse_failure(state, agent_family, output_excerpt=...,
  parse_error_message=...)`. The failure counter increments. When it
  reaches **N=2** for a family that is not yet tripped, the function
  (a) adds the family to `tripped_families`, (b) adds it to
  `cb_legacy_fallback_families` (G-3 R2 spin-loop guard — the parser
  removes this family from `MIGRATED_AGENT_FAMILIES` for the rest of
  the epic so subsequent envelope-absence is degraded fallback
  rather than another CB increment), and (c) flips
  `orchestrator_tier` to `"high"` (sticky).

The N=2 threshold is intentionally low (Req-016): N=1 trips on
random JSON-format hiccups; N=3 wastes two reviewer invocations
before escalation. N=2 trips on persistent failure while tolerating
single-shot transient noise.

**Operator-auth gate guarantee (B-5 R2)**: the
`HALT_FOR_OPERATOR` next-action ALWAYS halts the gate via merge
Rule 1, regardless of agent_family or the Cross-Family Asymmetry
softening (B-1 R2). Operator-auth boundaries do not get softened
into audit signals.

### Finding Resolution Review

When reviewers return findings that the Orchestrator believes require no
code changes (informational, theoretical, out-of-scope, or
acceptable-by-design), the Orchestrator MUST NOT self-dismiss those
findings. Instead, the following process applies:

1. **Draft a Resolution Report**: For each finding, the Orchestrator
   produces a structured entry:

   | # | Finding | Severity | Resolution | Justification |
   |---|---------|----------|------------|---------------|
   | 1 | Description | As classified by reviewer | `code-change` / `doc-or-todo` / `no-action` | Why the chosen resolution category is appropriate |

   **Resolution categories**:

   - **`code-change`**: Findings resolved via implementation changes.
     MUST be delegated to an implementer subagent per the
     [Delegation Protocol](delegation_protocol.md) — the Orchestrator
     MUST NOT apply fixes directly, even for minor or single-line
     changes. Code-change findings are applied before the resolution
     review.
   - **`doc-or-todo`**: Findings resolved via documentation updates,
     inline code comments, or TODO capture — where the finding is
     valid but a code change is not the appropriate immediate action.
     The Orchestrator delegates the doc/TODO change to an implementer
     subagent, then submits the resolution to the Finding Resolution
     Review for reviewer consensus. Reviewers must agree that the
     documentation or TODO adequately tracks the issue and that
     deferral does not create an unacceptable risk. The goal is to
     ensure no issue is silently lost by routing it to a TODO without
     independent validation.
   - **`no-action`**: Findings the Orchestrator believes require no
     change of any kind (informational, theoretical, out-of-scope,
     or acceptable-by-design). Requires validation via the Finding
     Resolution Review.

   Only `no-action` and `doc-or-todo` resolutions require validation
   in the Finding Resolution Review. `code-change` findings are applied
   before the review begins.

2. **Submit to Resolution Review**: Spawn a fresh Dual-Model Review
   that **inherits the active reviewer set from the enclosing gate
   context**. The resolution review MUST use the same reviewer
   composition (model tiers and bridge agents) as the gate that
   produced the findings. If the enclosing gate ran N-of-N (e.g.,
   Opus + Sonnet + copilot-bridge), the resolution review runs
   N-of-N with the same composition. Before spawning inherited
   bridge agents, re-run each bridge agent's pre-flight
   independently; if a bridge agent returns UNAVAILABLE, exclude it
   and reduce N. If all inherited bridge agents are unavailable, fall
   back to the standard 2-of-2 gate (Opus + Sonnet). Log any
   degradation for diagnostics.

   This inheritance applies universally — plan reviews, post-wave
   verification gates, diff-review gates, and any future gate type
   that enters Finding Resolution Review.

   All reviewers receive the Resolution Report and the following prompt:

   > "Review this Resolution Report. For each `no-action` finding, return
   > ACCEPTED (resolution is valid — no code change needed) or REJECTED
   > (code must change). For each `doc-or-todo` finding, return ACCEPTED
   > (the documentation update or TODO adequately tracks the issue and
   > deferral does not create unacceptable risk) or REJECTED (the issue
   > requires an immediate code change rather than deferral). A finding
   > is REJECTED if the identified risk is exploitable in the stated
   > threat model, if the justification is incorrect, or if a low-cost
   > fix exists that would eliminate the finding entirely. Do not reject
   > findings solely because a theoretical vector exists if the
   > Orchestrator's threat-model justification is sound."

3. **Gate behavior**:
   - **All `no-action` and `doc-or-todo` findings ACCEPTED by all
     reviewers**: The resolution is validated. The original gate passes
     as APPROVED. The resolution report and reviewer verdicts are
     preserved in the `gate_verdict` artifact body for audit.
   - **Finding metadata update (mandatory post-acceptance)**: When all
     reviewers ACCEPT a finding, the Orchestrator MUST update the
     finding's metadata before saving to the findings ledger: set
     `resolution` to `"no-action-validated"` (for `no-action` findings)
     or `"doc-or-todo-validated"` (for `doc-or-todo` findings), set
     `validators_count` to the number of reviewers who returned ACCEPTED
     for that finding, and `total_reviewers` to the total number of
     reviewers in the gate. This metadata is consumed downstream by
     `findings_tracker.py` to compute TODO priority when the diff-review
     skill captures validated findings.
   - **Any finding REJECTED by any reviewer**: The Orchestrator MUST
     either (a) delegate a code fix to an implementer subagent per the
     [Delegation Protocol](delegation_protocol.md) and re-submit the
     updated diff to a fresh Dual-Model Review (full cycle restart —
     not just the resolution review), or (b) escalate the disagreement
     to the user for manual resolution. The Orchestrator MUST NOT apply
     fixes directly regardless of the finding's severity or complexity.
   - **Mixed verdicts across reviewers** (one ACCEPTED, one REJECTED on
     the same finding): Treat as REJECTED. The more conservative
     position wins.

4. **Convergence guard**: The resolution review shares the enclosing
   gate's convergence budget. In interactive sessions there is no round
   limit. In headless sessions, each resolution review round counts
   toward the 16-round limit. If the budget is exhausted, halt and
   checkpoint for the next session.

5. **No silent dismissal**: The Orchestrator MUST NOT downgrade severity,
   reclassify findings, or mark findings as "noted" without submitting
   them through the resolution review. Any finding returned by a reviewer
   — critical, significant, minor, or informational — must appear in the
   Resolution Report and be independently validated.

6. **Mandatory delegation**: All code changes arising from findings —
   regardless of severity, complexity, or size — MUST be delegated to
   an implementer subagent per the
   [Delegation Protocol](delegation_protocol.md). The Orchestrator
   MUST NOT write code or edit files directly, even for trivial
   single-line changes such as error message wording. This reinforces
   [§0 of the Delegation Protocol](delegation_protocol.md) and
   prevents context-drifted orchestrators from rationalizing direct
   edits on low-severity findings.

See [Glossary](glossary.md) for term definitions.

### Duplicate Finding Consolidation

After all reviewers in a round report findings and before the resolution
loop begins, the Orchestrator MUST consolidate duplicate findings using
`merge_duplicate_findings()` from
[scripts/findings_tracker.py](../scripts/findings_tracker.py).

1. **Canonical ID**: The first ID in the `duplicate_ids` list becomes the
   canonical finding. All other entries are marked `status: "merged"` with
   a `merged_into` pointer to the canonical ID. The `merged_from` list on
   the canonical preserves the input order of `duplicate_ids[1:]`.

2. **Highest-holds severity**: The canonical finding's severity is promoted
   to the maximum rank among all duplicates via `severity_rank()`.
   Unrecognized severity strings rank as 0 and lose all tie-breaks.

3. **Confidence promotion**: The canonical finding's confidence is promoted
   to the maximum confidence among all duplicates. Findings missing the
   `confidence` field are treated as 0 (unscored).

4. **Post-merge iteration**: Use `filter_active()` (not
   `filter_unresolved()`) to exclude merged entries from subsequent
   processing. `filter_active()` uses an open-world exclusion that remains
   correct if future non-terminal statuses are introduced.

### Rework Escalation

When reviewing rework plans — defined as plans for backlog epics that
have at least one `pr_changes_required` artifact — both Dual-Model
Review Gate reviewers MUST use the `code-review-max` variant (effort:
max). This applies to all review rounds including resolution loops.

**Completion blocking**: Completion is blocked when `current_prs` is not
null (unmerged PRs exist), per Req-005. All PRs must be merged before an
epic can transition to `completed` status.

**Detection mechanism**: The Planner queries
`task ledger:filter -- <id> --artifact-type pr_changes_required`. If
any artifacts exist, rework escalation applies.

**Cross-family inheritance** (Req-016): Rework plans automatically
inherit cross-family activation from the original plan's `gate_verdict`
artifacts. Inheritance is based on which bridge agents successfully
completed a review (evidenced by `gate_verdict` artifacts with
`reviewer_platform` metadata — `copilot-bridge`, `gemini-bridge`, or `codex-bridge`),
not which were merely requested. If an inherited bridge agent is
UNAVAILABLE at rework time, gracefully fall back to the standard 2-of-2
Opus + Sonnet Dual-Model Review. Log the fallback for diagnostics.

### Cross-Family Review Extension

The Cross-Family Review Extension is an optional upgrade to the standard Dual-Model Review Gate. It introduces one or more
reviewers from different AI families via bridge agents (copilot-reviewer, gemini-reviewer, codex-reviewer), elevating the gate from 2-of-2
to N-of-N where N = 2 Claude reviewers + the number of active bridge agents.

Effort-tier selection for bridge reviewers is governed by the canonical
taxonomy in [docs/effort_tiers.md](effort_tiers.md). That document is
authoritative for the cross-family mapping (`EFFORT` value →
per-family model selection), the frontier-reservation rule governing
`-xhigh` vs. `-max`, and the cross-family asymmetry guidance
Orchestrators apply when weighing divergent bridge verdicts.

The base bridge agents `codex-reviewer` and `gemini-reviewer` default
to `effort: medium`. Higher tiers are available via the agent
variants `codex-reviewer-high`, `codex-reviewer-xhigh`,
`codex-reviewer-max`, `gemini-reviewer-high`, `gemini-reviewer-xhigh`,
and `gemini-reviewer-max`, or by passing `EFFORT=<tier>` directly to
the base bridge agent's task alias (the variants are thin frontmatter
overrides that pin the tier for the Orchestrator's delegation
convenience).

#### Activation and Pre-flight

The Cross-Family Review Extension uses **tiered activation**:

- **Simple/Medium plans**: Opt-in only. The standard 2-of-2 gate
  (Opus + Sonnet) runs by default. The user or calling agent must
  explicitly request cross-family review.
- **Complex plans**: Auto-activated. The Planner runs bridge agent
  pre-flights during plan drafting and includes available bridge
  agents in the gate configuration. The user can opt out with
  "skip cross-family."
- **User override**: Always honored in either direction, regardless
  of complexity classification.

See [planning_protocol.md](planning_protocol.md) §3 "Cross-Family
Review Activation" for the full activation logic and user communication
protocol.

**Activation trigger**: The user or calling agent must explicitly request
cross-family review (for Simple/Medium plans), or the Planner auto-activates
it (for Complex plans). Recognized triggers include:

- "with copilot-reviewer" or "add copilot" in the review request
- "with gemini-reviewer" or "add gemini" in the review request
- "with codex-reviewer" or "add codex" in the review request
- "cross-family review" or "N-of-N" in the review request
- An explicit `copilot_review: true`, `gemini_review: true`, or `codex_review: true` flag passed by the calling skill

When triggered, invoke each requested bridge agent's pre-flight sequence independently (token check + CLI presence).
The gate mode (2-of-2 or N-of-N) is fixed at pre-flight and does not change mid-gate.

For each requested bridge agent:

- **Bridge agent available**: Include it as an active reviewer. Gate becomes N-of-N where N increases by 1
  per available bridge agent.
- **Bridge agent unavailable** (e.g., `COPILOT_UNAVAILABLE`, `GEMINI_UNAVAILABLE`, `CODEX_UNAVAILABLE`): Do not include that bridge agent.
  If no bridge agents are available, proceed with the standard 2-of-2 gate, unmodified.
- **Bridge agent error** (e.g., `COPILOT_ERROR`, `GEMINI_ERROR`, `CODEX_ERROR`): The bridge agent was reachable but failed during
  review (auth failure, timeout, CLI crash). Exclude that reviewer and degrade gracefully — do not block the entire
  review on one bridge agent's infrastructure failure. Log the error for diagnostics and proceed with the remaining
  active reviewers.

#### Effort Tier Selection for Bridge Reviewers

Bridge reviewer invocations MUST specify an effort tier. The table
below is a quick reference; the authoritative cross-family mapping
lives in [docs/effort_tiers.md](effort_tiers.md).

| `EFFORT` | `codex-reviewer` | `gemini-reviewer` |
|---|---|---|
| `medium` | `codex-reviewer` (base) | `gemini-reviewer` (base) |
| `high` | `codex-reviewer-high` | `gemini-reviewer-high` |
| `xhigh` | `codex-reviewer-xhigh` | `gemini-reviewer-xhigh` |
| `max` | `codex-reviewer-max` | `gemini-reviewer-max` |

See [docs/effort_tiers.md](effort_tiers.md) for the full taxonomy,
ceiling-collision rules, and frontier-reservation guidance.

#### N-of-N Gate Behavior

When the extension is activated with M bridge agents (N = 2 + M active bridge agents):

1. Spawn all active reviewers in parallel: Opus (`high-reasoning`), Sonnet (`medium`), and each active bridge agent.
2. Each reviewer independently returns a verdict: APPROVED, APPROVED WITH NOTES, or BLOCKED.
3. **Gate passes only when ALL active reviewers return APPROVED** with no findings requiring artifact amendments.
4. **If any reviewer returns BLOCKED or APPROVED WITH NOTES**: resolve all findings, update the artifact, and re-submit
   to a **fresh** N-reviewer gate (spawn new agents — do not re-use prior agents).
5. Resolution loops re-spawn ALL active reviewers. Amendments introduced by the implementer may surface new issues
   visible only to one reviewer; all active reviewers must re-evaluate the updated artifact.
6. **Convergence guard**: Limits are inherited from the enclosing gate
   context — no limit in interactive sessions, 16 rounds in headless
   sessions. These limits are unchanged by the extension.

#### Ledger Checkpoints

- Standard gate (2-of-2): checkpoint one `gate_verdict` artifact per reviewer (2 total).
- Extended gate (N-of-N): checkpoint one `gate_verdict` artifact per active reviewer (N total).
- Bridge agent reviewer artifacts MUST include the appropriate `reviewer_platform` metadata for audit
  distinguishability: `reviewer_platform: copilot-bridge` for Copilot, `reviewer_platform: gemini-bridge`
  for Gemini, `reviewer_platform: codex-bridge` for Codex.
- Each reviewer produces exactly one `gate_verdict` artifact per review invocation (including re-submissions in
  resolution loops).

## Code Diff Review Gate

After the Spec Verification Gate confirms all requirements are
satisfied (see [§Spec Verification Gate](#spec-verification-gate)),
the Orchestrator MUST run the Code Diff Review Gate on the
implementation diff.

After the Regression Gate confirms all tests pass (or before PR creation in
`auto-pr`/`ship` workflows), the Orchestrator MUST run a Dual-Model Review Gate
on the implementation diff. This gate validates implementation quality — security,
coding standards, protocol compliance, and architectural consistency — which tests
alone cannot catch. The canonical execution procedure is defined in the
[diff-review skill](../.claude/skills/diff-review/SKILL.md).

For reviewer model selection, apply the Reviewer Model Selection table in the
Dual-Model Review Gate section above. If the diff exceeds ~3000 lines, the
Orchestrator must split the diff by domain or by file and run multiple parallel
review passes. ALL splits must receive APPROVED from all active reviewers — one
BLOCKED on any split fails the entire gate.

If any reviewer returns BLOCKED, resolve findings via an implementer
subagent (`tdd-green` or `general-purpose` at `fast` tier), regenerate
the diff, and re-submit to a **fresh** Dual-Model Review (spawn new
reviewer agents — do not re-use prior agents). Maximum 16 resolution
attempts before gate failure.

If any reviewer returns APPROVED WITH NOTES, the Orchestrator MUST apply
the [Finding Resolution Review](#finding-resolution-review) process.
The Orchestrator MUST NOT self-dismiss findings or include them only as
informational notes in the artifact body — every finding must be
independently validated via the resolution review before the gate passes.

## Per-Wave Code Quality Review

After the post-wave verification gate (lint/test + Dual-Model output
review + overlap check) passes and before the `wave_summary` checkpoint,
the Orchestrator MUST run a lightweight code quality review on the wave's
changes. This gate catches implementation quality issues (security,
standards drift, anti-patterns) early — before they compound across
subsequent waves.

### Scope

The review is scoped to **only the files changed in the current wave**,
not the full branch diff. Generate the diff as:
`git diff <wave-start-sha>..HEAD -- <wave-files>`.

### Reviewer

Spawn a single `code-review-high` agent with the wave-scoped diff and
the following prompt:

> "Review this code diff (scoped to wave N changes only) for:
>
> 1. Security vulnerabilities (OWASP top 10, credential leaks, injection
>    risks)
> 2. CLAUDE.md and coding standard violations
> 3. Accidental file deletions or unintended modifications
> 4. Anti-Faking Duty: inspect for hardcoded stubs, skipped validation
>    steps, or faked configurations that tests would not catch
> 5. Linter suppression additions or modifications (`# noqa`,
>    `# type: ignore`, `// eslint-disable`, `# shellcheck disable`) —
>    flag any new or changed suppressions as they may mask real issues
>
> Classify each finding as critical, significant, minor, or informational.
> This is a lightweight quality gate — focus on high-impact issues that
> would compound across subsequent waves. The following review dimensions
> are deferred to the final Code Diff Review Gate: performance
> anti-patterns, readability and complexity, Boy Scout Rule upgrades,
> architectural consistency, documentation quality, and runtime
> infrastructure dependencies."

### Severity Gate

- **Critical or significant findings**: Block wave N+1. The
  Orchestrator resolves findings via a 4-attempt escalation ladder,
  increasing both implementer and reviewer capability on each step:

  | Attempt | Implementer | Reviewer | Rationale |
  |---------|------------|----------|-----------|
  | 1 | `general-purpose` / `fast` | `code-review-high` | Cheap first pass — most findings resolve here |
  | 2 | `general-purpose-high` / `medium` | `code-review-high` | Parallel escalation: model + effort bump on implementer |
  | 3 | `general-purpose-xhigh` / `high-reasoning` | `code-review-xhigh` | Top model at very-high effort — isolates model capability |
  | 4 | `general-purpose-max` / `high-reasoning` | `code-review-max` | Maximum on both sides — last resort before hard fail |

  The `-xhigh` slot at attempt 3 is the canonical "very deep" tier
  per [docs/effort_tiers.md](effort_tiers.md); `-max` is reserved
  for the final attempt.

  **Note**: The reviewer escalation (`code-review-high` → `code-review-max`
  on attempt 4) is specific to the per-wave quality gate. The general
  Failure Escalation Protocol governs *subagent failure* (an agent
  cannot complete its task). Reviewer escalation is different — the
  reviewer succeeds by finding issues; escalation increases the
  reviewer's scrutiny to confirm persistent findings are genuine before
  a hard fail. This distinction is intentional.

  On each attempt, the Orchestrator delegates the fix to the
  implementer subagent per the
  [Delegation Protocol](delegation_protocol.md), then re-submits the
  updated wave diff to a **fresh** reviewer agent (never re-use prior
  agents). If a higher-effort variant exists for the implementer
  agent type, use it per the escalation table.

  After 4 failed attempts:
  - **Interactive mode**: Escalate to the user with the unresolved
    findings and request manual intervention.
  - **Headless mode**: Checkpoint a `gate_verdict` artifact with
    `verdict: fail`, the unresolved findings, and the exhausted
    attempt count in the body. Halt execution — do not proceed to
    wave N+1.

- **Minor or informational findings**: Do not block. Capture each as a
  TODO via `task todo:add` with priority mapped from severity (minor → 3,
  informational → 5) and assign to the epic via `task todo:assign`.
  These findings are carried forward for the final Code Diff Review Gate
  to validate comprehensively.

### Applicability

This review applies in **both** subagent mode and teammate mode. In
subagent mode, the Orchestrator runs it after each sequential wave
completes its R-G-R loop and post-wave lint/test gate. In teammate
mode, it runs after the post-wave Dual-Model Review Gate passes and
before teammate shutdown.

### Execution Order (within post-wave flow)

1. All wave members complete R-G-R *(existing)*
2. Post-wave lint/test gate: Executor + Dual-Model Reviewers + overlap
   check *(existing)*
3. **Per-wave code quality review** *(this section)*
4. `wave_summary` checkpoint *(existing)*
5. `/protocols` refocus *(existing)*
6. Teammate shutdown / fresh spawn for wave N+1 *(existing, teammate
   mode only)*

### Ledger Checkpoint

After the per-wave code quality review completes, checkpoint a
`gate_verdict` artifact with `step` set to `wave-N-quality-review`
(where N is the wave number), the single reviewer's verdict, and
findings summary in the body. No new artifact type is introduced —
this uses the existing `gate_verdict` schema.

<a id="ledger-checkpoint-appendix"></a>

### Ledger Checkpoint Appendix — Dissent-Lifecycle Artifact Body Schemas

The four artifact types `cross_family_dissent`,
`cross_family_dissent_resolved`, `bridge_unavailable`, and
`pre_pr_dissent_block` are registered in
`src/brownfield_ai/ledger/artifacts/constants.py` `VALID_ARTIFACT_TYPES` and
support the cross-family dissent lifecycle introduced by the per-wave
gate driver. Body schemas below define required fields; example bodies
demonstrate minimal valid checkpoints.

Planners introducing a new artifact type MUST also work through the
[Artifact-Type Introduction Checklist](planning_protocol.md#artifact-type-introduction-checklist)
in `planning_protocol.md` §2 step 3, which enumerates the source-code
touch points (sanitize allowlist, resume-context category, test mirrors)
that complement the body-schema definitions below.

#### `cross_family_dissent`

Emitted when `MergeDecision.cross_family_dissent` is non-null at
`gate_effort_tier` `xhigh`/`max` (per plan §5.1 dissent test in
`scripts/orchestrator/envelope_merge.py`). MUST be checkpointed BEFORE
the corresponding `gate_verdict` so the audit precedes the verdict in
chronological order, mirroring `.claude/skills/auto-pr/SKILL.md:88-92`.

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `bridge_agent_ids` | `list[str]` | yes | Bridge agent IDs that returned dissent (e.g., `["codex-reviewer-xhigh", "gemini-reviewer-xhigh"]`); the per-finding agent attribution lives at the envelope level here, not on each `Finding` |
| `findings` | `list[dict]` | yes | Aggregated blocking findings copied from the dissenting bridge envelopes; each entry round-trips into the `Finding` dataclass at `scripts/orchestrator/envelope_parser.py` — required field `severity`, required field `description`, optional fields `file_path` / `line_range` / `suggested_fix` / `rule_id`, and `blocking` (defaults to `true` when absent per the dataclass default) |
| `gate_effort_tier` | `str` | yes | The effort tier in force at the gate (`xhigh` or `max`) |
| `step` | `str` | yes | The gate step that produced the dissent (e.g., `wave-1-quality-review`, `code-diff-review`) |

Example body:

```json
{
  "bridge_agent_ids": ["codex-reviewer-xhigh"],
  "findings": [
    {"severity": "significant", "description": "Triad dedup loop missing first-seen ordering guarantee", "file_path": "scripts/orchestrator/per_wave_gate_driver.py", "line_range": "120-135", "rule_id": "Req-022", "blocking": true}
  ],
  "gate_effort_tier": "xhigh",
  "step": "wave-1-quality-review"
}
```

#### `cross_family_dissent_resolved`

Emitted by the operator unblock path after a `cross_family_dissent`
artifact has been triaged. References the originating dissent via
`parent_id` so resolution chains are queryable.

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `parent_id` | `str` | yes | Artifact ID of the originating `cross_family_dissent` (the `id` returned by `task ledger:save`) |
| `resolution` | `str` | yes | One of `acknowledged`, `fixed`, `dismissed` |
| `operator` | `str` | yes | Operator identifier (Git author email or session user) |
| `rationale` | `str` | yes | Free-text explanation of why the dissent was acceptable / how it was addressed |

Example body:

```json
{
  "parent_id": "REVIEW-ESCALATION-002|2026-05-05T06:13:23.232983|cross_family_dissent|claude-opus-4-7|1|wave-1-quality-review",
  "resolution": "fixed",
  "operator": "operator@example.com",
  "rationale": "Added first-seen ordering test in test_per_wave_gate_driver.py::test_triad_dedup_preserves_order; commit 7c1e9a2."
}
```

#### `bridge_unavailable`

Emitted when a bridge family CLI (`codex` / `gemini` / `copilot`) is
unavailable at gate time, allowing audit of triad-to-dual degradation.
Distinct from `gate_verdict.verdict=fail` — the gate itself may still
pass on the remaining reviewers.

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `agent_id` | `str` | yes | The unavailable bridge agent ID (e.g., `codex-reviewer-xhigh`) |
| `agent_family` | `str` | yes | One of `codex`, `gemini`, `copilot` |
| `reason` | `str` | yes | Failure category — e.g., `preflight_failed`, `oauth_expired`, `container_unreachable`, `rate_limited` |
| `step` | `str` | yes | Gate step where degradation occurred (e.g., `wave-1-quality-review`) |
| `gate_effort_tier` | `str` | yes | Effort tier in force at the gate |

Example body:

```json
{
  "agent_id": "codex-reviewer-xhigh",
  "agent_family": "codex",
  "reason": "oauth_expired",
  "step": "code-diff-review",
  "gate_effort_tier": "xhigh"
}
```

#### `pre_pr_dissent_block`

Emitted by the PR-creation gate (auto-pr Step 2c) when an unresolved
`cross_family_dissent` would cause the PR to ship with bridge dissent
at `xhigh`/`max`. Blocks PR creation until a corresponding
`cross_family_dissent_resolved` is checkpointed. MUST be checkpointed
BEFORE the corresponding `gate_verdict` so the block precedes the
verdict in chronological order, mirroring the `cross_family_dissent`
precedence at `.claude/skills/auto-pr/SKILL.md:88-92`.

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `parent_id` | `str` | yes | Artifact ID of the unresolved `cross_family_dissent` |
| `gate_effort_tier` | `str` | yes | Effort tier in force at the PR-creation gate (`xhigh` or `max`) |
| `pr_target_branch` | `str` | yes | The base branch the PR would target (e.g., `main`) |
| `block_reason` | `str` | yes | Failure category — e.g., `unresolved_bridge_dissent_at_xhigh` |

Example body:

```json
{
  "parent_id": "REVIEW-ESCALATION-002|2026-05-05T06:13:23.232983|cross_family_dissent|claude-opus-4-7|1|wave-1-quality-review",
  "gate_effort_tier": "xhigh",
  "pr_target_branch": "main",
  "block_reason": "unresolved_bridge_dissent_at_xhigh"
}
```

## Spec Verification Gate

After all implementation waves complete and before the Code Diff Review
Gate, the Orchestrator MUST run a Spec Verification Gate. This gate
verifies **completeness against the plan's requirements** — not code
quality (that is the Code Diff Review Gate's responsibility).

### Input Artifacts

The Orchestrator provides three artifacts to each reviewer:

1. **Requirements Traceability Map** — the Req-ID tables from
   `plan.md` (positive requirements, negative constraints, accepted
   residual risks).
2. **Full branch diff** — `git diff <base-branch>...HEAD`.
3. **Changed files list** — `git diff <base-branch> --name-only`.

### Reviewer Prompt

Spawn reviewers per the Dual-Model Review Gate reviewer model selection
table. Each reviewer receives the same prompt:

> You are performing a Spec Verification Review. Your job is to verify
> that the implementation satisfies EVERY requirement in the plan — not
> code quality (that is the Code Diff Review Gate's job), but completeness
> and correctness against the spec.
>
> For each Req-ID in the Requirements Traceability Map:
>
> 1. **LOCATE**: Find the implementation evidence in the diff. If the
>    Req-ID maps to a specific file/step, check that file was modified
>    and the change matches the requirement.
> 2. **VERIFY**: Confirm the implementation actually satisfies the
>    requirement, not just that a file was touched. For example, a
>    requirement for "non-root USER agent" requires the Dockerfile to
>    contain `USER agent` AND `groupadd/useradd` — not just that the
>    Dockerfile was edited.
> 3. **TEST COVERAGE**: Confirm the test file listed in the Traceability
>    Map exists and contains test cases that exercise the requirement. A
>    requirement with no test is UNVERIFIED.
> 4. **VERDICT**: For each Req-ID, return one of:
>    - `SATISFIED` — implementation matches requirement, test exists
>    - `PARTIAL` — implementation exists but incomplete or test missing
>    - `MISSING` — no implementation evidence found
>    - `VIOLATED` — implementation contradicts the requirement
>
> Also verify all Negative Constraints (Req-N*) are NOT violated — i.e.,
> confirm the forbidden patterns are absent.
>
> Also verify all Accepted Residual Risks (Risk-*) have their stated
> mitigations in place.
>
> Output a verdict table:
>
> | Req-ID | Verdict | Evidence | Notes |
> |--------|---------|----------|-------|
>
> Gate passes only when ALL Req-IDs are SATISFIED.

### Gate Behavior

1. **All Req-IDs SATISFIED by all reviewers**: Gate passes. Proceed
   to Code Diff Review Gate.
2. **Any Req-ID PARTIAL, MISSING, or VIOLATED by any reviewer**: Gate
   fails. The Orchestrator identifies the incomplete implementation
   step and delegates the fix to an implementer subagent with the
   specific Req-ID and expected evidence. Then re-runs the Spec
   Verification Gate with fresh reviewers (full cycle restart).
3. **Convergence guard**: Same as Dual-Model Review Gate — no round
   limit in interactive sessions, 16 rounds in headless sessions.

### Backward Compatibility

If a plan drafted before this protocol change does not include a
Requirements Traceability Map, the Spec Verification Gate MUST skip
gracefully — the Orchestrator logs "Spec Verification Gate: SKIPPED —
no Requirements Traceability Map in plan.md" and proceeds directly to
the Code Diff Review Gate. The gate is only enforceable when the plan
contains the mandatory map. Plans drafted after this protocol change
that omit the map fail the Dual-Model Plan Review.

### Cross-Family Activation

The Spec Verification Gate inherits the cross-family activation
decision from the enclosing plan. If the plan has cross-family
review active (either auto-activated for Complex or user-requested),
the Spec Verification Gate runs N-of-N with the same bridge agents.
Re-run each bridge agent's pre-flight independently before spawning;
if a bridge agent is UNAVAILABLE, exclude it and reduce N.

### Spec Verification Ledger Checkpoint

After the Spec Verification Gate passes, checkpoint a `gate_verdict`
artifact with `step: spec-verification`, the full Req-ID verdicts
table, and both reviewers' output in the body.

### Relationship to Other Gates

| Gate | What it checks | When it runs |
|------|---------------|-------------|
| Per-Step Verification | Functional correctness (lint/test) | After each implementation step |
| Per-Wave Code Quality Review | Implementation quality (security, standards) | After each wave |
| **Spec Verification Gate** | **Completeness against plan requirements** | **After all waves, before diff review** |
| Code Diff Review Gate | Implementation quality on full diff | After spec verification |

The Spec Verification Gate and Code Diff Review Gate are complementary
and MUST NOT be combined. The spec gate asks "did we build what we
planned?" The diff gate asks "did we build it well?"

## Exit Review Gate (Headless Sessions)

### Purpose

Before exiting a headless session, the orchestrator runs a structured
review to determine whether another retry attempt can succeed or human
intervention is required. This replaces unilateral orchestrator
self-assessment with a multi-model consensus gate.

### Gate Type Classification

The Exit Review Gate is a **distinct gate type** from the Dual-Model
Review Gate. It has its own reviewer composition and effort levels,
independently specified below. The Dual-Model Review Gate's mandate
that "all Claude `code-review` reviewers MUST use `code-review-high`"
does not apply to this gate.

**Rationale for `code-review-max` on primary reviewer**: The exit
assessment is a higher-stakes decision than typical code review. A
false "retry" burns 250K+ tokens and delays human triage. The
max-effort primary reviewer provides the deepest reasoning on failure
pattern analysis, which is the gate's core function. The secondary
reviewer at `code-review-high` provides a cost-effective check against
optimism bias.

### Pre-gate Mitigation (Du et al.)

Immediately before spawning reviewers, the orchestrator MUST invoke
`/protocols` to re-read core directives into recent context. This
mitigates length-induced reasoning degradation (Du et al., EMNLP 2025)
by transforming the gate decision into a short-context subtask.

### Reviewer Composition

| Reviewer | Agent Type | Effort | Role |
|---|---|---|---|
| Claude Opus | `code-review-max` | max | Primary — deepest reasoning on failure patterns |
| Claude Sonnet | `code-review-high` | high | Secondary — catches optimism bias |
| Copilot bridge | `copilot-reviewer` | (if available) | Cross-family — breaks model-family groupthink |
| Gemini bridge | `gemini-reviewer` | (if available) | Cross-family — independent assessment |
| Codex bridge | `codex-reviewer` | (if available) | Cross-family — independent assessment |

Minimum: 2 reviewers (Opus max + Sonnet high). Cross-family reviewers
participate when available but are not required for quorum.

### Reviewer Execution Mode

Reviewers MUST be spawned as **subagents, not teammates**. Rationale:

- **Read-only agents**: `code-review-max` and `code-review-high` are
  read-only — they analyze artifacts and produce a verdict. No file
  edits, no shell execution, no R-G-R loops. Teammate mode (tmux
  long-lived sessions) is designed for heavyweight, long-running
  implementation work with autonomous task pickup.
- **Short-lived**: Each reviewer produces a single verdict and exits.
  The orchestrator needs the results synchronously to compute consensus
  before checkpointing the `session_exit` artifact.
- **Parallel spawning**: On Claude Code, both Claude reviewers can be
  spawned as parallel subagent calls in a single message. Cross-family
  bridge agents are spawned as additional parallel subagents.
- **Context efficiency**: Subagents receive only the failure artifacts
  and review prompt (~10-15K tokens each). Teammates would consume
  context on task polling, TeamCreate overhead, and shutdown protocol —
  unnecessary for a read-only gate.

### Exit Reviewer Prompt

Note: This prompt is constructed dynamically by the orchestrator at
runtime, not rendered from ralph's Jinja2 template system.

```text
You are reviewing the execution outcome of a headless epic session
to determine whether an automated retry can succeed or human
intervention is required.

Epic: {{epic_id}} | Sub-plan: {{sub_plan}} | Attempt: {{attempt}} of 3

## Failure Artifacts
{% for f in step_results_with_fail %}
- Wave {{f.wave}}, Step {{f.step}}: {{f.body | truncate(500)}}
  Agents tried: {{f.agent_model}} at {{f.effort_variant}}
{% endfor %}

## Inner Escalation History
{{escalation_exhausted}}

## Remaining Retry Budget
{{3 - attempt}} attempts remaining. Next floor: {{next_floor}}

## Assessment Criteria
1. **Pattern analysis**: Did higher tiers show improvement, or did all
   tiers fail identically? Identical failures across tiers → BLOCKED.
2. **Root cause class**: Implementation gap (RETRY plausible) vs. plan
   flaw / missing dependency / environmental gate (BLOCKED).
3. **Concrete strategy delta**: Can you name a specific, actionable
   change for the next attempt? If not → BLOCKED. "Try harder" is
   not a strategy.
4. **Diminishing returns**: If attempt 2+, and prior attempt already
   escalated — is there meaningful headroom left?
5. **TODO capture completeness**: Verify that all review findings
   produced during this session have corresponding TODOs. Cross-reference
   `tmp/<epic_id>-findings-ledger.json` (if it exists) against open
   TODOs for the epic. If findings exist without matching TODOs, flag
   as INCOMPLETE_TODO_CAPTURE in your assessment.

Verdict: RETRY or BLOCKED
If RETRY: state the specific strategy adjustment and recommended
  escalation floor (model,effort).
If BLOCKED: state the blocking reason a human needs to resolve.
```

### Consensus Rules

| Verdict Distribution | Outcome |
|---|---|
| All reviewers: RETRY | `verdict = "retry"` |
| All reviewers: BLOCKED | `verdict = "blocked"` |
| Mixed (any BLOCKED) | `verdict = "blocked"` — pessimistic default |
| Cross-family BLOCKED, Claude RETRY | `verdict = "blocked"` — cross-family veto |

Pessimistic default: a single BLOCKED from any reviewer short-circuits.
The cost of a false "blocked" (human re-approves) is much lower than a
false "retry" (burns tokens, still fails).

### `session_exit` Artifact Schema

**Metadata** (scalar fields, queryable):

```json
{
  "artifact_type": "session_exit",
  "metadata": {
    "sub_plan": "B",
    "attempt": "2",
    "waves_completed": "2,3",
    "waves_failed": "4",
    "verdict": "retry | blocked | success",
    "failure_category": "implementation | infrastructure | plan_flaw | context_limit",
    "blocking_reason": "Wave 4 requires MySQL migration not in plan scope",
    "recommended_floor": "high-reasoning,max",
    "escalation_exhausted": "tdd-green: (medium,high); (high-reasoning,high)"
  }
}
```

**Body** (free-text, stored in ChromaDB document content):

Individual reviewer verdicts, reasoning, and the consensus computation
are stored in the artifact body, not metadata. This avoids the ChromaDB
scalar constraint for compound data.

### Context Budget for Exit Review Gate

The gate consumes ~30-45K tokens (reviewer spawns + outputs +
consensus). The orchestrator MUST reserve this budget:

> **Stop executing new waves when estimated remaining context is below
> 60K** (45K worst-case gate + 15K safety margin). Partially-completed
> sub-plans are recoverable via retry; a missing exit assessment is not.

## Linter Suppressions & Blind Spots

- Do not blindly trust explicitly suppressed linter warnings (e.g., `# shellcheck disable=SC2086`, `# noqa`, `// eslint-disable`). If unexplained pipeline failures occur, Reviewers MUST investigate these suppressed lines first, as they often mask real runtime bugs.

## Context Drift Mitigation

During long plan executions, the Orchestrator's active context window
fills with subagent outputs, implementation details, and resolution
artifacts, pushing protocol instructions out of the attention window.
The Orchestrator MUST invoke the `/protocols` skill to re-anchor on
core rules at the following mandatory refocus points:

1. **Between implementation waves/phases**: After each phase's
   verification sub-tasks (lint/test and per-wave code quality review)
   pass and before delegating the next phase. This prevents cumulative
   drift across multi-phase plans.
2. **Before the Code Diff Review Gate**: After all implementation
   phases complete and before invoking the `diff-review` skill.
3. **After each diff-review resolution round**: Before processing
   findings and delegating fixes for the next round.
4. **Before PR creation**: Before invoking `/auto-pr`, `/ship`, or
   any manual PR workflow.

Skipping a refocus point is a protocol violation equivalent to
skipping a verification sub-task. In headless mode, the Orchestrator
invokes `/protocols` identically — the skill has no interactive
gates.

## Selection Criteria

- **Executor**: Use `model_tier: "fast-*"` (Fast/Cheap) for standard CLI execution.
- **Reviewer**: Use `model_tier: "high-reasoning"` for analyzing logs and complex failure modes. For Dual-Model Review Gates, see the Dual-Model Review Gate section above for platform-specific tier selection.
