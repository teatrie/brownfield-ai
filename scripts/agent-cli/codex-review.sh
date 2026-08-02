#!/usr/bin/env bash
# codex-review.sh — Invoke the Codex CLI to perform a structured code review.
# Usage: codex-review.sh [--base BRANCH] [--round N] [--model MODEL]
#   BRANCH defaults to main.
#   ROUND defaults to 1.
#   MODEL is optional — overrides profile model (passed as -m to codex exec).
#   REVIEW_TYPE (required): one of {plan, spec, diff, epic, spec-req-verification}.
#   DIFF_FILE (required): path to the subject artifact under tmp/ or agent-review/.
#   REVIEW_MODE (optional, default branch): one of {branch, fixture}. Only
#     meaningful for REVIEW_TYPE=diff. In branch mode, the wrapper invokes
#     `codex review --base` so Codex runs its native 10-point rubric against
#     `git diff $BASE_BRANCH..HEAD`; the combined prompt rides along as
#     instructions supplement. In fixture mode, the wrapper invokes plain
#     `codex exec -p reviewer` with the combined template+DIFF_FILE prompt
#     on stdin as the sole subject — required when DIFF_FILE is a synthetic
#     or fixture diff that does not match the working-tree git diff
#     (otherwise `--base` would silently override the fixture and review
#     the live working tree instead). Non-diff review types ignore
#     REVIEW_MODE and always use plain `codex exec -p reviewer`.
#   Output written to tmp/codex-review-output-<ROUND>.md.
#   Signals written to tmp/codex-exit.json on unavailability or error.

set -euo pipefail

# ---------------------------------------------------------------------------
# SECRETS GUARD — must never run inside a container where .env is readable
# ---------------------------------------------------------------------------
if [ -f /app/.env ] && [ -r /app/.env ]; then
  echo "FATAL: .env is readable inside container" >&2
  exit 1
fi
# Note: /app/.env only exists inside the container. On host, this check no-ops.

mkdir -p tmp

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
ROUND="${ROUND:-1}"
BASE_BRANCH="main"
# BASE_BRANCH_EXPLICIT flips to 1 only when the caller passes `--base <X>`.
# Read later to emit a visibility notice when `--base` is silently ignored
# by REVIEW_MODE=fixture or by a non-diff REVIEW_TYPE (TODO-0120/0126).
BASE_BRANCH_EXPLICIT=0
MODEL="${MODEL:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      if [ -z "${2:-}" ]; then
        echo "Error: --base requires a value" >&2
        exit 1
      fi
      BASE_BRANCH="$2"
      BASE_BRANCH_EXPLICIT=1
      shift 2
      ;;
    --round)
      if [ -z "${2:-}" ]; then
        echo "Error: --round requires a value" >&2
        exit 1
      fi
      ROUND="$2"
      shift 2
      ;;
    --model)
      if [ -z "${2:-}" ]; then
        echo "Error: --model requires a value" >&2
        exit 1
      fi
      MODEL="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--base BRANCH] [--round N] [--model MODEL]" >&2
      exit 1
      ;;
  esac
done

if ! [[ "$ROUND" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --round must be a positive integer >= 1, got '$ROUND'" >&2
  printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"--round must be a positive integer >= 1"}\n' > tmp/codex-exit.json
  exit 1
fi

# ---------------------------------------------------------------------------
# Source shared reviewer helpers and validate REVIEW_TYPE + DIFF_FILE.
# ---------------------------------------------------------------------------
# shellcheck source=scripts/agent-cli/_review-common.sh
. "$(dirname "$0")/_review-common.sh"

if ! _review_validate_type; then
  printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"REVIEW_TYPE invalid or missing"}\n' > tmp/codex-exit.json
  exit 1
fi
if ! _review_validate_diff_file; then
  printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"DIFF_FILE invalid or missing"}\n' > tmp/codex-exit.json
  exit 1
fi

