#!/usr/bin/env bash
# cli-args-to-env.sh — validate KEY=value tokens and exec a single target
# script with the validated values injected into its environment.
#
# Motivation: Taskfile callers previously prepended env vars inline
# (`VAR=val task foo`). That pattern creates per-invocation permission
# matcher tokens distinct from `Bash(task *)` and is blocked by
# .claude/hooks/block-sandbox-prompt-patterns.sh. This shim lets recipes
# accept values via `task <target> -- KEY=val KEY=val` (Task exposes
# these as {{.CLI_ARGS}}) without reintroducing shell-eval /
# `$(...)`-injection paths.
#
# Signature (target-first — no `--` separator):
#   cli-args-to-env.sh <target-script-path> [KEY=value ...]
#
# The target is the FIRST positional argument; remaining args are
# KEY=value tokens. Any token that is not KEY=value form is rejected.
# Dropping `--` closes the smuggling path that allowed a caller-supplied
# `--` inside {{.CLI_ARGS}} to prematurely terminate the key-parse loop
# and promote the remaining tokens into caller-controlled argv (which
# `exec env` would then run as a command).
#
# Keys must match ALLOWED_KEYS_REGEX. Values must match VALUE_REGEX — no
# whitespace, no shell metacharacters, no expansion tokens. The target
# inherits the current environment plus the validated KEY=value entries
# (which override same-named inherited values).
set -euo pipefail

ALLOWED_KEYS_REGEX='^(ROUND|EFFORT|REVIEW_SESSION_ID|WORKSPACE|REVIEW_TYPE|GEMINI_MODEL|GEMINI_TIMEOUT|MODEL|DIFF_FILE|REVIEW_MODE)$'
VALUE_REGEX='^[A-Za-z0-9._/:@+=-]*$'

if [[ $# -eq 0 ]]; then
  echo "cli-args-to-env: no target command" >&2
  exit 2
fi
TARGET="$1"
shift

env_args=()
while [[ $# -gt 0 ]]; do
  tok="$1"
  shift
  if [[ "$tok" != *=* ]]; then
    echo "cli-args-to-env: invalid token '$tok' — expected KEY=value form" >&2
    exit 2
  fi
  key="${tok%%=*}"
  value="${tok#*=}"
  if ! [[ "$key" =~ $ALLOWED_KEYS_REGEX ]]; then
    echo "cli-args-to-env: key '$key' is not allowlisted. Allowed: $ALLOWED_KEYS_REGEX" >&2
    exit 2
  fi
  if ! [[ "$value" =~ $VALUE_REGEX ]]; then
    echo "cli-args-to-env: value for key '$key' contains disallowed characters (allowed: [A-Za-z0-9._/:@+=-])" >&2
    exit 2
  fi
  env_args+=("$tok")
done

# ${env_args[@]+"${env_args[@]}"} expands to the array contents when the
# array is non-empty and to nothing when the array is empty. This handles
# the bash 3.2 + `set -u` interaction where a bare "${env_args[@]}" on an
# empty array raises "unbound variable".
exec env ${env_args[@]+"${env_args[@]}"} "$TARGET"
