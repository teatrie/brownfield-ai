#!/usr/bin/env bash
# PreToolUse hook: block a NAMED, BACKGROUNDED, in-process Agent dispatch of a
# no-SendMessage agent type. Such a dispatch is promoted to a persistent
# in-process teammate that finishes its turn, goes idle, and — lacking the
# SendMessage tool — cannot relay its deliverable back to the caller. The result
# is stranded in the subagent transcript and the work must be re-run (pure token
# waste). See CLAUDE.md Principle 18 / docs/delegation_protocol.md §3.
#
# Exemptions (none of these strand, so all are allowed):
#   - run_in_background:false        → synchronous; result returns inline
#   - no name                        → unnamed background subagent returns via
#                                       its completion task-notification
#   - team_name set                  → agent-team tmux teammate: a full claude
#                                       process that DOES have SendMessage
#   - subagent_type claude / empty   → full-tools catch-all; has SendMessage
set -uo pipefail
trap 'echo "DENIED: hook error — failing closed." >&2; exit 2' ERR

INPUT=$(cat)
[[ -z "$INPUT" ]] && exit 0
if ! printf '%s' "$INPUT" | jq empty 2>/dev/null; then
  echo "DENIED: malformed hook input — failing closed." >&2
  exit 2
fi

# Matcher is "Agent", but re-check defensively so a mis-registration can't
# silently apply this to another tool.
TOOL=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')
[[ "$TOOL" != "Agent" ]] && exit 0

# NOTE: no `// empty` here — jq's `//` treats BOTH null AND false as absent,
# which would collapse run_in_background:false to "" and wrongly deny the
# (recommended) synchronous path. Read the raw value: "true"/"false"/"null".
BG=$(printf '%s' "$INPUT" | jq -r '.tool_input.run_in_background')
NAME=$(printf '%s' "$INPUT" | jq -r '.tool_input.name // empty')
TEAM=$(printf '%s' "$INPUT" | jq -r '.tool_input.team_name // empty')
SUBAGENT=$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // empty')

# Synchronous dispatch is always safe.
[[ "$BG" == "false" ]] && exit 0
# Unnamed background subagents complete and return via task-notification.
[[ -z "$NAME" ]] && exit 0
# tmux teammates (agent-team) are full claude processes with SendMessage.
[[ -n "$TEAM" ]] && exit 0

# SendMessage-capable subagent types (safe to name+background). The default
# agent (empty subagent_type) resolves to "claude", which has the full toolset.
# EXTEND this allowlist if a future custom agent is granted SendMessage.
case "$SUBAGENT" in
  ""|claude) exit 0 ;;
esac

# Everything else is a restricted custom agent type with no SendMessage.
echo "DENIED: subagent_type '$SUBAGENT' has no SendMessage tool, so a NAMED background dispatch becomes a persistent in-process teammate that idles and cannot relay its result back (CLAUDE.md Principle 18). Fix: set run_in_background:false for a synchronous dispatch — the result returns inline, and multiple synchronous Agent calls in one message still run in parallel. (Or drop 'name' for an unnamed background subagent awaited via task-notification; or use agent-team tmux teammates via team_name for true background parallelism.)" >&2
exit 2
