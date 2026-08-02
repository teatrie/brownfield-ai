#!/usr/bin/env bash
# agent-cli entrypoint — command allowlist dispatcher.
#
# Allowed commands: copilot-review, gemini-review, codex-review, preflight.
# No emergency bypass variable (intentional — commands are fixed).
# No --prompt-file validation: the task-driven wrapper contract carries
# REVIEW_TYPE + DIFF_FILE through the process environment (populated by
# scripts/agent-cli/cli-args-to-env.sh). Remaining argv is passed
# through to the underlying wrapper unchanged so flags like --round
# and --model still reach the target script.
#
# Exit 1 = unknown / missing command.
# Dispatches to /usr/local/bin/<cmd>.sh via exec.

set -euo pipefail

CMD="${1:-}"
shift || true

if [[ -z "$CMD" ]]; then
  echo "ERROR: no command specified. Allowed: copilot-review, gemini-review, codex-review, preflight" >&2
  exit 1
fi

case "$CMD" in
  copilot-review|gemini-review|codex-review|preflight)
    exec "/usr/local/bin/${CMD}.sh" "$@"
    ;;
  *)
    echo "ERROR: unknown command '$CMD'. Allowed: copilot-review, gemini-review, codex-review, preflight" >&2
    exit 1
    ;;
esac
