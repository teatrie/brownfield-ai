#!/usr/bin/env bash
# PreToolUse hook: block Bash command patterns that trigger sandbox
# expansion/process-substitution prompts. Patterns are anchored to command
# positions (start-of-string or after ; && || |) so that quoted arguments
# to grep/rg/awk don't false-positive.
#
# Quote-stripping note: three rule classes operate over two evaluation
# buffers. The command-position rules (for/while/env-var-prefix/$?/FILES/
# echo-var) scan the newline-normalized raw buffer (`COMMAND_NORMALIZED`).
# Rules whose trigger tokens are NEVER shell-expanded inside any quoting
# form (process substitution `<(`, leading printf/tee, bash grep/rg/find)
# scan `COMMAND_ALL_STRIPPED` — both single- and double-quoted literals
# removed — so literal occurrences inside quoted argument text do not
# trip the rule. Rules whose trigger tokens ARE shell-expanded inside
# double quotes (`$(...)` and backticks) scan `COMMAND_NORMALIZED`
# directly: stripping any form of quoting before these checks opens a
# nested-quote bypass where the outer `"..."` renders the inner `'...'`
# literal at the token-parse level but bash still expands `$(...)` /
# backticks at runtime (e.g., `echo " '$(evil)' "`). The accepted
# cosmetic false positive is `echo '$(date)'` — agents should use the
# native Grep tool for content searches that need literal metachars.
#
# Rule ordering note: the `$(...)`, backtick, and `<(...)` rules run
# BEFORE the `git commit` / `task git:commit` fast-path bypass. This is
# load-bearing: bash tokenizes argv AFTER the PreToolUse hook returns,
# so a commit body containing `$()`, backticks, or `<(...)` inside
# double quotes (e.g. `git commit -m "msg $(evil)"`) or unquoted as an
# extra argv (e.g. `git commit -m <(evil)`) would be expanded by bash
# at execution time even though the hook had already approved the
# command. Running the code-execution-vector rules before the commit
# bypass ensures any command containing those metachars — including
# inside a commit message body — is rejected before the fast-path can
# exit. Commit messages do not legitimately need runtime `$()`,
# backticks, or `<(...)` — agents precompute dynamic values and pass
# literal strings.
#
# Why `<(...)` belongs with the other two pre-bypass rules: the
# unquoted form `git commit -m <(evil)` is expanded by bash at argv
# tokenization time (same class as `$()`), so if the bypass ran first
# the subshell spawned by `<(evil)` would execute before git ever saw
# its argv. The quoted form (`git commit -m "msg <(evil)"`) stays safe
# because bash does not perform process substitution inside double
# quotes, and `COMMAND_ALL_STRIPPED` already ignores quoted content —
# so the rule continues to only fire on unquoted occurrences.
set -uo pipefail
trap 'echo "DENIED: hook error — failing closed." >&2; exit 2' ERR

INPUT=$(cat)
[[ -z "$INPUT" ]] && exit 0
if ! printf '%s' "$INPUT" | jq empty 2>/dev/null; then
  echo "DENIED: malformed hook input — failing closed." >&2
  exit 2
fi
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
[[ -z "$COMMAND" ]] && exit 0

# Normalize newlines to spaces so multi-line payloads cannot hide a denied
# command behind a leading line that matches an anchor (e.g. a multi-line
# `evil\ngit commit` slipping past the commit bypass).
COMMAND_NORMALIZED=$(printf '%s' "$COMMAND" | tr '\n' ' ')

# Quote-stripped buffer. Only one flavor now because the `$(...)` and
# backtick rules that previously consumed a single-quote-stripped buffer
# were moved back onto the raw `COMMAND_NORMALIZED` — see the header
# comment for the nested-quote bypass rationale.
#
# * COMMAND_ALL_STRIPPED — both single- and double-quoted literals
#   removed. Used for rules whose trigger tokens (`<(`, leading
#   printf/tee, bash grep/rg/find) are not valid shell expansions
#   inside ANY quoting form — they are parsed only at command-argument
#   positions outside quotes. Literal occurrences in quoted arguments
#   (e.g. `awk '/<(/{print}'`, `echo 'foo|grep bar'`) are safe to
#   strip regardless of quote style.
#
# This handling is imperfect — escaped quotes (`"a\"b"`), nested
# quotes, and concatenated quoting styles are not fully modeled. sed
# is permitted here because hook scripts are invoked BY the hook
# system, not through the agent's Bash tool.
COMMAND_ALL_STRIPPED=$(printf '%s' "$COMMAND_NORMALIZED" | sed -e "s/'[^']*'//g" -e 's/"[^"]*"//g')

