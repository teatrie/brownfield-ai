#!/bin/bash
set -e

# Script: ci_lint_changed.sh
# Description: Determines which files have changed in a Pull Request or Push event
#              and runs the appropriate lint tasks only on those files.
#              This optimizes CI runtime by avoiding linting the entire codebase.
#
# Usage: ./ci_lint_changed.sh [options]
#
# Options:
#   -h, --help    Show this help message and exit

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Description:"
    echo "  Determines changed files (via git diff) and runs lint tasks only on them."
    echo "  Detects context automatically (PR, Push, or Local)."
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  GITHUB_EVENT_NAME   (Optional) 'pull_request' or 'push'"
    echo "  GITHUB_BASE_REF     (Optional) Base branch for PRs (default: main)"
}

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    exit 0
fi

# Default to linting all files if something goes wrong or we can't determine changes
LINT_ALL=false

# Detect task command
TASK_CMD=(task)

echo "Using task command: ${TASK_CMD[*]}"

# Determine changes
CHANGED_FILES=""

if [ "$GITHUB_EVENT_NAME" == "pull_request" ]; then
    echo "Running in PR context"
    # Fetch base ref
    git fetch origin "${GITHUB_BASE_REF:-main}" --depth=1 || true
    BASE_SHA=$(git rev-parse "origin/${GITHUB_BASE_REF:-main}" 2>/dev/null || echo "origin/main")
    echo "Diffing against base $BASE_SHA"
    CHANGED_FILES=$(git diff --name-only "$BASE_SHA" HEAD || echo "")
elif [ "$GITHUB_EVENT_NAME" == "push" ]; then
    echo "Running in Push context"
    # A root commit has no parent, so HEAD^ does not resolve, the diff comes
    # back empty, and this script would report success having linted nothing.
    # Fall back to a full lint — the honest reading of "every file is new".
    if git rev-parse --verify HEAD^ >/dev/null 2>&1; then
        CHANGED_FILES=$(git diff --name-only HEAD^ HEAD || echo "")
    else
        echo "Root commit detected (no parent) — linting all files."
        LINT_ALL=true
    fi
else
    echo "Running locally or unknown context"
    # Try diff against main, fallback to all if fails
    if git rev-parse --verify main >/dev/null 2>&1; then
        # Committed changes vs main
        COMMITTED=$(git diff --name-only main HEAD || true)
        # Staged changes
        STAGED=$(git diff --name-only --cached || true)
        # Unstaged changes
        UNSTAGED=$(git diff --name-only || true)
        # Untracked files
        UNTRACKED=$(git ls-files --others --exclude-standard || true)

        # Combine all
        CHANGED_FILES=$(echo -e "${COMMITTED}\n${STAGED}\n${UNSTAGED}\n${UNTRACKED}" | sort -u | grep -v '^$')
    elif git rev-parse --verify origin/main >/dev/null 2>&1; then
        CHANGED_FILES=$(git diff --name-only origin/main HEAD)
    else
        echo "Could not find main or origin/main. Linting all files."
        LINT_ALL=true
    fi
fi

if [ "$LINT_ALL" == "true" ] || [ -z "$CHANGED_FILES" ]; then
    if [ "$LINT_ALL" == "true" ]; then
        echo "Linting all files..."
        "${TASK_CMD[@]}" lint
    else
        echo "No changed files detected."
    fi
    exit 0
fi

# Gather ignored paths dynamically from lint config files
IGNORE_PATTERNS=()

# Extract from pyproject.toml (Python)
if [ -f "pyproject.toml" ]; then
    PY_IGNORES=$(awk '/exclude[[:space:]]*=[[:space:]]*\[/,/\]/' pyproject.toml | grep -o '"[^"]*"' | tr -d '"')
    while IFS= read -r p; do
        [ -n "$p" ] && IGNORE_PATTERNS+=("$p")
    done <<< "$PY_IGNORES"
fi

# Extract from .markdownlint-cli2.yaml (Markdown)
if [ -f ".markdownlint-cli2.yaml" ]; then
    MD_IGNORES=$(awk '/^ignores:/,/^[[:alnum:]]/' .markdownlint-cli2.yaml | grep -o '"[^"]*"' | tr -d '"')
    while IFS= read -r p; do
        [ -n "$p" ] && IGNORE_PATTERNS+=("$p")
    done <<< "$MD_IGNORES"