# ---------------------------------------------------------------------------
# REVIEW_MODE — {branch, fixture}, default "branch". Enum validation.
# Controls the REVIEW_TYPE=diff dispatch path (see `run_codex`). Non-diff
# review types ignore this flag. TODO-0114: fixture-driven smokes require
# a stdin-subject path that `codex review --base` does not honor.
# ---------------------------------------------------------------------------
REVIEW_MODE="${REVIEW_MODE:-branch}"
case "$REVIEW_MODE" in
  branch|fixture) ;;
  *)
    echo "Error: REVIEW_MODE must be one of {branch,fixture}, got '$REVIEW_MODE'" >&2
    printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"REVIEW_MODE enum rejected"}\n' > tmp/codex-exit.json
    exit 1
    ;;
esac

# TODO-0120 + TODO-0126: visibility when `--base <X>` is silently ignored.
# Guard on BASE_BRANCH_EXPLICIT (not just BASE_BRANCH != default) so callers
# who default BASE_BRANCH don't get a spurious notice. Two dispatch paths
# silently override --base:
#
#   1. REVIEW_MODE=fixture (TODO-0114): routes REVIEW_TYPE=diff through plain
#      `codex exec -p reviewer` instead of `codex review --base`, so the
#      combined template+DIFF_FILE prompt on stdin is the sole subject.
#   2. REVIEW_TYPE != diff (TODO-0126): non-diff types (plan/spec/epic/
#      spec-req-verification) always use plain `codex exec -p reviewer`;
#      the `review --base` subcommand is gated on REVIEW_TYPE=diff inside
#      `run_codex`, so --base never reaches the CLI for non-diff invocations.
#
# Branch 1 takes precedence when both conditions hold (editorial choice:
# REVIEW_MODE=fixture is the TODO-0114 regression context and the most
# likely caller-intent signal, even though for non-diff REVIEW_TYPEs the
# fixture gate is itself a no-op and the non-diff dispatch is technically
# the operative override — locked by test_fixture_precedence_when_both_
# override_conditions_hold). Direct-invocation only: the Taskfile
# CLI_ARGS shim forwards only KEY=value tokens, not argv flags, so in
# task-driven calls BASE_BRANCH_EXPLICIT is always 0 and this notice is
# unreachable.
if [ "${BASE_BRANCH_EXPLICIT}" = "1" ]; then
  if [ "${REVIEW_MODE}" = "fixture" ]; then
    echo "NOTICE: --base ${BASE_BRANCH} ignored because REVIEW_MODE=fixture routes through plain \`codex exec -p reviewer\`; the combined template+DIFF_FILE prompt on stdin is the sole subject." >&2
  elif [ "${REVIEW_TYPE}" != "diff" ]; then
    echo "NOTICE: --base ${BASE_BRANCH} ignored because REVIEW_TYPE=${REVIEW_TYPE} routes through plain \`codex exec -p reviewer\`; the \`review --base\` subcommand applies only to REVIEW_TYPE=diff." >&2
  fi
fi

# ---------------------------------------------------------------------------
# Req-003: EFFORT env var — upfront enum validation.
# Accepts {medium, high, xhigh, max}. Rejects "low" and "minimal"
# (reviewers run at HIGH internal reasoning minimum) and any other
# value with non-zero exit. When set, constructs `-c` override below.
#
# Ceiling-collapse composition:
#   medium -> model_reasoning_effort=high   (MEDIUM tier runs lower-capability
#             model at MAX internal reasoning; model upgrade happens at HIGH+)
#   high   -> model_reasoning_effort=high
#   xhigh  -> model_reasoning_effort=xhigh
#   max    -> model_reasoning_effort=xhigh  (ceiling collision — Codex tops
#             out at xhigh; max and xhigh share the same -c value)
# ---------------------------------------------------------------------------
EFFORT="${EFFORT:-}"
if [ -n "$EFFORT" ]; then
  case "$EFFORT" in
    medium|high|xhigh|max) ;;
    *)
      echo "Error: EFFORT must be one of {medium,high,xhigh,max}, got '$EFFORT'" >&2
      printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"EFFORT enum rejected"}\n' > tmp/codex-exit.json
      exit 1
      ;;
  esac