# Command-position prefix: start-of-string or after a shell separator.
# Using [[:space:]]* (not \s) for BSD grep portability on macOS.
CMD_START='(^|[;&|][[:space:]]*|&&[[:space:]]*|\|\|[[:space:]]*)'

# $(...) command substitution triggers 'Unhandled node type: string' sandbox
# prompts when combined with JSON-literal arguments (e.g. the old
# `task ledger:save -- "$(cat tmp/body.md)" ...` workaround; prefer
# `task ledger:save -- --content-file tmp/body.md --fields ...`, which passes
# the path literally instead of substituting).
# Write intermediate output to a tmp/ file and pass the path, or precompute
# the value and pass it as an explicit literal. Use the RAW normalized
# buffer (no quote stripping): sed-based single-quote stripping lets
# `echo " '$(evil)' "` bypass the rule because the outer `"..."` renders
# the inner `'...'` literal only at the token-parse level — bash still
# expands `$(evil)` at runtime. Matching against the raw buffer closes
# this nested-quote bypass at the cost of one cosmetic false positive
# (`echo '$(date)'`), which is acceptable because the native Grep tool
# is the preferred path for content searches.
#
# This rule runs BEFORE the commit bypass: a commit message like
# `git commit -m "msg $(evil)"` would otherwise match the bypass
# pattern (the outer `"..."` contains no `|`) and be approved, yet
# bash would still expand `$(evil)` when it tokenizes argv after the
# hook returns. Running the raw-buffer code-execution rules first
# closes that nested-quote bypass for commit bodies.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE '\$\('; then
  echo "DENIED: '\$(...)' command substitution triggers 'Unhandled node type' sandbox prompts. Write intermediate output to tmp/ and pass the file path, or precompute and inline the literal value." >&2
  exit 2
fi

# Backtick command substitution — same class as $(...). Same raw-buffer
# policy: stripping any quote form opens the same nested-quote bypass
# (`echo " \`evil\` "`), so the rule scans COMMAND_NORMALIZED. Also
# runs before the commit bypass for the same argv-tokenization reason
# documented on the $(...) rule above.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qF '`'; then
  echo "DENIED: backtick command substitution triggers sandbox prompts. Use a tmp/ file for intermediate values." >&2
  exit 2
fi

# Process substitution <(...) or >(...). No anchor — these are unambiguous.
# Use the all-stripped buffer: process substitution is not expanded inside
# either single or double quotes — it is parsed only at command-argument
# positions — so literal '<(' inside a quoted string (e.g.
# `awk '/<(/{print}' file`, `echo "<(literal)"`) is safe.
#
# This rule runs BEFORE the commit bypass for the same
# argv-tokenization reason documented on the $(...) and backtick rules
# above: the unquoted form `git commit -m <(evil)` would otherwise
# match the bypass regex (every char in the body matches `[^|]`) and
# be approved, yet bash would spawn the `<(evil)` subshell at argv
# tokenization time — before git sees its arguments. Matching
# COMMAND_ALL_STRIPPED keeps the quoted case (`-m "msg <(literal)"`)
# allowed because bash does not perform process substitution inside
# double quotes and the stripped buffer removes the quoted occurrence
# entirely.
if printf '%s' "$COMMAND_ALL_STRIPPED" | grep -qE '[<>]\('; then
  echo "DENIED: '<(' or '>(' triggers process_substitution sandbox prompt. Use temporary files instead." >&2
  exit 2
fi

# Skip all checks for git commit commands — commit message bodies contain
# arbitrary text that trips every pattern below. True start-of-string
# anchor (NOT CMD_START): the bypass fires only when the entire invocation
# begins with `git commit` or `task git:commit`, so compound/multi-line
# prefixes (`foo && git commit`, `evil\ngit commit`) cannot escape the
# deny rules. The pattern also end-anchors to reject trailing pipeline
# suffixes (`git commit -m ok | grep foo`): a trailing `| <cmd>` would
# let `<cmd>` escape every downstream deny rule because the bypass exits
# before they run. The regex allows any body text up to end-of-string
# but forbids an unquoted `|` anywhere in the body — pipes inside a
# commit-message argument must be safely quoted (`-m "has | pipe"`).
#
# Ordering note: bash tokenizes argv only AFTER the PreToolUse hook
# returns, so any `$()` / backticks inside a double-quoted commit body
# would still be expanded at execution time. The two raw-buffer rules
# above run FIRST and reject such bodies before this fast-path can
# exit, closing the nested-quote code-execution vector for commit
# messages.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE "^[[:space:]]*(task[[:space:]]+git:commit|git[[:space:]]+commit)[[:space:]]([^|]|\"[^\"]*\"|'[^']*')*$"; then
  exit 0
