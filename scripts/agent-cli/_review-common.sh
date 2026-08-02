#!/usr/bin/env bash
# _review-common.sh — shared helpers for reviewer wrappers.
# Sourced (not executed) by gemini-review.sh, codex-review.sh, copilot-review.sh
# and by their container-mode wrappers.

# Single source of truth for REVIEW_TYPE enum.
# Adding a type requires: (1) add here; (2) add the template under
# .claude/prompts/reviewer/<type>.md; (3) add the stem to the
# TEMPLATE_NAMES tuple in tests/scripts/test_reviewer_templates.py
# (used for parametrized test coverage and cross-checked against the
# lint script's auto-discovery). scripts/lint_reviewer_templates.py
# auto-enumerates TEMPLATE_NAMES from the template directory
# (TODO-0103), so it does NOT require editing — but the test tuple
# still does, and drift between it and the lint-side discovery fails
# test_lint_template_names_matches_committed_templates.
REVIEW_TYPES=(plan spec diff epic spec-req-verification)

# Validate REVIEW_TYPE env var; echo error + exit 1 if invalid or empty.
_review_validate_type() {
  local t="${REVIEW_TYPE:-}"
  if [ -z "$t" ]; then
    echo "Error: REVIEW_TYPE is required (one of: ${REVIEW_TYPES[*]})" >&2
    return 1
  fi
  local ok=0
  for cand in "${REVIEW_TYPES[@]}"; do
    if [ "$t" = "$cand" ]; then ok=1; break; fi
  done
  if [ "$ok" != "1" ]; then
    echo "Error: REVIEW_TYPE '$t' not in {${REVIEW_TYPES[*]}}" >&2
    return 1
  fi
  return 0
}

# Portable realpath (prefer realpath(1), fall back to python3).
_review_realpath() {
  if command -v realpath >/dev/null 2>&1; then
    realpath -- "$1" 2>/dev/null
  else
    python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$1" 2>/dev/null
  fi
}

