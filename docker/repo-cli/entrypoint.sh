#!/bin/bash
set -euo pipefail

# =============================================================================
# repo-cli entrypoint — command-restricted gateway for git/gh operations
# =============================================================================

# --- Section 1: Git environment hardening (Req-017) -------------------------
# These env vars take precedence over .git/config values, closing the
# shared-workspace hook/config/pager RCE vector.
export GIT_CONFIG_COUNT=2
export GIT_CONFIG_KEY_0=core.hooksPath
export GIT_CONFIG_VALUE_0=/dev/null
export GIT_CONFIG_KEY_1=core.pager
export GIT_CONFIG_VALUE_1=cat
export GIT_PAGER=cat
export GIT_EDITOR=cat
export GIT_ASKPASS=true
export GIT_SSH_COMMAND="ssh -F /dev/null"
export GIT_CONFIG_NOSYSTEM=1
export GIT_TERMINAL_PROMPT=0

# --- Section 2: Transparent gh auth (Req-003) --------------------------------
if [ -n "${GH_TOKEN:-}" ]; then
  gh auth setup-git 2>/dev/null || true
fi

# --- Section 3: Dangerous flag scanner (reused by git and gh) ----------------
check_dangerous_flags() {
  for arg in "$@"; do
    case "$arg" in
      -c|--exec|--exec=*|--config-env|--config-env=*|--exec-path|--exec-path=*|--upload-pack|--upload-pack=*|--receive-pack|--receive-pack=*|--config|--config=*|--template|--template=*)
        echo "DENIED: flag '$arg' is not allowed — potential code-execution vector." >&2
        exit 1
        ;;
    esac
  done
}

# --- Section 4: Command dispatch ---------------------------------------------
case "${1:-}" in
  git)
    # git subcommand allowlist (Req-002)
    case "${2:-}" in
      push|pull|clone|fetch|add|status|checkout|diff|log|commit|rebase|rev-parse|ls-files|stash|sparse-checkout|--version)
        ;;
      *)
        echo "DENIED: git subcommand '${2:-}' is not allowed." >&2
        exit 1
        ;;
    esac
    check_dangerous_flags "$@"
    ;;
  gh)
    # gh subcommand allowlist (Req-002)
    case "${2:-}" in
      search|api|repo|pr|run|--version)
        ;;
      *)
        echo "DENIED: gh subcommand '${2:-}' is not allowed. Use the entrypoint's transparent auth instead of 'gh auth'." >&2
        exit 1
        ;;
    esac
    # gh passthrough flag scanning — catches `gh repo clone <repo> -- -c core.sshCommand="evil"`
    check_dangerous_flags "$@"
    ;;
  sparse-clone.sh)
    ;;
  *)
    echo "DENIED: command '${1:-}' is not allowed in repo-cli. Only git, gh, and sparse-clone.sh are permitted." >&2
    exit 1
    ;;
esac

exec "$@"
