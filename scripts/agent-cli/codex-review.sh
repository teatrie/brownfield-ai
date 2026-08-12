#!/usr/bin/env bash
# codex-review.sh — Invoke the Codex CLI to perform a structured code review.
# Usage: codex-review.sh [--round N] [--model MODEL]
#   ROUND defaults to 1.
#   MODEL is optional — overrides profile model (passed as -m to codex exec).
#   REVIEW_TYPE (required): one of {plan, spec, diff, epic, spec-req-verification}.
#   DIFF_FILE (required): path to the subject artifact under tmp/ or agent-review/.
#   EFFORT (optional): one of {medium, high, xhigh, max}, mapped onto the Codex
#     model_reasoning_effort key (ceiling-collapse: medium/high -> high,
#     xhigh/max -> xhigh).
#   Every review type invokes `codex exec -p reviewer` with the combined
#     reviewer template + DIFF_FILE prompt on stdin as the sole subject.
#   Output written to tmp/codex-review-output-<ROUND>.md.
#   Signals written to tmp/codex-exit.json on unavailability or error.

set -euo pipefail

# ---------------------------------------------------------------------------
# Signal hygiene — must precede the FIRST signal write on any path, including
# the secrets guard's own. The bridge agent reads tmp/codex-exit.json as this
# run's authoritative outcome, so a leftover is reported as this run's result;
# probing writability here reports an unwritable tmp/ instead of aborting
# silently under `set -e` at whichever signal write comes first.
#
# The probe is a real write because `rm -f` on a missing operand returns 0 even
# under a read-only parent. Its name carries the PID: `touch` on an existing
# writable file succeeds even when the parent is not writable, so a fixed name
# left behind by an earlier run would mask exactly the case being probed.
# The mkdir, the probe, and both removals are each checked; nothing after this
# block is covered.
# ---------------------------------------------------------------------------
if ! mkdir -p tmp; then
  echo "FATAL: cannot create tmp/ — nowhere to record an exit signal" >&2
  exit 1
fi
WRITE_PROBE="tmp/.codex-write-probe.$$"
if ! touch "${WRITE_PROBE}" 2>/dev/null; then
  echo "FATAL: tmp/ is not writable — this run could not record an exit signal" >&2
  exit 1
fi
if ! rm -f "${WRITE_PROBE}"; then
  echo "FATAL: cannot remove ${WRITE_PROBE} — tmp/ is not writable" >&2
  exit 1
fi
if ! rm -f tmp/codex-exit.json; then
  echo "FATAL: cannot clear tmp/codex-exit.json — tmp/ is not writable" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# SECRETS GUARD — must never run inside a container where .env is readable
# ---------------------------------------------------------------------------
if [ -f /app/.env ] && [ -r /app/.env ]; then
  echo "FATAL: .env is readable inside container" >&2
  printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"secrets_guard","stderr_excerpt":".env is readable inside container"}\n' > tmp/codex-exit.json
  exit 1
fi
# Note: /app/.env only exists inside the container. On host, this check no-ops.

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
ROUND="${ROUND:-1}"
MODEL="${MODEL:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --round)
      if [ -z "${2:-}" ]; then
        echo "Error: --round requires a value" >&2
        printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"--round requires a value"}\n' > tmp/codex-exit.json
        exit 1
      fi
      ROUND="$2"
      shift 2
      ;;
    --model)
      if [ -z "${2:-}" ]; then
        echo "Error: --model requires a value" >&2
        printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"--model requires a value"}\n' > tmp/codex-exit.json
        exit 1
      fi
      MODEL="$2"
      shift 2
      ;;
    *)
      printf 'Usage: %s [--round N] [--model MODEL]\n' "$0" >&2
      printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"unknown argument"}\n' > tmp/codex-exit.json
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
# Default to the reviewer floor rather than to empty. An unset EFFORT composes
# no -c, which lands the run on the CLI's own default — below the
# {medium,high,xhigh,max} enum enforced just below, so the wrapper would refuse
# a named low tier while accepting no tier at all. Defaulting here holds the
# floor for every caller, not only those following the skill's caller contract.
EFFORT="${EFFORT:-high}"
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

