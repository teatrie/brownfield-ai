# Reviewer Output Envelope

Canonical reference for the structured-output contract emitted by every
reviewer agent in the brownfield-ai workspace. The envelope is the
deterministic-routing companion to the reviewer's prose review — the
prose remains the human-readable analysis, and the envelope is the
machine-readable verdict the orchestrator uses to drive merge / retry /
escalate / halt routing without an LLM call.

This document is the Wave 1 deliverable of epic
`REVIEWER-ENVELOPE-001`; the merge function and circuit-breaker spec
land in W4. Until the plan moves to its final docs location, the
authoritative source for cross-references is
`tmp/plan-reviewer-output-envelope.md`.

## Schema

- **Schema file**: [`docs/schemas/reviewer_envelope.schema.json`](./schemas/reviewer_envelope.schema.json)
- **Envelope version**: `"1"` (constant — bumped only on a breaking shape change)
- **Validator**: JSON Schema Draft 2020-12

The schema declares `additionalProperties: false` on the top-level
object and on every finding entry, so unknown keys are a hard parse
error. Out-of-band annotations (e.g. reroute audits) live on
`ParseResult.audit_annotations`, never on the envelope JSON.

## Emission Contract

After your prose review, emit the envelope as the **final** block of
your output, fenced with the literal info-string `json envelope` (the
word `json`, a single space, then `envelope`). Nothing follows the
envelope.

Do **not** use this info-string for any other JSON snippet. Regular
fenced JSON inside your prose body — including JSON examples in a
finding's `suggested_fix` — MUST use plain ` ```json `. The
discriminator exists so the orchestrator parser can tell the structured
verdict apart from inline illustrations.

If two or more `json envelope` fences appear in the output, the parser
raises `EnvelopeParseError(reason="multiple_envelope_fences")` and the
orchestrator routes the verdict as `RETRY_REVIEWER` — there is no
last-wins fallback (closes the smuggling vector that motivated the
discriminator).

If a `json envelope` opener line appears without a well-formed
body+closer (e.g. a literal-empty-fence with no body line at all, or
a closer attached to the body line with no preceding newline), the
parser raises `EnvelopeParseError(reason="malformed_envelope_fence")`
rather than treating the case as "envelope absent." This pre-scan
guard exists so the orchestrator's circuit-breaker classifier can
distinguish "the agent attempted to emit an envelope and the bytes
came out malformed" from "the agent emitted prose only" — the former
routes through `RETRY_REVIEWER`, the latter through the per-wave
migration allowlist branch.

## Required Keys

| Key | Type | Description |
|-----|------|-------------|
| `envelope_version` | string `"1"` | Schema version constant. |
| `agent_id` | string | Exact agent name from frontmatter (e.g. `code-review-high`). |
| `agent_family` | enum | One of `claude-native`, `codex-bridge`, `gemini-bridge`, `copilot-bridge`, `qa-internal`. |
| `agent_effort_tier` | enum | One of `medium`, `high`, `xhigh`, `max`. |
| `round` | integer >= 1 | The review round number for this gate. |
| `status` | enum | One of `APPROVED`, `APPROVED_WITH_NOTES`, `REJECTED`, `BLOCKED`, `ESCALATE`, `ABSTAIN`. |
| `next_action` | enum | One of `APPROVE`, `RETURN_TO_WORKER`, `RETURN_TO_WORKER_ADVISORY`, `ESCALATE_REVIEWER_TIER`, `HALT_FOR_OPERATOR`, `RETRY_REVIEWER`. |
| `feedback_to_forward` | array (`maxItems: 50`) | Findings the orchestrator forwards to the worker. May be empty for unanimous APPROVE. Each entry's `description` is required (`minLength: 1, maxLength: 2000`); the optional `suggested_fix` is also `maxLength: 2000`. Findings beyond the 50-entry cap MAY be moved to a `spillover_findings_path` sidecar — but until the W4 merge function lands, the W1 parser does not consume sidecars; reviewers MUST treat the inline 50 as the complete actionable list and prioritize accordingly. |
| `recommended_next_tier` | enum or null | Required non-null when `next_action == ESCALATE_REVIEWER_TIER` (schema-enforced). For every other `next_action` (`APPROVE`, `RETURN_TO_WORKER`, `RETURN_TO_WORKER_ADVISORY`, `RETRY_REVIEWER`, `HALT_FOR_OPERATOR`) set `recommended_next_tier: null` by convention — the schema only enforces non-null on the ESCALATE path, but the orchestrator treats a non-null tier on any other path as out-of-spec noise. The field is always present in the envelope so the top-level shape is uniform across all routing paths. |
| `halt_trigger` | enum or null | Required non-null when `next_action == HALT_FOR_OPERATOR`. Allowed values: `destructive_action`, `operator_auth_boundary`, `repeated_envelope_failure`. |

