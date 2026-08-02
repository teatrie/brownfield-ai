# Reviewer History — Per-Cycle Log

Historical log of every multi-reviewer review cycle. Companion to [reviewer-profiles.md](./reviewer-profiles.md) — the profiles doc holds lean recommendations; this doc holds the evidence that backs them.

**Workflow**: after every multi-reviewer gate, add a new entry at the bottom of this file using the template below. When the log accumulates enough cycles to shift a recommendation in the profiles doc, update that doc separately and reference the supporting entries here.

**Scope**: this doc is long-lived and grows unbounded. Do NOT load it into an agent's context just to decide which reviewers to use — load `reviewer-profiles.md` instead. Load this doc only when tuning recommendations.

---

## Entry format

```text
### Entry N — [YYYY-MM-DD] <branch> — <title>

- **Ledger EPIC ID / TODO ID**: <id or "none — ad-hoc">
- **Plan / purpose**:
- **Branch**:
- **Commit(s) reviewed**:
- **Reviewer roster**:
- **Findings table per round** (columns: ID, severity, per-reviewer U=unique, S=shared, —=missed)
- **Notes**: anything unusual — drift, new reviewer, unusual payload class, etc.
```

---

## Entry 1 — [2026-04-17] `qa/cli-args-shim-r1` — CLI_ARGS headless-safe task invocation convention

- **Ledger EPIC ID / TODO ID**: `QA-CLI-ARGS-SHIM-001` (plan_snapshot + gate_verdict + design_decision artifacts saved 2026-04-17); deferred findings tracked as `TODO-0081`
- **Plan / purpose**: migrate reviewer task recipes from legacy positional `task foo VAR=val` to a CLI_ARGS shim form (`task foo -- VAR=val`) so headless sessions stop hitting Bash permission prompts. Add a PreToolUse hook (`.claude/hooks/block-sandbox-prompt-patterns.sh`) to fail-closed on sandbox-prompt-trigger patterns. Add a shim (`scripts/agent-cli/cli-args-to-env.sh`) that validates `KEY=value` tokens against an allowlist regex before exec'ing the target with env injected.
- **Branch**: `qa/cli-args-shim-r1` (5 commits: r1 `083e908` → r2 `59b9469` → r3 `c9649c6` → r4 `a9c636c` → r5 `f2907dc`)
- **Reviewer roster** (all rounds used the same 4):

  | Reviewer | Model | Effort | Mechanism |
  |---|---|---|---|
  | Opus | claude-opus-4-7 | high | code-review-high, 10-dim rubric |
  | Gemini | gemini-3.1-pro-preview | high | gemini-reviewer-high, custom prompt piped via gemini-review.sh |
  | Codex-custom | gpt-5.4 | high | codex-reviewer-high, custom prompt piped via codex-review.sh → `codex exec -p reviewer` |
  | Codex-builtin | gpt-5.4 | high | codex-reviewer-high, `codex exec -p reviewer review --base <base>` (native 10-point) |

### Round 1 — commit `083e908` (initial shim + Taskfile migration)

Verdicts: Opus YELLOW, Gemini RED, Codex-custom BLOCKED, Codex-builtin BLOCKED.

| ID | Finding | Severity | Opus | Gemini | Codex-custom | Codex-builtin |
|---|---|---|---|---|---|---|
| F1 | `git commit` bypass via compound/newline separator | P1 | — | **U** | **S** | — |
| F2 | Quoted-literal FP for `<(`/`$()`/backticks | P2 | — | — | **S** | **S** |
| F3 | Quoted-literal FP for pipe/`&&`/tee/grep rules | P2 | — | — | — | **U** |
| F4 | CLI_ARGS regression — agent docs still use `task foo VAR=val` | P1 | — | — | — | **U** |
| F5 | `--` smuggling — caller-controlled argv via `exec env` | defense-in-depth | **U** | — | — | — |
| F6 | bash 3.2 + `set -u` empty env_args array | portability | **U** | — | — | — |
| F7 | Missing valid-zero-token invocation test | concern | — | **U** | — | — |

- **Unique catches per reviewer**: Opus 2 (F5, F6), Gemini 2 (F1, F7), Codex-custom 0 (both shared), Codex-builtin 2 (F3, F4).
- **Shared catches**: F1 (Gemini + Codex-custom), F2 (Codex-custom + Codex-builtin).
- **Notes**: First round. Each reviewer surfaced different classes — no single reviewer caught all blockers. Validates the 4-reviewer orchestration cost.

### Round 2 — commit `59b9469` (F1–F7 fixes; review was r2-targeted delta)

Verdicts: Opus GREEN, Gemini **RED**, Codex-custom APPROVED WITH NOTES, Codex-builtin APPROVED WITH NOTES.

| ID | Finding | Severity | Opus | Gemini | Codex-custom | Codex-builtin |
|---|---|---|---|---|---|---|
| G1 | **Nested-quote bypass** — `echo " '$(evil)' "` expands `$(evil)` because outer `"..."` makes inner `'...'` literal at parse but bash still expands at runtime | **BLOCKER (code exec)** | — | **U** | — | — |
| G2a | Commit-bypass pipe-suffix leak (`git commit -m ok \| grep foo`) | BYPASS | — | — | **U** | — |
| G2b | Commit-bypass compound `;` leak | MITIGATED | — | — | **S** | — |
| G3 | Env-var-prefix evasion (`LC_ALL=C grep ...`) | GAP | — | — | **U** | — |
| G4 | `env VAR=val task ...` bypass | GAP | — | — | — | **U** |
| G5 | Path-qualified binaries bypass (`/usr/bin/grep`) | GAP | — | — | — | **U** |
| G6 | `gemini-review-container.sh` missing `-e REVIEW_DIFF_FILE` forward | GAP | — | — | **U** | — |
| G7 | Un-migrated reviewer personas + `docs/effort_tiers.md` legacy form | GAP | — | — | — | **U** |
| O1 | Stale `COMMAND_UNQUOTED` comment in hook header | COSMETIC | **U** | — | — | — |

- **Unique catches**: Opus 1 (O1), Gemini 1 (**G1 blocker**), Codex-custom 4 (G2a, G2b mitigated, G3, G6), Codex-builtin 3 (G4, G5, G7).
- **Notes**: **Gemini was the sole reviewer that caught G1**, the blocker that forced r3. This is the strongest single-reviewer find of the cycle — without Gemini, the branch would have merged with a code-execution bypass. Opus went GREEN and under-rotated on security analysis this round (focused on claim-verification against the r2 prompt rather than fresh security analysis).

### Round 3 — commit `c9649c6` (G1/G2a/G6/G7/O1 fixes; r3-targeted delta)

