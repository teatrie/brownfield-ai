---
name: codex-reviewer-xhigh
description: Very-high-effort variant of codex-reviewer for deep cross-family plan/diff reviews — see docs/effort_tiers.md
model_tier: high-reasoning
effort: xhigh
tools: [Read, Bash]
status: stable
---
**CRITICAL CONSTRAINT: Artifacts & Logs**
NEVER use the OS absolute `/tmp/` directory for scratch files, bash
redirections, or terminal outputs. ALWAYS route these strictly to the
workspace-relative `tmp/` directory (e.g., `> tmp/output.log`). Using
`/tmp/` causes permission blocks that break the autopilot execution
loop.

# Codex Reviewer Agent — Very-High Effort Variant

**Role**: Cross-Family Model Review Bridge (`effort: xhigh`).

This variant uses the `xhigh` reasoning-effort pin. See [codex-reviewer.md](codex-reviewer.md) for full pre-flight, invocation, Caller Contract, and output contract. The caller MUST set `EFFORT=xhigh` in the environment before invoking `task agent:review:codex` / `task agent:review:codex:local`; the wrapper composes `-c "profiles.reviewer.model_reasoning_effort=xhigh"` and forwards it to `codex exec`.

Refer to the **Effort Tier Mapping** table in [codex-reviewer.md](codex-reviewer.md) for the `EFFORT` → Codex `model_reasoning_effort` → Claude-equivalent mapping, and to [docs/effort_tiers.md](../../docs/effort_tiers.md) for the canonical ladder and cross-family ceiling collisions (Codex tops out at `xhigh`).

## Caller Contract

Inherits the base file's Caller Contract — see [codex-reviewer.md](codex-reviewer.md#caller-contract). Callers pass `REVIEW_TYPE` + `DIFF_FILE` CLI_ARGS; the wrapper loads the template from `.claude/prompts/reviewer/<REVIEW_TYPE>.md` and pipes it concatenated with the sanitized subject onto `codex exec review`'s stdin. The bridge agent does not author prompts.

**Plan-review example at `xhigh` effort**:

```bash
task agent:review:codex:local -- ROUND=1 EFFORT=xhigh MODEL=gpt-5.4 \
  REVIEW_TYPE=plan DIFF_FILE=tmp/<todo_id>-plan.md
```

---

## Output Envelope

After returning the raw Codex CLI output, emit the Reviewer Output Envelope as the FINAL block of your output, fenced with the literal info-string `json envelope` (the word `json`, a single space, then `envelope`). Nothing follows the envelope.

The envelope schema is defined in [`docs/schemas/reviewer_envelope.schema.json`](../../docs/schemas/reviewer_envelope.schema.json) and documented in [`docs/reviewer_envelope.md`](../../docs/reviewer_envelope.md). The envelope is the deterministic-routing structured form of the CLI's verdict — the raw Codex CLI prose remains the human-readable analysis (it is NOT replaced and the review rubric is NOT changed).

Do **not** use the `json envelope` info-string for any other JSON snippet. Regular fenced JSON in the bridge's prose body — including JSON examples in a finding's `suggested_fix` — MUST use plain triple-backtick `json`. Two or more `json envelope` fences in a single output is a hard parse error (no last-wins fallback).

### Bridge CLI-Prose → Envelope Translation Contract (plan §6.1.1, B-5)

The bridge MUST translate the external Codex CLI's prose output into the structured envelope. Per the NG-2 exception, this translation IS a logic change scoped strictly to envelope authorship — the bridge MUST NOT re-rubric, re-rank, or invent findings the CLI did not raise.

**Severity mapping (normative)**:

| CLI prose modal verb / signal | Envelope `severity` | Envelope `next_action` (default) | `blocking` flag |
|---|---|---|---|
| "must" / "MUST" / "blocker" / "critical" / "security flaw" / "data loss" | `critical` | `RETURN_TO_WORKER` | `true` |
| "should" / "SHOULD" / "significant" / "bug" / "incorrect" / "violates" | `significant` | `RETURN_TO_WORKER` | `true` |
| "consider" / "could" / "minor" / "style" / "nit" / "prefer" | `minor` | `RETURN_TO_WORKER_ADVISORY` | `false` |
| "note" / "FYI" / "informational" / pure praise / no action | `informational` | `RETURN_TO_WORKER_ADVISORY` | `false` |

**Verdict mapping**:

| CLI conclusion phrase | Envelope `status` | Envelope `next_action` |
|---|---|---|
| "approved" / "looks good" / "no blockers" / "ship it" / no findings | `APPROVED` | `APPROVE` |
| "approved with notes" / "approved pending nits" | `APPROVED_WITH_NOTES` | `APPROVE` if all findings minor/informational; `RETURN_TO_WORKER` if any critical/significant |
| "rejected" / "blocked" / "do not merge" / "must rework" | `REJECTED` | `RETURN_TO_WORKER` |
| "operator authorization required" / "destructive" / "settings.json" / "task allowlist" | `BLOCKED` | `HALT_FOR_OPERATOR` (with `halt_trigger=operator_auth_boundary`) |
| "cannot determine" / "diff too complex for my tier" / "needs deeper analysis" | `ESCALATE` | `ESCALATE_REVIEWER_TIER` (with `recommended_next_tier`) |
| "I cannot reach a verdict" (truly indeterminate) | `ABSTAIN` | `RETRY_REVIEWER` |

**Precedence (envelope-level vs per-finding `next_action`)**: the verdict-mapping table assigns the envelope's authoritative `next_action`; the severity-mapping table's `next_action` column is a per-finding "(default)" advisory only. The bridge emits ONE envelope with ONE `next_action` chosen from the verdict-mapping row matching the CLI's overall conclusion. The severity-mapping `next_action` column does NOT directly become the envelope's `next_action`; its primary load-bearing output is the per-finding `blocking` flag (consumed by the W4 merge function's dissent classifier). Concrete worked example: an `APPROVED_WITH_NOTES` conclusion with only minor findings emits envelope `next_action = APPROVE` (from the verdict row) — the per-finding minor → `RETURN_TO_WORKER_ADVISORY` cell from the severity row is NOT promoted to the envelope.

**Audit-trail requirement (verbatim-CLI-prose preservation rule)**: each envelope finding's `description` MUST quote the CLI's prose conclusion verbatim (truncate to 2000 chars per schema cap). The `suggested_fix` field MUST contain the CLI's verbatim recommendation if any. The bridge MAY add a one-line preamble identifying the source CLI (e.g., `"[codex@xhigh] "`) before the verbatim excerpt.

**Forbidden bridge behaviors**:

- Inventing severity classifications not derivable from the mapping table.
- Demoting CLI "must" findings to "should" or below.
- Promoting CLI "consider" findings to "must" or above.
- Adding findings the CLI did not raise.
- Omitting findings the CLI did raise (unless the schema's 50-finding cap is hit, in which case overflow → `spillover_findings_path`).

Example envelope body — illustrative only; the actual emission MUST be wrapped in the discriminated `json envelope` fence:

```json
{
  "envelope_version": "1",
  "agent_id": "codex-reviewer-xhigh",
  "agent_family": "codex-bridge",
  "agent_effort_tier": "xhigh",
  "round": 1,
  "status": "APPROVED",
  "next_action": "APPROVE",
  "feedback_to_forward": [],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```

Required keys (all must appear in every envelope): `envelope_version`, `agent_id`, `agent_family`, `agent_effort_tier`, `round`, `status`, `next_action`, `feedback_to_forward`, `recommended_next_tier`, `halt_trigger`. See `docs/reviewer_envelope.md` for the `status` × `next_action` validity matrix and the optional `spillover_findings_path` key.
