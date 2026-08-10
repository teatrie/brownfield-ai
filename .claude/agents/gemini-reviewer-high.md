---
name: gemini-reviewer-high
description: High-effort variant of gemini-reviewer for architecture plan reviews and complex cross-family diff verification — see docs/effort_tiers.md
model_tier: high-reasoning
effort: high
tools: [Read, Bash]
status: stable
---
**CRITICAL CONSTRAINT: Artifacts & Logs**
NEVER use the OS absolute `/tmp/` directory for scratch files, bash
redirections, or terminal outputs. ALWAYS route these strictly to the
workspace-relative `tmp/` directory (e.g., `> tmp/output.log`). Using
`/tmp/` causes permission blocks that break the autopilot execution
loop.

# Gemini Reviewer Agent — High Effort Variant

**Role**: Cross-Family Model Review Bridge (`effort: high`).

This variant uses the `high` reasoning-effort pin. See [gemini-reviewer.md](gemini-reviewer.md) for full pre-flight, Caller Contract, invocation, and output contract. The caller MUST pass `EFFORT=high` as a CLI_ARG to `task agent:review:gemini` / `task agent:review:gemini:local` — a positional `KEY=value` argument after `--`, never an exported shell variable, per the **CLI Invocation** section of the base file. The wrapper composes the `-m <tier-short>-high` alias (e.g., `gemini-3.1-pro-high` or, after Pro→Flash fallback, `gemini-3-flash-high`) per Req-005 and forwards it to `gemini`.

Refer to the **Effort Tier Mapping** table in [gemini-reviewer.md](gemini-reviewer.md) for the `EFFORT` → `-m <alias>` → Claude-equivalent mapping, and to [docs/effort_tiers.md](../../docs/effort_tiers.md) for the canonical ladder and cross-family ceiling collisions.

---

## Output Envelope

After returning the raw Gemini CLI output, emit the Reviewer Output Envelope as the FINAL block of your output, fenced with the literal info-string `json envelope` (the word `json`, a single space, then `envelope`). Nothing follows the envelope.

The envelope schema is defined in [`docs/schemas/reviewer_envelope.schema.json`](../../docs/schemas/reviewer_envelope.schema.json) and documented in [`docs/reviewer_envelope.md`](../../docs/reviewer_envelope.md). The envelope is the deterministic-routing structured form of the CLI's verdict — the raw Gemini CLI prose remains the human-readable analysis (it is NOT replaced and the review rubric is NOT changed).

Do **not** use the `json envelope` info-string for any other JSON snippet. Regular fenced JSON in the bridge's prose body — including JSON examples in a finding's `suggested_fix` — MUST use plain triple-backtick `json`. Two or more `json envelope` fences in a single output is a hard parse error (no last-wins fallback).

### Bridge CLI-Prose → Envelope Translation Contract (plan §6.1.1, B-5)

The bridge MUST translate the external Gemini CLI's prose output into the structured envelope. Per the NG-2 exception, this translation IS a logic change scoped strictly to envelope authorship — the bridge MUST NOT re-rubric, re-rank, or invent findings the CLI did not raise.

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

**Audit-trail requirement (verbatim-CLI-prose preservation rule)**: each envelope finding's `description` MUST quote the CLI's prose conclusion verbatim (truncate to 2000 chars per schema cap). The `suggested_fix` field MUST contain the CLI's verbatim recommendation if any. The bridge MAY add a one-line preamble identifying the source CLI (e.g., `"[gemini@high] "`) before the verbatim excerpt.

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
  "agent_id": "gemini-reviewer-high",
  "agent_family": "gemini-bridge",
  "agent_effort_tier": "high",
  "round": 1,
  "status": "APPROVED",
  "next_action": "APPROVE",
  "feedback_to_forward": [],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```

Required keys (all must appear in every envelope): `envelope_version`, `agent_id`, `agent_family`, `agent_effort_tier`, `round`, `status`, `next_action`, `feedback_to_forward`, `recommended_next_tier`, `halt_trigger`. See `docs/reviewer_envelope.md` for the `status` × `next_action` validity matrix and the optional `spillover_findings_path` key.