Verdicts: Opus **RED**, Gemini **RED**, Codex-custom **BLOCKED**, Codex-builtin APPROVED WITH NOTES.

| ID | Finding | Severity | Opus | Gemini | Codex-custom | Codex-builtin |
|---|---|---|---|---|---|---|
| Hα | Commit-bypass reopens G1 for commit bodies: `git commit -m "payload $(evil)"` matches via `"[^"]*"` atom, bypass fires, bash expands `$(evil)` at argv tokenization | **BLOCKER (code exec)** | **S** | **S** | **S** | — |
| Hβ | G7 migration incomplete — `workflows/repository-maintenance/prompts/security-verification.prompt.md:314-315` still legacy form | P2 (breaks smoke test) | — | — | — | **U** |
| Hδ | Commit-bypass admits `;`/`&&`/`\|\|`/`&` trailers | BLOCKER (mitigated upstream) | noted | **S** | **S** | — |
| Hγ1 | Backslash-escaped inner dquote edge case | YELLOW | **S** | **S** | — | — |
| Hγ2 | Missing negative test for `$()` in commit body | YELLOW | **U** | noted | — | — |
| Hγ3 | `:-` vs `:=` in `gemini-review.sh` fallback | YELLOW | — | — | — | **U** |
| Hγ4 | Header comment "body not re-parsed by bash" factually wrong | COSMETIC (but load-bearing for docs) | noted | **U** | — | — |
| Hγ5 | Header comment "three buffers" miscount | COSMETIC | **U** | — | — | — |
| Hγ6 | `docs/tool_chain.md` stale buffer model check | COSMETIC | **U** | noted | — | — |
| Hγ7 | Test-file style-only reformatting drift | NIT | **S** | — | **S** | — |

- **Unique catches**: Opus 2 (Hγ2, Hγ5), Gemini 1 (Hγ4), Codex-custom 0 unique (all shared), Codex-builtin 2 (Hβ, Hγ3).
- **Three-way convergence on Hα (blocker)**: Opus, Gemini, Codex-custom all independently produced identical regex traces. This is the strongest cross-model convergence of the cycle. Codex-builtin missed it because its workflow-integration scan axis did not examine hook regex semantics.
- **Notes**: Codex-builtin continued to uniquely surface cross-file workflow drift (Hβ). The pattern from r2 held (workflow gaps = Codex-builtin's axis).

### Round 4 — commit `a9c636c` (Hα/Hβ/Hγ4/Hγ5 fixes; r4-targeted delta)

Verdicts: Opus GREEN, Gemini **YELLOW**, Codex-custom off-rubric (~APPROVED WITH NOTES), Codex-builtin GREEN.

| ID | Finding | Severity | Opus | Gemini | Codex-custom | Codex-builtin |
|---|---|---|---|---|---|---|
| J1 | `<(...)` process-substitution rule left below commit bypass — `git commit -m <(evil)` unquoted spawns subshell at argv tokenization | **BLOCKER (code exec)** | — (analyzed quoted case only, concluded safe) | **U** | — (off-rubric) | — |
| J2 | Newline-to-space collapse CMD_START gap (pre-existing since r2) | YELLOW | — | — | **U** | — |
| J3 | `EFFORT_FALLBACK_ON_REJECT=1` not in shim allowlist | YELLOW | — | — | **U** | — |
| J4 | `DIFF_FILE` allowlisted in shim but no entrypoint consumes it | YELLOW | — | — | **U** | — |
| J5 | Header comment missing `<(...)` rationale | NIT | **U** | — | — | — |
| J6 | `$var` in `test_bare_commit_still_bypasses` — risk of future-maintainer misread | NIT | **U** | — | — | — |
| J7 | Whitespace inconsistency at security-verification.prompt.md:315 | NIT | **U** | — | — | — |

- **Unique catches**: Opus 3 (J5/J6/J7 — all nits), Gemini 1 (**J1 blocker**), Codex-custom 3 (J2/J3/J4 — off-rubric surface-area), Codex-builtin 0 on r4 (GREEN pass).
- **Notes**: **Gemini was again the sole reviewer that caught the blocker (J1)**. Same pattern as r2's G1: the code-execution vector analogous to the fixed case was missed by Opus (analyzed only the quoted case), off-rubric by Codex-custom (returned default P1/P2/P3 findings rather than r4 rubric), not in-axis for Codex-builtin. This is the second consecutive round where Gemini's bypass-pattern focus caught the only real blocker. **Codex-custom drifted off the r4 rubric** — it returned codex's default review format instead of using the r4-targeted prompt. Findings were still useful (all three surface-area gaps are real) but the critical r4 question about Hα regression was unanswered.

### Round 5 — commit `f2907dc` (J1 fix; r5-targeted delta)

Verdicts: Opus GREEN, Gemini GREEN, Codex-custom APPROVED WITH NOTES (bridge direct analysis, task invocation blocked), Codex-builtin GREEN.

| ID | Finding | Severity | Opus | Gemini | Codex-custom | Codex-builtin |
|---|---|---|---|---|---|---|
| K1 | `git commit -m<(evil)` (no space) — denied but not in parametrized tests | NIT | **S** | — | **S** | — |
| K2 | `git commit -m foo -F <(evil)` (trailing flag) — denied but not in tests | NIT | **S** | — | **S** | — |
| K3 | `COMMAND_ALL_STRIPPED` sed stripper fragile on escaped dquotes (pre-existing) | INFO | **U** | — | — | — |
| K4 | No section separator comment above three pre-bypass code-exec rules | INFO | **U** | — | — | — |
| K5 | `tests/scripts/test_gemini_review.py::test_empty_string_falls_through` pre-r1 debt | INFO | — | — | — | **U** |
| K6 | `docs/learnings.md` lacks "commit-bypass ordering" class-of-lesson entry | NIT (post-merge) | — | — | — | **U** |

- **Unique catches**: Opus 2 (K3, K4), Gemini 0, Codex-custom 0 unique, Codex-builtin 2 (K5, K6).
- **Three-way convergence on J1 closure**: Opus executed the exhaustive bash-expansion-class audit requested in the r5 prompt and concluded the three pre-bypass rules (`$()`, backtick, `<(...)`) exhaust bash's code-execution-at-argv-tokenization-time expansion classes. Gemini independently performed the same audit and reached the same conclusion. Strongest cross-model convergence on a closure claim of the cycle.
- **Notes**: First round without a security blocker since r1. All findings are NIT/INFO severity. **Opus did the exhaustive audit it failed to do in r4** — the r5 prompt explicitly enumerated expansion classes as a dimension, and Opus then produced the rigorous table. Lesson: Opus's rubric adherence is a strength when the rubric is comprehensive; its weakness is that it won't go beyond the rubric. Prompt design matters.

### Cycle-wide patterns observed on `qa/cli-args-shim-r1`

1. **Gemini was the sole catcher of the r2 blocker (G1) and the r4 blocker (J1).** Both were code-execution vectors that the other three reviewers missed via different failure modes (Opus: analyzed stated case only; Codex-custom: narrower security focus; Codex-builtin: different axis). This is load-bearing evidence for Gemini's mandatory designation on QA diff-review of security-adjacent diffs.

2. **Codex-builtin uniquely caught 4 different cross-file workflow-drift issues** across r2 and r3 (G4, G5, G7, Hβ). None of the other three reviewers found any of these in their respective rounds. This validates Codex-builtin as the mandatory workflow-integration reviewer.

3. **Codex-custom is the surface-area specialist.** Caught 8+ gaps across the cycle (G2a, G2b, G3, G6, Hα confirm, Hδ confirm, J2, J3, J4). Value is consistent but narrower than Gemini's bypass detection or Codex-builtin's cross-file sweep.

4. **Opus's value is the floor, not the ceiling.** Rarely catches unique blockers, but reliably covers the 10-dimension rubric and anchors the review record. When prompted to do exhaustive analysis (r5's expansion-class audit), delivers it rigorously.