fi

# Filter out deleted files (files that don't exist on disk) and ignored paths
EXISTING_FILES=""
while IFS= read -r file; do
    [ -z "$file" ] && continue
    if [ ! -f "$file" ]; then
        continue
    fi

    IGNORED=false
    for pattern in "${IGNORE_PATTERNS[@]}"; do
        # Convert glob to extended regex (replace . with \. and * with .*)
        regex_pattern="${pattern//\./\.}"
        regex_pattern="^${regex_pattern//\*/.*}"

        # Match using grep
        if echo "$file" | grep -q -E "$regex_pattern"; then
            IGNORED=true
            break
        fi
    done

    if [ "$IGNORED" = false ]; then
        EXISTING_FILES="$EXISTING_FILES $file"
    fi
done <<< "$(echo "$CHANGED_FILES" | tr ' ' '\n')"
CHANGED_FILES="$EXISTING_FILES"

echo "Changed files:"
echo "$CHANGED_FILES"

if [ -n "$CHANGED_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Checking for unauthorized linter bypasses..."
    if ! "${TASK_CMD[@]}" lint:bypasses FILES="$CHANGED_FILES"; then
        echo "Linter bypass check failed"
        EXIT_CODE=1
    fi
fi

# Filter files (grep || true to avoid exit on no match)
PY_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '\.py$' | xargs || true)
YML_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '\.ya?ml$' | xargs || true)
EVALS_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E 'evals\.ya?ml$' | xargs || true)
MD_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '\.md$' | xargs || true)
SKILL_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '(\.claude/skills/|workflows/).*/SKILL\.md$' | xargs || true)
SH_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '\.sh$' | xargs || true)
JSON_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '\.json$' | grep -v 'tests/.*fixtures/' | xargs || true)
DOCKER_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E 'Dockerfile' | xargs || true)
COMPOSE_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E 'docker-compose.*\.ya?ml$' | xargs || true)

# Route repo-specific Python files (returns non-repo files for generic linting)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ci/repo_routing.sh
source "$SCRIPT_DIR/repo_routing.sh"
PY_FILES=$(route_repo_lints "$PY_FILES" "${TASK_CMD[*]}") || EXIT_CODE=1

# Run tasks
EXIT_CODE=${EXIT_CODE:-0}

