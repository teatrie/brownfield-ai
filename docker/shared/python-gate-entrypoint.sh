#!/usr/bin/env bash
set -euo pipefail
# The gate artifact contains GATE_PASS=<timestamp>:<sha256_of_paths>.
# The entrypoint validates the timestamp (120s TTL) but does NOT verify
# the hash — the hash is written by the host-side gate script for audit
# trail purposes only. Command-binding enforcement is in Layer 2 (host).
GATE_FILE="/tmp/.python-gate-pass"

# Emergency bypass for human operators
if [[ "${PYTHON_GATE_DISABLED:-}" == "1" ]]; then
  echo "WARNING: Security gate bypassed (PYTHON_GATE_DISABLED=1)." >&2
  exec "$@"
fi

if [[ ! -f "$GATE_FILE" ]]; then
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
# Layer 3 security lint: block scripts with dangerous patterns before execution.
# Scans all positional args for the first .py file (handles flags like -u before
# the script path). Only fires when $1 is python3.
if [[ "${1:-}" == "python3" ]]; then
  _PY_FILE=""
  for _arg in "${@:2}"; do
    if [[ "$_arg" == *.py && -f "$_arg" ]]; then
      _PY_FILE="$_arg"
      break
    fi
  done
  if [[ -n "$_PY_FILE" ]]; then
    if ! ruff check --select S --no-cache "$_PY_FILE"; then
      echo "BLOCKED: ruff security lint (S-rules) failed for: $_PY_FILE" >&2
      echo "Fix the violations or run via the host terminal." >&2
      exit 1
    fi
  fi
fi
# Layer 3 conftest lint: when pytest is invoked with directory args, scan all
# conftest.py files under those directories for dangerous patterns before
# allowing test execution. This prevents injected conftest fixtures from
# running arbitrary code (e.g., eval, exec, subprocess) inside the container.
if [[ "${1:-}" == "pytest" ]]; then
  _CONFTEST_FAIL=0
  for _arg in "${@:2}"; do
    # Skip flags (anything starting with -)
    if [[ "$_arg" == -* ]]; then
      continue
    fi
    # Only scan directory args
    if [[ -d "$_arg" ]]; then
      while IFS= read -r -d '' _cf; do
        if ! ruff check --select S --no-cache "$_cf"; then
          echo "BLOCKED: ruff security lint (S-rules) failed for conftest: $_cf" >&2
          _CONFTEST_FAIL=1
        fi
      done < <(find "$_arg" -name 'conftest.py' -print0 2>/dev/null)
    fi
  done
  if (( _CONFTEST_FAIL )); then
    echo "Fix conftest.py S-rule violations before running pytest." >&2
    exit 1
  fi
fi
exec "$@"
