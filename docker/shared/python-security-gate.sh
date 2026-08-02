#!/usr/bin/env bash
# python-security-gate.sh — Host-side validation gate for Python execution.
# Validates paths, flags, and git-tracking before allowing Docker execution.
#
# Usage: docker/shared/python-security-gate.sh <mode> [args...]
# Modes: run, test, lint

set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
    echo "ERROR: mode argument required (run|test|lint)" >&2
    exit 1
fi

MODE="$1"
shift

REMAINING_ARGS=("$@")

# Split remaining args into pre-separator and post-separator (after --)
PRE_SEP=()
POST_SEP=()
found_sep=false
for arg in "${REMAINING_ARGS[@]+"${REMAINING_ARGS[@]}"}"; do
    if [[ "$arg" == "--" ]]; then
        found_sep=true
        continue
    fi
    if $found_sep; then
        POST_SEP+=("$arg")
    else
        PRE_SEP+=("$arg")
    fi
done

# ---------------------------------------------------------------------------
# Mode: lint
# ---------------------------------------------------------------------------

if [[ "$MODE" == "lint" ]]; then
    # Reconstruct the command string from pre-separator args
    cmd_str=""
    for arg in "${PRE_SEP[@]+"${PRE_SEP[@]}"}"; do
        if [[ -z "$cmd_str" ]]; then
            cmd_str="$arg"
        else
            cmd_str="$cmd_str $arg"
        fi
    done

    allowed_prefixes=(
        "ruff "
        "mypy "
        "python ci/detect_bypasses.py "
        "python ci/lint_evals.py "
        "python ci/lint_skills_header.py "
        "python scripts/lint_sql_wildcards.py "
        "python scripts/lint_reviewer_templates.py"
    )

    matched=false
    for prefix in "${allowed_prefixes[@]}"; do
        if [[ "$cmd_str" == "${prefix}"* ]]; then
            matched=true
            break
        fi
    done

    if ! $matched; then
        echo "ERROR: lint command not in allowlist: $cmd_str" >&2
        exit 1
    fi

    # Write gate artifact
    mkdir -p "$WORKSPACE_ROOT/tmp"
    path_hash=$(printf '%s' "$cmd_str" | shasum -a 256 | cut -d' ' -f1)
    ts=$(date +%s)
    echo "GATE_PASS=${ts}:${path_hash}" > "$WORKSPACE_ROOT/tmp/.python-gate-pass"
    exit 0
fi

# ---------------------------------------------------------------------------
# Mode: test — collect paths and flags
# ---------------------------------------------------------------------------

if [[ "$MODE" != "run" && "$MODE" != "test" && "$MODE" != "lint" ]]; then
    echo "ERROR: unknown mode '$MODE' (expected run|test|lint)" >&2
    exit 1
fi

# Check for dangerous flags in pre-separator args
FLAGS=()
PATHS=()
for arg in "${PRE_SEP[@]+"${PRE_SEP[@]}"}"; do
    if [[ "$arg" == "-c" || "$arg" == "-m" ]]; then
        echo "ERROR: dangerous flag '$arg' is not allowed" >&2
        exit 1
    elif [[ "$arg" == -* ]]; then
        # Allow -u and other non-dangerous flags
        FLAGS+=("$arg")
    else
        PATHS+=("$arg")
    fi
done

# At least one path is required
if [[ ${#PATHS[@]} -eq 0 ]]; then
    echo "ERROR: at least one path argument is required" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Validate each path
# ---------------------------------------------------------------------------

for p in "${PATHS[@]}"; do
    # Resolve real path for symlink/traversal check
    if [[ "$p" == /* ]]; then
        resolved="$p"
    else
        resolved="$WORKSPACE_ROOT/$p"
    fi

    # Use realpath if the path exists (for symlink resolution)
    if [[ -e "$resolved" || -L "$resolved" ]]; then
        resolved=$(realpath "$resolved" 2>/dev/null || echo "$resolved")
    else
        # For non-existent paths, try to resolve what we can
        resolved=$(cd "$WORKSPACE_ROOT" && realpath -m "$p" 2>/dev/null || echo "$WORKSPACE_ROOT/$p")
    fi

    # Check that resolved path is within workspace
    case "$resolved" in
        "${WORKSPACE_ROOT}"/*) ;;
        "${WORKSPACE_ROOT}") ;;
        *)
            echo "ERROR: path resolves outside workspace: $p -> $resolved" >&2
            exit 1
            ;;
    esac

    # Git-tracked validation
    if [[ -d "$WORKSPACE_ROOT/$p" ]]; then
        # Directory: check at least one tracked file
        tracked_count=$(cd "$WORKSPACE_ROOT" && git ls-files "$p/" | head -1)
        if [[ -z "$tracked_count" ]]; then
            echo "ERROR: no git-tracked files in directory: $p" >&2
            exit 1
        fi
    else
        # File: must be tracked
        if ! (cd "$WORKSPACE_ROOT" && git ls-files --error-unmatch "$p" > /dev/null 2>&1); then
            echo "ERROR: file is not git-tracked: $p" >&2
            exit 1
        fi
    fi
done

# ---------------------------------------------------------------------------
# Run-mode: only .py files allowed
# ---------------------------------------------------------------------------

if [[ "$MODE" == "run" ]]; then
    for p in "${PATHS[@]}"; do
        if [[ "$p" != *.py ]]; then
            echo "ERROR: run mode only accepts .py files, got: $p" >&2
            exit 1
        fi
    done
fi

# ---------------------------------------------------------------------------
# Write gate artifact
# ---------------------------------------------------------------------------

mkdir -p "$WORKSPACE_ROOT/tmp"

# Build the paths string for hashing (space-separated)
paths_str=""
for p in "${PATHS[@]}"; do
    if [[ -z "$paths_str" ]]; then
        paths_str="$p"
    else
        paths_str="$paths_str $p"
    fi
done

path_hash=$(printf '%s' "$paths_str" | shasum -a 256 | cut -d' ' -f1)
ts=$(date +%s)
echo "GATE_PASS=${ts}:${path_hash}" > "$WORKSPACE_ROOT/tmp/.python-gate-pass"

exit 0
