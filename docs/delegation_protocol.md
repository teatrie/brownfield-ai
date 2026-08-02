# Delegation & Security Protocol

To minimize risk and prevent accidental damage, the Orchestrator (and Planner when delegating research) must enforce **Least Privilege** (Just-in-Time Permissions) when delegating tasks to sub-agents. For term definitions (Orchestrator, Executor, Reviewer, etc.), see the [Glossary](glossary.md).

## 0. MANDATORY DELEGATION (CRITICAL DIRECTIVE)

The Orchestrator is a **Manager**, NOT a **Worker**.

- **DO NOT ACT AS A MONOLITHIC AGENT.**
- **DO NOT WRITE CODE OR EDIT FILES DIRECTLY.**
- **DO NOT RUN TERMINAL COMMANDS FOR IMPLEMENTATION OR VERIFICATION.**
- You **MUST** use your platform's native delegation mechanism (e.g., the `runSubagent` tool in Copilot, or spawning isolated sub-instances/MCP tools in Claude Code) for all execution, file modification, testing, schema generation, and code review tasks.
- Disobeying this rule destroys the conceptual boundary required for unbiased work and makes you prone to taking lazy shortcuts (like faking schemas or skipping validations). If you are editing files or running task scripts directly instead of delegating to a worker, you are violating your primary directive.

## 1. Minimal Permission Selection

Always select the `agent_type` with the most restricted toolset capable of completing the task. Do not grant "Full" access unless strictly required.

| Task Category | Recommended Agent Type | Permissions |
| :--- | :--- | :--- |
| **Research / Search** | `explore` | **Read-Only**: `grep`, `glob`, `view`. No execution. |
| **Deep Context Analysis** | `deep-researcher` | **Execution**: Script execution for API/cache management. No code modification. |
| **Architecture / Triage** | `planner` | **Read-Only**: Analysis, blueprinting, plan generation. No code modification. |
| **Management / Routing** | `orchestrator` | **System**: Sub-agent delegation, synthesis, PR creation. |
| **Code Analysis** | `code-review` | **Read-Only**: Analysis only. No code modification. |
| **Cross-Family Code Review (Copilot)** | `copilot-reviewer` | **Execution**: Bash scoped to Copilot CLI. Read-only for code context. |
| **Cross-Family Code Review (Gemini)** | `gemini-reviewer` | **Execution**: Bash scoped to Gemini CLI. Read-only for code context. |
| **Cross-Family Code Review (Codex)** | `codex-reviewer` | **Execution**: Bash scoped to Codex CLI. Read-only for code context. |
| **Testing / Linting** | `task` | **Execution**: CLI access. Optimized for non-interactive output. |
| **TDD (Failing Tests)** | `tdd-red` | **Code Modification**: Only adds failing tests. No implementation. |
| **TDD (Implementation)** | `tdd-green` | **Code Modification**: Implements fixes strictly to pass tests. |
| **TDD (Code Cleanup)** | `tdd-refactor` | **Code Modification**: Reformats/cleans passing code. No behavior changes. |
| **General Implementation** | `general-purpose` | **Full**: Full toolset. Use *only* when necessary for complex edits. |

High-effort variants (e.g., `code-review-high` [effort: high], `code-review-xhigh` [effort: xhigh], `code-review-max` [effort: max], `tdd-red-high`, `tdd-green-xhigh`, `tdd-green-max`) inherit the same permissions as their base agent. The `-high`, `-xhigh`, and `-max` suffixes control effort depth (reasoning intensity), not the model tier declared in the agent's frontmatter. The model tier used at runtime is determined by the escalation matrix — the orchestrator selects the concrete model when spawning each matrix point. Select the initial variant by domain complexity per [planning_protocol.md](planning_protocol.md) §3. The canonical 4-level ladder (`medium → high → xhigh → max`) is defined in [docs/effort_tiers.md](effort_tiers.md).

## 2. Escalation Protocol

If a sub-agent fails because it lacks a necessary tool (e.g., an `explore` agent tries to run a script):

1. **Analyze**: The Orchestrator (or delegating Agent) must review the failure.
    - *Why* was the tool requested?
    - *Is the request legitimate?*
    - *Is the operation safe?*
2. **Decide**:
    - **Deny**: If the request is unsafe or unnecessary, instruct the agent to find an alternative.
    - **Grant**: If justified, re-dispatch the task using the next higher `agent_type` (e.g., upgrade `explore` → `task`).
