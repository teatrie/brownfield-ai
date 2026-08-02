#!/usr/bin/env bash
# preflight.sh — Check CLI binary presence and token availability.
# Usage: preflight.sh [copilot|gemini|codex]
#   No argument checks all agents.
# Exit 0 if at least one CLI is fully available (binary + token).
# Exit 1 if none.

set -euo pipefail

AGENT="${1:-all}"

# -------------------------------------------------------------------
# Helper: emit a single agent's JSON fragment {"cli":bool,"token":bool}
# -------------------------------------------------------------------
check_agent() {
  local name="$1"
  local binary="$2"
  local token_var="$3"

  local cli_ok="false"
  local token_ok="false"

  if command -v "$binary" > /dev/null 2>&1; then
    cli_ok="true"
  fi

  # Indirect expansion (bash 3+) to read the named env var safely
  local token_val="${!token_var:-}"
  if [ -n "$token_val" ]; then
    token_ok="true"
  fi

  printf '"%s":{"cli":%s,"token":%s}' \
    "$name" "$cli_ok" "$token_ok"
}

# -------------------------------------------------------------------
# Determine which agents to check
# -------------------------------------------------------------------
case "$AGENT" in
  copilot)
    AGENTS=("copilot")
    ;;
  gemini)
    AGENTS=("gemini")
    ;;
  codex)
    AGENTS=("codex")
    ;;
  all)
    AGENTS=("copilot" "gemini" "codex")
    ;;
  *)
    echo "Usage: $0 [copilot|gemini|codex]" >&2
    exit 1
    ;;
esac

# -------------------------------------------------------------------
# Resolve binary name and token env-var name per agent.
# Case statements for bash 3.2 compatibility (no declare -A).
# -------------------------------------------------------------------
binary_for() {
  case "$1" in
    copilot) echo "copilot" ;;
    gemini)  echo "gemini"  ;;
    codex)   echo "codex"   ;;
    *) echo "ERROR: unknown agent '$1'" >&2; return 1 ;;
  esac
}

token_var_for() {
  case "$1" in
    copilot) echo "COPILOT_GITHUB_TOKEN" ;;
    gemini)  echo "GEMINI_API_KEY"       ;;
    codex)   echo "OPENAI_API_KEY"       ;;
    *) echo "ERROR: unknown agent '$1'" >&2; return 1 ;;
  esac
}

# -------------------------------------------------------------------
# Build JSON output
# -------------------------------------------------------------------
json="{"
first=1
any_fully_available=0

for agent in "${AGENTS[@]}"; do
  if [ "$first" -eq 0 ]; then
    json+=","
  fi
  fragment=$(check_agent "$agent" \
    "$(binary_for "$agent")" "$(token_var_for "$agent")")
  json+="$fragment"
  first=0

  if [[ "$fragment" == *'"cli":true,"token":true'* ]]; then
    any_fully_available=1
  fi
done

json+="}"

echo "$json"

if [ "$any_fully_available" -eq 1 ]; then
  exit 0
else
  exit 1
fi