5. **Three-way convergence is the strongest blocker confirmation.** Both Hα (r3) and J1-closure (r5) saw three reviewers independently produce matching traces/analyses. When ≥3 of 4 converge on the same regex trace or closure claim, the finding is very high-confidence.

6. **Custom prompts matter.** Codex-custom drifted off-rubric in r4 when the prompt was not structurally distinct from codex's defaults. When the critical question is specific (e.g., "does the reorder reopen G1 for commit messages?"), state it explicitly near the top of the prompt or it may be skipped.

7. **Bridge-agent file persistence is unreliable.** Every round had at least one bridge reviewer that could not save its own review file. Orchestrator must plan to capture inline subagent output and persist with the main-session Write tool.

### Medium-tier comparison (2026-04-17)

Calibration experiment: re-ran the r3 and r4 review rounds using the MEDIUM-effort variant of each reviewer agent (same four reviewers, lower-capability models at max internal reasoning) to quantify the capability gap vs the HIGH-tier baseline. Output files: `tmp/review-{sonnet,gemini-flash,codex-custom,codex-builtin}-r{3,4}-medium.md`; consolidated synthesis at `tmp/review-synthesis-medium-eval.md`.

**Medium reviewer roster**:

| HIGH sibling | Medium agent type | Medium model |
|---|---|---|
| Opus 4.7 (code-review-high) | code-review | Claude Sonnet 4.6 high-reasoning |
| Gemini 3.1 Pro (gemini-reviewer-high) | gemini-reviewer | Gemini 3 Flash high |
| Codex-custom gpt-5.4 (codex-reviewer-high custom) | codex-reviewer | gpt-5.3-codex high |
| Codex-builtin gpt-5.4 (codex-reviewer-high builtin) | codex-reviewer (native) | gpt-5.3-codex high |

#### r3 — finding-delta per medium reviewer vs HIGH sibling

| Finding | Severity | Opus HIGH | Sonnet MED | Gemini Pro HIGH | Flash MED | Codex-custom HIGH | Codex-custom MED | Codex-builtin HIGH | Codex-builtin MED |
|---|---|---|---|---|---|---|---|---|---|
| Hα (commit-body `$(...)`/backtick bypass) | **BLOCKER** | **S** | **S** | **S** | **S** | **S** | **S** | — | — |
| Hδ (compound `;`/`&&`/`\|\|`/`&` trailers) | P2 | noted | **S** (H5) | **S** | — (miss) | **S** | **S** | — | — |
| Hβ (workflow prompt migration) | P2 | — | — | — | — | — | — | **U** | **U** (same P1 on settings.json different axis) |
| Hγ1 (escaped-quote edge case) | P2 | **S** | **S** (H3) | **S** | **S** (H2 relabelled) | — | — (miss) | — | — |
| Hγ2 (missing negative test) | P2 | **U** | **S** (H4) | noted | **S** (H3) | — | — | — | — |
| Hγ4 (factually wrong prose) | cosmetic | noted | — | **U** | — | — | — | — | — |
| Hγ5 (buffer-count miscount) | cosmetic | **U** | noted §5 | — | — | — | — | — | — |
| Hγ6 (tool_chain.md spot-check) | cosmetic | **U** | — (miss) | noted | **S** (H2) | — | — | — | — |

- **Hα convergence held at medium**: 3-of-4 medium reviewers (Sonnet, Flash, Codex-custom) produced identical regex traces matching the HIGH-tier synthesis.
- **Codex-builtin same-axis drift at both tiers**: both medium and HIGH builtin flagged the same `.claude/settings.json` hook-wiring P1 (pre-existing unrelated working-tree modification), not the rubric Hα.

#### r4 — finding-delta per medium reviewer vs HIGH sibling

| Finding | Severity | Opus HIGH | Sonnet MED | Gemini Pro HIGH | Flash MED | Codex-custom HIGH | Codex-custom MED | Codex-builtin HIGH | Codex-builtin MED |
|---|---|---|---|---|---|---|---|---|---|
| J1 (unquoted `<(...)` commit-body bypass) | **BLOCKER** | — (quoted-case only, concluded safe) | **U** (J1, full trace) | **U** | **U** (I1) | — (off-rubric) | **U** (I1, 10/10 confidence) | — | — |
| J2 (newline-collapse CMD_START gap, pre-existing) | P2 | — | — | — | — | **U** | — | — | — |
| J3 (EFFORT_FALLBACK allowlist) | P2 | — | — | — | — | **U** | — | — | — |
| J4 (DIFF_FILE dead knob) | P2 | — | — | — | — | **U** | — | — | — |
| J5 (header invariant missing) | nit | **U** | **S** (J2 relabelled) | — | — | — | **S** (I3) | — | — |
| Test gap for `<(`/`>(`/shim-routed backtick | P1 | — | **S** (J3) | — | **S** | — | **S** (I2) | — | — |
| Hδ compound trailer carryover | P2 | — | **S** | — | **S** | — | — | — | — |

- **r4 bypass detection: MEDIUM outperforms HIGH.** J1 was caught by 1-of-4 HIGH reviewers (Gemini Pro alone) but by 3-of-4 MEDIUM reviewers (Sonnet, Flash, Codex-custom). Sonnet (medium) beat Opus (high) on this specific finding. Codex-custom (medium) beat Codex-custom (high) because the drift-mitigation preamble in the medium prompt worked.

