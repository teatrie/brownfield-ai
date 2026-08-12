# Reviewer Effort Tiers

## Purpose

This document is the canonical taxonomy for reviewer-agent reasoning
effort across the three families wired into the repo's Dual-Model and
Cross-Family Review gates: Anthropic Claude (`code-review*`), OpenAI
Codex (`codex-reviewer*`), and Google Gemini (`gemini-reviewer*`).

Epic 1 (REVIEWER-EFFORT-001) normalized effort-tier semantics for the
three reviewer-agent families above. Epic 2 extends the same taxonomy
to the remaining non-reviewer agent families: `-xhigh` variants now
ship for `deep-researcher`, `planner`, `qa-standards`, `tdd-red`,
`tdd-green`, `tdd-refactor`, and `general-purpose`. The `explore`
family uses `-high` only (its `fast-search` model tier does not pair
meaningfully with `-xhigh`/`-max` reasoning-budget knobs;
`deep-researcher-{xhigh,max}` covers the deeper-research need). Some
non-reviewer agents still lack `-max` variants — see the per-family
columns in the Cross-Family Mapping table below for current coverage.

## Canonical 4-Level Ladder

The ladder below is the source of truth for the `EFFORT` env var
threaded through the Taskfile CLI_ARGS pipeline into each reviewer's
wrapper script. The reviewer floor is HIGH internal reasoning. No
config layer sets it: it is held by the caller contract on both
bridges, and on Codex additionally by the wrapper, which defaults an
omitted `EFFORT` to `high`. Every Codex and Gemini bridge invocation is
required to pass `EFFORT` explicitly: the `codex-reviewer*` and
`gemini-reviewer*` variants each
name their own tier, and the diff-review gate carries `EFFORT` in the
bridge invocation contract in `.claude/skills/diff-review/SKILL.md`
Step 2. Claude-native reviewers take their tier from the agent
frontmatter instead, per Model-Tier and Effort-Tier Binding below.
The wrapper then validates the value it received against the enum
`{medium,high,xhigh,max}`, so `low` and `minimal` are rejected — see
[Where the Codex Effort Value Comes From](#where-the-codex-effort-value-comes-from).

| Level | `EFFORT` value | Scope | Model Tier |
|---|---|---|---|
| medium (standard) | `medium` | default for all reviewers | Sonnet 4.6 / Flash / caller-supplied `MODEL` (the CLI's own default when unset) |
| high | `high` | plan reviews, architecture audits | Opus 4.7 / Pro / gpt-5.4 |
| xhigh | `xhigh` | very deep diff/plan reviews — Opus 4.7 only | Opus 4.7 @ xhigh |
| max | `max` | frontier reservation, exceptional cases | Opus 4.7 @ max |

## Cross-Family Mapping

The following table maps each `EFFORT` value to the corresponding
model selection per reviewer family. Columns that show a ceiling
collision indicate the family's upstream enum does not expose a
distinct tier at that level — the wrapper collapses to the highest
available tier at composition time.

**Where the collapse happens**: the collapse is applied inside each
family's wrapper script (`scripts/agent-cli/<family>-review.sh`) at
CLI_ARGS → env-var marshalling time — *not* at bridge-agent-body
composition time, and *not* at runtime inside the reviewer CLI. The
bridge agent bodies (`.claude/agents/<family>-reviewer-{high,xhigh,max}.md`)
declare the caller's intent (`effort: max`) and the wrapper translates
that into the best available upstream tier. This means an Opus `max`
caller always gets Opus at `max`, but a Gemini `max` caller receives
the same `gemini-3.1-pro-high` binding as a Gemini `xhigh` caller; the
bridge bodies link back to this table so reviewers understand the
translation without inspecting the wrapper.

| `EFFORT` | Claude `code-review` | Codex (model + reasoning) | Gemini (`-m <alias>`) |
|---|---|---|---|
| medium | Sonnet `high` | caller-supplied `MODEL` (the CLI's own default when unset) + `high` | `<tier-sn>-high` |
| high | Opus `high` | `gpt-5.4` + `high` (MODEL override) | `gemini-3.1-pro-high` |
| xhigh | Opus `xhigh` | `gpt-5.4` + `xhigh` (MODEL override) | `gemini-3.1-pro-high` (ceiling collision) |
| max | Opus `max` | `gpt-5.4` + `xhigh` (MODEL override, ceiling collision) | `gemini-3.1-pro-high` (ceiling collision) |

> **Reviewers run at HIGH internal reasoning minimum.** The Codex
> wrapper defaults an omitted `EFFORT` to `high`, and the caller
> contract requires every bridge invocation to name its tier anyway.
> `EFFORT=low` is rejected by both bridge wrappers and has no
> Claude-native variant —
> LOW is a false economy for review quality. MEDIUM is the floor for
> reviewers; if a caller wants cheaper execution, they should pick a
> lower model tier (Flash / gpt-5.3-codex / Sonnet) at HIGH internal
> setting rather than a high-capacity model at LOW internal.

### Design Rationale — MEDIUM = lower model at HIGH internal setting

The MEDIUM effort tier runs the lower-capability model at its MAX
internal reasoning/thinking setting — it is not a "medium-everything"
tier. This economizes on model cost (Sonnet and Flash are
substantially cheaper per token than Opus/Pro/gpt-5.4) while keeping
reviews thorough. On Codex the `medium` model is not pinned to a
lower tier by anything in this repo — it is caller-supplied via
`MODEL`; the CLI's own default when unset — so the economy there
depends on what the caller passes. HIGH+ tiers elevate the model
itself, not the internal reasoning level — from HIGH onwards, the
internal setting stays at its maximum (collapsing at the family's
ceiling for xhigh and max).

## Model-Tier and Effort-Tier Binding

`medium` effort runs the standard reviewer model per family at its
MAX internal setting — Sonnet 4.6 at `high` reasoning on Claude and
`gemini-3-flash-high` on Gemini (Flash tier at HIGH thinking); those
two are pinned. Codex is not: the wrapper passes no `-m` at
`medium`, so the model is caller-supplied via `MODEL`; the CLI's own
default when unset — at `high` reasoning either way. This is the
baseline gate posture for routine code review (see the **Design
Rationale** note above the Cross-Family Mapping table).

`high`, `xhigh`, and `max` all require the deep-reasoning model per
family: Opus 4.7 on Claude, `gemini-3.1-pro-preview` on Gemini, and
`gpt-5.4` on Codex. Pairing a deep-effort tier with the standard
reviewer model is a configuration error — the wrapper enforces the
mapping via the customAliases (Gemini) and `-c model_reasoning_effort`
override (Codex); Claude variants are pinned via `model_tier:
high-reasoning` in the agent frontmatter.

## Fallback Chain

When the HIGH-tier model (Opus 4.7 / Pro / gpt-5.4) returns HTTP
429 (rate limit / quota) or 503 (service unavailable), reviewer
wrappers automatically retry once with the MEDIUM tier model at HIGH
internal reasoning/thinking. This preserves review quality while
degrading gracefully under capacity pressure.

### Decision Tree

```text
HIGH-tier invocation (EFFORT in {high,xhigh,max} or MODEL override = HIGH)
    │
    ├─ success → done
    │
    └─ 429 or 503
          │
          ├─ Codex (wrapper-level): MODEL=gpt-5.4 <e> → MODEL=gpt-5.3-codex + reasoning=high
          │     │
          │     ├─ success → done (NOTICE on stderr)
          │     └─ failure → CODEX_ERROR (error_class=high_tier_fallback_failed)
          │
          ├─ Gemini (wrapper-level): gemini-3.1-pro-<e> → gemini-3-flash-high
          │     │
          │     ├─ success → done (NOTICE on stderr)
          │     └─ failure → GEMINI_ERROR (no further chain; agent
          │                  surfaces the failure to the orchestrator)
          │
          └─ Claude (platform-level): Opus 4.7 <e> → Sonnet 4.6 high
                │
                (Claude Code's built-in platform fallback mechanism is
                expected to handle this degradation — no wrapper code.)
```

### Per-Family Behavior

- **Codex** (`scripts/agent-cli/codex-review.sh`): only triggers when
  the orchestrator passed a non-default `MODEL` (e.g., `gpt-5.4`). If
  `MODEL` is unset the wrapper passed no `-m` at all, so there is no
  caller-selected model to step down from and the fallback is a
  no-op. The transient-retry path still handles same-model retries
  where appropriate.
- **Gemini** (`scripts/agent-cli/gemini-review.sh`): triggers whenever
  the resolved `-m` alias is a Pro-tier alias (`gemini-3.1-pro-*`)
  and stderr indicates 429 or 503. The wrapper retries once with
  `gemini-3-flash-high`; on second failure it emits `GEMINI_ERROR`.
  Preview models (`-preview` aliases) require `GEMINI_API_KEY` auth
  for stable capacity — see [docs/learnings.md](learnings.md). With
  API-key auth on preview, 429/503 events are not observed in
  practice, so the Pro→Flash retry is belt-and-suspenders.
- **Claude** (`code-review*`): no wrapper-level fallback is
  implemented. Claude Code's platform has a built-in Opus 4.7 →
  Sonnet 4.6 degradation on capacity pressure; this is an expected
  behavior contract, not repo code.

The fallback is narrowly keyed on 429/503 (and rate-limit / quota /
service-unavailable stderr markers). Auth failures (401/403), invalid
arguments, and other terminal error classes do not trigger the
fallback — they propagate as-is.

## Frontier-Reservation Rule

`xhigh` is the default for deep-effort reviews. The `-xhigh` variants
(`code-review-xhigh`, `codex-reviewer-xhigh`, `gemini-reviewer-xhigh`)
are the right choice for complex plan reviews, multi-file security
audits, and cross-cutting architecture assessments.

`max` is reserved for exceptional cases where `-xhigh` has
demonstrably failed — for example, a rework review after a fresh
BLOCKED verdict from `-xhigh` on the same artifact, or a high-stakes
architectural decision where the Orchestrator has explicit evidence
that `-xhigh` left critical ambiguity unresolved. Agents should
default to `-xhigh` and only escalate to `-max` on explicit
re-invocation. Treating `max` as the default erases the signal that
`xhigh` provides and wastes frontier capacity on ordinary reviews.

## Where the Codex Effort Value Comes From

No config file pins a reviewer reasoning effort. `.codex/config.toml`
declares no `[profiles.*]` table and none may be added: on codex-cli
0.146.0 that project-local path is not a config layer codex loads at
all, so anything written there — a profile table included — is inert
and reaches no run, while still reading like a live pin. Where a
`config.toml` *is* loaded, a declared profile is worse than inert:
`codex exec -p reviewer` aborts with a fatal config-load error,
directing the settings into a separate
`$CODEX_HOME/<name>.config.toml` instead. The user-level reviewer
profile that ships in the agent-cli image
(`docker/agent-cli/codex-config.toml`) pins the reviewer *model* only
— and it is installed as a loaded `/home/agent/.codex/config.toml`, so
its `[profiles.reviewer]` table currently trips that abort instead of
pinning anything; relocating it to `$CODEX_HOME/reviewer.config.toml`
is tracked as TODO-0228.

Effort is therefore carried entirely on the invocation. When the
wrapper is invoked with `EFFORT=<value>` it applies the ceiling
collapse (`medium`/`high` → `high`, `xhigh`/`max` → `xhigh`) and
passes the result as a **top-level** `-c` override:

```text
-c model_reasoning_effort=<mapped-value>
```

The key must be top-level. The same key sent in a
`profiles.reviewer.`-prefixed form does not reach the run — the CLI
accepts the override and still reports its own default effort in the
startup banner. The command the wrapper composes for a `high` override,
with the combined template+subject prompt on stdin, is shown below as an
illustration only — raw `codex exec` invocations that bypass the task
wrapper are not a supported path:

```bash
codex exec -p reviewer \
  -c model_reasoning_effort=high \
  < tmp/codex-combined-prompt-1.txt
```

When `EFFORT` is unset the wrapper substitutes `high`, so the run
still carries a `-c` override and never falls through to the CLI's own
default reasoning effort — that substitution is what makes the HIGH
floor above hold mechanically. Callers still pass `EFFORT` explicitly
so the tier the reviewer reports is the tier the gate selected.

## Cross-Family Asymmetry

Claude's `xhigh` tier reports a substantially larger thinking budget
than the peer `HIGH` tiers exposed by Codex and Gemini at the time
of this writing. The underlying numbers are not reproduced here
because they are expected to shift with every upstream release, and
are best re-verified against current vendor documentation rather than
captured as repo artifacts.
The practical consequence is that a bridge reviewer running at
`-xhigh` or `-max` produces a strictly shallower review than a
Claude-native reviewer at the equivalent tier — not just "one tier
step" less.

**Encoding in the merge function.** The orchestrator applies the
Cross-Family Asymmetry rule via the merge function in
[`scripts/orchestrator/envelope_merge.py`](../scripts/orchestrator/envelope_merge.py);
see [`docs/reviewer_envelope.md`](reviewer_envelope.md) §5 for the
canonical algorithm. The merge function is **faithful** to the
"signal to investigate, not automatic veto" guidance below: at
`gate_effort_tier` of `xhigh` or `max`, when all claude-native
envelopes APPROVE and at least one bridge envelope returns
`RETURN_TO_WORKER` with critical/significant blocking findings, the
gate result is `APPROVE` with a `cross_family_dissent` audit
artifact attached — **not a HALT** (B-1 R2). The orchestrator MUST
checkpoint the dissent to the Execution Ledger so operators can
investigate post-hoc, but the gate does not block.

The bridge `HALT_FOR_OPERATOR` next-action is **not** softened by
this rule — operator-auth boundaries always halt the gate via merge
Rule 1, regardless of agent_family (B-5 R2). The
Frontier-Reservation Rule below is encoded in
`envelope_merge.py` Rule 4 (B-4 R2): a reviewer that recommends
`max` is capped to `xhigh` when the prior round did not run at
`xhigh`, preserving the planner's intended escalation cadence.

This is a present-state asymmetry, not a permanent structural limit.
Future OpenAI and Google releases are expected to introduce matching
effort tiers as the upstream APIs stabilize. The repo's taxonomy is
designed to absorb those additions without renaming the `EFFORT` enum
— the cross-family mapping table above will gain new rows or lose
ceiling-collision notes as upstream tiers expand.

Orchestrator guidance: at `-xhigh` and `-max`, treat the
Claude-native reviewer's verdict as load-bearing. Bridge reviewers
serve as cross-family sanity checks — a diverging verdict is a
signal to investigate, not an automatic veto. Re-evaluate this
posture on every Codex or Gemini release that changes the tier
enums; update this section when the asymmetry narrows.

## Invocation Quick Reference

Three canonical invocations, one per family, at `-xhigh`:

```text
Agent(subagent_type="code-review-xhigh")   # Claude native — subagent
                                          # dispatch; no task alias exists
task agent:review:codex:local -- ROUND=1 EFFORT=xhigh REVIEW_TYPE=diff DIFF_FILE=tmp/qa-diff.txt
task agent:review:gemini:local -- ROUND=1 EFFORT=xhigh GEMINI_MODEL=gemini-3.1-pro-preview REVIEW_TYPE=diff DIFF_FILE=tmp/qa-diff.txt
```

For the full bridge-reviewer invocation contract (pre-flight, session
UUID, prompt construction, exit artifacts), see
[.claude/agents/codex-reviewer.md](../.claude/agents/codex-reviewer.md)
and [.claude/agents/gemini-reviewer.md](../.claude/agents/gemini-reviewer.md).

## Related Documents

- [docs/verification_protocol.md](verification_protocol.md) —
  Cross-Family Review Extension gate behavior.
- [.claude/agents/code-review.md](../.claude/agents/code-review.md) —
  Claude-native reviewer base agent.
- [.claude/agents/codex-reviewer.md](../.claude/agents/codex-reviewer.md) —
  Codex bridge reviewer agent.
- [.claude/agents/gemini-reviewer.md](../.claude/agents/gemini-reviewer.md) —
  Gemini bridge reviewer agent.