fi

# Shell for-loops at command position.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE "${CMD_START}for[[:space:]]+[a-zA-Z_][a-zA-Z_0-9]*[[:space:]]+in[[:space:]]"; then
  echo "DENIED: shell for-loops trigger simple_expansion prompts. Use the Write tool to create files individually, or use explicit chained commands without shell variables." >&2
  exit 2
fi

# Shell while-loops at command position.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE "${CMD_START}while[[:space:]].*;[[:space:]]*do\b"; then
  echo "DENIED: shell while-loops trigger simple_expansion prompts. Use the Write tool for multi-file operations." >&2
  exit 2
fi

# $? only when used with echo/printf (the pattern that trips the sandbox).
# A literal '$?' inside a grep/rg argument is intentionally allowed.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE "${CMD_START}(echo|printf)[[:space:]][^|;&]*\\\$\\?"; then
  echo "DENIED: 'echo/printf ... \$?' triggers simple_expansion sandbox prompt. The Bash tool reports exit codes natively — run the command directly." >&2
  exit 2
fi

# FILES="a b ..." inline assignment at command position.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE "${CMD_START}FILES=\"[^\"]*[[:space:]][^\"]*\""; then
  echo "DENIED: multi-file FILES=\"...\" triggers sandbox prompt. Stage files with 'task git:add' then use 'task lint:staged' / 'task test:staged'." >&2
  exit 2
fi

# printf/tee only when invoked as the leading command, not inside quoted args
# to other commands (e.g. `grep 'printf' file.py` remains allowed). Use the
# all-stripped buffer — printf/tee tokens inside either single or double
# quotes are arguments to some outer command, not a leading invocation.
if printf '%s' "$COMMAND_ALL_STRIPPED" | grep -qE "${CMD_START}(printf|tee)[[:space:]]"; then
  echo "DENIED: leading 'printf'/'tee' invocations trigger interactive behaviors and sandbox prompts. Use the Write tool or native test/lint commands instead." >&2
  exit 2
fi

# echo "VAR=$VAR" at command position.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE "${CMD_START}echo[[:space:]]+[\"']?[a-zA-Z_][a-zA-Z_0-9]*=\\\$[a-zA-Z_][a-zA-Z_0-9]*"; then
  echo "DENIED: echo \"VAR=\$VAR\" triggers simple_expansion sandbox prompt. Use the Write tool to create files or export variables natively." >&2
  exit 2
fi

# Bash grep/rg/find require per-command permission approval and have direct
# native-tool replacements (Grep, Glob). Block at command position. sed/awk
# mutation is already covered by block-container-escape.sh. Use the
# all-stripped buffer so a literal 'grep'/'rg'/'find' inside either
# single- or double-quoted argument text (e.g. `echo 'foo|grep bar'`,
# `echo "find pattern"`) does not fire.
if printf '%s' "$COMMAND_ALL_STRIPPED" | grep -qE "${CMD_START}(grep|rg|find)[[:space:]]"; then
  echo "DENIED: 'grep'/'rg'/'find' via Bash triggers permission prompts. Use the native Grep (content search) or Glob (file-pattern match) tools instead." >&2
  exit 2
fi

# Inline env-var prefix before 'task' creates a permission matcher token that
# does not match 'Bash(task *)' — each distinct env-var set produces its own
# 'Yes, and don't ask again for...' prompt. Force agent to pass values via
# CLI_ARGS ('task <target> -- KEY=val') and route them through the
# cli-args-to-env.sh shim.
#
# See docs/tool_chain.md (section: "'task' Invocation Convention: CLI_ARGS
# over Env-Var Prefix") for the full convention, the shim's key/value
# allowlist, and the procedure for adding a new allowlisted key or target.
if printf '%s' "$COMMAND_NORMALIZED" | grep -qE "${CMD_START}[A-Za-z_][A-Za-z_0-9]*=[^[:space:]]+([[:space:]]+[A-Za-z_][A-Za-z_0-9]*=[^[:space:]]+)*[[:space:]]+task[[:space:]]"; then
  echo "DENIED: inline env-var prefix before 'task' ('VAR=val task target') creates per-invocation permission tokens distinct from 'Bash(task *)'. Rewrite as: task <target> -- KEY=val KEY=val, routed through scripts/agent-cli/cli-args-to-env.sh. See docs/tool_chain.md section \"'task' Invocation Convention: CLI_ARGS over Env-Var Prefix\" for the full convention and the procedure for extending the key allowlist or adding a new target." >&2
  exit 2
fi

exit 0
