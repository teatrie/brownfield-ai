#!/usr/bin/env bash
# lint-security-gate.sh — Host-side validation gate for lint execution.
# Validates commands against an allowlist and writes gate artifacts before
# allowing Docker container execution.
#
# Usage: docker/shared/lint-security-gate.sh <mode> <command> [args...]
# Modes: lint, fix

set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
    echo "ERROR: mode argument required (lint|fix)" >&2
    exit 1
fi

MODE="$1"
shift

if [[ $# -lt 1 ]]; then
    echo "ERROR: command argument required after mode" >&2
    exit 1
fi

REMAINING_ARGS=("$@")

# Build the command string from all remaining args
cmd_str=""
for arg in "${REMAINING_ARGS[@]+"${REMAINING_ARGS[@]}"}"; do
    if [[ -z "$cmd_str" ]]; then
        cmd_str="$arg"
    else
        cmd_str="$cmd_str $arg"
    fi
done

# ---------------------------------------------------------------------------
# Shared allowlist validation
# ---------------------------------------------------------------------------

validate_command() {
    local cmd="$1"
    local allowed_prefixes=(
        "shellcheck "
        "shellcheck"
        "hadolint "
        "hadolint"
        "yamllint "
        "yamllint"
        "sqlfluff "
        "sqlfluff"
        "markdownlint-cli2 "
        "markdownlint-cli2"
        "jsonlint "
        "jsonlint"
        "jsonlint-batch.sh "
        "jsonlint-batch.sh"
        "kubeconform "
        "kubeconform"
    )

    local matched=false
    for prefix in "${allowed_prefixes[@]}"; do
        if [[ "$cmd" == "${prefix}"* || "$cmd" == "$prefix" ]]; then
            matched=true
            break
        fi
    done

    # helm requires subcommand validation: only template and lint allowed
    if ! $matched; then
        if [[ "$cmd" == "helm template"* || "$cmd" == "helm lint"* ]]; then
            matched=true
        elif [[ "$cmd" == "helm "* || "$cmd" == "helm" ]]; then
            echo "ERROR: helm subcommand not allowed. Only 'helm template' and 'helm lint' are permitted: $cmd" >&2
            exit 1
        fi
    fi

    if ! $matched; then
        echo "ERROR: command not in allowlist: $cmd" >&2
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Mode: lint
# ---------------------------------------------------------------------------

if [[ "$MODE" == "lint" ]]; then
    validate_command "$cmd_str"

    # Write gate artifact
    mkdir -p "$WORKSPACE_ROOT/tmp"
    path_hash=$(printf '%s' "$cmd_str" | shasum -a 256 | cut -d' ' -f1)
    ts=$(date +%s)
    echo "GATE_PASS=${ts}:${path_hash}" > "$WORKSPACE_ROOT/tmp/.lint-gate-pass"
    exit 0
fi

# ---------------------------------------------------------------------------
# Mode: fix
# ---------------------------------------------------------------------------

if [[ "$MODE" == "fix" ]]; then
    validate_command "$cmd_str"

    # Write gate artifact
    mkdir -p "$WORKSPACE_ROOT/tmp"
    path_hash=$(printf '%s' "$cmd_str" | shasum -a 256 | cut -d' ' -f1)
    ts=$(date +%s)
    echo "GATE_PASS=${ts}:${path_hash}" > "$WORKSPACE_ROOT/tmp/.lint-fix-gate-pass"
    exit 0
fi

# ---------------------------------------------------------------------------
# Unknown mode
# ---------------------------------------------------------------------------

echo "ERROR: unknown mode '$MODE' (expected lint|fix)" >&2
exit 1