if [ -n "$PY_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting Python files: $PY_FILES"
    if ! "${TASK_CMD[@]}" lint:python FILES="$PY_FILES"; then
        echo "Python lint failed"
        EXIT_CODE=1
    fi
else
    echo "No Python files changed."
fi

if [ -n "$PY_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Checking SQL wildcards in Python files: $PY_FILES"
    if ! "${TASK_CMD[@]}" lint:python-sql FILES="$PY_FILES"; then
        echo "SQL wildcard check failed"
        EXIT_CODE=1
    fi
fi

if [ -n "$YML_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting YAML files: $YML_FILES"
    if ! "${TASK_CMD[@]}" lint:yaml FILES="$YML_FILES"; then
        echo "YAML lint failed"
        EXIT_CODE=1
    fi
else
    echo "No YAML files changed."
fi

if [ -n "$EVALS_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting Evals files: $EVALS_FILES"
    if ! "${TASK_CMD[@]}" lint:evals FILES="$EVALS_FILES"; then
        echo "Evals file linting failed!"
        EXIT_CODE=1
    fi
fi

if [ -n "$SKILL_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting Skill headers: $SKILL_FILES"
    if ! "${TASK_CMD[@]}" lint:skills FILES="$SKILL_FILES"; then
        echo "Skill header linting failed!"
        EXIT_CODE=1
    fi
fi

if [ -n "$MD_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting Markdown files: $MD_FILES"
    if ! "${TASK_CMD[@]}" lint:markdown FILES="$MD_FILES"; then
        echo "Markdown lint failed"
        EXIT_CODE=1
    fi
else
    echo "No Markdown files changed."
fi

if [ -n "$SH_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting Shell scripts: '$SH_FILES'"
    if ! "${TASK_CMD[@]}" lint:shell FILES="$SH_FILES"; then
        echo "Shell lint failed"
        EXIT_CODE=1
    fi
else
    echo "No Shell files changed."
fi

if [ -n "$JSON_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting JSON files: '$JSON_FILES'"
    if ! "${TASK_CMD[@]}" lint:json FILES="$JSON_FILES"; then
        echo "JSON lint failed"
        EXIT_CODE=1
    fi
else
    echo "No JSON files changed."
fi

if [ -n "$DOCKER_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Linting Dockerfiles: $DOCKER_FILES"
    if ! "${TASK_CMD[@]}" lint:docker-hadolint FILES="$DOCKER_FILES"; then
        echo "Dockerfile lint failed"
        EXIT_CODE=1
    fi
fi

if [ -n "$COMPOSE_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Validating docker-compose files: $COMPOSE_FILES"
    if ! "${TASK_CMD[@]}" lint:docker-compose-validate; then
        echo "Docker Compose validation failed"
        EXIT_CODE=1
    fi
fi

NON_PY_SQL_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' \
    | grep -E '\.(sql|sql\.j2|yaml|yml|ipynb|sh)$' | xargs || true)
if [ -n "$NON_PY_SQL_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Checking SQL wildcards in non-Python files (warning only): $NON_PY_SQL_FILES"
    if echo "$NON_PY_SQL_FILES" | xargs rg -U -i '(select|returning)\s+([a-zA-Z0-9_]+\.)?\*' 2>/dev/null; then
        echo "WARNING: SQL wildcard(s) found in non-Python files above."
        echo "Review per .claude/rules/sql.queries.md — this is advisory, not blocking."
    fi
fi

# The CI `lint` job runs `task lint:changed` as its only lint step
# (.github/workflows/ci.yml), so this router — not lint_staged.sh — is what a
# pull request is gated on, and a check present only in the staged gate never
# fires on a PR at all. The two blocks below are byte-identical to their
# lint_staged.sh counterparts, which a byte-identity test asserts directly;
# tests/ci/ subclasses one shared LintRouterContract for both routers so a
# trigger dropped from either one also fails.

# Reviewer template invariant check — triggered when a reviewer prompt, a
# codex config, the mirrored rubric half in the diff-review SKILL.md, or the
# checker itself changes. Delegates to `task lint:reviewer-templates`
# which runs the lint inside the pytest-cli container.
TEMPLATE_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '^\.claude/prompts/reviewer/.*\.md$|^\.codex/config\.toml$|^docker/agent-cli/codex-config\.toml$|^\.claude/skills/diff-review/SKILL\.md$|^scripts/lint_reviewer_templates\.py$' | xargs || true)
if [ -n "$TEMPLATE_FILES" ]; then
    echo "--------------------------------------------------"
    echo "Checking reviewer template invariants..."
    if ! "${TASK_CMD[@]}" lint:reviewer-templates; then
        echo "Reviewer template invariant lint failed"
        EXIT_CODE=1
    fi
fi

# Reviewer Output Envelope compliance — triggered when a reviewer agent
# definition, the envelope canonical doc, or the envelope schema
# changes. Per the per-wave scope-expansion contract (plan §10.3,
# Req-018 / B-3 R2), the trigger pattern is intentionally broader than
# the W1 SCOPE constant in tests/lint/test_reviewer_envelope_required.py
# so future-wave reviewer files (codex-reviewer*, gemini-reviewer*,
# qa-*) automatically invoke the gate once W2/W3 add them to SCOPE.
ENVELOPE_AGENTS=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '^\.claude/agents/(code-review|codex-reviewer|gemini-reviewer|copilot-reviewer|qa-(standards|lint|test))(-(high|xhigh|max))?\.md$' | xargs || true)
ENVELOPE_DOCS=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '^docs/reviewer_envelope\.md$|^docs/schemas/reviewer_envelope\.schema\.json$' | xargs || true)
if [ -n "$ENVELOPE_AGENTS" ] || [ -n "$ENVELOPE_DOCS" ]; then
    echo "--------------------------------------------------"
    echo "Checking reviewer envelope compliance..."
    if ! "${TASK_CMD[@]}" lint:reviewer-envelope; then
        echo "Reviewer envelope lint failed"
        EXIT_CODE=1
    fi
fi

exit "$EXIT_CODE"