3. **Log**: If the escalation was unexpected, log it in [docs/tech_debt.md](tech_debt.md) as a potential process improvement. When an escalation occurs, the Orchestrator MUST also checkpoint a
`design_decision` artifact to the execution ledger with the original agent
model tier, escalated (upgraded) tier, and the failure reason that
necessitated the escalation.

**Effort escalation**: Escalation follows the 1-per-matrix-point rule — each unique (model tier, effort variant) combination gets exactly 1 attempt. The orchestrator bumps model tier, effort variant, or both according to the agent's escalation path (e.g., `tdd-green` → `tdd-green-high` → `tdd-green-xhigh` → `tdd-green-max`). The total attempt budget is an emergent property of the agent's variant chain. See [Failure Escalation Protocol](../.claude/skills/agent-team/SKILL.md) in `agent-team` SKILL.md.

## 3. Guard Rails

- **Never** grant `general-purpose` access for simple information retrieval.
- **Strict Negative Constraints (Anti-Hallucination):** When delegating to sub-agents (especially `explore` or `code-review`), you **MUST** provide explicit fail conditions. For example: "If the `repos/<repo>` directory does not exist, STOP and return 'MISSING_DEPENDENCY'. Do not attempt to guess or search alternative directories."
- **Pre-Flight Dependency Verification:** The delegating Agent (Orchestrator or Planner) must proactively verify that the required dependencies (such as target repositories being cloned in [repos/](../repos)) actually exist *before* handing the task to the sub-agent. If the target repo is missing, the Orchestrator must either clone it first or fallback to remote CLI tools (like `gh search code`), rather than hoping the sub-agent figures it out.
- **Convention Context in Delegation Prompts:** Sub-agents cannot infer
  repository conventions from filesystem state alone — directories may
  not exist locally because repos have not been cloned yet. When
  delegating path or convention verification, the delegating agent MUST
  include the relevant convention rule in the prompt. Specifically: all
  upstream repositories (`<org>/<repo>`) are cloned under the
  [repos/](../repos) directory (see [repos/README.md](../repos/README.md)).
  Directory absence does NOT mean a path is "intentionally top-level" —
  it means the repo has not been cloned. Glob patterns in
  `.claude/rules/` and `.github/instructions/` must use `**/repos/<repo>/`
  to match cloned content.
- **Verify** that the sub-agent is not hallucinating the need for higher privileges or hallucinating answers based on unrelated files.
- **Isolate**: When possible, restrict the agent's scope (e.g., specific file paths) in the prompt instructions and require the sub-agent to cite the exact file paths it bases its conclusions on.
- **Environment Isolation (Principle 11 Enforcement)**: Sub-agents do NOT inherit your memory or the repository's core guidelines. Therefore, when delegating CLI tasks or script execution to a `task` or `general-purpose` agent, you **MUST explicitly provide the fully-constructed `docker compose run --rm python-cli ...` command** directly within the prompt payload. Do not simply tell the subagent to "run the script", as it will default to its systemic training and run `python3` natively on the host machine.
- **CLI Syntax Verification**: When delegating CLI commands to sub-agents, the delegating agent MUST verify the exact invocation syntax (flag names, positional vs keyword arguments) by reading the target function signature or `--help` output before constructing the command. Do not infer flag names from the task alias — many `task` aliases (e.g., `ledger:*`, `chromadb:*`, `todo:*`) wrap `defopt`-based Python CLIs where keyword-only parameters require explicit `--flag` syntax that cannot be guessed from the alias name alone. See [tool_chain.md](tool_chain.md) and [learnings.md](learnings.md) §Python CLI & Environment for `defopt` gotchas.
- **Workspace Hygiene (Principle 10 Enforcement)**: When delegating execution tasks (e.g., running shell scripts, capturing logs, dumping outputs), you **MUST** explicitly instruct the sub-agent to output all temporary files to a designated `tmp/` subdirectory. Sub-agents frequently pollute the workspace root with quick bash redirections (e.g., `> output.txt`). It is the delegating agent's responsibility to proactively enforce `> tmp/output.txt` in the task prompt.
- **File Creation Enforcement (Principle 10 Enforcement)**: When delegating implementation tasks, you **MUST** include this directive in the subagent prompt: "**CRITICAL: Use the Write tool to create new files. Do NOT use `cat` heredocs or Bash redirection.**" The Bash sandbox's injection detector rejects heredocs containing Python type annotations (brace adjacent to quote character). This is a platform-level constraint that cannot be configured away. See [learnings.md](learnings.md) §Claude Code Sandbox for full details.
- **Scope Boundary Enforcement**: Every subagent prompt MUST include the directive: "Do NOT modify, remove, or add anything not explicitly listed in your instructions. If you believe an out-of-scope change is needed, STOP and report it — do not make the change." After a subagent completes, the Orchestrator MUST compare the reported file changes against the stated scope. Any out-of-scope modification is flagged to the user before accepting the output.
- **Subagent Bash Ceiling**: Subagents inherit the production `.claude/settings.json` nine-entry `Bash(task <ns>:*)` allowlist — there is no per-subagent widening path. The enumerated baseline (see [CLAUDE.md](../CLAUDE.md) §17 and [tool_chain.md](tool_chain.md) §Task Permission Baseline) is the ceiling; delegating agents MUST construct subagent prompts so the subagent's needed tasks resolve within the baseline. If a subagent needs a namespace that falls outside the ceiling, the fix is either (a) route through an enumerated-allowed task in the parent's scope, or (b) escalate to the user to widen the baseline via a reviewed PR. Subagent prompts MUST NOT ask the subagent to "just accept the prompt" — headless subagents cannot approve Ask-tier prompts and will hard-fail.

