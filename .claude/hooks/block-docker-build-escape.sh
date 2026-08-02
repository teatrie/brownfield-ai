#!/usr/bin/env bash
# PreToolUse hook: audit docker build commands for security bypass attempts.
#
# Blocked patterns:
#   1. docker build -f <untracked-Dockerfile>  (agent-created Dockerfile)
#   2. docker [compose] build when untracked Dockerfiles exist under docker/
#   3. docker [compose] build when security-critical files have uncommitted
#      changes that match security-weakening patterns (entrypoint removal,
#      USER removal, gate bypass, permission loosening)
#
# Allowed:
#   - Builds from tracked, clean (committed) Dockerfiles
#   - Builds from tracked Dockerfiles with non-security changes
#   - User terminal commands (hooks only fire on Claude Code tool calls)
#
# Exit 2 + stderr = deny the tool call.
# Exit 0 + no output = allow.
#
# Requires: git (host-level).

set -uo pipefail

# Failure-closed: any unexpected error denies the tool call.
trap 'echo "DENIED: docker-build hook error — failing closed." >&2; exit 2' ERR

INPUT=$(cat)
[[ -z "$INPUT" ]] && exit 0
# Fail-closed: reject malformed (non-JSON) input.
if ! printf '%s' "$INPUT" | jq empty 2>/dev/null; then
  echo "DENIED: malformed hook input — failing closed." >&2
  exit 2
fi
# Extract the "command" field. jq handles all JSON escaping correctly
# (unicode, nested quotes, backslashes). If "command" is absent, jq
# outputs nothing — the existing [[ -z "$COMMAND" ]] guard handles it.
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
[[ -z "$COMMAND" ]] && exit 0

# Only intercept docker build commands. Covers all Docker CLI build forms:
#   docker build, docker compose build, docker buildx build,
#   docker image build, docker builder build
# Also allows optional global flags between 'docker' and the subcommand.
FLAGS='(-[^[:space:]]+[[:space:]]+)*'
if ! printf '%s' "$COMMAND" | grep -qiE "docker[[:space:]]+${FLAGS}(compose[[:space:]]+${FLAGS})?build|docker[[:space:]]+${FLAGS}(image|builder|buildx)[[:space:]]+build"; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Gate 1: Block builds from untracked Dockerfiles (-f flag)
# ---------------------------------------------------------------------------

# Extract ALL -f / --file arguments (Docker honors the last one, so we must
# validate every occurrence — not just the first). Handles -f <path>,
# -f=<path>, --file <path>, --file=<path>.
DOCKERFILES=()
while IFS= read -r match; do
  df=$(printf '%s' "$match" | sed 's/^-f[= ]*//; s/^--file[= ]*//')
  [[ -n "$df" ]] && DOCKERFILES+=("$df")
done < <(printf '%s' "$COMMAND" | grep -oE '(\-f|\-\-file)[[:space:]=][^[:space:]]+' || true)

for DOCKERFILE in "${DOCKERFILES[@]}"; do
  if ! git ls-files --error-unmatch -- "$DOCKERFILE" >/dev/null 2>&1; then
    echo "DENIED: docker build from untracked Dockerfile: $DOCKERFILE" >&2
    echo "Only git-tracked Dockerfiles may be built by the agent." >&2
    exit 2
  fi
done

# ---------------------------------------------------------------------------
# Gate 2: Block builds when untracked Dockerfiles exist anywhere in tree
# ---------------------------------------------------------------------------

# Scan the entire tree for untracked Dockerfiles. Gate 1 is the primary
# blocker for arbitrary -f paths; this gate catches ambient untracked files
# that could be referenced by a docker compose build without an explicit -f.
UNTRACKED_DOCKERFILES=$(git ls-files --others --exclude-standard -- '**/Dockerfile*' 2>/dev/null || true)
if [[ -n "$UNTRACKED_DOCKERFILES" ]]; then
  echo "DENIED: untracked Dockerfile(s) detected in build context:" >&2
  printf '%s\n' "$UNTRACKED_DOCKERFILES" >&2
  echo "Remove or git-add them before building." >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Gate 3: Audit uncommitted changes to security-critical files
# ---------------------------------------------------------------------------

