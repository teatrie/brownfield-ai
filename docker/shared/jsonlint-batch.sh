#!/usr/bin/env bash
set -euo pipefail
for f in "$@"; do
  jsonlint -q "$f" || exit 1
done
