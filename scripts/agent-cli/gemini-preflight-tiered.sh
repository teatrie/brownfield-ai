#!/usr/bin/env bash
# Gemini pre-flight: pick local vs container path. Authentication is
# NOT verified here — assumed valid if the local CLI is on PATH or, in
# the container path, if GEMINI_API_KEY is set. Auth failures surface
# at execution time and are reported to the user (interactive) or
# logged (headless).
#
# Modes:
#   local      — `gemini` is on PATH; invoke against the local CLI
#                (OAuth or API key, indistinguishable from preflight).
#   container  — no local `gemini`; GEMINI_API_KEY is set; invoke via
#                the agent-cli container.
#   none       — no local CLI and no API key; calling agent excludes
#                Gemini from the gate.
#
# Exit 0 on `local` or `container`; exit 1 on `none`.
#
# Caching: a successful result is written to PREFLIGHT_CACHE_FILE
# (default `tmp/.gemini-preflight-cache.json`) and reused for up to
# PREFLIGHT_CACHE_TTL_SECONDS (default 86400 = 24h). The `none` result
# is intentionally NOT cached so a newly-installed CLI is picked up
# immediately. Set PREFLIGHT_FORCE=1 to bypass the cache for one call,
# or `rm` the cache file to invalidate manually.
set -euo pipefail

CACHE_FILE="${PREFLIGHT_CACHE_FILE:-tmp/.gemini-preflight-cache.json}"
CACHE_TTL_SECONDS="${PREFLIGHT_CACHE_TTL_SECONDS:-86400}"

# Cross-platform mtime (GNU stat first, BSD/macOS stat fallback).
_file_age_seconds() {
  local path="$1"
  local mtime
  mtime=$(stat -c %Y "$path" 2>/dev/null || stat -f %m "$path" 2>/dev/null || echo 0)
  echo $(( $(date +%s) - mtime ))
}

# Cache hit: serve cached JSON if file exists, is non-empty, and is
# younger than TTL. Bypassed when PREFLIGHT_FORCE=1.
if [ "${PREFLIGHT_FORCE:-}" != "1" ] && [ -s "$CACHE_FILE" ]; then
  if [ "$(_file_age_seconds "$CACHE_FILE")" -lt "$CACHE_TTL_SECONDS" ]; then
    cat "$CACHE_FILE"
    exit 0
  fi
fi

# Compute fresh result.
if command -v gemini >/dev/null 2>&1; then
  result='{"mode":"local","gemini":{"cli":true}}'
elif [ -n "${GEMINI_API_KEY:-}" ]; then
  result='{"mode":"container","gemini":{"cli":false,"api_key":true}}'
else
  # Do NOT cache `none` — re-check every call so a newly-installed CLI
  # or a freshly-set API key is picked up without manual invalidation.
  printf '{"mode":"none","gemini":{"cli":false,"api_key":false}}\n'
  exit 1
fi

# Atomic cache write (best-effort — never fails the script). Write to
# a sibling tmp file then rename so a partial write can never be
# observed by a concurrent reader.
mkdir -p "$(dirname "$CACHE_FILE")" 2>/dev/null || true
tmp_cache="${CACHE_FILE}.$$.tmp"
if printf '%s\n' "$result" > "$tmp_cache" 2>/dev/null; then
  if ! mv "$tmp_cache" "$CACHE_FILE" 2>/dev/null; then
    rm -f "$tmp_cache"
  fi
fi

printf '%s\n' "$result"
exit 0
