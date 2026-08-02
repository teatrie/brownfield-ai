#!/usr/bin/env bash
# setup_codex_reviewer.sh — Provision the [profiles.reviewer] section
# in ~/.codex/config.toml from the canonical source.
#
# Canonical source: docker/agent-cli/codex-config.toml
#
# Three code paths:
#   1. Fresh install: copy canonical file directly
#   2. Append: existing config without [profiles.reviewer] — append block
#   3. Update: existing config with [profiles.reviewer] — delete old, append new
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANONICAL="${SCRIPT_DIR}/../docker/agent-cli/codex-config.toml"
CONFIG_DIR="${HOME}/.codex"
CONFIG_FILE="${CONFIG_DIR}/config.toml"

TEMP_FILE="${SCRIPT_DIR}/../tmp/codex-config-cleaned.toml"

mkdir -p "${CONFIG_DIR}"

trap 'rm -f "$TEMP_FILE"' EXIT

if [ ! -f "$CONFIG_FILE" ]; then
  # Path 1: Fresh install — copy canonical file directly
  cp "$CANONICAL" "$CONFIG_FILE"
elif ! grep -q '^\[profiles\.reviewer\]' "$CONFIG_FILE"; then
  # Path 2: Existing config without [profiles.reviewer] — append block
  printf '\n' >> "$CONFIG_FILE"
  cat "$CANONICAL" >> "$CONFIG_FILE"
else
  # Path 3: Existing config with [profiles.reviewer] — delete old, append new
  cp "$CONFIG_FILE" "${CONFIG_FILE}.bak"

  # Delete the old [profiles.reviewer] section using awk (NOT sed — sed range
  # deletion is inclusive and would eat the next profile header).
  # This awk script sets skip=1 when it sees [profiles.reviewer], sets skip=0
  # when it sees any other [ header that isn't [profiles.reviewer (preserving
  # [profiles.reviewer.instructions] in the skip zone but NOT unrelated
  # profiles like [profiles.reviewer_backup]), and prints lines where
  # skip is not set.
  mkdir -p "$(dirname "$TEMP_FILE")"
  awk '/^\[profiles\.reviewer\]/{skip=1} /^\[/{if(!/^\[profiles\.reviewer[\].]/)skip=0} !skip' \
    "$CONFIG_FILE" > "$TEMP_FILE"
  mv "$TEMP_FILE" "$CONFIG_FILE"

  printf '\n' >> "$CONFIG_FILE"
  cat "$CANONICAL" >> "$CONFIG_FILE"
fi

# Verify the section is present after all code paths
if ! grep -q '^\[profiles\.reviewer\]' "$CONFIG_FILE"; then
  echo "ERROR: [profiles.reviewer] not found in ${CONFIG_FILE} after install" >&2
  exit 1
fi

echo "Codex reviewer profile installed at ${CONFIG_FILE}"

# Post-setup hints
if ! command -v codex >/dev/null 2>&1; then
  echo "Install Codex CLI: npm install -g @openai/codex"
fi

if [ -z "${OPENAI_API_KEY:-}" ] && [ ! -s "${HOME}/.codex/auth.json" ]; then
  echo "Set OPENAI_API_KEY or run 'codex login' for OAuth"
fi