See [CLAUDE.md](../CLAUDE.md) for core principles and architectural index.

## 3a. Reviewer Output Envelope

All reviewer subagent delegations (Claude `code-review*`, bridge agents
`codex-reviewer*`/`gemini-reviewer*`, internal QA `qa-*`) MUST instruct
the reviewer to emit a structured Output Envelope as the final block of
its response. The canonical schema lives at
[`docs/schemas/reviewer_envelope.schema.json`](schemas/reviewer_envelope.schema.json);
the discriminated-fence format and merge contract are documented in
[`docs/reviewer_envelope.md`](reviewer_envelope.md).

**Prompt-payload requirement**: every delegation prompt that targets a
reviewer agent in the active per-wave migration allowlist MUST include
the directive "emit envelope as final block" (or an equivalent phrasing
that points to the agent's "Output Envelope" section). Without this
directive, headless reviewers may default to prose-only output and the
orchestrator's `parse_or_fallback` will trip the
[`envelope_circuit_breaker`](../scripts/orchestrator/envelope_circuit_breaker.py)
on the second consecutive failure (Req-016 / Req-017, N=2 trip).

**Planner-tier-pin propagation (Req-N06)**: when a delegating subagent
spawns a reviewer, it MUST pass through the planner-pinned
`reviewer_effort_tier` from `plan.md` Execution Strategy (Req-014). The
delegating subagent MUST NOT override the pin downward — Req-N06
forbids any orchestrator path from downgrading a planner-pinned tier.
Override upward is permitted only via the `ESCALATE_REVIEWER_TIER`
envelope path (round-1 bypass per S-8) or via the circuit-breaker tier
escalation (Req-016 sticky `orchestrator_tier="high"`).

**Forbidden in reviewer prompts**: the delegating subagent MUST NOT
instruct the reviewer to "summarize without the envelope" or "skip the
JSON output" or "emit prose only" — those instructions break the
deterministic routing contract (Req-N02 / Risk-007). If a reviewer
genuinely cannot emit an envelope (a bug or a transient failure), the
correct path is to let the parser fall back via the per-wave
allowlist's `cb_legacy_fallback_families` set, not to instruct
envelope omission in the prompt.

## 4. Pre-flight Authentication (AWS / SSO)

Sub-agents run headless and will freeze or crash if challenged for interactive credentials. Therefore:

- **NO DELEGATED AUTHENTICATION**: Sub-agents MUST NOT be told to run `aws-vault exec` or logging commands.
- **CREDENTIAL FETCHER MODEL**: The main Orchestrator MUST invoke the `aws-vault-auth` skill to securely extract temporary STS variables (`AWS_ACCESS_KEY_ID`, etc.) into a git-ignored, temporary file (`tmp/.aws-credentials.env`) without bleeding them into the LLM context.
- **INJECTION**: When subsequently spawning the sub-agent or Docker container, the Orchestrator explicitly sources the generated `.env` file into the spawned terminal shell (e.g., `source tmp/.aws-credentials.env && docker run ...`) or passes it natively via container arguments (e.g., `--env-file tmp/.aws-credentials.env`).
- **EXPIRATION & RETRIES**: STS tokens expire. Sub-agents must blindly reuse cached properties. If testing or containers throw `ExpiredToken` or `AccessDenied` errors, silently drop cached credentials, renew them via the auth script, and retry.
- **ROLE FALLBACK**: If STS tokens cannot be fetched due to a bad config or unrecognized profile, do not silently hallucinate another profile. You MUST read `~/.aws/config`, ask the user for their exact profile choice, cache it, and re-run Auth before continuing.

## 5. Headless Session Convention

Skills and protocols are invoked both interactively (user present) and
headlessly (`claude -p`, subagent delegation, CI pipelines, agent loop
scripts). Interactive gates — user prompts, approval waits, flag-to-
user steps, browser interactions, feedback collection — require special
handling in headless mode.

### Detection (Two-Layer Convention)

1. **Infrastructure layer**: The `CI` environment variable is the
   industry-standard signal for non-interactive execution. GitHub
   Actions sets `CI=true` automatically. For local headless sessions
   (skill evals via `ClaudeCodeRunner`, agent loop scripts executing
   plans from the Execution Ledger), callers MUST `export CI=true`
   before invocation.
2. **Skill layer**: The caller passes a headless signal into the
   skill's prompt or `$ARGUMENTS` — e.g., the calling orchestrator
   includes "You are running in a headless non-interactive session"
   in the delegation prompt, or the skill detects pipeline context
   like "invoked from `/auto-pr`."

**Default is interactive**: When no headless signal is received, skills
assume an interactive session (user is present). Headless mode is only
active when `CI=true` is set or the calling pipeline explicitly signals
non-interactive execution.

### Fail-Closed Enforcement

When headless mode IS active and a skill hits an interactive gate
without an explicit fallback, it MUST:

1. **FAIL execution immediately** — never silently proceed or "pass
   with caveats."
2. Checkpoint a `step_result` artifact to the Execution Ledger with
   `verdict: fail` and the gate that could not be resolved.
3. Halt. The next session (human or bot) resumes via
   `execution-ledger resume` and sees the failure context.

Acceptable fallbacks before halting (must be explicitly defined per
gate — if the fallback itself fails, the skill still halts):

- Derive the answer from git diffs or conversation context.
- Checkpoint results to the Execution Ledger.
- Halt on unresolvable blockers.

See [docs/verification_protocol.md](verification_protocol.md) lines
47-55 for the canonical headless failure pattern.

### Signal Propagation

The headless signal does NOT propagate automatically across delegation
boundaries. Each orchestrator or skill that delegates work in headless
mode MUST:

- **Subagents**: Include the headless signal in every delegation prompt
  (e.g., "You are running in a headless non-interactive session").
- **Docker containers**: Pass `--env CI=true` or
  `--env-file tmp/.aws-credentials.env` explicitly. The `CI` env var
  propagates automatically within the host process tree but is NOT
  inherited by Docker containers unless explicitly passed.
- **Failure to propagate** the headless signal is a protocol violation
  equivalent to failing to propagate AWS credentials (see §4).

## 6. Session Handoff Protocol (Dual-Track)

When a plan is split into sub-plans (see
[planning_protocol.md](planning_protocol.md) §4), each sub-plan
executes in its own session. The handoff protocol ensures no context
is lost between sessions.

**Envelope artifacts persist across handoffs.** The
[`Envelope`](../scripts/orchestrator/envelope_parser.py) dataclass
produced by the parser is the authoritative routing artifact. Its
state survives session handoff in three ways:

1. **`circuit_breaker_state` artifact** (per `epic_id`): persisted to
   the Execution Ledger by
   [`envelope_circuit_breaker.to_ledger_artifact`](../scripts/orchestrator/envelope_circuit_breaker.py)
   on every parse outcome. The next session's orchestrator reads it
   on spawn via `from_ledger_artifact` to recover the failure
   counters, the tripped-families set, and the sticky
   `orchestrator_tier`.
2. **`gate_verdict` artifact body**: when a gate verdict checkpoint
   is written, the body MAY embed the merge function's
   `MergeDecision` (action, feedback list, recommended_next_tier,
   audit_note, cross_family_dissent) so resumed sessions see exactly
   how the prior round routed.
3. **`cross_family_dissent` artifact**: when bridge dissent at
   xhigh/max is softened to an audit annotation rather than a HALT
   (per [`docs/effort_tiers.md`](effort_tiers.md) Cross-Family
   Asymmetry), the audit is checkpointed independently so post-hoc
   readers can correlate the dissent with the routing decision.

The parser is the contract boundary — once an `Envelope` is
constructed and persisted (directly or via the artifacts above), the
data is durable across handoffs without re-parsing the original LLM
output.

### Interactive Track (Human Session Driver)

**End-of-session checklist:**

1. Checkpoint `wave_summary` for each completed wave to the Execution
   Ledger.
2. Checkpoint `plan_snapshot` (if plan was mutated during session).
3. Update `plan.md` status with completed waves and next sub-plan scope.
4. Output resume prompt to the user with: epic ID, branch, completed
   waves, next sub-plan, numbered instructions.

**Start-of-session checklist:**

1. `/protocols` — re-read core rules.
2. `execution-ledger resume <epic_id>` — bootstrap full context.
3. Read `plan.md` — verify alignment with ledger state.
4. Verify branch state (`git status`, `git log`).
5. Proceed with next sub-plan scope.

**Resume prompt template (interactive):**

```markdown
Resume epic {{epic_id}}.
Branches: {{branches}}

Completed: Waves {{completed_waves}} (Sub-plan {{completed_sub_plan}}).
Next scope: Waves {{next_waves}} (Sub-plan {{next_sub_plan}}).

Instructions:
1. Run `/protocols`
2. Run `execution-ledger resume {{epic_id}}`
3. Read `plan.md` and verify branch state
4. Execute waves {{next_waves}} using `/agent-team`
5. Checkpoint all artifacts per verification protocol
```

### Headless Track (Ralph Session Driver)

**End-of-session contract:**

1. Checkpoint `wave_summary` for each completed wave.
2. Run the Exit Review Gate (see
   [verification_protocol.md](verification_protocol.md)) — produces
   `session_exit` artifact.
3. Exit cleanly (exit 0 on success, non-zero on failure).

**Session prompt construction:** Ralph is a deterministic Python script.
It renders a Jinja2 template from ledger state — no LLM inference in the
outer loop.

**Scope determination (ralph-side):** Ralph computes the next sub-plan
scope by:

1. Parsing `sub_plans` and `branches` from the active `plan_snapshot`
   metadata.
2. Querying `wave_summary` artifacts to identify completed waves.
3. The first sub-plan with incomplete waves becomes the session scope.

## 7. Sub-plan Retry Protocol

Max **3 attempts** per sub-plan. This is a ceiling, not a target.

### Retry Loop

```text
for attempt in 1..3:
    failures = ledger failures for this epic + sub-plan + attempt-1
    completed_waves = passing wave_summaries
    escalation_floor = from prior session_exit.recommended_floor (or default)

    prompt = render_template(epic, sub_plan, attempt, completed_waves,
                             failures, escalation_floor)
    exit_code = claude -p "$prompt" --env CI=true

    exit_artifact = ledger:query epic --filters {
        "artifact_type": "session_exit",
        "sub_plan": sub_plan.label,
        "attempt": str(attempt)
    }

    if exit_artifact exists:
        if verdict == "success": break
        if verdict == "blocked": transition → blocked; break
        if verdict == "retry":
            escalation_floor = exit_artifact.recommended_floor
            continue

    else:  # Missing exit assessment
        consecutive_missing += 1
        if consecutive_missing >= 2:
            transition → blocked  # systematic issue
            break
        else:
            continue  # retry once — likely transient crash

if attempts exhausted and verdict != "success":
    transition → blocked
```

### Escalation Floor (model + effort)

The floor specifies the minimum starting point for the inner escalation
matrix. The orchestrator reads the floor from the retry prompt and
overrides plan-assigned tiers when they fall below it.

| Outer Attempt | Default Model Floor | Default Effort Floor | Effect |
|---|---|---|---|
| 1 | Per-plan complexity | base | Normal — cheapest inner matrix path |
| 2 | Per-plan complexity | high | Skips base effort variants entirely |
| 3 | One model tier up from plan | max | Maximum capability, no cheap attempts |

These defaults apply when the prior `session_exit` has no
`recommended_floor`. When the Exit Review Gate produces a
`recommended_floor`, ralph uses that instead.

### Partial Progress Preservation

Each retry session MUST skip already-completed waves. Ralph passes
`completed_waves` in the prompt. The session's orchestrator confirms via
`execution-ledger resume` on startup.

### Token Budget per Attempt

Each retry adds failure context to the prompt:

| Attempt | Failure Context Added | Effective Budget for Waves |
|---|---|---|
| 1 | 0K | ~155-185K (250K minus 65-95K fixed overhead) |
| 2 | ~5-10K | ~145-180K |
| 3 | ~10-20K | ~135-175K |

Failure context capped at 500 chars per artifact to prevent context
bloat.