#### Calibration conclusions

1. **Medium-tier is not strictly inferior on targeted regex/bypass rubrics.** For both rounds, medium convergence on the load-bearing blocker matched or exceeded HIGH-tier convergence. Sonnet 4.6 at high-reasoning is competitive with Opus 4.7 on narrow-scope security regex tracing. Gemini Flash retains the full bypass-detection behaviour of Gemini Pro.

2. **Bypass-detection is a Google-family property, not a Pro-tier property.** Flash caught J1 independently, matching Pro. The HIGH-tier "only-Gemini-Pro-caught-J1" result was about HIGH-tier Opus/Codex-custom drift patterns, not a Pro-specific ceiling.

3. **Prompt engineering > model tier for Codex drift.** Adding "the custom rubric takes precedence over codex native review defaults; the critical question is X — answer it explicitly" at the top of the prompt prevented codex's default-framing drift at MEDIUM. The same preamble at HIGH would plausibly close the HIGH-tier drift gap — worth folding into the codex-reviewer agent definitions rather than per-invocation prompts.

4. **Convergence is a fragile signal when reviewers drift on different axes.** r4 HIGH looked like 3-GREEN consensus; the MEDIUM replay showed the "consensus" was drift (Opus: quoted-only; Codex-custom: off-rubric; Codex-builtin: different axis) and Gemini Pro's YELLOW was the signal. Minority findings from the bypass-specialist reviewers deserve priority over majority GREEN.

5. **Codex-builtin is an orthogonal axis at any tier.** Both medium and HIGH builtin consistently caught workflow/config drift; neither tier does deep regex semantics. Model tier does not shift its role.

6. **MEDIUM suffices for**: targeted rubric follow-ups, delta-only reviews with narrow scope, cost-sensitive calibration/confirmation passes, and rounds where the HIGH baseline already exists and MEDIUM is confirming or challenging. **Escalate to HIGH for**: novel architectural reviews where the reviewer must propose rubric dimensions, cross-axis synthesis, and tiebreaking when MEDIUM reviewers disagree.

7. **Bridge-agent Write-tool unreliability holds at medium.** Sonnet medium and Codex-custom medium returned reviews inline. Gemini Flash wrote to non-canonical path (`tmp/gemini-review-output-{round}.md`) requiring orchestrator rename. Codex-builtin wrote directly to canonical path via the task wrapper. No tier change here.

---

## Entry 2 — [2026-04-17] `qa/hook-registration-integrity-001` — Hook-registration integrity check (TODO-0083)

- **Ledger EPIC ID / TODO ID**: `QA-HOOK-REGISTRATION-INTEGRITY-001` (step_result checkpointed 2026-04-17T23:15:24, verdict green). Closes `TODO-0083`. Deferred findings tracked as `TODO-0084` (bridge-agent Write), `TODO-0085` (integrity-depth umbrella), `TODO-0086` (nits).
- **Plan / purpose**: add a pytest guard preventing hook-registration regressions where `.claude/settings.json` points a registered PreToolUse hook at a non-existent script — the harness treats missing scripts as no-ops so the rule goes silent without any runtime signal. Triggering incident: an uncommitted settings.json edit during `qa/cli-args-shim-r1` rewrote the 4th PreToolUse entry from `block-sandbox-prompt-patterns.sh` to `block-shell-loops.sh` (nonexistent), silently disabling the entire sandbox-prompt deny rule set; observed only when four `task ledger:save -- "\$(cat tmp/...)" ...` invocations hit user-ask prompts instead of being denied.
- **Branch**: `qa/hook-registration-integrity-001` → fast-forward-merged to `main` at `9941885`.
- **Commit(s) reviewed**: `9f03d56` (initial test, 97 lines — reviewed by all three agents); `9941885` (A3 extension added post-review to close Finding A HIGH).
- **Reviewer roster**:

| Reviewer | Model | Tier | Agent type | Dispatch mode |
|---|---|---|---|---|
| Opus | `claude-opus-4-7` | HIGH | `code-review-high` | read-only (main session) |
| Gemini Flash | `gemini-3-flash-high` | MEDIUM | `gemini-reviewer` | bridge (Gemini CLI dispatch blocked by sandbox — fell through to host-model review) |
| Codex-builtin | `gpt-5.3-codex` | MEDIUM | `codex-reviewer` (native) | bridge via `codex exec -p reviewer review --base main` (custom prompt-file could not be materialized — fell through to default 10-point rubric) |

Codex-custom was not dispatched this cycle — the diff had no shim / CLI / config surface.

- **Findings table** (columns: ID, severity, Opus, Gemini, Codex-builtin; U=unique catch, S=shared, —=missed):

| ID | Finding | Severity | Opus | Gemini | Codex-builtin |
|---|---|---|---|---|---|
| A | `.claude/settings.local.json` not validated — same TOCTOU regression class as TODO-0083 | HIGH | — | **U** (V6) | — |
| B | Broken-but-present hook body (empty / wrong shebang / neutered `exit 0`) | MED-HIGH | **S** (T4) | **S** (V5) | — |
| C | `${CLAUDE_PROJECT_DIR}` brace form + literal `.replace()` brittleness | MED | **S** (T1) | **S** (V2) | — |
| D | Missing `type` key: walker skips; harness may default to `"command"` | MED | **S** (T2) | **S** (V3) | — |
| E | No positive rule-set inventory — `"hooks"` can be replaced with one no-op entry | MED | — | **U** (V1) | — |
| F | Symlink escape — committed symlink → `/bin/true` passes both checks | MED | — | **U** (V7) | — |
| G | `S_IXUSR` bit check ≠ effective `os.access(X_OK)` for non-owner users | LOW | — | **U** (V4) | — |
| H | Relative paths resolve against cwd, not `REPO_ROOT` (latent today) | INFO | **U** (T3) | — | — |
| I | Assertion-format style consistency | NIT | **U** (T5) | — | — |

- **Resolution**: A (HIGH) fixed on-branch in commit `9941885` (A3 extension — walk both `settings.json` and `settings.local.json`; at-least-one-hook sanity scoped to committed baseline only). B/C/D/E/F deferred to umbrella `TODO-0085`. G/H/I deferred to nits `TODO-0086`. Post-A3 verdict: GREEN.

