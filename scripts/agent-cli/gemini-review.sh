#!/usr/bin/env bash
# gemini-review.sh — Invoke the Gemini CLI to perform a structured code review.
# Usage: gemini-review.sh [--round N]
#   ROUND defaults to 1.
#   REVIEW_TYPE (required): one of {plan, spec, diff, epic, spec-req-verification}.
#   DIFF_FILE (required): path to the subject artifact under tmp/ or agent-review/.
#   GEMINI_MODEL defaults to gemini-3.1-pro-preview.
#   GEMINI_TIMEOUT (seconds) — if set and >0, run gemini in the background
#     and wait up to this many seconds for completion. Any non-zero exit
#     (capacity, auth, transient, crash) writes GEMINI_FALLBACK to
#     tmp/gemini-exit.json and exits 3, signalling the agent to try the
#     next step in the fallback chain.
#   Output written to tmp/gemini-review-output-<ROUND>.md.
#   Signals written to tmp/gemini-exit.json on unavailability or error.

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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --round)
      if [ -z "${2:-}" ]; then
        echo "Error: --round requires a value" >&2
        exit 1
      fi
      ROUND="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--round N]" >&2
      exit 1
      ;;
  esac
done

if ! [[ "$ROUND" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --round must be a positive integer >= 1, got '$ROUND'" >&2
  printf '{"signal":"GEMINI_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"--round must be a positive integer >= 1"}\n' > tmp/gemini-exit.json
  exit 1
fi

# ---------------------------------------------------------------------------
# Source shared reviewer helpers (REVIEW_TYPES enum, DIFF_FILE containment,
# subject sanitation, template path). The helpers live in the same
# directory as this script.
# ---------------------------------------------------------------------------
# shellcheck source=scripts/agent-cli/_review-common.sh
. "$(dirname "$0")/_review-common.sh"

# ---------------------------------------------------------------------------
# Validate REVIEW_TYPE + DIFF_FILE — required by the new wrapper contract.
# Emit GEMINI_ERROR arg_validation JSON on failure so callers can degrade.
# ---------------------------------------------------------------------------
if ! _review_validate_type; then
  printf '{"signal":"GEMINI_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"REVIEW_TYPE invalid or missing"}\n' > tmp/gemini-exit.json
  exit 1
fi
if ! _review_validate_diff_file; then
  printf '{"signal":"GEMINI_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"DIFF_FILE invalid or missing"}\n' > tmp/gemini-exit.json
  exit 1
fi

# ---------------------------------------------------------------------------
# Req-005: EFFORT env var — enum validation. Tier-alias composition happens
# after GEMINI_MODEL is resolved below (so Pro->Flash fallback can rewrite
# the tier mid-call per Req-N03). Accepts {medium, high, xhigh, max}.
# "low" and "minimal" are rejected — reviewers run at HIGH internal thinking
# minimum.
#
# Ceiling-collapse composition:
#   medium -> <tier-sn>-high    (MEDIUM tier runs lower-capability model at
#             MAX internal thinking; model upgrade happens at HIGH+)
#   high   -> <tier-sn>-high
#   xhigh  -> <tier-sn>-high    (ceiling collision — Gemini Pro tops out at HIGH)
#   max    -> <tier-sn>-high    (ceiling collision)
# ---------------------------------------------------------------------------
EFFORT="${EFFORT:-}"
if [ -n "$EFFORT" ]; then
  case "$EFFORT" in
    medium|high|xhigh|max) ;;
    *)
      echo "Error: EFFORT must be one of {medium,high,xhigh,max}, got '$EFFORT'" >&2
      printf '{"signal":"GEMINI_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"EFFORT enum rejected"}\n' > tmp/gemini-exit.json
      exit 1
      ;;
  esac
fi

# Map EFFORT -> effective alias suffix (ceiling-collapse rules above).
_map_effort_to_gemini_suffix() {
  case "$1" in
    medium|high|xhigh|max) echo "high" ;;
    *) echo "" ;;
  esac
}

