#!/usr/bin/env bash
set -euo pipefail

readonly ALLOWED_COMMANDS=("init" "fmt" "plan" "show")
readonly TF_BIN="/bin/_tf_exec_internal"

if [[ $# -lt 1 ]]; then
  echo "Usage: $(basename "$0") <cmd> [args...] [-- <cmd> [args...]]..." >&2
  exit 1
fi

run_command() {
  local cmd="$1"
  shift
  case "$cmd" in
    init|fmt|plan|show) sudo "$TF_BIN" "$cmd" "$@" ;;
    *) echo "Error: '$cmd' is not allowed. Permitted: ${ALLOWED_COMMANDS[*]}" >&2; exit 1 ;;
  esac
}

# Split arguments on "--" and run each group as a validated terraform subcommand
group=()
for arg in "$@"; do
  if [[ "$arg" == "--" ]]; then
    if [[ ${#group[@]} -gt 0 ]]; then
      run_command "${group[@]}"
      group=()
    fi
  else
    group+=("$arg")
  fi
done

if [[ ${#group[@]} -gt 0 ]]; then
  run_command "${group[@]}"
fi
