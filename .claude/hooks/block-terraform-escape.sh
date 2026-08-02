#!/usr/bin/env bash
# PreToolUse hook: block dangerous Terraform/Docker patterns.
#
# Blocked patterns:
#   1. Any reference to _tf_exec_internal (bypass task wrapper)
#   2. --entrypoint combined with infra-terraform (shell escape)
#   3. --user/-u on infra-terraform: allowlist validated per-token
#      (only "agent" or "agent:agent" permitted; all others denied
#       including root, numeric UIDs, variables, and unknown names)
#
# Exit 2 + stderr = deny the tool call.
# Exit 0 + no output = allow.
set -uo pipefail

# Failure-closed: any unexpected error denies the tool call.
trap 'echo "DENIED: hook error — failing closed." >&2; exit 2' ERR

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

# Normalize multiline commands: collapse backslash-continuations and bare
# newlines into spaces so patterns cannot be split across lines.
COMMAND=$(printf '%s' "$COMMAND" | tr '\n' ' ')

# 1. Block direct access to _tf_exec_internal containers (unconditional).
if printf '%s' "$COMMAND" | grep -qF '_tf_exec_internal'; then
  echo "DENIED: direct access to _tf_exec_internal containers is not allowed." >&2
  exit 2
fi

# Remaining checks are docker-specific; skip non-docker commands.
if ! printf '%s' "$COMMAND" | grep -qiF 'docker'; then
  exit 0
fi

# 2. Block entrypoint override on infra-terraform (any value, including variables).
#    Anchored with word boundary to avoid false positives on unrelated flags.
if printf '%s' "$COMMAND" | grep -qE '(^|[[:space:]])--entrypoint([[:space:]=]).*infra-terraform|infra-terraform.*--entrypoint([[:space:]=])'; then
  echo "DENIED: --entrypoint override on infra-terraform is not allowed." >&2
  exit 2
fi

# 3. Allowlist --user/-u on infra-terraform: only "agent" or "agent:agent".
#    Tokenize the command, iterate ALL --user/-u flags, and validate each value.
#    This prevents multi-flag bypass (Docker uses the last flag) and multi-space
#    evasion. Any non-allowed value on ANY flag position triggers denial.
if printf '%s' "$COMMAND" | grep -qF 'infra-terraform'; then
  # Normalize: collapse all whitespace runs into single spaces, strip quotes
  NORMALIZED=$(printf '%s' "$COMMAND" | tr '\t' ' ' | sed 's/  */ /g' | tr -d "\"'")
  # Tokenize into array
  read -ra TOKENS <<< "$NORMALIZED"
  EXPECT_USER_VAL=false
  for i in "${!TOKENS[@]}"; do
    TOK="${TOKENS[$i]}"
    if [[ "$EXPECT_USER_VAL" == true ]]; then
      # This token is the value for a preceding --user/-u flag
      if ! printf '%s' "$TOK" | grep -qE '^agent(:agent)?$'; then
        echo "DENIED: --user '$TOK' on infra-terraform is not allowed. Only '--user agent' is permitted." >&2
        exit 2
      fi
      EXPECT_USER_VAL=false
      continue
    fi
    # --user=VAL or -u=VAL (= separator)
    if printf '%s' "$TOK" | grep -qE '^(--user|-u)='; then
      VAL="${TOK#*=}"
      if ! printf '%s' "$VAL" | grep -qE '^agent(:agent)?$'; then
        echo "DENIED: --user '$VAL' on infra-terraform is not allowed. Only '--user agent' is permitted." >&2
        exit 2
      fi
    # -uVAL (short flag, no separator)
    elif printf '%s' "$TOK" | grep -qE '^-u.+'; then
      VAL="${TOK#-u}"
      if ! printf '%s' "$VAL" | grep -qE '^agent(:agent)?$'; then
        echo "DENIED: --user '$VAL' on infra-terraform is not allowed. Only '--user agent' is permitted." >&2
        exit 2
      fi
    # --user VAL or -u VAL (space separator — next token is the value)
    elif [[ "$TOK" == "--user" || "$TOK" == "-u" ]]; then
      EXPECT_USER_VAL=true
    fi
  done
  # Dangling --user/-u with no value
  if [[ "$EXPECT_USER_VAL" == true ]]; then
    echo "DENIED: --user with no value on infra-terraform." >&2
    exit 2
  fi
fi

exit 0