# ---------------------------------------------------------------------------
# Token guard — signal unavailability and exit cleanly (not an error).
# Skipped for local OAuth (host context handles auth via cached credentials).
# Must run BEFORE artifact path setup because the container-mode mkdir
# may fail in read-only test environments.
# ---------------------------------------------------------------------------
if [ "${GEMINI_EXECUTION_CONTEXT:-}" != "host" ] && [ -z "${GEMINI_API_KEY:-}" ]; then
  # Exit signals always go to tmp/ (not agent-review/) — they are read by the
  # bridge agent (Claude Code), not by Gemini CLI, so no .gitignore issue.
  printf '{"signal":"GEMINI_UNAVAILABLE","reason":"token_missing"}\n' > tmp/gemini-exit.json
  exit 0
fi

# ---------------------------------------------------------------------------
# Artifact path setup — container mode routes to agent-review/ (Gemini
# respects .gitignore which excludes tmp/), host mode stays in tmp/.
# ---------------------------------------------------------------------------
WORKSPACE="${WORKSPACE:-brownfield-ai}"
SESSION_ID="${REVIEW_SESSION_ID:-local}"

if [ "${GEMINI_EXECUTION_CONTEXT:-}" != "host" ]; then
  OUTPUT_DIR="agent-review"
  OUTPUT_FILE="${OUTPUT_DIR}/${WORKSPACE}-gemini-review-output-${SESSION_ID}.md"
  ERR_FILE="${OUTPUT_DIR}/${WORKSPACE}-gemini-review-err-${SESSION_ID}.txt"
else
  OUTPUT_DIR="tmp"
  OUTPUT_FILE="tmp/gemini-review-output-${ROUND}.md"
  ERR_FILE="tmp/gemini-review-err.txt"
fi

mkdir -p "${OUTPUT_DIR}"

# ---------------------------------------------------------------------------
# Resolve template + sanitize subject. Wrapper owns both; bridge agents
# do not supply prompt text and do not sanitize the subject themselves.
# ---------------------------------------------------------------------------
TEMPLATE_PATH=$(_review_template_path)
if [ ! -f "$TEMPLATE_PATH" ]; then
  echo "Error: reviewer template not found: $TEMPLATE_PATH" >&2
  printf '{"signal":"GEMINI_ERROR","exit_code":1,"retried":false,"error_class":"template_missing","stderr_excerpt":"reviewer template not found"}\n' > tmp/gemini-exit.json
  exit 1
fi

SANITIZED_SUBJECT=$(_review_sanitize_subject gemini "${ROUND}")

# ---------------------------------------------------------------------------
# Invoke Gemini CLI — output captured to tmp files, never piped into eval
# ---------------------------------------------------------------------------
EXIT_CODE=0

GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.1-pro-preview}"
GEMINI_TIMEOUT="${GEMINI_TIMEOUT:-0}"

# Validate GEMINI_TIMEOUT is numeric — default to 0 if not
if ! [[ "$GEMINI_TIMEOUT" =~ ^[0-9]+$ ]]; then
  GEMINI_TIMEOUT=0
fi

# ---------------------------------------------------------------------------
# Req-005: Tier-alias composition.
# Maps GEMINI_MODEL (full "-preview" tier) to the shortname used in the
# customAliases block of .gemini/settings.json, then suffixes EFFORT to
# select the concrete alias. Called at invocation time so Req-N03's
# Pro->Flash capacity fallback (which rewrites GEMINI_MODEL mid-call)
# re-derives the alias via the same mapping.
# ---------------------------------------------------------------------------
_tier_shortname() {
  case "$1" in
    gemini-3.1-pro-preview) echo "gemini-3.1-pro" ;;
    gemini-3-flash-preview) echo "gemini-3-flash" ;;
    # Already-short aliases pass through (defensive — callers occasionally
    # pass the shortname directly, esp. during fallback rewrites).
    gemini-3.1-pro|gemini-3-flash) echo "$1" ;;
    *) echo "" ;;
  esac
}

