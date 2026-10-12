Status: Approved v6 — operator approved without a further review round; implementation in progress (2026-10-11)

# Plan — PR 1: port "Guidance Over Exhaustive Rules" (`PROTOCOL-PORT-001`)

This PR ports the parent repo's **Guidance Over Exhaustive Rules** principle: agent-facing docs give an agent enough
guidance to reason to the best decision, instead of a rule for every case. It adds one local extension: mechanics a
doc defines are drawn as a diagram or pseudocode rather than narrated (Req-030). It is the first PR of the port. The clean-room PR review gate is ported
afterwards, under its own epic and plan folder, which do not exist yet.

**How this plan is written.** It follows the principle it ports (operator instruction, 2026-10-10): intent, decision
criteria and the traps an implementer cannot derive, with pointers instead of copies. The Requirements Traceability Map
stays explicit. Claims are tagged (validated), (sourced) or (unverified). File:line citations are as of base commit
`44e1002`; lines in files this PR edits shift after merge. Review history (rounds 1–5, when PR 1 and PR 2a shared one
plan) was session scratch in `tmp/protocol-port/` and is not committed; this epic's Execution Ledger artifacts
(`step_result`, `gate_verdict`) are the durable record.

**Parent source.** The source of truth for the ported text is commit `66126cc` (PR #686) in the parent repo
`data-ai`. A local snapshot of that commit's diff, `tmp/protocol-port/parent/66126cc.diff`, was the implementers'
working copy; it is scratch, and the commit is the durable reference. `task git:run` runs in the `repo-cli`
container, which mounts only the workspace and `~/.ssh` (sourced: `docker-compose.yml:40-42`), so the parent checkout is not mounted. The commit's `full-pr-reviewer`
Lens 4 hunk belongs to the clean-room gate port, not this PR.

## Domain Research Summary

- **Signals:** `diff-review`, `docs-review`, `claude-review`, `coding_standards.md`, `planning_protocol.md`,
  `verification_protocol.md`, `CLAUDE.md`. All in this workspace; no `repos/` signal.
- **Ledger:** `task ledger:index -- --limit 20` (validated) shows no epic covering this work.
- **Context Sufficiency Gate:** sufficient. Every anchor below was located in the tree (sourced).

## Decisions (operator, 2026-10-10 and 2026-10-11)

- One plan and one ledger epic per PR; this folder holds PR 1's plan.
- **Plan-file exception:** the root `plan.md` holds slice 1a of `UPSTREAM-PORT-001`. For this epic, this plan file
  and its working copy `tmp/protocol-port/guidance-working.md` stand in for the root `plan.md` wherever the protocols
  read it: the per-step read (Principle 13, `verification_protocol.md:42`) and the Spec Verification Gate's input
  (`verification_protocol.md:959-965`).
- **Spec Verification deviation:** rows whose Test Coverage is `none — read` are graded on their Verification column
  instead of requiring a test. This epic only; no protocol text changes. In Spec Verification round 2 codex rejected
  the deviation (F1) because the gate's written verdict definitions (`verification_protocol.md:989-1009`) then
  disagree with this epic's practice; the operator kept the deviation on 2026-10-11, and TODO-0388 tracks amending
  the gate so rule and practice agree.
- **Normative change approved:** `diff-review` Step 3's rule that the Orchestrator MUST delegate every finding gains
  the held-cut exception (Req-004). The operator approved it directly in session on 2026-10-11; the approval is
  recorded in the S1.7 `step_result`.
- Steps run sequentially.

## Safeguards

| Safeguard | Check |
|---|---|
| Every shell step is a `task <ns>:*` call in the allow list | `.claude/settings.json:3-12` has exactly eight namespaces (sourced) |
| No `>` redirect | Hook rule 11b (sourced: `block-container-escape.sh:116-139`) |
| Agents with Edit can create files; `task` agents (`[Read, Bash]`) cannot | An Edit with an empty `old_string` created a new file (validated: `tmp/protocol-port/edit-create-probe.md`, uncommitted session scratch) |
| No ported text names a parent-only thing | e.g. lineage bullets, Cascade Search, Inventory Rule Parity, JIRA ticket lines |

## Requirements

### Positive requirements

| Req-ID | Requirement | Impl Step | Test Coverage | Verification |
|---|---|---|---|---|
| Req-001 | `docs/coding_standards.md` gains `## Guidance Over Exhaustive Rules` after `## Documentation Standards`, from parent commit `66126cc`. Every example is true here: the Cut example cites `lifecycle.py` and `claims.py`; the "Point, do not restate" exception example is a local one (e.g. `claude-review`'s **Content parity** check, `.claude/rules/` against `.github/instructions/`) | S1.1 | none — read | `claimed_by` is cleared in `lifecycle.py` (sourced: 111, 256), stale auto-release is `claims.py:28-71`, `task ledger:touch` exists (`taskfiles/ledger.yml:176`), Content parity is at `claude-review/SKILL.md:53`. No parent-only name remains |
| Req-030 | Local extension beyond the parent (operator, 2026-10-11): the new section gains the **Draw mechanics, don't narrate them** bullet (P2). It applies only to mechanics a doc itself defines; behaviour owned by code or a tool is still pointed to. Diagrams use Mermaid, which the repo already uses (validated: 5 fences in `docs/vertical_slicing_guide.md` and `docs/local_development.md`) | S1.1 | none — read | The bullet matches P2 and sits with the section's other bullets |
| Req-002 | `docs/planning_protocol.md`: the Draft step gains the guidance bullet, and Resolution step 6.1 gains the fix-rule sentence. Both keep the Requirements Traceability Map explicit | S1.2 | none — read | Read §2 steps 3 and 6 |
| Req-003 | The FRR prompt (`verification_protocol.md` §Finding Resolution Review step 2) accepts a cut or generalisation to intent plus a pointer, except a cut that changes what a normative rule requires, and still rejects a claim that is wrong or missing a trap | S1.2, S1.13 | none — read | The prompt has one copy in the tree (sourced), so no mirror changes |
| Req-004 | `.claude/skills/diff-review/SKILL.md` gets all four of `66126cc`'s hunks: the Critical Invariants pointer, the item 5 extension (item 5 is lines 211–226, between `SHARED:diff-scope` end at 202 and `SHARED:diff-dimensions` start at 242), the normative-cut carve-out in Step 3 (headless: checkpoint unresolved and HALT), and the cross-reference note that the item 5 extension needs no `tdd-refactor.md` change (`66126cc.diff:61-68`; the local paragraph is near `diff-review/SKILL.md:453`) | S1.3 | `none — read` (the parity test, `tests/scripts/test_reviewer_templates.py`, guards only the `SHARED:` blocks, which this row does not touch) | Read item 5 and Step 3; the parity test still passes with `diff.md` untouched; bridge reviewers do not get the item 5 extension (Risk-006, TODO-0394) |
| Req-005 | `docs-review/SKILL.md` gains the **Over-Specified Rules** audit and the headless guard. The parent's "Step 4 lineage bullets" example is replaced with a local audited copy (e.g. the `.github/instructions/` mirror) or dropped. The audit also covers every `SKILL.md` under `workflows/`, which Step 2's read list does not otherwise include and `claude-review` (scoped to `.claude/`) does not reach; third-party skills (e.g. under `third-party/`) are report-only | S1.4, S1.6, S1.10, S1.11, S1.14 | none — read | Read Step 2 and the headless paragraph (near line 155); no parent-only name remains |
| Req-006 | `claude-review/SKILL.md` gains the **Guidance Over Exhaustive Rules** check, with its `.github/instructions/` mirror clause and the route to the existing *Exception* (line 98) and report (line 103). "Cascade Search" becomes plain intent (e.g. "and every restated copy") | S1.4, S1.13, S1.14 | none — read | Read the check list near line 34; no parent-only name remains |
| Req-007 | The `CLAUDE.md` Coding Standards Index gains one entry pointing at the new section (P1) | S1.5 | none — read | Read the index |
| Req-029 | PR 1 commits this folder, `docs/plans/PROTOCOL-PORT-001/`, with its `README.md` lifecycle block and this plan (`docs/plans/README.md:26-59`). Both are committed with status `IN PROGRESS` / approved, not `DRAFT` | S1.5 | none — read | The folder is in PR 1's diff with a current status |

### Negative constraints

| Req-ID | Constraint | Verification |
|---|---|---|
| Req-N07 | MUST NOT apply a cut or generalisation that changes what a normative rule requires without operator sign-off | A read of the diff finds one hunk that changes a normative rule: `diff-review` Step 3's "MUST delegate every finding" gains the held-cut exception (and the matching Critical Invariants pointer). The FRR prompt addition (Req-003) adds a criterion rather than cutting one and was approved with the plan. The reviewer checks it against the operator's approval of 2026-10-11 recorded in the S1.7 ledger `step_result`, and its S1.9 rewording (a rejected cut leaves the finding open) against the approval recorded in the S1.9 `step_result`. Any other such hunk needs the same direct sign-off; the PR body points to the record rather than serving as the evidence |
| Req-N08 | MUST NOT write into `repos/` or overwrite the root `plan.md` | Diff paths |
| Req-N11 | MUST NOT port the parent's `full-pr-reviewer` Lens 4 hunk; it lands with the agent in the clean-room gate port | `.claude/agents/full-pr-reviewer.md` is not in PR 1's diff |

### Accepted residual risks

| Risk-ID | Risk | Mitigation |
|---|---|---|
| Risk-002 | `none — read` rows have no automated test | Graded per the Spec Verification deviation; TODO-0388 amends the gate |
| Risk-005 | Edits under `.claude/skills/` may prompt: Bash writes there are sandbox-denied (sourced: session sandbox config); whether Edit prompts is unverified | The operator approves prompts |
| Risk-006 | Bridge reviewers learn the principle only through the shared preamble's pointer to `docs/coding_standards.md` (sourced: `_invariants.md:8`) | Accepted; editing the invariant block would leak diff-only text into other templates; TODO-0394 tracks giving bridge diff reviewers the item 5 criterion without editing the invariant block |
| Risk-008 | Nothing checks Mermaid syntax: `@probelabs/maid` is installed in the `infra-lint` image (sourced: `docker/builders/Dockerfile.infra-lint`) but no lint task calls it (sourced: `git grep`), so a broken diagram would pass lint | Wiring `maid` into `task lint:markdown` is follow-up TODO-0387, outside this PR |
| Risk-007 | The codex seat cannot run inside the sandbox, and codex writes its review to a file of its own choosing (seen in rounds 1–5) | The main session runs codex with the sandbox disabled (operator-approved each time) and moves the file before the bridge translates it |

## Out of Scope

- `full-pr-reviewer` and every change of the clean-room gate port.
- Sweeping existing docs to apply the principle retroactively.
- Slice 1a of `UPSTREAM-PORT-001`, and the root `plan.md`.

## Proposed Wording

- **P1 (Req-007), `CLAUDE.md` Coding Standards Index entry:**
  `- [Guidance Over Exhaustive Rules](./docs/coding_standards.md#guidance-over-exhaustive-rules) — how agent-facing docs and plans state rules: intent, decision criteria, pointers and traps, not a case per rule.`

- **P2 (Req-030), bullet for `## Guidance Over Exhaustive Rules`:**
  "**Draw mechanics, don't narrate them**: when a doc defines a procedure with states, loops, ordering or several
  exits (e.g. a review gate's fold loop, a step's verify → checkpoint → commit order), give it as a state or flow
  diagram (Mermaid) or short decision-level pseudocode, and make that the normative form; prose gives intent, decision
  criteria and traps. Draw only mechanics the doc owns. For behaviour owned by code or a tool, point to the source
  instead (e.g. ledger transitions in `src/brownfield_ai/ledger/epics/constants.py`)."

Everything else comes from parent commit `66126cc`, adapted per the requirements above.

## Execution Strategy

**Platform:** Claude Code (per-subagent model selection). **Merge strategy:** one PR, branched from `main`.

| Slice | Epic | Complexity | Model tier | Implementer | Reviewer effort tier (Spec + Diff gates) |
|---|---|---|---|---|---|
| S1 — PR 1 | `PROTOCOL-PORT-001` | Simple | fast | `general-purpose` (effort medium, its lowest) | `high`¹ |

¹ Raised from the Simple default by the Dual-Model Review Gate floor (`planning_protocol.md:911-914`).

- **Epic lifecycle:** S1.0 runs `task ledger:create -- PROTOCOL-PORT-001 --title "..." --epic-status approved`, then
  `task ledger:status -- PROTOCOL-PORT-001 --new-status in_progress`. `auto-pr` CREATE later makes
  `in_progress → in_review`. Traps (sourced):
  - A plain `backlog → approved` exits 1 without a fast-path artifact (`lifecycle.py:197-202`); `create` checks only
    that the status is valid (`lifecycle.py:79-81`).
  - A `plan_snapshot` save rewrites the epic row (`artifacts/mutations.py:111-112`); its `--metadata` defaults
    `epic_status` to `pending` (`artifacts/cli.py:53`). Every save passes `epic_status` explicitly (the status the
    epic should hold, or `""` to keep it). A failed save has already superseded the previous snapshot
    (`artifacts/mutations.py:79-80`).
  - `ledger:next` returns an `in_progress` epic idle for over 24 hours to `approved` (`claims.py:28-71`), and
    `step_result` saves do not refresh it. Run `task ledger:touch -- PROTOCOL-PORT-001` with each checkpoint.
- **Parallelism:** none. Steps run one at a time, because `ci/test_staged.sh:22` checks the whole index.
- **Step order and commit boundary:** each step reads the working plan, checks scope against `CLAUDE.md`, stages, runs
  its gates, checkpoints the `step_result`, and only then commits (`auto-commit`, `planning_protocol.md:647-651`) and
  ticks the step. The index is empty before the next step starts, and Final QA's `git diff <base>...HEAD` sees every
  step. A step whose gates fail is fixed and re-verified before its checkpoint.
- **Cost:** direct subagents, not `agent-team`. The PR is one Simple slice run sequentially, so a team adds
  coordination with no tiering saving (`planning_protocol.md:819-821`).
- **Cross-family review:** no Complex slice, so §3 does not auto-activate it (`planning_protocol.md:731`). The operator
  chose Opus + codex for plan review; the Spec Verification and Code Diff Review gates also add the codex seat, run per
  Risk-007. Say "skip cross-family" to drop it.
- **Recommended Skill:** none. Implementation is direct subagent delegation (§7); the PR ships through `auto-pr`.
- **Progress tracking:** on approval, the orchestrator copies this plan to `tmp/protocol-port/guidance-working.md`.
- **Plan approval (operator, 2026-10-11):** approved after five Opus + codex review rounds on the earlier shared plan,
  none of whose round 3–5 findings concerned PR 1's content; Req-030 is new since then. The diff's Spec Verification
  and Code Diff Review gates still run before the PR.
- **PR protocol (operator):** `auto-pr`, with no automation signals.
- **Commit protocol (operator):** `auto-commit`.

## Phases

The sub-tasks follow `CLAUDE.md` Principle 13 and `verification_protocol.md:42`, `:182`. Staging uses `task git:add`
with this step's files only; `qa-lint` and `qa-test` run the gates; a `code-review` agent reads their raw output; a
`task` agent commits; the `step_result` goes to `PROTOCOL-PORT-001`. `test:staged` may be skipped only per
Principle 13.

- [ ] S1.0 Create and start epic `PROTOCOL-PORT-001`; copy this plan to `tmp/protocol-port/guidance-working.md`; branch `chore/guidance-over-rules` from `main`.
- [ ] S1.1 `coding_standards.md` section, including the local diagram bullet (Req-001, Req-030, P2).
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.2 `planning_protocol.md`, `verification_protocol.md` (Req-002, Req-003).
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.3 `diff-review` (Req-004); also run `task lint:reviewer-templates`.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.4 `docs-review`, `claude-review` (Req-005, Req-006).
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.5 `CLAUDE.md` index entry and this plan folder, with current statuses (Req-007, Req-029, P1).
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.6 Fix-ups from Spec Verification round 1 (codex F2–F5, F7): `diff-review` Step 3 item 1 excludes a finding held for the user; the `docs-review` audit covers workflow skill files; this plan cites parent commit `66126cc` and drops claims about plans that do not exist yet; Req-N07's verification needs a recorded operator reply.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.7 Fix-ups from Spec Verification round 2: `diff-review` Step 3 defines what happens to a held cut after the user decides (codex R2-F1); Req-N07 names the approved normative change and its record (R2-F2); the Decisions record the F1 ruling and TODO-0388.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.8 Fix-ups from `auto-pr` Step 2b (docs-review and claude-review, operator-approved 2026-10-11): `diff-review` Critical Invariants say a normative cut is first held for the user, matching Step 3; the `docs-review` audit links `.github/instructions/` and `.claude/rules/`.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.9 Fix-ups from Code Diff Review Gate round 1 (operator-approved 2026-10-11): `diff-review` Step 3 gives the held-cut branch as pseudocode and a rejected cut leaves the finding open (codex F2, F3); item 5 links `coding_standards.md` (F4); `claude-review` scopes the mirror to rules; this plan dates its line citations, marks `tmp/` scratch as uncommitted, and notes Req-003 under Req-N07.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.10 Fix-ups from Code Diff Review Gate round 2: the headless held-cut branch records an ad hoc run's cut in the report when there is no epic (codex F2); the `docs-review` audit covers every workflow `SKILL.md`, third-party report-only (codex F3); the Spec-gate citation uses base numbering (Opus F1). Codex's F1 (Spec deviation) stands on the operator's ruling.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.11 Fix-up from Code Diff Review Gate round 3: headless `docs-review` fails closed on a held normative cut (checkpoint `verdict: fail`, halt before Step 7) instead of reporting completion (codex F2). Codex's F1 (Spec deviation) stands on the operator's ruling.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.12 Fix-ups from Code Diff Review Gate round 4: Req-004's test coverage is a read, since the parity test guards only the `SHARED:` blocks (codex F2); the `repo-cli` visibility claim cites `docker-compose.yml` (codex F3). Codex's F1 (Spec deviation) stands on the operator's ruling.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.13 Fix-ups from Code Diff Review Gate round 5: headless `claude-review` ends the run as failed when it holds a normative cut (codex P1); the FRR prompt's cut clause carries the normative-cut caveat (Sonnet note). The bridge-template gap (codex F2) is recorded under Risk-006 and TODO-0394.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] S1.14 Fix-ups from Code Diff Review Gate round 6: `docs-review`'s headless branch is decision-level pseudocode (codex F2, Opus note); Req-004 lists the parent's four hunks correctly (Opus note); `claude-review` clarifies "applied to every restated copy" (Sonnet note). Codex's F1 (Spec deviation) stands on the operator's ruling.
  - [ ] Sub-task: Read `tmp/protocol-port/guidance-working.md` and confirm this step's scope.
  - [ ] Sub-task: Parse [CLAUDE.md](../../../CLAUDE.md) to verify strict adherence to architectural standards/limits.
  - [ ] Sub-task: Explicitly stage changed files (git add) and run task test:staged and task lint:staged to ensure pipeline gates still pass.
  - [ ] Sub-task: Checkpoint the `step_result` and run `task ledger:touch -- PROTOCOL-PORT-001`; only then commit, and tick this step in the working copy.
  - [ ] Sub-task: Invoke /protocols to re-anchor on core rules before delegating the next phase.
- [ ] Execute docs-review and claude-review skills to validate structural alignment.

### Final QA

- [ ] Invoke `/protocols`.
- [ ] `task lint:changed` and `task test:changed`, run by `qa-lint` / `qa-test`.
- [ ] Spec Verification Gate on this plan's Requirements Traceability Map (all of it: every row here is PR 1's), at the reviewer tier above, with the codex seat. The reviewers receive the plan-file exception and the Spec Verification deviation.
- [ ] Code Diff Review Gate via the `diff-review` skill, at the reviewer tier above, with the codex seat (memory: invoke the skill, never hand-roll its steps).
- [ ] Invoke `/protocols`, then the selected PR protocol.

### Close-out (after merge)

- [ ] Set this folder's README lifecycle `Status` to `SHIPPED` and record any material deviation from this plan (`docs/plans/README.md:61-74`); this ships with the next PR's first step, since `main` is protected. Confirm `PROTOCOL-PORT-001` reaches `completed` (`task ledger:check-reviews`).