The optional `spillover_findings_path` key is set only when a reviewer
truncates more than 50 findings — it points to a JSON file under `tmp/`
containing the full list (`maxLength: 1024` on the path string itself).
Absence means there is no spillover. See the worked example below for
the canonical envelope-plus-sidecar shape.

## Status x Next-Action Validity

The schema's `allOf` clauses pin every legal pairing. The matrix:

| `status` | Allowed `next_action` |
|----------|----------------------|
| `APPROVED` | `APPROVE` only |
| `APPROVED_WITH_NOTES` | `APPROVE`, `RETURN_TO_WORKER_ADVISORY`, `RETURN_TO_WORKER` |
| `REJECTED` | `RETURN_TO_WORKER` only |
| `BLOCKED` | `HALT_FOR_OPERATOR` only |
| `ESCALATE` | `ESCALATE_REVIEWER_TIER` only |
| `ABSTAIN` | `RETRY_REVIEWER` only |

Any `status` x `next_action` combination outside this matrix fails
schema validation and raises `EnvelopeParseError`.

Additional cross-cutting rules (also schema-enforced):

- `next_action == HALT_FOR_OPERATOR` requires a non-null `halt_trigger` string.
- `next_action == ESCALATE_REVIEWER_TIER` requires a non-null `recommended_next_tier` string.
- `next_action == RETURN_TO_WORKER` requires `feedback_to_forward` with at least one finding.
- `next_action == RETURN_TO_WORKER_ADVISORY` requires `feedback_to_forward` with at least one finding.

## Worked Examples

The orchestrator routes envelopes from three agent families: native
Claude reviewers (`claude-native`), bridge reviewers that translate an
external CLI's prose conclusion into the envelope contract
(`codex-bridge`, `gemini-bridge`, `copilot-bridge`), and internal QA
agents (`qa-internal`). Each family uses the same envelope schema, but
the authoring conventions differ — these three examples mirror the
canonical fixtures under `tests/fixtures/envelopes/` and cover the
representative shapes a W4 maintainer is most likely to encounter.

### Claude-native unanimous APPROVE

Plan §4.2 Example A. The simplest non-degenerate envelope: a
high-tier native reviewer approves with no findings. Note the
discriminated `json envelope` fence — this is the literal byte sequence
the parser scans for.

```json envelope
{
  "envelope_version": "1",
  "agent_id": "code-review-high",
  "agent_family": "claude-native",
  "agent_effort_tier": "high",
  "round": 1,
  "status": "APPROVED",
  "next_action": "APPROVE",
  "feedback_to_forward": [],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```

### Bridge REJECTED with §6.1.1-derived findings

Plan §6.1.1 mandates that bridge agents quote the external CLI's prose
conclusion verbatim in each finding's `description` (audit-trail
requirement). The `[codex@high]` prefix carries the originator
attribution the merge function uses for cross-family dissent
classification (§6.1.1 verdict-mapping table). Mirrors fixture
`tests/fixtures/envelopes/bridge_blocking_dissent_critical.md`.

```json envelope
{
  "envelope_version": "1",
  "agent_id": "codex-reviewer-high",
  "agent_family": "codex-bridge",
  "agent_effort_tier": "high",
  "round": 2,
  "status": "REJECTED",
  "next_action": "RETURN_TO_WORKER",
  "feedback_to_forward": [
    {
      "severity": "critical",
      "file_path": "scripts/orchestrator/envelope_merge.py",
      "line_range": "118-124",
      "description": "[codex@high] The merge introduces a critical security flaw: the new authorization check at scripts/orchestrator/envelope_merge.py:118 short-circuits when the agent_family field is missing. An adversarial reviewer could omit the field to bypass the per-family ceiling normalization. This MUST be addressed before merge.",
      "suggested_fix": "Validate agent_family is non-empty before applying the ceiling lookup; raise EnvelopeParseError(reason=\"agent_family_missing\") if absent.",
      "rule_id": "Req-005",
      "blocking": true
    }
  ],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```

### qa-internal BLOCKED with operator_auth_boundary HALT

QA-internal agents emit `agent_family: "qa-internal"` and author the
envelope from their own native verdict (no §6.1.1 mapping applies
because there is no external CLI prose to translate). The
`HALT_FOR_OPERATOR` next_action requires a non-null `halt_trigger` —
the `operator_auth_boundary` value names the §17 contract the agent
is honoring. Mirrors fixture
`tests/fixtures/envelopes/qa_internal_test_halt_operator_auth.md`.

```json envelope
{
  "envelope_version": "1",
  "agent_id": "qa-test",
  "agent_family": "qa-internal",
  "agent_effort_tier": "medium",
  "round": 1,
  "status": "BLOCKED",
  "next_action": "HALT_FOR_OPERATOR",
  "feedback_to_forward": [
    {
      "severity": "critical",
      "file_path": "tests/scripts/test_repos_reset.py",
      "line_range": "42",
      "description": "Staged test invokes `task repos:reset`, which mutates the local repo clone and requires explicit operator authorization (CLAUDE.md §9). Halting for user confirmation rather than executing autonomously.",
      "rule_id": "operator-auth-boundary",
      "blocking": true
    }
  ],
  "recommended_next_tier": null,
  "halt_trigger": "operator_auth_boundary"
}
```