# Resolve the effective -m argument. When EFFORT is set, compose
# <tier-shortname>-<effort-suffix>; otherwise pass GEMINI_MODEL through unchanged.
# The effort-suffix comes from _map_effort_to_gemini_suffix (ceiling-collapse
# rules documented above).
_resolve_model_arg() {
  if [ -z "$EFFORT" ]; then
    echo "$GEMINI_MODEL"
    return
  fi
  local _sn
  _sn=$(_tier_shortname "$GEMINI_MODEL")
  if [ -z "$_sn" ]; then
    # Unknown tier — degrade gracefully: pass the raw model through.
    echo "$GEMINI_MODEL"
    return
  fi
  local _suffix
  _suffix=$(_map_effort_to_gemini_suffix "$EFFORT")
  if [ -z "$_suffix" ]; then
    echo "$GEMINI_MODEL"
    return
  fi
  echo "${_sn}-${_suffix}"
}

run_gemini() {
  local _model_arg
  _model_arg=$(_resolve_model_arg)
  # `--skip-trust` bypasses the Gemini CLI's interactive
  # trusted-folder prompt, which fires unconditionally in non-TTY
  # invocations even when the cwd is already listed in
  # ~/.gemini/trustedFolders.json. The trust decision is owned by
  # the operator's host config; this wrapper only runs for headless
  # review and never loads workspace extensions.
  mkdir -p "$HOME/.gemini" && cat "$TEMPLATE_PATH" "$SANITIZED_SUBJECT" | gemini \
    --skip-trust \
    -m "$_model_arg" \
    -p "Follow the review instructions." \
    >| "${OUTPUT_FILE}" \
    2>| "${ERR_FILE}"
}

# ---------------------------------------------------------------------------
# Timeout-aware invocation: background process with deadline.
# Uses process group kill to clean up the entire pipeline (cat | gemini)
# and prevent orphaned child processes.
# ---------------------------------------------------------------------------
run_gemini_with_timeout() {
  # Launch gemini in background, wait up to GEMINI_TIMEOUT seconds.
  # Returns: 0 on success, 124 on timeout, or the gemini exit code.
  : > "${ERR_FILE}"
  : > "${OUTPUT_FILE}"

  # Run in a new process group so kill can target the entire pipeline.
  set -m
  run_gemini &
  local GEMINI_PID=$!
  set +m

  local ELAPSED=0
  local POLL_INTERVAL=5

  while kill -0 "$GEMINI_PID" 2>/dev/null; do
    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))

    if [ "$ELAPSED" -ge "$GEMINI_TIMEOUT" ]; then
      # Kill the entire process group (cat | gemini pipeline)
      kill -- -"$GEMINI_PID" 2>/dev/null || kill "$GEMINI_PID" 2>/dev/null || true
      wait "$GEMINI_PID" 2>/dev/null || true
      return 124
    fi
  done

  wait "$GEMINI_PID" 2>/dev/null
  return $?
}

# ---------------------------------------------------------------------------
# Dispatch: timeout-aware (timeout > 0) or synchronous (timeout = 0)
# ---------------------------------------------------------------------------
set +e
if [ "$GEMINI_TIMEOUT" -gt 0 ]; then
  run_gemini_with_timeout
  EXIT_CODE=$?
else
  run_gemini
  EXIT_CODE=$?
fi
set -e