# Both values are caller-supplied and are interpolated into the artifact paths
# below, which this run creates, writes and deletes. The shared
# cli-args-to-env.sh shim admits `/` and `.` in values because DIFF_FILE needs
# them, so an unchecked WORKSPACE of ../tmp/victim would escape agent-review/
# and aim those writes and that delete at an arbitrary path. Slug-only here:
# with no separator admitted there is no traversal to reject separately.
if ! [[ "$WORKSPACE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Error: WORKSPACE must match [A-Za-z0-9._-]+ (no path separators), got '$WORKSPACE'" >&2
  printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"WORKSPACE is not a valid slug"}\n' > tmp/codex-exit.json
  exit 1
fi
if ! [[ "$SESSION_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Error: REVIEW_SESSION_ID must match [A-Za-z0-9._-]+ (no path separators), got '$SESSION_ID'" >&2
  printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"REVIEW_SESSION_ID is not a valid slug"}\n' > tmp/codex-exit.json
  exit 1
fi

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
# The combined prompt is the sole subject channel: reviewer criteria and
# adversarial rigor from the template, then the sanitized DIFF_FILE contents,
# piped to `codex exec` on stdin.
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
# ---------------------------------------------------------------------------
EXIT_CODE=0

run_codex() {
  # Clear the output artifact before EVERY attempt. The path is reused across
  # attempts and across rounds, so an attempt that exits zero WITHOUT writing
  # -o would leave the final non-empty-output check reading an earlier
  # attempt's or an earlier round's review and returning it as this run's
  # verdict. Clearing here rather than once at startup also keeps the
  # destructive step behind the template-existence guard, which aborts before
  # any call can reach this line.
  if ! rm -f "${OUTPUT_FILE}"; then
    echo "FATAL: cannot clear ${OUTPUT_FILE} - its directory is not writable" >&2
    printf '{"signal":"CODEX_ERROR","exit_code":1,"retried":false,"error_class":"output_clear_failed","stderr_excerpt":"cannot clear the review output artifact"}\n' > tmp/codex-exit.json
    exit 1
  fi

  # --sandbox danger-full-access disables Codex's internal sandbox layer
  # because Claude Code's outer sandbox already contains the process
  # (filesystem + network restrictions enforced). Codex's nested
  # sandbox-exec call fails with "sandbox_apply: Operation not permitted"
  # under macOS nested sandboxing, so the inner layer provides no added
  # protection — it only blocks operation entirely. Scope is narrow:
  # this flag applies to review invocations only.
  #
  # --ephemeral keeps the run out of Codex's on-disk session store: the prompt
  # carries repository contents and the trace carries the reviewed diff, and
  # nothing here prunes that store.
  local cmd_args=(-p reviewer --ephemeral --sandbox danger-full-access -o "${OUTPUT_FILE}")
  if [ -n "${MODEL:-}" ]; then
    cmd_args+=(-m "$MODEL")
  fi

  # Thread EFFORT into Codex via a top-level -c override.
  # model_reasoning_effort is honored as a top-level key only; the same key
  # nested under `profiles.<name>.` does not reach the run.
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
    cmd_args+=(-c "model_reasoning_effort=${_effort}")
  fi

  # The combined template+DIFF_FILE prompt on stdin is the sole subject
  # channel for every review type. The `review` subcommand is deliberately
  # not used: it takes its subject from the live working-tree diff, and its
  # [PROMPT] argument carries no implicit-stdin clause, so a piped prompt is
  # discarded rather than read.
  codex exec "${cmd_args[@]}" < "$COMBINED_PROMPT" 2>| "${ERR_FILE}"
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
  # If MODEL is unset the wrapper passed no -m at all, so there is no
  # caller-selected model to step down from and the fallback is a no-op; the
  # transient-retry path handles same-model retries instead.
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