### Spillover Worked Example

When a reviewer surfaces more than 50 findings, the envelope MUST keep
`feedback_to_forward` at exactly 50 entries (the schema's `maxItems`)
and MAY forward the remainder via `spillover_findings_path`. The path
points to a JSON file under `tmp/`; once the W4 merge function lands,
the orchestrator will merge the sidecar with the inline list before
downstream routing.

> **W1 caveat — read this before relying on spillover.** The W1 parser
> does NOT consume `spillover_findings_path` sidecars. Until the W4
> merge function ships
> (`scripts/orchestrator/envelope_merge.py`), anything in the sidecar
> is silently dropped from worker routing — only the inline 50 reach
> the worker. Reviewers MUST prioritize the inline 50 as the complete
> actionable list, not as the "first page" of a paginated set.

Envelope (60 findings — 50 inline, 10 in sidecar; finding bodies
elided for brevity):

```json envelope
{
  "envelope_version": "1",
  "agent_id": "code-review-xhigh",
  "agent_family": "claude-native",
  "agent_effort_tier": "xhigh",
  "round": 2,
  "status": "REJECTED",
  "next_action": "RETURN_TO_WORKER",
  "feedback_to_forward": [
    {
      "severity": "critical",
      "file_path": "src/brownfield_ai/foo.py",
      "line_range": "42-58",
      "description": "Finding 1 of 60 — full prose elided. The first 50 entries appear inline in this array.",
      "suggested_fix": "Replace bare except with structured EnvelopeParseError raise.",
      "rule_id": "Req-N05",
      "blocking": true
    }
  ],
  "recommended_next_tier": null,
  "halt_trigger": null,
  "spillover_findings_path": "tmp/findings-overflow-r2.json"
}
```

Sidecar (`tmp/findings-overflow-r2.json` — same finding shape as
`feedback_to_forward[*]`, holding entries 51–60):

```json
{
  "envelope_agent_id": "code-review-xhigh",
  "envelope_round": 2,
  "spillover_findings": [
    {
      "severity": "minor",
      "file_path": "src/brownfield_ai/bar.py",
      "line_range": "120",
      "description": "Finding 51 of 60 — first overflow entry.",
      "suggested_fix": "Narrow the catch to ValueError.",
      "rule_id": "lang.python.exception-handling",
      "blocking": false
    }
  ]
}
```

Sidecar conventions:

- File lives under `tmp/findings-overflow-<round>.json` so the
  workspace `tmp/` policy (CLAUDE.md §10) keeps it out of the working
  tree.
- The sidecar repeats `envelope_agent_id` and `envelope_round` so the
  orchestrator can verify it pairs with the right envelope before
  merging.
- Each entry follows the same JSON Schema as
  `feedback_to_forward[*]` (description ≤ 2000 chars, suggested_fix
  ≤ 2000 chars, valid `severity` enum, etc.). The merge function
  rejects malformed sidecar entries the same way it would reject
  malformed inline findings.
- The sidecar is read-only after emission; do not append after the
  envelope has been forwarded.
- The orchestrator's per-sidecar validation (path existence,
  `envelope_agent_id` / `envelope_round` identity-pair check, per-entry
  schema validation against the `feedback_to_forward[*]` shape) lands
  with the W4 merge function (`scripts/orchestrator/envelope_merge.py`).
  Until that ships, the sidecar shape documented above is a forward
  spec — reviewers MAY emit it, but the W1 parser does not consume it.

## Merge and Circuit-Breaker

The merge function and per-family circuit-breaker spec land in Wave 4
of the same epic. Until those modules ship, the orchestrator continues
to consume reviewer output via the legacy prose path for non-migrated
agent families.

- Forward reference (W4): `scripts/orchestrator/envelope_merge.py`
- Forward reference (W4): `scripts/orchestrator/envelope_circuit_breaker.py`

Wave 1 ships only the parser (`scripts/orchestrator/envelope_parser.py`).
The parser exposes `parse_or_fallback`, which validates the envelope
JSON, applies the per-family ceiling normalization, and produces a
`ParseResult` with the (optionally rerouted) envelope plus any
out-of-band audit annotations.

## Cross-references

- Plan source: [`tmp/plan-reviewer-output-envelope.md`](../tmp/plan-reviewer-output-envelope.md) §4 (envelope schema), §5 (merge), §7 (circuit-breaker), §9 (backward-compat path).
- Effort-tier policy: [`docs/effort_tiers.md`](./effort_tiers.md).
- Verification protocol: [`docs/verification_protocol.md`](./verification_protocol.md).