# ---------------------------------------------------------------------------
# HIGH-tier 429/503 -> MEDIUM-HIGH retry.
# When `_model_arg` resolves to a Pro-tier alias (gemini-3.1-pro-*) and the
# Gemini CLI stderr indicates a 429 or 503, retry once with gemini-3-flash-high
# (MEDIUM tier at HIGH thinking). Emit a stderr notice. Only emit
# GEMINI_FALLBACK (exit 3) if the flash-high retry also fails or if the error
# class is not 429/503 (terminal: auth, invalid args, etc.).
# ---------------------------------------------------------------------------
if [ "$EXIT_CODE" -ne 0 ]; then
  STDERR_EXCERPT=""
  if [ -f "${ERR_FILE}" ]; then
    STDERR_EXCERPT=$(head -c 500 "${ERR_FILE}")
  fi

  # Detect Pro-tier 429/503 — only retry in this narrow case.
  _model_arg_now=$(_resolve_model_arg)
  IS_PRO_429_503=0
  case "$_model_arg_now" in
    gemini-3.1-pro-*|gemini-3.1-pro)
      if printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "(^|[^0-9])(429|503)([^0-9]|$)|rate.*limit|too.*many.*requests|resource.*exhaust|quota.*exceed|service.*unavailable"; then
        IS_PRO_429_503=1
      fi
      ;;
  esac

  # Preserve the originally requested model so a failure JSON written
  # after a Pro->Flash fallback still reports the Pro tier the caller
  # asked for, not the Flash tier the wrapper degraded to.
  ORIGINAL_GEMINI_MODEL="$GEMINI_MODEL"

  if [ "$IS_PRO_429_503" = "1" ]; then
    _status_hit="429"
    if printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "(^|[^0-9])503([^0-9]|$)|service.*unavailable"; then
      _status_hit="503"
    fi
    echo "NOTICE: ${_model_arg_now} returned ${_status_hit}; falling back to gemini-3-flash-high (MEDIUM tier at HIGH thinking)." >&2
    # Rewrite GEMINI_MODEL so _resolve_model_arg produces gemini-3-flash-high.
    # EFFORT is already in {medium,high,xhigh,max}; force high.
    GEMINI_MODEL="gemini-3-flash-preview"
    EFFORT="high"
    set +e
    if [ "$GEMINI_TIMEOUT" -gt 0 ]; then
      run_gemini_with_timeout
      EXIT_CODE=$?
    else
      run_gemini
      EXIT_CODE=$?
    fi
    set -e
    if [ "$EXIT_CODE" -eq 0 ]; then
      # Flash-high retry succeeded.
      exit 0
    fi
    # Flash-high retry also failed — fall through to GEMINI_FALLBACK emit.
    if [ -f "${ERR_FILE}" ]; then
      STDERR_EXCERPT=$(head -c 500 "${ERR_FILE}")
    fi
  fi

  # Invalidate the preflight cache when the failure looks like an auth
  # or missing-binary problem, so the NEXT preflight re-checks rather
  # than serving the stale `local` verdict that led to this failure.
  # 429/503 capacity events do NOT invalidate (cache was correct;
  # quota is the upstream problem). `command.*not.*found` and the
  # generic `no.*such.*file.*or.*directory` cover the case where the
  # gemini binary was uninstalled while the cache was still asserting
  # `mode: local`.
  if printf "%s\n" "$STDERR_EXCERPT" | grep -qiE "(^|[^0-9])(401|403)([^0-9]|$)|unauthorized|forbidden|invalid.*api.*key|invalid.*token|expired.*token|not.*authenticated|permission.*denied|command.*not.*found|no.*such.*file.*or.*directory"; then
    rm -f "${PREFLIGHT_CACHE_FILE:-tmp/.gemini-preflight-cache.json}" 2>/dev/null || true
  fi

  jq -n --arg model "$ORIGINAL_GEMINI_MODEL" \
        --argjson exit_code "$EXIT_CODE" \
        --argjson timeout "$GEMINI_TIMEOUT" \
        --arg stderr_excerpt "$STDERR_EXCERPT" \
        '{signal:"GEMINI_FALLBACK",model:$model,exit_code:$exit_code,timeout:$timeout,stderr_excerpt:$stderr_excerpt}' \
        > tmp/gemini-exit.json
  exit 3
fi