- **Notes**:
  1. **Opus systematically underweighted threat-class generalization.** It confirmed the test catches the stated TODO-0083 instance (settings.json → nonexistent path) but did not ask where else the same abstract threat class (uncommitted local edit silently disabling a hook) could land. Gemini made that leap to `settings.local.json` naturally. This is the same "analyzes the exact stated case" weakness documented in Entry 1 (Opus analyzed quoted `<(...)` but missed unquoted in r4) — repeated on a different subject class. The prompt-authoring fix promoted to §Orchestration: state both the original instance and the abstract threat class.
  2. **Gemini Flash MEDIUM caught the only HIGH finding (V6).** Another data point confirming the Google-family bypass-detection claim in §Medium-tier calibration. Notable extension: the subject was Python test logic guarding against a regression, not security-adjacent regex / sandbox code. The bypass-enumeration skill generalizes from security logic to regression-guard review — motivated the new matrix row.
  3. **Codex-builtin dispatch degraded to default rubric.** The bridge agent has `Read + Bash` only and could not materialize the custom workflow-integration prompt file — every file-creation path (Write tool, heredoc, tee, interpreter, compound commands) is blocked by existing deny rules and the sandbox-prompt hook. Shim fell through to `codex exec review --base main` against the default 10-point rubric; returned a one-sentence review. Workflow-integration axis effectively uncovered this cycle. Filed as `TODO-0084` to grant bridge agents Write scoped to `tmp/**`; input-direction mirror of the documented output-direction limitation.
  4. **Gemini bridge dispatch also failed** (same Write-tool class) but its subagent host model returned a high-quality review directly from its own analysis — producing a stronger result than Codex-builtin's successful-but-default output. Not reliable as a design pattern (fallback quality is not guaranteed), but a useful data point: when the bridge fails, the fallback can still carry the review depending on which agent you're dispatching to.
  5. **Reviewer convergence + complementarity.** B/C/D were shared Opus+Gemini catches (convergence = high-confidence findings). A + E + F were unique-Gemini (enumeration axis). H + I were unique-Opus (style + portability axis). Zero shared-with-Codex-builtin findings, reflecting its default-rubric fall-through. The shape corroborates Entry 1's observation that Opus and Gemini axes are genuinely complementary — not redundant.

---

## Entry 3 — [2026-04-23/24] `main` (ad-hoc) — `findings:apply-batch` python-cli migration + JSONL batch entrypoint

- **Ledger EPIC ID / TODO ID**: none (ad-hoc; the cycle was triggered by a CLAUDE.md §11 compliance gap discovered during routine review of `taskfiles/findings.yml`). New TODO candidates surfaced for follow-up are noted at the end.
- **Plan / purpose**: migrate all 8 existing `findings:*` taskfile targets from host-side `python3` to the `python-cli` container behind the 3-layer python-security-gate (CLAUDE.md §11), AND add a new `findings:apply-batch` JSONL entrypoint that amortises ~1–2s container-startup latency across the diff-review skill's two genuine hot loops (Step 3.1 create-per-finding, Step 5.1 filter+priority+marker fan-out).
- **Branch**: `main` direct (no remote push). 5-commit bundle `cec8968..7048d5f`, +1188 / -171 across 4 files (`scripts/findings_tracker.py`, `taskfiles/findings.yml`, `tests/scripts/test_findings_tracker_cli.py`, `.claude/skills/diff-review/SKILL.md`).
- **Commit(s) reviewed**: `cec8968` (R1), `85eaad2` (R2 fix), `3f8af12` (R3 fix), `bc08cce` (R4 fix), `7048d5f` (R5 fix). Five rounds of tri-family review; convergence reached at R5.
- **Reviewer roster** (all rounds used the same 3):

  | Reviewer | Model | Effort | Mechanism |
  |---|---|---|---|
  | Opus | claude-opus-4-7 | high | code-review-high, 10-dim rubric, read-only main-session inheritance |
  | Gemini | gemini-3.1-pro-preview | high | gemini-reviewer-high, custom prompt piped via `gemini-review.sh` (`:local` variant) |
  | Codex-custom | gpt-5.4 | high | codex-reviewer-high, custom prompt piped via `codex-review.sh` (`:local`) with `REVIEW_MODE=fixture` (committed-diff path) |

  Codex-builtin was not dispatched this cycle — no cross-directory workflow scope; the diff was four files all in adjacent layers.

### Round summary table — verdicts and finding counts per reviewer per round

| Round | Diff (lines) | Opus | Gemini | Codex | Real bugs caught | Convergent finds |
|---|---|---|---|---|---|---|
| **R1** on `cec8968` | +851 / −117 | APPROVED W/ NOTES (12) | 3 valid | 4 valid | 8 | C4+G3 ("seven lines" typo) |
| **R2** on `85eaad2` | +303 / −47 | APPROVED W/ NOTES (2 LOW) | 1 Critical, 1 Med | 3 (1 High) | 5 | G1+C2 (cross-pollution on divergent paths) |
| **R3** on `3f8af12` | +218 / −23 | APPROVED (3 LOW INFO) | APPROVED 10/10 | 3 (1 High, 1 Med, 1 Low) | 3 | none — all Codex-only |
| **R4** on `bc08cce` | +81 / −25 | APPROVED (3 INFO) | APPROVED 10/10 | 1 Med | 1 | none — Codex-only |
| **R5** on `7048d5f` | +38 / −6 | APPROVED (2 INFO) | APPROVED 10/10 | APPROVED (no actionable defects) | — | — |

### Notable findings (a load-bearing subset; full set in commit messages of the R2–R5 commits)

| ID | Finding | Severity | Round | Opus | Gemini | Codex | Resolution |
|---|---|---|---|---|---|---|---|
| L1 | `op_def.get("id", ...)` ran BEFORE try → uncaught AttributeError on non-dict op_def; uncaught TypeError from `create(**args)` with missing kwargs | High (fail-fast contract breach) | R1 | — | **U** (G1, conf 10) | **S** (C1, conf 9) | R2 — isinstance guards, widened except |
| L2 | N+1 file I/O on per-op load/save defeated batching gain | Med | R1 | — | **U** (G2, conf 9) | — | R2 — atomic ledger_cache + end-of-batch save (also resolved Opus F3 create-retry hazard as side effect) |
| L3 | Cross-pollution on `in_path != out_path` divergent fan-out: shared list mutated, source cache silently polluted | Crit | R2 | F2 (test-gap framing only) | **S** (G1.1, conf 10) | **S** (C2, conf 7) | R3 — `_materialise_target` deep-copy when paths diverge |
| L4 | Temporal read leakage: `load` op returned live cached list ref; later mutation backflows into earlier read snapshot at end-of-batch JSON serialisation | Crit | R2 | — | **U** (G1.2, conf 10) | — | R3 — `copy.deepcopy` on filter/load returns |
| L5 | Unhashable `id` (JSON list/dict) crashed `if op_id in results:` check before try, bypassing JSON output contract | High | R2 | — | — | **U** (C1, conf 10) | R3 — moved check inside try, widened except to include OSError |
| L6 | `id=1` (int) vs `id="1"` (str) JSON-key collision: distinct Python dict keys, both serialise to `"1"` → invalid duplicate-key JSON output | High | R3 | — | — | **U** (R3-1, conf 8) | R4 — strict `isinstance(id, str)` validation rejects int/list/dict/None |
| L7 | omit-id + dispatch-fail loses synthesised default `op-N` in error record (R4 regression introduced by L5 fix) | Med | R4 | — | — | **U** (R4-1, conf 9) | R5 — initialise `op_id = None` upfront, conditional echo |
| L8 | UnboundLocalError trap latent in R3-fix design: had `op_id` been referenced post-validation-raise, would have leaked stale value or raised | (preventive trace) | R4 | — | **U** (adversarial trace) | — | R5 — preserved by initial `op_id = None` |