fi

# Map EFFORT -> effective Codex model_reasoning_effort (ceiling-collapse
# rules above). EFFORT_CODEX_VALUE is the string forwarded via `-c`.
_map_effort_to_codex() {
  case "$1" in
    medium) echo "high" ;;
    high) echo "high" ;;
    xhigh) echo "xhigh" ;;
    max) echo "xhigh" ;;
    *) echo "" ;;
  esac
}

# ---------------------------------------------------------------------------
# Token guard — signal unavailability and exit cleanly (not an error).
# Skipped for local OAuth (host context handles auth via ~/.codex/auth.json).
# Must run BEFORE artifact path setup because the container-mode mkdir
# may fail in read-only test environments.
# ---------------------------------------------------------------------------
if [ "${CODEX_EXECUTION_CONTEXT:-}" != "host" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  # Exit signals always go to tmp/ (not agent-review/) — they are read by the
  # bridge agent (Claude Code), not by Codex CLI, so no .gitignore issue.
  printf '{"signal":"CODEX_UNAVAILABLE","reason":"token_missing"}\n' > tmp/codex-exit.json
  exit 0
fi

# ---------------------------------------------------------------------------
# Artifact path setup — container mode routes to agent-review/ (Codex
# respects .gitignore which excludes tmp/), host mode stays in tmp/.
# ---------------------------------------------------------------------------
WORKSPACE="${WORKSPACE:-brownfield-ai}"
SESSION_ID="${REVIEW_SESSION_ID:-local}"

if [ "${CODEX_EXECUTION_CONTEXT:-}" != "host" ]; then
  OUTPUT_DIR="agent-review"
  OUTPUT_FILE="${OUTPUT_DIR}/${WORKSPACE}-codex-review-output-${SESSION_ID}.md"
  ERR_FILE="${OUTPUT_DIR}/${WORKSPACE}-codex-review-err-${SESSION_ID}.txt"
else
  OUTPUT_DIR="tmp"
  OUTPUT_FILE="tmp/codex-review-output-${ROUND}.md"
  ERR_FILE="tmp/codex-review-err.txt"
fi

mkdir -p "${OUTPUT_DIR}"

# ---------------------------------------------------------------------------
# Resolve template + sanitize subject + build combined prompt file.
# Codex `review --base` reads the git diff against BASE_BRANCH; the combined
# prompt on stdin is the instructions channel (criteria + adversarial rigor
# + subject data).
# ---------------------------------------------------------------------------
TEMPLATE_PATH=$(_review_template_path)
if [ ! -f "$TEMPLATE_PATH" ]; then
  echo "Error: reviewer template not found: $TEMPLATE_PATH" >&2
  printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"template_missing","stderr_excerpt":"reviewer template not found"}\n' > tmp/codex-exit.json
  exit 1
fi

SANITIZED_SUBJECT=$(_review_sanitize_subject codex "${ROUND}")
COMBINED_PROMPT="tmp/codex-combined-prompt-${ROUND}.txt"
cat "$TEMPLATE_PATH" "$SANITIZED_SUBJECT" > "$COMBINED_PROMPT"

# ---------------------------------------------------------------------------
# Invoke Codex CLI — output captured to tmp files, never piped into eval.
# exec-level flags (-p, --sandbox, -o, -m) come BEFORE the review subcommand.
# review-level flags (--base, --ephemeral) come AFTER the review subcommand.
# ---------------------------------------------------------------------------
EXIT_CODE=0