SECURITY_FILES=(
  "docker/python-cli/Dockerfile"
  "docker/pytest-cli/Dockerfile"
  "docker/repo-cli/Dockerfile"
  "docker/repo-cli/entrypoint.sh"
  "docker/repo-cli/sparse-clone.sh"
  "docker/shared/python-gate-entrypoint.sh"
  "docker/shared/python-security-gate.sh"
  ".claude/hooks/block-container-escape.sh"
  ".claude/hooks/block-terraform-escape.sh"
  ".claude/hooks/block-docker-build-escape.sh"
  "docker-compose.yml"
  "docker/builders/Dockerfile.infra-lint"
  "docker/builders/Dockerfile.infra-terraform"
  "docker/agent-cli/Dockerfile"
  "docker/agent-cli/entrypoint.sh"
  "docker/shared/lint-gate-entrypoint.sh"
  "docker/shared/lint-security-gate.sh"
  "docker/shared/jsonlint-batch.sh"
)

# Collect files changed relative to origin/main (not HEAD) to prevent bypass
# via local commits that advance HEAD and empty the diff. Fail-closed if
# origin/main is unavailable — an agent could delete the ref to force a
# weaker fallback.
DIFF_BASE=$(git rev-parse --verify origin/main 2>/dev/null) || {
  echo "DENIED: origin/main ref not found — cannot establish security baseline." >&2
  echo "Run 'git fetch origin main' to restore the ref." >&2
  exit 2
}
MODIFIED=()
CHANGED_FILES=$(git diff --name-only "$DIFF_BASE" 2>/dev/null || true)
for f in "${SECURITY_FILES[@]}"; do
  if printf '%s\n' "$CHANGED_FILES" | grep -qxF "$f"; then
    MODIFIED+=("$f")
  fi
done

if [[ ${#MODIFIED[@]} -eq 0 ]]; then
  exit 0
fi

# Deleted security files are inherently suspicious — block immediately.
for f in "${MODIFIED[@]}"; do
  if ! [[ -f "$f" ]]; then
    echo "DENIED: security-critical file deleted: $f" >&2
    echo "Restore the file or commit the deletion via your terminal." >&2
    exit 2
  fi
done

# Suspicious diff patterns that indicate security weakening.
# Each pattern is checked against `git diff` output (unified diff format).
SUSPICIOUS_PATTERNS=(
  # Dockerfile security
  "^-.*ENTRYPOINT"               # removing entrypoint enforcement
  "^-.*USER agent"               # removing non-root user
  "^\\+.*USER root"              # switching to root user
  "^-.*python-gate-entrypoint"   # removing gate entrypoint copy
  "^\\+.*chmod.*777"             # weakening file permissions
  "^-.*chown root:root"          # removing root ownership of gate
  "^\\+.*--entrypoint"           # injecting entrypoint override in RUN
  # Gate script / entrypoint security
  "^-.*GATE_FILE"                # removing gate file check
  "^-.*exit 1"                   # removing failure exit
  "^-.*exit 2"                   # removing deny exit in hooks
  "^\\+.*PYTHON_GATE_DISABLED"   # injecting bypass env var
  "^\\+.*exec.*\\$@.*#.*bypass"  # adding labeled bypass
  # Hook security
  "^-.*DENIED:"                  # removing denial messages
  "^-.*trap.*ERR"                # removing fail-closed trap
  # docker-compose.yml
  "^-.*entrypoint.sh"            # removing entrypoint mapping
  "^\\+.*privileged"             # adding privileged mode
  # New container entrypoint / gate security
  "^-.*lint-gate-entrypoint"     # removing lint gate entrypoint
  "^-.*agent-cli.*entrypoint"    # removing agent-cli entrypoint
  "^-.*tf-safe"                  # removing terraform safety wrapper
  "^-.*chmod.*0700"              # weakening restricted permissions
  "^-.*_tf_exec_internal"        # removing terraform exec safety function
)

for f in "${MODIFIED[@]}"; do
  # Filter to content lines only: strip diff headers (---, +++, @@) to
  # prevent false positives from "--- a/file" matching "^-.*" patterns.
  DIFF=$(git diff "$DIFF_BASE" -- "$f" 2>/dev/null | grep -vE '^(---|\+\+\+|@@|diff|index)' || true)
  [[ -z "$DIFF" ]] && continue
  for pattern in "${SUSPICIOUS_PATTERNS[@]}"; do
    if printf '%s\n' "$DIFF" | grep -qE "$pattern"; then
      MATCHED_LINE=$(printf '%s\n' "$DIFF" | grep -E "$pattern" | head -1)
      echo "DENIED: security-weakening change detected in $f" >&2
      echo "Matched: $MATCHED_LINE" >&2
      echo "Commit the change via your terminal (not the agent) to proceed." >&2
      exit 2
    fi
  done
done

# Modified security files exist but no suspicious patterns matched — allow.
exit 0
