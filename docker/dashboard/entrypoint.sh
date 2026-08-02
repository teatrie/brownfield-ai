#!/usr/bin/env bash
# Entrypoint gate for ledger-dashboard container.
# Only uvicorn is permitted — no bypass variable (intentional).
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "DENIED: no command specified." >&2
  exit 1
fi

case "$1" in
  uvicorn)
    exec "$@"
    ;;
  *)
    echo "DENIED: only 'uvicorn' is permitted in this container." >&2
    exit 1
    ;;
esac