run_codex() {
  # --sandbox danger-full-access disables Codex's internal sandbox layer
  # because Claude Code's outer sandbox already contains the process
  # (filesystem + network restrictions enforced). Codex's nested
  # sandbox-exec call fails with "sandbox_apply: Operation not permitted"
  # under macOS nested sandboxing, so the inner layer provides no added
  # protection — it only blocks operation entirely. Scope is narrow:
  # this flag applies to review invocations only.
  local cmd_args=(-p reviewer --sandbox danger-full-access -o "${OUTPUT_FILE}")
  if [ -n "${MODEL:-}" ]; then
    cmd_args+=(-m "$MODEL")
  fi

  # Req-003: thread EFFORT into Codex via -c override on the reviewer profile.
  # The local EFFORT_OVERRIDE shadow allows Req-017's retry path to inject
  # a different value without mutating the outer EFFORT var.
  # Apply ceiling-collapse mapping (medium/high -> high; xhigh/max -> xhigh).
  # EFFORT_OVERRIDE is already a raw Codex value (set to "high" on retry),
  # so it is passed through unchanged; only the outer EFFORT is mapped.
  local _effort
  if [ -n "${EFFORT_OVERRIDE:-}" ]; then
    _effort="$EFFORT_OVERRIDE"
  else
    _effort=$(_map_effort_to_codex "$EFFORT")
  fi
  if [ -n "$_effort" ]; then
    cmd_args+=(-c "profiles.reviewer.model_reasoning_effort=${_effort}")
  fi

  # Non-diff REVIEW_TYPE values (plan/spec/epic/spec-req-verification)
  # supply a static subject artifact — `codex review --base` would
  # ignore that artifact and critique the git diff against BASE_BRANCH
  # instead. Gate the `review` subcommand on REVIEW_TYPE=diff; other
  # types invoke plain `codex exec -p reviewer` with the combined
  # prompt on stdin as the sole input channel.
  #
  # TODO-0114: REVIEW_MODE=fixture forces the same stdin-subject path
  # for REVIEW_TYPE=diff. `codex review --base` runs `git diff
  # $BASE_BRANCH..HEAD` and treats the live working-tree diff as the
  # subject — which silently overrides a synthetic/fixture DIFF_FILE
  # that does not match the working tree. Fixture-driven smokes must
  # opt into REVIEW_MODE=fixture so the stdin combined-prompt becomes
  # the sole subject channel.
  if [ "${REVIEW_TYPE}" = "diff" ] && [ "${REVIEW_MODE}" = "branch" ]; then
    local review_args=(--base "$BASE_BRANCH" --ephemeral)
    codex exec "${cmd_args[@]}" review "${review_args[@]}" < "$COMBINED_PROMPT" 2>| "${ERR_FILE}"
  else
    codex exec "${cmd_args[@]}" < "$COMBINED_PROMPT" 2>| "${ERR_FILE}"
  fi
}