- **Resolution**: All 8 findings landed on-bundle. New TODO candidates surfaced (not landed): two-phase commit for multi-ledger atomic flush; defensive count check in `update_status`; coverage tests for `id=null` and `id={...}`.

- **Notes**:
  1. **Codex carried R3 + R4 single-reviewer signal.** Both R3-1 (JSON-key collision) and R4-1 (default-id regression) were Codex-only catches that Opus and Gemini missed at the smaller (218-line and 81-line) diff sizes. This is the first cycle where Codex-custom uniquely caught load-bearing late-round findings without Gemini/Opus support — extends the surface-area-specialist pattern from Entry 1 into late-round contract-correctness. **Worth folding into profiles**: at small-diff late rounds, drop Codex at your peril even when Opus + Gemini have converged on APPROVED.
  2. **Gemini regained credibility.** Resume-prompt notes from prior sessions ("consider dropping to dual-family for sub-200-line hygiene diffs — Gemini adds no net value") were inverted this cycle. Gemini's R2 G1+G2 catches were both load-bearing; Gemini's R4 adversarial trace caught the latent UnboundLocalError trap that motivated R5's `op_id = None` initialisation pattern. From R3 onward, every Gemini round was APPROVED 10/10 with substantive trace evidence, no hallucinations. **Lesson**: Gemini's hallucination rate appears to be context-contamination-driven (IDE-open files in system-reminders during prior sessions); in a clean session it operates at full capability.
  3. **Convergence trajectory was monotonic and clean.** Diff size shrank R1→R5 (851 / 303 / 218 / 81 / 38 lines); finding count shrank correspondingly (8 / 5 / 3 / 1 / 0). Every round's diff was a precise targeted fix of the prior round's findings, not a re-architecture. This is what good convergence looks like and is worth using as a positive control template for future multi-round gates.
  4. **Five rounds was the natural depth** for a 1.2k-line refactor touching contract semantics. Convergence hit at R5 because the contract surface-area is bounded (8 op types × 3 path semantics × 2 error paths = small finite matrix); each round closed one quadrant of the matrix. For diffs without contract semantics, expect fewer rounds.
  5. **Pre-commit absorption did NOT happen this cycle** — every round produced a separate fix commit and re-review. Different from the Phase C / Phase D polish bundles in TODO-0092 family which absorbed findings into r2 commits without re-review. The driver of the difference: TODO-0092 polish bundles had unanimous APPROVED with notes and bounded local fixes; here the R1 verdict was APPROVED WITH NOTES + 12 findings (Opus alone), several of which had architectural implications (atomic semantics, deepcopy strategy) that warranted full re-review of the resulting redesign. **Heuristic**: re-review when fixes change the contract; absorb when fixes are local polishes.
  6. **defopt's docstring parser crashes on RST bullet-lists in block-quotes** (`TypeError: can only join an iterable`). Caught early when adding `_cli_apply_batch`'s docstring; rewriting to Google-style prose was the fix. Worth recording as a sandbox/environment quirk for future Python-CLI work using defopt.
  7. **`# type: ignore` strings appear in the bypass-detector regex** even when only mentioned in a comment referencing them. Bit me twice during R3 testing; comment phrasing now uses "those" instead of the literal string. Operational gotcha; not a profile-level pattern.
  8. **Codex-builtin was not dispatched** (the diff had no cross-directory workflow scope). All four files were adjacent: script + taskfile + tests + skill. Decision matched the criterion in the existing profiles "where each reviewer should always be included" matrix (Codex-builtin is `O` for diffs that touch ≤3 directories) and was not regretted — no findings would plausibly have come from a workflow-integration sweep on this surface.

---

## Entry 4 — [2026-04-30] `main` (W1 of REVIEWER-ENVELOPE-001) — Reviewer Output Envelope: schema + parser + lint scaffold

- **Ledger EPIC ID / TODO ID**: `REVIEWER-ENVELOPE-001` (epic in_progress; W2/W3/W4 outstanding). Step results saved 2026-04-29..30 (RED `step_result|pass`, GREEN `step_result|pass`, GREEN closeout `step_result|pass`); wave_summary saved 2026-04-30. 13 follow-up TODOs created (`TODO-0136..0148`) and auto-assigned to the epic.
- **Plan / purpose**: Wave 1 of a 4-wave migration that moves reviewer verdict / next-action / tier-recommendation / halt-trigger from prose into a structured JSON envelope, so the orchestrator can route deterministically (table-driven instead of LLM-interpreted) and drop to Opus 4.7 medium after W4. W1 ships the foundation: schema, parser, lint scaffold, Claude-native `code-review*` agent body updates. Plan: `tmp/plan-reviewer-output-envelope.md` (Draft v3.1 — three rounds of tri-family plan review prior to W1 implementation).
- **Branch**: committed directly to `main` as `9b0bd95` (single-commit-equivalent of a feature PR; tri-family review run pre-commit on the staged tree, fixes folded in, then committed).
- **Commit reviewed**: working tree (24 files, +2031 / -0) at point of `git diff --cached` capture; final commit `9b0bd95` differs only by ruff-format corrections + the F1+F2 fixes that the review surfaced.
- **Reviewer roster**:

  | Reviewer | Model | Effort | Mechanism |
  |---|---|---|---|
  | Opus | claude-opus-4-7 | high | code-review-high, 10-dim rubric, dual-role: instructed to emit the new envelope under review |
  | Gemini | gemini-3.1-pro-preview | high | gemini-reviewer-high, custom prompt piped via gemini-review.sh |
  | Codex-custom | gpt-5.4 | high | codex-reviewer-high, custom prompt piped via codex-review.sh → `codex exec -p reviewer` (envelope-emission rubric explicit in prompt) |

