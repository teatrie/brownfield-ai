#!/usr/bin/env bash
# copilot-review.sh — Invoke the Copilot CLI to perform a structured code review.
# Usage: copilot-review.sh [--model MODEL] [--round N]
#   MODEL defaults to gemini-3-pro-preview.
#   ROUND defaults to 1.
#   REVIEW_TYPE (required): one of {plan, spec, diff, epic, spec-req-verification}.
#   DIFF_FILE (required): path to the subject artifact under tmp/ or agent-review/.
#   Output written to tmp/copilot-review-output-<ROUND>.md.
#   Signals written to tmp/copilot-exit.json on unavailability or error.

set -euo pipefail

# ---------------------------------------------------------------------------
# SECRETS GUARD — must never run inside a container where .env is readable
# ---------------------------------------------------------------------------
if [ -f /app/.env ] && [ -r /app/.env ]; then
  echo "FATAL: .env is readable inside container" >&2
  exit 1
fi

mkdir -p tmp

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
# Default: highest-tier cross-family model via Copilot CLI routing.
# Copilot CLI supports --model to select non-Copilot models (Gemini, GPT).
MODEL="gemini-3-pro-preview"
ROUND="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      if [ -z "${2:-}" ]; then
        echo "Error: --model requires a value" >&2
        exit 1
      fi
      MODEL="$2"
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
    *)
      echo "Usage: $0 [--model MODEL] [--round N]" >&2
      exit 1
      ;;
  esac
done

if ! [[ "$ROUND" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --round must be a positive integer >= 1, got '$ROUND'" >&2
  printf '{"signal":"COPILOT_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"--round must be a positive integer >= 1"}\n' > tmp/copilot-exit.json
  exit 1
fi

# ---------------------------------------------------------------------------
# Source shared reviewer helpers and validate REVIEW_TYPE + DIFF_FILE.
# ---------------------------------------------------------------------------
# shellcheck source=scripts/agent-cli/_review-common.sh
. "$(dirname "$0")/_review-common.sh"

if ! _review_validate_type; then
  printf '{"signal":"COPILOT_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"REVIEW_TYPE invalid or missing"}\n' > tmp/copilot-exit.json
  exit 1
fi
if ! _review_validate_diff_file; then
  printf '{"signal":"COPILOT_ERROR","exit_code":1,"retried":false,"error_class":"arg_validation","stderr_excerpt":"DIFF_FILE invalid or missing"}\n' > tmp/copilot-exit.json
  exit 1
fi

# ---------------------------------------------------------------------------
# Token guard — signal unavailability and exit cleanly (not an error)
# ---------------------------------------------------------------------------
if [ -z "${COPILOT_GITHUB_TOKEN:-}" ]; then
  printf '{"signal":"COPILOT_UNAVAILABLE","reason":"token_missing"}\n' > tmp/copilot-exit.json
  exit 0
fi

# ---------------------------------------------------------------------------
# Resolve template + sanitize subject + build combined prompt file.
# Copilot reads the prompt file by reference (-p "Follow the instructions in ...").
# ---------------------------------------------------------------------------
TEMPLATE_PATH=$(_review_template_path)
if [ ! -f "$TEMPLATE_PATH" ]; then
  echo "Error: reviewer template not found: $TEMPLATE_PATH" >&2
  printf '{"signal":"COPILOT_ERROR","exit_code":1,"retried":false,"error_class":"template_missing","stderr_excerpt":"reviewer template not found"}\n' > tmp/copilot-exit.json
  exit 1
fi

SANITIZED_SUBJECT=$(_review_sanitize_subject copilot "${ROUND}")
COMBINED_PROMPT="tmp/copilot-combined-prompt-${ROUND}.txt"
cat "$TEMPLATE_PATH" "$SANITIZED_SUBJECT" > "$COMBINED_PROMPT"

# ---------------------------------------------------------------------------
# Invoke Copilot CLI — output captured to tmp files, never piped into eval
# ---------------------------------------------------------------------------
EXIT_CODE=0

run_copilot() {
  CI=1 copilot --model "$MODEL" \
    --deny-tool shell \
    --deny-tool edit \
    --deny-tool write \
    --allow-all-paths --allow-all-urls \
    -p "Follow the instructions in $COMBINED_PROMPT." \
    >| "tmp/copilot-review-output-${ROUND}.md" \
    2>| tmp/copilot-review-err.txt
}

set +e
run_copilot
EXIT_CODE=$?
set -e
if [ "$EXIT_CODE" -ne 0 ]; then

  # Inspect stderr to classify the error
  STDERR_EXCERPT=""
  if [ -f tmp/copilot-review-err.txt ]; then
    STDERR_EXCERPT=$(head -c 500 tmp/copilot-review-err.txt)
  fi

  ERROR_CLASS="transient"
  if echo "$STDERR_EXCERPT" | grep -qiE "authentication|401|403"; then
    ERROR_CLASS="auth"
  fi

  if [ "$ERROR_CLASS" = "auth" ]; then
    # Auth errors are non-retriable — write signal immediately
    jq -n --argjson exit_code "$EXIT_CODE" \
          --arg stderr_excerpt "$STDERR_EXCERPT" \
          '{signal:"COPILOT_ERROR",exit_code:$exit_code,retried:false,error_class:"auth",stderr_excerpt:$stderr_excerpt}' \
          > tmp/copilot-exit.json
    exit 0
  fi

  # Transient — retry once after a short delay
  sleep 5

  set +e
  run_copilot
  EXIT_CODE=$?
  set -e
  if [ "$EXIT_CODE" -ne 0 ]; then
    STDERR_EXCERPT=""
    if [ -f tmp/copilot-review-err.txt ]; then
      STDERR_EXCERPT=$(head -c 500 tmp/copilot-review-err.txt)
    fi
    jq -n --argjson exit_code "$EXIT_CODE" \
          --arg stderr_excerpt "$STDERR_EXCERPT" \
          '{signal:"COPILOT_ERROR",exit_code:$exit_code,retried:true,error_class:"transient",stderr_excerpt:$stderr_excerpt}' \
          > tmp/copilot-exit.json
    exit 0
  fi
fi
