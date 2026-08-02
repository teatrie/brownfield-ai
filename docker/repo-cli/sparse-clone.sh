#!/bin/bash
set -euo pipefail

# =============================================================================
# sparse-clone.sh — sparse-checkout clone for repo-cli
# Accepts ORG/REPO and SPARSE_PATH with strict input validation (Req-004).
# =============================================================================

if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
  echo "Usage: sparse-clone.sh ORG/REPO SPARSE_PATH" >&2
  exit 1
fi

ORG_REPO="$1"
SPARSE_PATH="$2"

# Validate ORG_REPO: only alphanumeric, dots, hyphens, underscores, and one slash
if ! echo "$ORG_REPO" | grep -qE '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$'; then
  echo "ERROR: invalid ORG/REPO format: '$ORG_REPO'" >&2
  echo "Must match: ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$" >&2
  exit 1
fi

# Validate SPARSE_PATH: strict allowlist (no .., no option injection)
if ! echo "$SPARSE_PATH" | grep -qE '^[A-Za-z0-9._/-]+$'; then
  echo "ERROR: invalid SPARSE_PATH format: '$SPARSE_PATH'" >&2
  echo "Must match: ^[A-Za-z0-9._/-]+$ (no spaces, no special chars, no ..)" >&2
  exit 1
fi

REPO_NAME="${ORG_REPO#*/}"
CLONE_DIR="/app/repos/${REPO_NAME}"

echo "Cloning ${ORG_REPO} (sparse: ${SPARSE_PATH}) into ${CLONE_DIR}..."

git clone --filter=blob:none --sparse -- "https://github.com/${ORG_REPO}.git" "$CLONE_DIR"
cd "$CLONE_DIR"
git sparse-checkout set -- "$SPARSE_PATH"

echo "Sparse clone complete: ${CLONE_DIR}"