# Validate DIFF_FILE env var: non-empty, exists, non-zero size, realpath
# contained under $PWD/tmp/ OR $PWD/agent-review/.
_review_validate_diff_file() {
  local p="${DIFF_FILE:-}"
  if [ -z "$p" ]; then
    echo "Error: DIFF_FILE is required (path to subject artifact under tmp/ or agent-review/)" >&2
    return 1
  fi
  if [ ! -f "$p" ] || [ ! -s "$p" ]; then
    echo "Error: DIFF_FILE '$p' is missing or empty" >&2
    return 1
  fi
  local real tmp_real ar_real
  real=$(_review_realpath "$p")
  tmp_real=$(_review_realpath "$PWD/tmp")
  ar_real=$(_review_realpath "$PWD/agent-review")
  if [ -z "$real" ] || [ -z "$tmp_real" ]; then
    echo "Error: failed to resolve realpath for DIFF_FILE or tmp/" >&2
    return 1
  fi
  # When agent-review/ doesn't exist on disk, _review_realpath returns an
  # empty string on some platforms. An empty ar_real would make the case
  # arm "${ar_real}"/* degrade to "/*", matching ANY absolute path and
  # defeating the containment guard. Substitute a sentinel that cannot
  # collide with any realpath result.
  if [ -z "$ar_real" ]; then
    ar_real="/__ABSENT_AGENT_REVIEW__"
  fi
  case "$real" in
    "${tmp_real}"/*) return 0 ;;
    "${ar_real}"/*) return 0 ;;
  esac
  echo "Error: DIFF_FILE '$real' must resolve under '${tmp_real}/' or '${ar_real}/'" >&2
  return 1
}

# Sanitize DIFF_FILE contents to a new sanitized path; echo the sanitized path.
# Preserves TAB (\t, 0x09), LF (\n, 0x0a), and CR (\r, 0x0d); strips all
# other C0 control bytes (NUL..BS, VT, FF, SO..US). ANSI CSI escape
# sequences (ESC + [ + params + letter) are also stripped.
# Args: $1=reviewer-name (gemini|codex|copilot), $2=round-or-session-id
#
# Implementation note: BSD sed (macOS default) does not honor `\xNN`
# byte ranges inside character classes — `[\x00-\x08]` is parsed as
# the 5-character set {\, x, 0, 0, -}, not a byte range. We use `tr`
# with portable octal ranges (\000-\010, \013-\014, \016-\037) for the
# control-byte strip, and a `sed` pass with a literal ESC byte via
# bash `$'\x1b'` (ANSI-C quoting) for the ANSI escape strip. Both
# forms are portable across GNU (coreutils) and BSD toolchains.
#
# Pipe order is LOAD-BEARING: `sed` MUST run first, before `tr`. The
# `tr` control-byte range \016-\037 (14-31) includes ESC (\033=27),
# so running `tr` first would delete ESC bytes before `sed` could
# match the `<ESC>[params<letter>` CSI pattern — leaving `[31m`
# bracket/params/letter residue in the output. Running `sed` first
# removes the full CSI sequence; `tr` then strips orphan ESCs that
# were not part of a matched CSI (e.g., OSC/DCS starts) along with
# the remaining C0 controls.
# Anchoring note (TODO-0094, TODO-0097): both helpers below are
# CWD-sensitive by construction (they write/read tmp/<name>.txt and
# .claude/prompts/reviewer/<type>.md as repo-root-relative paths).
# When invoked from a nested subdirectory, the resulting paths are
# wrong. Both functions are always consumed via command substitution
# ($(...)), so any `cd` inside them is scoped to the subshell and
# cannot leak into the caller's CWD — this makes anchoring safe.
#
# Both helpers echo an ABSOLUTE path when anchored (inside a git
# worktree) so the returned value remains valid after the `$(...)`
# subshell exits and the caller's CWD is restored. Echoing a
# relative path would break the cross-directory invariant: the
# sanitized file lands at ${top}/tmp/... but a nested-CWD caller
# would read ${PWD}/tmp/... (a different path). Only the non-worktree
# fallback echoes a relative path; that branch is only hit by
# fixture-based tests whose scratch CWD has no `.git` ancestor.
_review_sanitize_subject() {
  local reviewer="$1"
  local suffix="$2"
  # Resolve DIFF_FILE before any cd so a relative DIFF_FILE supplied
  # from the caller's original CWD still points at the right file
  # after we anchor to repo root. Hard-fail on realpath failure
  # (rather than silently falling through to a possibly-relative
  # path) because _review_validate_diff_file is assumed to have run
  # first and rejected unresolvable paths; reaching here with empty
  # realpath is an invariant violation, not a recoverable state.
  local diff_abs
  diff_abs=$(_review_realpath "$DIFF_FILE")
  if [ -z "$diff_abs" ]; then
    echo "Error: _review_sanitize_subject could not resolve DIFF_FILE='$DIFF_FILE' — validation should have caught this" >&2
    return 1
  fi
  local top out
  if top=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$top" ]; then
    cd "$top" || {
      echo "Error: _review_sanitize_subject failed to cd to repo toplevel '$top'" >&2
      return 1
    }
    out="${top}/tmp/${reviewer}-subject-sanitized-${suffix}.txt"
  else
    out="tmp/${reviewer}-subject-sanitized-${suffix}.txt"
  fi
  mkdir -p tmp
  LC_ALL=C sed -E $'s/\x1b\\[[0-9;]*[a-zA-Z]//g' < "$diff_abs" \
    | LC_ALL=C tr -d '\000-\010\013\014\016-\037' > "$out"
  echo "$out"
}

# Resolve the template path for the validated REVIEW_TYPE.
# Anchored to repo root (absolute path) when invoked inside a git
# worktree so callers at a nested CWD still get a valid path;
# callers CANNOT influence which template file is loaded (the
# <type>.md family is hardcoded to .claude/prompts/reviewer/).
# Falls back to a CWD-relative path outside a worktree so
# fixture-based tests work without a real repo on disk.
_review_template_path() {
  local top
  if top=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$top" ]; then
    echo "${top}/.claude/prompts/reviewer/${REVIEW_TYPE}.md"
  else
    echo ".claude/prompts/reviewer/${REVIEW_TYPE}.md"
  fi
}
