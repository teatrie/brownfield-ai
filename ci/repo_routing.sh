#!/bin/bash

# Script: repo_routing.sh
# Description: Shared routing logic for repo-specific lint/test commands.
#              Sourced by lint_staged.sh and lint_changed.sh to avoid
#              duplicating per-repo routing in multiple scripts.
#
#              When onboarding a new cloned repo under repos/, add a routing
#              block to route_repo_lints() below. This is the ONLY file that
#              needs updating — both lint scripts inherit the change.
#
# Usage: source ci/repo_routing.sh

# Runs repo-specific lint tasks for Python files under repos/.
# Prints the remaining (non-repo) Python files to stdout for generic linting.
# Sets REPO_LINT_EXIT_CODE to non-zero if any repo lint fails.
#
# Args:
#   $1 - space-separated list of all changed Python files
#   $2 - task command to use (e.g., "task"); available to routing blocks
route_repo_lints() {
    local all_py_files="$1"
    REPO_LINT_EXIT_CODE=0

    # ── Add repo routing blocks above this line ───────────────────
    #
    # A block filters "$all_py_files" for its repo's path prefix, runs that
    # repo's own lint target via "$2", and sets REPO_LINT_EXIT_CODE=1 on
    # failure. Files under repos/ that no block claims fall through to the
    # generic linter below, so an unrouted repo is not silently skipped.

    # Return files NOT under repos/ for generic linting (stdout)
    echo "$all_py_files" | tr ' ' '\n' \
        | grep -v -E '^repos/' | xargs || true

    # Propagate lint failure via exit code (subshell-safe)
    return "$REPO_LINT_EXIT_CODE"
}
