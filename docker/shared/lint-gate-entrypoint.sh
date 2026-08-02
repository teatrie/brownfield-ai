#!/usr/bin/env bash
set -euo pipefail
# The gate artifact contains GATE_PASS=<timestamp>:<sha256_of_command>.
# The entrypoint validates the timestamp (120s TTL) but does NOT verify
# the hash — the hash is written by the host-side gate script for audit
# trail purposes only. Command-binding enforcement is in Layer 2 (host).
GATE_FILE_LINT="/tmp/.lint-gate-pass"
GATE_FILE_FIX="/tmp/.lint-fix-gate-pass"

# Command allowlist — only lint tools are permitted.
ALLOWED_COMMANDS="shellcheck|hadolint|yamllint|sqlfluff|markdownlint-cli2|jsonlint|jsonlint-batch.sh|kubeconform"

# Emergency bypass for human operators
if [[ "${LINT_GATE_DISABLED:-}" == "1" ]]; then
  echo "WARNING: Security gate bypassed (LINT_GATE_DISABLED=1)." >&2
  exec "$@"
fi

# ---------------------------------------------------------------------------
# Command allowlist check
# ---------------------------------------------------------------------------
CMD="${1:-}"

# Check standard allowlist first
cmd_allowed=false
if printf '%s' "$CMD" | grep -qE "^($ALLOWED_COMMANDS)$"; then
  cmd_allowed=true
fi

# helm requires subcommand validation: only template and lint allowed
if [[ "$CMD" == "helm" ]]; then
  SUBCMD="${2:-}"
  if [[ "$SUBCMD" == "template" || "$SUBCMD" == "lint" ]]; then
    cmd_allowed=true
  else
    echo "ERROR: helm subcommand '$SUBCMD' not allowed. Only 'helm template' and 'helm lint' are permitted." >&2
    echo "Only lint tools are permitted in this container." >&2
    exit 1
  fi
fi

if ! $cmd_allowed; then
  echo "ERROR: command '$CMD' not in allowlist ($ALLOWED_COMMANDS|helm template|helm lint)." >&2
  echo "Only lint tools are permitted in this container." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Gate artifact validation — accept either lint or fix artifact
# ---------------------------------------------------------------------------
GATE_FILE=""
if [[ -f "$GATE_FILE_LINT" ]]; then
  GATE_FILE="$GATE_FILE_LINT"
elif [[ -f "$GATE_FILE_FIX" ]]; then
  GATE_FILE="$GATE_FILE_FIX"
fi

if [[ -z "$GATE_FILE" ]]; then
  echo "ERROR: Security gate artifact not found." >&2
  echo "Execution must go through task wrappers." >&2
  exit 1
fi
GATE_TS=$(sed 's/GATE_PASS=//' "$GATE_FILE" | cut -d: -f1)
if ! [[ "$GATE_TS" =~ ^[0-9]+$ ]]; then
  echo "ERROR: Gate artifact has invalid timestamp format." >&2
  exit 1
fi
NOW=$(date +%s)
AGE=$(( NOW - GATE_TS ))
if (( AGE > 120 )); then
  echo "ERROR: Gate artifact expired (${AGE}s old, max 120s)." >&2
  exit 1
fi

exec "$@"