set +e
run_codex
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then

  # Inspect stderr to classify the error
  STDERR_EXCERPT=""
  if [ -f "${ERR_FILE}" ]; then
    STDERR_EXCERPT=$(head -c 500 "${ERR_FILE}")
  fi

  ERROR_CLASS="transient"
  # Note: 429 (rate-limit) must NOT match this regex — it is transient, not auth
  # NB2: `printf "%s\n" "$var" | grep` avoids mis-interpretation when the
  # excerpt starts with `-n`/`-e` (which `echo` would treat as flags).
  # `command.*not.*found` and `no.*such.*file.*or.*directory` cover the case
  # where the codex binary was uninstalled while the preflight cache was
  # still asserting `mode: local` — same invalidation path as auth errors,
  # since both indicate the cached verdict is wrong.
  if printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "authenticat|401|403|invalid.*api.*key|incorrect.*api.*key|unauthorized|no.*api.*key|command.*not.*found|no.*such.*file.*or.*directory"; then
    ERROR_CLASS="auth"
  fi

  if [ "$ERROR_CLASS" = "auth" ]; then
    # Auth errors are non-retriable. Invalidate the preflight cache so
    # the next preflight re-checks rather than serving the stale `local`
    # verdict that led us here.
    rm -f "${PREFLIGHT_CACHE_FILE:-tmp/.codex-preflight-cache.json}" 2>/dev/null || true
    jq -n --argjson exit_code "$EXIT_CODE" \
          --arg stderr_excerpt "$STDERR_EXCERPT" \
          '{signal:"CODEX_ERROR",exit_code:$exit_code,retried:false,error_class:"auth",stderr_excerpt:$stderr_excerpt}' \
          > tmp/codex-exit.json
    exit 0
  fi

  # HIGH-tier model transient failure -> MEDIUM tier fallback.
  # When MODEL is gpt-5.4 (or any non-default the orchestrator passed) and
  # the Codex CLI returned a retryable-at-another-model error (429/502/503/
  # 504, rate-limit text, or connection-layer failure such as timeout,
  # connection-refused, deadline-exceeded, TLS handshake, DNS lookup, or
  # upstream gateway error), retry once with MODEL=gpt-5.3-codex +
  # model_reasoning_effort=high (MEDIUM tier at HIGH internal reasoning).
  # Connection-layer errors belong here, not in the generic transient-retry
  # path below, because retrying the same unreachable HIGH-tier model burns
  # the single transient-retry slot without changing the outcome (TODO-0104).
  # TODO-0123 broadened the regex with gateway/TLS/DNS/Envoy tokens:
  # reset-by-peer, broken-pipe, TLS-handshake, DNS-lookup, no-route-to-host,
  # upstream-connect-error.
  # If MODEL was unset (default gpt-5.3-codex from TOML pin already in effect),
  # the fallback is a no-op: retrying with the same model is pointless.
  #
  # _NETWORK_TOKENS is the shared network-class token list referenced by both
  # the IS_4XX_5XX_RETRY gate and the _status_hit network-bucket cascade below.
  # Single source of truth: a future token addition updates both call sites.
  _NETWORK_TOKENS='connection.*refused|network.*error|unexpected.*end.*of.*stream|socket.*hang.*up|reset.*by.*peer|broken.*pipe|tls.*handshake|dns.*lookup|no.*route.*to.*host|upstream.*connect.*error'
  IS_4XX_5XX_RETRY=0
  if [ -n "${MODEL:-}" ] && [ "${MODEL}" != "gpt-5.3-codex" ] \
      && printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "(^|[^0-9])(429|502|503|504)([^0-9]|$)|rate.*limit|too.*many.*requests|service.*unavailable|connection.*timeout|timed.?out|i/o.*timeout|deadline.*exceeded|${_NETWORK_TOKENS}"; then
    IS_4XX_5XX_RETRY=1
  fi

  if [ "$IS_4XX_5XX_RETRY" = "1" ]; then
    # Branch order is load-bearing: `502|504` must precede the `timeout`
    # branch because stderr like "504 Gateway Timeout" matches both — the
    # 5xx classification is canonically more informative than timeout.
    _status_hit="429"
    if printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "(^|[^0-9])503([^0-9]|$)|service.*unavailable"; then
      _status_hit="503"
    elif printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "(^|[^0-9])(502|504)([^0-9]|$)"; then
      _status_hit="5xx"
    elif printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "connection.*timeout|timed.?out|i/o.*timeout|deadline.*exceeded"; then
      _status_hit="timeout"
    elif printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "${_NETWORK_TOKENS}"; then
      _status_hit="network"
    fi
    echo "NOTICE: ${MODEL} ${EFFORT:-default} returned ${_status_hit}; falling back to gpt-5.3-codex high (MEDIUM tier)." >&2
    MODEL="gpt-5.3-codex"
    EFFORT_OVERRIDE="high"
    set +e
    run_codex
    EXIT_CODE=$?
    set -e
    unset EFFORT_OVERRIDE
    if [ "$EXIT_CODE" -ne 0 ]; then
      STDERR_EXCERPT=""
      if [ -f "${ERR_FILE}" ]; then
        STDERR_EXCERPT=$(head -c 500 "${ERR_FILE}")
      fi
      jq -n --argjson exit_code "$EXIT_CODE" \
            --arg stderr_excerpt "$STDERR_EXCERPT" \
            '{signal:"CODEX_ERROR",exit_code:$exit_code,retried:true,error_class:"high_tier_fallback_failed",stderr_excerpt:$stderr_excerpt}' \
            > tmp/codex-exit.json
      exit 1
    fi
    # Fallback succeeded — skip remaining error handling
    if [ ! -s "${OUTPUT_FILE}" ]; then
      echo "Warning: Codex produced empty output" >&2
    fi
    exit 0
  fi

  # Req-017: xhigh-rejection handling — fail-closed by default.
  # Detect Codex rejecting the EFFORT enum value (e.g., unknown variant xhigh).
  # Regex deliberately narrow: must mention "xhigh" AND an enum/variant/invalid
  # indicator to avoid false-positives from unrelated stderr text.
  IS_XHIGH_REJECT=0
  if { [ "${EFFORT:-}" = "xhigh" ] || [ "${EFFORT:-}" = "max" ]; } \
      && printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "xhigh" \
      && printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "(unknown|invalid|unrecognized|variant|enum|not.*supported)"; then
    IS_XHIGH_REJECT=1
  fi

  if [ "$IS_XHIGH_REJECT" = "1" ]; then
    if [ "${EFFORT_FALLBACK_ON_REJECT:-0}" = "1" ]; then
      # Opt-in: retry once with EFFORT=high. Prominent stderr notice.
      echo "NOTICE: Codex rejected EFFORT=xhigh; EFFORT_FALLBACK_ON_REJECT=1 is set — retrying once with EFFORT=high." >&2
      EFFORT_OVERRIDE="high"
      set +e
      run_codex
      EXIT_CODE=$?
      set -e
      unset EFFORT_OVERRIDE
      if [ "$EXIT_CODE" -ne 0 ]; then
        STDERR_EXCERPT=""
        if [ -f "${ERR_FILE}" ]; then
          STDERR_EXCERPT=$(head -c 500 "${ERR_FILE}")
        fi
        jq -n --argjson exit_code "$EXIT_CODE" \
              --arg stderr_excerpt "$STDERR_EXCERPT" \
              '{signal:"CODEX_ERROR",exit_code:$exit_code,retried:true,error_class:"xhigh_fallback_failed",stderr_excerpt:$stderr_excerpt}' \
              > tmp/codex-exit.json
        exit 1
      fi
      # Fallback retry succeeded — skip the transient retry path and continue.
    else
      # Fail-closed: xhigh rejected and no opt-in. Non-zero exit, diagnostic stderr.
      echo "Error: Codex rejected EFFORT=xhigh. Set EFFORT_FALLBACK_ON_REJECT=1 to opt into a one-shot retry with EFFORT=high." >&2
      jq -n --argjson exit_code "$EXIT_CODE" \
            --arg stderr_excerpt "$STDERR_EXCERPT" \
            '{signal:"CODEX_ERROR",exit_code:$exit_code,retried:false,error_class:"xhigh_rejected",stderr_excerpt:$stderr_excerpt}' \
            > tmp/codex-exit.json
      exit 1
    fi
  else
    # Transient — retry once after a short delay
    sleep 5

    set +e
    run_codex
    EXIT_CODE=$?
    set -e
    if [ "$EXIT_CODE" -ne 0 ]; then
      STDERR_EXCERPT=""
      if [ -f "${ERR_FILE}" ]; then
        STDERR_EXCERPT=$(head -c 500 "${ERR_FILE}")
      fi
      jq -n --argjson exit_code "$EXIT_CODE" \
            --arg stderr_excerpt "$STDERR_EXCERPT" \
            '{signal:"CODEX_ERROR",exit_code:$exit_code,retried:true,error_class:"transient",stderr_excerpt:$stderr_excerpt}' \
            > tmp/codex-exit.json
      exit 0
    fi
  fi
fi

# Guard against silent success with no output
if [ ! -s "${OUTPUT_FILE}" ]; then
  echo "Warning: Codex produced empty output" >&2
fi