- **Codex-builtin not dispatched**: diff was 24 files but concentrated in 4 directories (`scripts/orchestrator`, `docs`, `tests`, `.claude/agents` + small touches to `taskfiles/` / `ci/` / `.markdownlint-cli2.yaml`). No cross-cutting workflow integration to sweep. Decision matched profile criterion (`O` for diffs touching ≤3 directories — borderline at 4-5 here). Not regretted: the review surface was Python parser correctness, schema validation, and JSON Schema soundness — not workflow-integration territory.

### Single-round review on staged tree (87 KB / 2129 lines / 24 files)

Verdicts (all three issued APPROVED_WITH_NOTES status; the new envelope's `next_action` field surfaced different blocker calibration across families):

- **Opus**: `APPROVED_WITH_NOTES` / `APPROVE` — 7 findings, 0 blocking
- **Codex-custom**: `APPROVED_WITH_NOTES` / `RETURN_TO_WORKER` — 5 findings, **2 marked `blocking: true`** (F1, F2)
- **Gemini**: `APPROVED_WITH_NOTES` / `RETURN_TO_WORKER_ADVISORY` — 7 findings, 0 blocking

Per Cross-Family Asymmetry (plan §5.1 Rule 5 / Req-009 / `docs/effort_tiers.md` "signal not veto") at gate-effort `high`, bridge dissent IS load-bearing — the asymmetry rule only softens to audit-only at `xhigh`/`max`. Codex's 2 blockers correctly drove the merge to RETURN_TO_WORKER.

| ID | Finding | Severity | Opus | Gemini | Codex | Block? | Resolution |
|---|---|---|---|---|---|---|---|
| F1 | `RecursionError` escapes the circuit-breaker — `parse_or_fallback`'s except tuple catches only `(JSONDecodeError, ValidationError)`; deeply-nested JSON raises `RecursionError` uncaught, bypassing CB counter increment per Req-N05 | significant | — | — | **U** | **yes** | Pre-commit — added `RecursionError` to except tuple + comment citing Req-N05; new regression test feeds depth=`4 * sys.getrecursionlimit()` brackets and asserts `EnvelopeParseError` |
| F2 | Tautological audit-leak test — `assert "_audit" not in result.envelope.to_dict()` is structurally guaranteed because `dataclasses.asdict()` only enumerates declared fields; Round 3 V3-N01 invariant ("envelope schema preserves `additionalProperties: false`") not actually verified | significant | — | — | **U** | **yes** | Pre-commit — rewrote with 4 independent invariant checks: declared-field check via `dataclasses.fields(Envelope)`, `to_dict()` dict, `json.dumps()` serialized string (catches `object.__setattr__` bypass), `vars()` instance dict; plus `Draft202012Validator.validate(envelope_dict)` round-trip relying on `additionalProperties: false` |
| F3 | Top-level string maxLength gap — `agent_id`, `spillover_findings_path` unbounded; 100MB `agent_id` would be loaded by `json.loads` before validation rejects it (DoS defense-in-depth) | minor | — | — | **U** | no | Deferred — TODO-0137 |
| F4 | `_legacy_prose_verdict_extractor` substring scans mis-classify "DISAPPROVED" as APPROVE | minor | **S** (S2) | **S** (INFO-3) | **S** | no | Deferred — TODO-0136 (consolidates 3-reviewer overlap) |
| F5 | No happy-path round-trip test through `parse_or_fallback` (only `find_envelope_block` tested in isolation) | minor | — | — | **U** | no | Deferred — TODO-0138 |
| MINOR-1 | `empty_fence.md` fixture passes for wrong reason — regex requires `\n(.*?)\n`; fixture has zero body lines, test passes via "envelope absent + claude-native in W1 allowlist" branch, NOT the malformed-body branch the docstring claims | minor | — | **U** | — | no | Deferred — TODO-0139 |
| MINOR-2 | No `parse_or_fallback` chain test for Gemini ESCALATE→max — only ESCALATE→high tested; normalize→reroute order is load-bearing | minor | — | **U** | — | no | Deferred — TODO-0140 |
| INFO-1 | `docs/reviewer_envelope.md` Required Keys table omits §4.1.1 footnote — authored RETURN_TO_WORKER envelopes should emit `recommended_next_tier=null` (downstream MergeDecision per G-4 R2 may differ) | informational | — | **U** | — | no | Deferred — TODO-0142 |
| INFO-2 | `_PER_FAMILY_CEILING_NORMALIZE` and `_PER_FAMILY_CEILING_REROUTE` duplicate bridge values — silent drift surface | informational | **S** (M3) | **S** | — | no | Deferred — TODO-0144 |
| INFO-4 | No positive happy-path test for ABSTAIN+RETRY_REVIEWER+empty_feedback envelope round-trip | informational | — | **U** | — | no | Deferred — TODO-0147 |
| INFO-5 | Forward-compat: adding new agent family in W4+ requires multi-file coordination (parser allowlist, ceiling tables, schema enum, CI trigger regex) | informational | — | **U** | — | no | Deferred — TODO-0146 |
| S1 | `_load_schema` docstring concurrency claim overpromises (cache read/write unguarded) | significant (Opus's call) | **U** | — | — | no | Skipped — 1-line docstring tweak, not worth tracking |
| M1 | `EnvelopeParseError` variadic `*args` produces 3 different positional shapes across callsites; `exc.args` inconsistent for downstream loggers | minor | **U** | — | — | no | Deferred — TODO-0145 |
| E1 | description maxLength=2000 / feedback_to_forward maxItems=50 silently enforced; not surfaced in agent body or canonical doc | informational (self-applied envelope friction) | **U** | — | — | no | Deferred — TODO-0141 |
| E2 | spillover_findings_path semantics under-specified — abstract description, no worked example | informational | **U** | — | — | no | Deferred — TODO-0143 |
| I1 | Plan §4.3 line 421 prose drift — "scan bottom-up for LAST fenced block" was inverted by B-4 R2 to multi-fence-raises | informational | **U** | — | — | no | Deferred — TODO-0148 |

- **Unique catches per reviewer**: Opus 6 (S1, M1, E1, E2, I1, plus M3 / INFO-2 shared with Gemini), Gemini 5 unique (MINOR-1, MINOR-2, INFO-1, INFO-4, INFO-5) + 2 shared, Codex 4 unique blockers/minors (F1, F2, F3, F5) + 1 shared (F4).
- **Shared catches across all three**: F4 only.
- **Verification (post-fix)**: `task lint:staged` → 0 (clean across ruff format/check, mypy, python-sql, yaml, markdown, json, shellcheck); `task test:staged` → **40/40** (was 39 + 1 new RecursionError regression test); `task lint:reviewer-envelope` → 12/12.
- **Final tri-family verdict (with blockers closed)**: APPROVE.

### Notable patterns

1. **Codex carried both blockers single-handed at LARGE diff size — extends Entry 3's pattern beyond the size qualifier.** F1 (RecursionError) and F2 (tautological assertion via `dataclasses.asdict()` projection) are both contract-correctness regressions where the verdict turns on **library/runtime semantics**: F1 on `json.loads`' recursion behavior under adversarial nesting depth, F2 on `asdict`'s "declared fields only" projection rule. Opus and Gemini reviewed the full diff; both missed both. Entry 3 saw the same Codex-only contract-correctness pattern at 218 / 81-line late rounds; Entry 4 saw it at 2129-line first round. The discriminator is NOT diff size — it's whether the verdict turns on library/runtime projection rules. **This evidence drove the 2026-04-30 profile sharpening** in `reviewer-profiles.md` (Codex-custom row Primary Strength column + the rationale paragraph): replaced the size qualifier ("at small-diff late rounds") with a semantic qualifier ("library/runtime semantics — `json` parser depth, `dataclasses.asdict` projection, exception-class coverage, regex flags").
2. **Test-soundness as a Codex/Gemini complementary pair (single-cycle observation, not yet a profile shift).** Both reviewers caught DIFFERENT test-soundness gaps via the same meta-question — "does this test verify what it claims to verify?":
    - Codex F2 instance: assertion vacuously true via library-semantics analysis (asdict projection).
    - Gemini MINOR-1 instance: test passes via different code path than docstring claims (regex shape + allowlist gating combined to silently bypass the "empty body" branch).
   Single-cycle pattern. If a second cycle confirms, consider adding a "test-soundness" row to the use-case matrix in `reviewer-profiles.md` as a Codex+Gemini-mandatory pair. For now, log only.
3. **Self-applied envelope review surfaced ergonomic findings only Opus produced.** The prompt instructed all three reviewers to emit the new envelope they were reviewing. Opus produced E1 / E2 ergonomic findings (description maxLength invisible to authors; spillover_findings_path under-specified) because it felt the authoring friction firsthand. Codex and Gemini emitted their envelopes successfully but did not surface ergonomic findings. **Prompt-engineering technique**: when the diff IS the contract being introduced, dogfooding the contract during review surfaces friction unavailable to a non-self-applied reviewer. Useful for any contract-introducing change but most valuable for envelope-style / DSL-style / shim-prompt-style work where the authoring UX is itself a quality dimension.
4. **Different blocker calibration across families — validated via the new envelope's `next_action` field.** All three issued APPROVED_WITH_NOTES status, but the envelope's `next_action` exposed three different "should this gate ship" calls: Codex `RETURN_TO_WORKER` (2 blocking), Gemini `RETURN_TO_WORKER_ADVISORY` (advisory only), Opus `APPROVE` (no blockers). Same status, three different calibrations. The Cross-Family Asymmetry rule (Req-009) at gate-effort=high made Codex's RETURN load-bearing; the orchestrator (this main session, manually walking the §5.1 merge precedence rules pre-W4 implementation) routed to RETURN, fixed the 2 blockers, then converged to APPROVE. **This validated the envelope-routing primitive a wave early**: the schematized blocking signal gave a deterministic decision path before W4's actual `envelope_merge.py` exists. Worth noting as a positive control for the W4 merge function design — the structured blocking flag carries the right information, and the asymmetry rule plus the precedence ordering produce the right answer.
5. **Tri-family at large diffs with regex/contract semantics confirms heuristic, no profile change.** Diff was 2129 lines (not small) but had regex semantics (discriminated fence regex), contract-correctness semantics (Round 3 V3-N01 audit invariant), and security-adjacent input handling (parser ingesting untrusted reviewer output). The profile's existing tri-family-escalation heuristic (line 62) already says "escalate to tri-family for any diff with regex / network classification / contract-correctness semantics even when the diff is small." This cycle confirms the heuristic at the OPPOSITE end of the size spectrum too — large first-round diffs with the same semantic profile. No profile change needed.
6. **Codex-custom drift was NOT observed.** The custom prompt explicitly cited the envelope-emission rubric and named the §4.1 schema verbatim near the prompt top. Codex stayed on-rubric and emitted a structurally-correct envelope while issuing substantive review. Reinforces "Codex drift-mitigation preamble is tier-independent" (profile line 75): citing the rubric question at the top of the prompt and structuring the custom rubric to be visually distinct from codex's native review framing keeps Codex on the caller's task.

---

## Backlog — uncaptured cycles to backfill

The following multi-reviewer cycles ran on the TODO-0089 / TODO-0090 / TODO-0091 / TODO-0092 epic family but are NOT yet documented in this file. Patterns observed during a 2026-04-24 inventory have been folded into [reviewer-profiles.md](./reviewer-profiles.md), but the per-entry evidence (findings tables, verdict trajectories, single-reviewer catches) still needs to be backfilled here. Each cycle's source artifacts are in `tmp/` (per the inventory below).

| Cycle | TODO | Plan vs Diff | Rounds | Source artifacts |
|---|---|---|---|---|
| Narrow `Bash(task *)` (predecessor) | 0089 | Plan | R1→R5 (5 plan revisions; superseded into 0092) | `tmp/todo-0089-plan.md`, `tmp/todo-0089-agent-pattern-audit.md` |
| Findings-tracker / diff-review CLI (predecessor) | 0090 | Plan | R1→R2 | `tmp/codex-plan-review-r1.md`, `tmp/codex-plan-review-r2.md`, `tmp/todo-0090-plan.md` |
| 0089+0090 unified plan | 0092 | Plan | R1→R2 | `tmp/codex-plan-review-0092-r1.md`, `tmp/codex-plan-review-0092-r2.md`, `tmp/todo-0092-plan.md` |
| Phase B diff (findings CLI) | 0092-B | Diff | R1 | `tmp/codex-review-phase-b-r1.md` |
| Phase C diff (settings narrow) | 0092-C | Diff | R1 + r2 absorption (no separate review round) | `tmp/todo-0092-resume-prompt-post-c.md` |
| Phase D diff (hygiene) | 0092-D | Diff | R1 | `tmp/codex-review-phase-d-r1.md` |
| Phase D polish bundle | TODO-0120/121/122/123/124 | Diff | R1 (281-line; tri-family escalated from dual) | `tmp/todo-0092d-polish-r1-resume-prompt-post.md` |

**Backfill scope**: each cycle needs a full Entry-format block (Ledger ID, branch, commit(s), reviewer roster, findings table, notes). The inventory captured headline patterns but not the per-finding detail required by the entry template. Estimated effort: 1–2 hours of source-file reading + structured extraction. Recommend doing this as a separate session rather than on top of routine work.
