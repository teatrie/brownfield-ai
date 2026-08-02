#!/usr/bin/env bash
# PreToolUse hook: block direct Docker access to gated containers
# and block host Python execution.
#
# Gated containers: python-cli, pytest-cli, repo-cli, agent-cli, infra-lint, ledger-dashboard
#
# Blocked patterns:
#   1. docker [compose] run with gated containers
#   2. docker [compose] exec with gated containers
#   3. docker run with gated containers (standalone)
#   4. docker exec with gated containers
#   5. --entrypoint combined with gated containers
#   6. docker-compose (legacy v1) with gated containers
#   7. task sh:<gated-container>
#   8. Direct python3/python execution on the host
#   9. chmod +x on .py files (prevents shebanged script execution)
#  10. --user override on gated containers (only agent allowed)
#  11b. Block bash output redirection + tee/dd file writes (use Write tool)
#  11c. Block compound shell commands (;, &&, ||, &, \n) — break allowlist
#  11d. Block shell -c invocations and eval — bypass 11b/11c via quoted payload
#  11e. Block pipe/here-string/heredoc/stdin-redirect → shell — stdin-injection bypass
#  11f. Block source / . FILE builtins — execute Write-staged content in current shell
#  12. docker run with brownfield-ai/infra-lint image (bypass compose)
#  13. docker run with ledger-dashboard image (bypass compose)
#  14. Direct pytest/py.test execution on the host
#  15. Direct .venv/bin/* execution on the host
#
# KNOWN RESIDUAL BYPASSES (documented, accepted trade-offs):
# - `| "bash" arg1` at end-of-line (1b pattern 2) — quoted shell after pipe
#   where a single trailing arg appears before EOL. The closing-quote+EOL
#   anchor is required to keep 1b from false-positiving on legit doc-search
#   payloads that contain `| "bash"` as literal text. Narrow attack surface:
#   the agent must know to quote the shell name AND arrange a single arg
#   after the closing quote. See Pattern 1b. The R13 (TODO-0079)
#   PIPE_TO_BOTH_QUOTED_PATTERN inherits the same `[[:blank:]]*$` EOL-anchor
#   residual class — `| "sudo" "bash" > /dev/null`, `| "sudo" "bash" -s`,
#   and similar wrapper+shell+trailing-token forms slip past for the same
#   reason. Tracked as a follow-up TODO alongside the wrapper-class
#   extensions (TODO-0135).
# - `tee /dev/null /tmp/file` (and the QUOTED form `"tee" /dev/null /tmp/file`
#   post-trio R13) — tee with multiple file args where at least one is a
#   /dev/ carve-out. The strip / COMMAND_DEV_CARVED pre-strip handles the
#   /dev/ target cleanly but leaves trailing file args disconnected from
#   their preceding `tee`, so the post-strip `tee` check does not fire.
#   The quoted form imports this exact residual via the C4 (TODO-0078
#   follow-up) carve-out — parity with the unquoted residual is
#   intentional. Full correctness requires a proper tokenizer.
# - `$(( (a+b) << c ))` nested arithmetic with bit-shift — the arithmetic
#   pre-strip uses `[^)]*` which stops at the first `)`, so nested forms
#   fall through to the heredoc check and may false-positive (deny-side
#   residual — over-blocks a legitimate arithmetic expression). See Pattern 3.
# - `bash tmp/x.sh` / `(bash|sh|...) FILE` positional script arg — executing
#   an arbitrary script file directly. Not covered by the stdin-redirect
#   rule (Pattern 4 requires `<`). The `Bash(task *)` permission allowlist
#   blocks this in normal operation (only `task *` is allowed; `bash` /
#   `sh` / etc. are not). Accepted as a defense-in-depth gap because a
#   direct shell-file-arg block would conflict with agent patterns like
#   `bash scripts/X.sh` if the allowlist were ever relaxed.
# - `b"a"sh -c`, `t'e'e`, `s"o"urce` — interleaved partial quoting where
#   a quote pair sits mid-token. The dual-strip deletes the inner fragment
#   (`"a"`) leaving an unrecognizable binary name (`bsh`) that no regex
#   pattern matches. This is an architectural limit of regex-based
#   tokenization: bash first removes quotes, then executes the resulting
#   name, but a regex cannot model that two-phase evaluation without a
#   real shell parser. Accepted as a residual; closing it would require
#   replacing the scan layer with a proper tokenizer.
# - `grep source file` / `grep "." file` — unquoted false-positive on
#   SOURCE_PATTERN (11f). The blank-inclusive prefix class
#   `(^|[;&|[:blank:]`(])` (for parity with SHELL_C_PATTERN) allows
#   `grep`-style prefix patterns to false-positive when the search term
#   matches the builtin keyword. R5 tightened the RAW-QUOTED arm but
#   not the unquoted arm. Accepted deny-side residual; workaround is
#   `grep -- source FILE` or `task gh:search`.
#
# Exit 2 + stderr = deny the tool call.
# Exit 0 + no output = allow.
set -uo pipefail

# Failure-closed: any unexpected error denies the tool call.
trap 'echo "DENIED: hook error — failing closed." >&2; exit 2' ERR

INPUT=$(cat)
[[ -z "$INPUT" ]] && exit 0
# Fail-closed: reject malformed (non-JSON) input.
if ! printf '%s' "$INPUT" | jq empty 2>/dev/null; then
  echo "DENIED: malformed hook input — failing closed." >&2
  exit 2
fi
# Extract the "command" field. jq handles all JSON escaping correctly
# (unicode, nested quotes, backslashes). If "command" is absent, jq
# outputs nothing — the existing [[ -z "$COMMAND" ]] guard handles it.
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
[[ -z "$COMMAND" ]] && exit 0

# --- Shared: dual-pass quote-stripped forms -----------------------------------
# Many rules below need to inspect the command with quoted literals removed
# so that text-data like `grep "bash -c"` does not false-positive on the
# wrapper-detection rules. A single-order sed strip is evadable by mixed-
# quote payloads (Gemini R1 HIGH): `"safe ' " ; evil ; " ' "` pairs its `'`
# characters across the outer `"..."` boundary under single-first stripping,
# swallowing the `;` separators in the process. Running BOTH strip orderings
# and failing if EITHER leaves a dangerous token closes the bypass — an
# attacker would need both orderings to simultaneously cleanse the token,
# which requires two distinct valid-looking quote pairings covering the
# same operator.
STRIPPED_A=$(printf '%s' "$COMMAND" | sed "s/'[^']*'//g" | sed 's/"[^"]*"//g')
STRIPPED_B=$(printf '%s' "$COMMAND" | sed 's/"[^"]*"//g' | sed "s/'[^']*'//g")

# --- File edit block ---------------------------------------------------------
# Block structural editing via bash inline commands
if printf '%s' "$COMMAND" | grep -qE '(cat >|cat <<|sed -i)'; then
  echo 'DENIED: Do not use bash to edit files. Use the native Edit or Write tool.' >&2
  exit 2
fi

# 11b. Block bash output redirection to files (use Write tool).
# Strategy: on each of the two strip orderings, strip known-safe redirect
# patterns and flag any remaining `>`. Safe patterns:
#   - N>&M, >&M (file-descriptor duplication, e.g., 2>&1, >&2)
#   - >/dev/null, >>/dev/stdout, etc. (discard/passthrough targets; the
#     /dev/dtracehelper and /dev/autofs_nowait entries are Darwin-only
#     writable paths the sandbox already permits — harmless on Linux)
#   - &>/dev/null, &>>/dev/stdout, etc. (bash-specific combined stdout+stderr
#     redirect form — same carve-out as >/dev/*)
#   - >(...) process substitution (a residual bare `>` before the strip
#     still gets flagged, catching `cmd > >(tee log)` style redirects)
# Forces agents to use the native Write tool for artifact creation, which
# is auditable and works in headless mode without bash allowlist prompts.
for REDIR_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  REDIR_CHECK=$(printf '%s' "$REDIR_BASE" | sed -E '
    s/[0-9]*>&[0-9-]+//g;
    s/(&|[0-9]*)>>?[[:space:]]*\/dev\/(null|stdout|stderr|tty|dtracehelper|autofs_nowait)//g;
    s/>\([^)]*\)//g
  ')
  if printf '%s' "$REDIR_CHECK" | grep -qE '>'; then
    echo 'DENIED: Do not use bash output redirection (> or >>) to write files. Use the native Write tool for file creation.' >&2
    exit 2
  fi
done

# 11b-extended. Block `tee FILE` and `dd of=FILE` — alternative file-write
# surfaces that pipelines (|) can use to bypass the `>`/`>>` block above.
# Targets of the form /dev/null|stdout|stderr|tty remain allowed as
# discard/passthrough sinks. The Write tool is the mandated path for file
# creation (Gemini R1 MEDIUM finding).
# Dual-pass strip: iterate both STRIPPED_A (single-quote-first) and STRIPPED_B
# (double-quote-first) so mixed-quote payloads like `echo " ' " | tee pwn.txt`
# cannot bypass via a single-order quote-pairing (Gemini R3 HIGH).
for TEE_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  # R10 (Gemini R9 HIGH): pre-normalize inline backslash escapes so
  # `t\ee`, `te\e`, `\tee` cannot hide behind bash's quote-removal
  # phase. Mirrors the R4 shell-binary normalization step.
  TEE_NORMALIZED=$(printf '%s' "$TEE_BASE" | sed 's/\\\(.\)/\1/g')
  # R10 (Gemini R9 HIGH): admit optional path prefix on tee so the
  # benign `/usr/bin/tee /dev/null` strip still matches.
  TEE_STRIPPED=$(printf '%s' "$TEE_NORMALIZED" | sed -E 's/(^|[[:blank:]|])(\/?[^[:blank:]|;]*\/)?tee[[:blank:]]+(-[-a-zA-Z]+[[:blank:]]+)*\/dev\/[a-z0-9]+([[:blank:]]|$)/ /g')
  # Strip-scan design constraint (SAME as SHELL_C_PATTERN / EVAL_PATTERN):
  # TEE_BASE is derived from STRIPPED_A/STRIPPED_B which ERASE the entire
  # quoted token (both quote chars and content). So `tee "pwn.sh"` reduces
  # to `tee ` at EOL in the stripped form, indistinguishable from the
  # benign bare `tee` (stdout-only) FP. The EOL branch `([[:blank:]]|$)`
  # is load-bearing — it catches the stripped-attack form. Attempting to
  # tighten the suffix to `[[:blank:]]+[^[:blank:]]` allows the quoted-
  # filename attack to bypass (reproduced empirically in Gemini Flash
  # review, 2026-04-16). The FP class (`echo x | tee` at EOL with no
  # file arg) joins SHELL_C/EVAL as a documented xfail residual.
  # R10: admit optional path prefix on tee in the deny pattern.
  if printf '%s' "$TEE_STRIPPED" | grep -qE '(^|[[:blank:]|])(/?[^[:blank:]|;]*/)?tee([[:blank:]]|$)'; then
    echo 'DENIED: tee writing to a file bypasses the redirect (11b) block. Use the native Write tool, or redirect tee output to /dev/null, /dev/stdout, /dev/stderr, or /dev/tty.' >&2
    exit 2
  fi
done
for DD_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  # R10 (Gemini R9 HIGH): pre-normalize inline backslash escapes so
  # `\dd`, `d\d` cannot hide behind bash's quote-removal phase.
  DD_NORMALIZED=$(printf '%s' "$DD_BASE" | sed 's/\\\(.\)/\1/g')
  DD_STRIPPED=$(printf '%s' "$DD_NORMALIZED" | sed -E 's/of=\/dev\/(null|stdout|stderr|tty)([[:blank:]]|$)/\2/g')
  # R10: admit optional path prefix on dd in the deny pattern.
  if printf '%s' "$DD_STRIPPED" | grep -qE '(^|[[:blank:]|])(/?[^[:blank:]|;]*/)?dd([[:blank:]]+[^|&;[:blank:]]+)*[[:blank:]]+of='; then
    echo 'DENIED: dd with an of=FILE target bypasses the redirect (11b) block. Use the native Write tool.' >&2
    exit 2
  fi
done

# R13 (TODO-0078): close quoted tee/dd binary bypasses. TEE_STRIPPED/
# DD_STRIPPED scan operates on STRIPPED_A/STRIPPED_B which erase quoted
# tokens entirely, leaving ` pwn.sh` with no tee/dd anchor. These raw-
# quoted scans mirror the structure of SHELL_C_PATTERN_RAW_QUOTED (R4 +
# R11 inner-quote-path prefix) but anchor on tee/dd instead of -c. The
# quoted arms are SELF-PROTECTING: closing quote must immediately follow
# the binary name, so `grep "tee something"` (single quoted literal) does
# not match. Trailing content requirement (`[[:blank:]]+[^[:blank:]]` for
# tee, `[[:blank:]]+of=` for dd) prevents EOL false-positives.
#
# /dev/* carve-out (Codex P2 follow-up): pre-strip `"tee" /dev/<name>`
# and `of=/dev/(null|stdout|stderr|tty)` from the COMMAND before the
# raw-quoted scan, so `echo x | "tee" /dev/null` and `"dd" of=/dev/null`
# remain ALLOWED — parity with the unquoted TEE_STRIPPED/DD_STRIPPED
# carve-out at lines 149/170. ASYMMETRY: the tee arm uses `\/dev\/[a-z0-9]+`
# (the same permissive class TEE_STRIPPED:149 uses today, which admits
# `/dev/sda`, `/dev/null`, etc.); the dd arm uses the strict
# `\/dev\/(null|stdout|stderr|tty)` alternation (matches DD_STRIPPED:170).
# Tightening the tee carve to the strict 4-sink alternation across BOTH
# unquoted and quoted paths is tracked as a follow-up TODO; today the
# trio mirrors the existing unquoted-path behavior verbatim. The DENIED
# message text on the tee pattern names the four discard sinks as the
# documented workaround; agents should not rely on /dev/sda-style
# block-device targets even though `[a-z0-9]+` would admit them.
COMMAND_DEV_CARVED=$(printf '%s' "$COMMAND" | sed -E 's/("(\/?[^"]*\/)?tee"|'"'"'(\/?[^'"'"']*\/)?tee'"'"')([[:blank:]]+(-[-a-zA-Z]+[[:blank:]]+)*\/dev\/[a-z0-9]+([[:blank:]]|$))/ /g' | sed -E 's/of=\/dev\/(null|stdout|stderr|tty)([[:blank:]]|$)/\2/g')
TEE_PATTERN_RAW_QUOTED='(^|[;&|[:blank:]`(])("(/?[^"]*/)?tee"|'"'"'(/?[^'"'"']*/)?tee'"'"')[[:blank:]]+[^[:blank:]]'
DD_PATTERN_RAW_QUOTED='(^|[;&|[:blank:]`(])("(/?[^"]*/)?dd"|'"'"'(/?[^'"'"']*/)?dd'"'"')[[:blank:]]+(-[-a-zA-Z]+[[:blank:]]+)*([^|&;[:blank:]]+[[:blank:]]+)*of='
if printf '%s' "$COMMAND_DEV_CARVED" | tr '\n' ' ' | grep -qE "$TEE_PATTERN_RAW_QUOTED"; then
  echo 'DENIED: quoted tee binary ("tee" / '"'"'tee'"'"' / "/usr/bin/tee" etc.) writing to a file bypasses the 11b-extended file-write block by hiding the binary inside quotes. Use the native Write tool, or redirect tee output to /dev/null, /dev/stdout, /dev/stderr, or /dev/tty.' >&2
  exit 2
fi
if printf '%s' "$COMMAND_DEV_CARVED" | tr '\n' ' ' | grep -qE "$DD_PATTERN_RAW_QUOTED"; then
  echo 'DENIED: quoted dd binary ("dd" / '"'"'dd'"'"' / "/bin/dd" etc.) with an of=FILE target bypasses the 11b-extended file-write block. Use the native Write tool.' >&2
  exit 2
fi

# 11c. Block compound shell commands (; && || &), newlines, and background.
# Rationale: Claude Code's permission-rule matcher tokenizes command
# strings on these separators and requires each segment to match an
# allowlist entry independently. A pattern like `task X; echo done`
# matches no single entry end-to-end and silently falls through to
# the ask tier, which fails-closed in headless/CI runs. Agents must
# issue one Bash call per command (exit codes are returned in the
# tool result) or move multi-step logic into a script under scripts/
# and allowlist the script path. Pipelines (|) are deliberately NOT
# blocked — each pipeline stage still runs inside the sandbox.
#
# Separators covered:
#   `;`       — statement terminator
#   `&&`, `||` — logical chain
#   `&`       — background detach (escapes the allowlist like a chain)
#   `\n`      — newlines arrive as real `\n` bytes after `jq -r`
#               unescapes the JSON; multi-line payloads chain statements
#               the same way `;` does
#
# Strategy: dual-pass quote strip (see shared rationale), then strip
# fd-duplication (`2>&1`, `>&2`, `&>`, `&>>`) and escaped separators
# (so `find -exec cmd {} \;` and literal `\&` do not false-positive),
# then flag remaining separators in either strip output.
for COMPOUND_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  COMPOUND_CHECK=$(printf '%s' "$COMPOUND_BASE" | sed -E '
    s/[0-9]*>&[0-9-]+//g;
    s/&>>?//g;
    s/\\;//g; s/\\&\\&//g; s/\\\|\\\|//g; s/\\&//g
  ')
  if printf '%s' "$COMPOUND_CHECK" | grep -qE ';|&&|\|\|'; then
    echo 'DENIED: compound shell commands (; && ||) break the permission allowlist in headless mode — each segment creates a matcher token that must independently match an allow entry. Issue one Bash call per command (exit codes are returned in the tool result), or move multi-step logic into a script under scripts/ and allowlist the script path. Pipelines (|) remain allowed.' >&2
    exit 2
  fi
  # Background `&` (after stripping `&&`, any remaining `&` is background).
  COMPOUND_NO_AND=$(printf '%s' "$COMPOUND_CHECK" | sed 's/&&//g')
  if printf '%s' "$COMPOUND_NO_AND" | grep -qE '&'; then
    echo 'DENIED: background-operator & detaches commands and bypasses the permission allowlist the same way compound (; && ||) commands do. Pipelines (|) remain allowed.' >&2
    exit 2
  fi
  # Literal newline separates statements across lines in a single tool call.
  if [[ "$COMPOUND_CHECK" == *$'\n'* ]]; then
    echo 'DENIED: newline in command separates statements and bypasses the permission allowlist the same way compound (; && ||) commands do. Issue one Bash call per command, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
    exit 2
  fi
done

# 11d. Block shell -c invocations and eval.
# Rationale: rules 11b (redirect) and 11c (compound) strip quoted
# strings before scanning, which intentionally avoids false-positives
# on jq/awk script literals. But `bash -c "..."` and `eval "..."`
# evaluate the quoted string AS SHELL CODE — the strip removes the
# very payload that needs inspection, leaving redirects and compound
# operators inside the quote unenforced. Examples:
#   bash -lc "echo hi > /tmp/x"     bypasses 11b
#   bash -lc "task a && task b"     bypasses 11c
#   eval "anything"                 bypasses both
# Closing this gap means denying shell-c wrappers and eval entirely.
# Agents that need multi-step shell logic must write a script under
# scripts/ and allowlist its path.
#
# Scan is a three-layer defense:
#   (1) Dual-strip scan (A + B) — catches `bash -c "evil"`, resists mixed-
#       quote bypass via both strip orderings. Pipe through an inline
#       backslash-escape strip (`\x → x`) so obfuscated forms like
#       `b\ash -c`, `\b\a\s\h -c` are normalized before matching
#       (Gemini R3 CRITICAL — backslash obfuscation component).
#   (2) Raw quoted-binary scan — catches `"bash" -c 'evil'` /
#       `'bash' -c "evil"` where the shell binary is quoted. The
#       quoted arms are SELF-PROTECTING: they require the closing quote
#       immediately after the shell name, so `grep "bash -c x"` (one
#       quoted literal) does not match (Gemini R3 CRITICAL — quoted-
#       binary erasure component). Re-introducing this raw scan does
#       NOT revive the Codex R2 P1 false-positive because the quoted
#       arm requires the name to sit alone inside its quote pair.
#       R6 revision (Gemini R6 HIGH + Opus R6 NIT):
#         - Tighten suffix anchor on the three raw-quoted `-c` patterns
#           (R4 SHELL_C_PATTERN_RAW_QUOTED, R5 SHELL_C_QUOTED_FLAG_PATTERN,
#           R6 SHELL_C_BOTH_QUOTED_PATTERN) from `([[:blank:]]|$)` to
#           `[[:blank:]]+[^[:blank:]]`. Requires content after `-c`; closes
#           the EOL false-positive on benign `echo "bash" -c`, `echo bash
#           "-c"`, `echo "bash" "-c"` where no payload follows.
#         - Harmonize R5 SHELL_C_QUOTED_FLAG_PATTERN prefix class to the
#           narrower R4/R6 form `(^|[;&|[:blank:]`(])` (drop `"` and `'`).
#       Post-R6 sweep (Gemini follow-up — EOL-anchor FP class closure):
#         - NOT TIGHTENED: SHELL_C_PATTERN (unquoted), EVAL_PATTERN, and
#           the `tee` bare-match (11b-extended) all scan STRIPPED_A/
#           STRIPPED_B where dual-quote-strip has erased the quoted
#           payload. `bash -c "rm"` reduces to `bash -c `, and
#           `tee "pwn.sh"` reduces to `tee ` at EOL in stripped form;
#           the EOL branch `([[:blank:]]|$)` is load-bearing. Tightening
#           here would allow real attacks to slip through — the tee
#           sweep-tightening attempt was reverted after Gemini Flash
#           reproduced `echo x | tee "pwn.sh"` as an ALLOW (2026-04-16).
#           FP residuals accepted: `echo bash -c`, `echo eval`,
#           `man bash -c`, `echo x | tee`, `ls | tee` at EOL remain
#           denied because the strip form is indistinguishable from a
#           stripped-payload attack without a proper tokenizer.
SHELL_C_PATTERN='(^|[;&|[:blank:]"'"'"'`(])(\/?[^ "'"'"'`]*\/)?(bash|sh|zsh|dash|ksh)[[:blank:]]+([^[:blank:]]+[[:blank:]]+)*-[ils]*c([[:blank:]]|$)'
EVAL_PATTERN='(^|[;&|[:blank:]"'"'"'`(])eval([[:blank:]]|$)'
SHELL_C_PATTERN_RAW_QUOTED='(^|[;&|[:blank:]`(])(/?[^|&;"'"'"'`[:blank:]()]*/)?("(/?[^"]*/)?(bash|sh|zsh|dash|ksh)"|'"'"'(/?[^'"'"']*/)?(bash|sh|zsh|dash|ksh)'"'"')[[:blank:]]+([^[:blank:]]+[[:blank:]]+)*-[ils]*c[[:blank:]]+[^[:blank:]]'
# R13 (TODO-0080): admit inner-quote-path prefix `(/?[^"]*/)?` (resp.
# single-quote equivalent) so absolute-path forms like `"/usr/bin/eval"`
# are caught. Mirrors the R11 fix on SHELL_C_PATTERN_RAW_QUOTED:297.
EVAL_PATTERN_RAW_QUOTED='(^|[;&|[:blank:]`(])("(/?[^"]*/)?eval"|'"'"'(/?[^'"'"']*/)?eval'"'"')[[:blank:]]+'
for SHELL_C_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  # Normalize inline backslash escapes (b\ash → bash) before the shell-
  # binary regex so bash's quote-removal step cannot obfuscate the name.
  SHELL_C_NORMALIZED=$(printf '%s' "$SHELL_C_BASE" | sed 's/\\\(.\)/\1/g')
  if printf '%s' "$SHELL_C_NORMALIZED" | tr '\n' ' ' | grep -qE "$SHELL_C_PATTERN"; then
    echo 'DENIED: shell -c invocations evaluate arbitrary code as a single argument, bypassing the redirect (11b) and compound-command (11c) hooks. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
    exit 2
  fi
  if printf '%s' "$SHELL_C_NORMALIZED" | tr '\n' ' ' | grep -qE "$EVAL_PATTERN"; then
    echo 'DENIED: eval evaluates arbitrary code as a string, bypassing the redirect (11b) and compound-command (11c) hooks. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
    exit 2
  fi
done
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$SHELL_C_PATTERN_RAW_QUOTED"; then
  echo 'DENIED: quoted shell -c invocations ("bash" -c / '"'"'bash'"'"' -c) bypass the strip-based scan by hiding the shell binary name inside quotes. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
  exit 2
fi
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$EVAL_PATTERN_RAW_QUOTED"; then
  echo 'DENIED: quoted eval ("eval" / '"'"'eval'"'"') bypasses the strip-based scan by hiding the keyword inside quotes. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
  exit 2
fi
# R5: also catch the symmetric form where the shell binary is unquoted
# but the `-c` flag is quoted (`bash "-c" "evil"`). STRIPPED_A/B erases
# both quoted tokens leaving `bash  ` with no `-c`, so the stripped
# scan misses; the raw-quoted-binary scan only fires on quoted binaries.
# This raw scan anchors on the shell binary + blank + QUOTED `-c` flag.
SHELL_C_QUOTED_FLAG_PATTERN='(^|[;&|[:blank:]`(])(\/?[^ "'"'"'`]*\/)?(bash|sh|zsh|dash|ksh)[[:blank:]]+([^[:blank:]]+[[:blank:]]+)*["'"'"']-[ils]*c["'"'"'][[:blank:]]+[^[:blank:]]'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$SHELL_C_QUOTED_FLAG_PATTERN"; then
  echo 'DENIED: quoted -c flag invocations (bash "-c" / bash '"'"'-c'"'"') bypass the strip-based scan by hiding the -c wrapper inside quotes. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
  exit 2
fi

# R6: close intersection case — both shell binary AND -c flag quoted.
# Example: "bash" "-c" "evil"  /  'bash' '-c' 'evil'  /  "bash"  '-c'  "evil"
# Bash quote-removal reduces all to `bash -c evil` at runtime. The binary
# and flag are quoted SEPARATELY — no single-token quoted form. Anchors
# match the shell name bounded by matching quotes, blank gap, then -c
# bounded by matching quotes (either quote style independently).
SHELL_C_BOTH_QUOTED_PATTERN='(^|[;&|[:blank:]`(])(/?[^|&;"'"'"'`[:blank:]()]*/)?("(/?[^"]*/)?(bash|sh|zsh|dash|ksh)"|'"'"'(/?[^'"'"']*/)?(bash|sh|zsh|dash|ksh)'"'"')[[:blank:]]+([^[:blank:]]+[[:blank:]]+)*("-[ils]*c"|'"'"'-[ils]*c'"'"')[[:blank:]]+[^[:blank:]]'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$SHELL_C_BOTH_QUOTED_PATTERN"; then
  echo 'DENIED: quoted shell binary with quoted -c flag (e.g., "bash" "-c" "cmd"). Use task <target>.' >&2
  exit 2
fi

# 11e. Block shell-stdin injection (pipe, here-string, heredoc, single-<
# stdin redirect → shell). Rule 11d blocks shell -c. These variants feed
# arbitrary code to the shell via stdin, bypassing rules 11b/11c/11d
# entirely (Gemini R1 CRITICAL + Opus R2 MEDIUM-2):
#   echo "cmd" | bash             pipe into shell
#   echo "cmd" | env bash         wrapper-prefixed pipe into shell (Opus R2 MEDIUM-1)
#   bash <<<"cmd"                 here-string
#   bash <<EOF ... EOF            heredoc (multi-line)
#   bash <tmp/x.sh                stdin from file (Opus R2 MEDIUM-2)
#   bash 0<tmp/x.sh               explicit fd-0 redirect
#   bash <&3                      stdin fd-dup (attacker must have opened fd 3 first)
#
# Scan the DUAL-STRIPPED command so benign text data like `echo "foo |
# bash script"`, `grep "bash <<<evil"`, `grep "bash <<EOF"` do not
# false-positive (Codex R2 P1-2). Attacks with pipe/here-string/heredoc
# OUTSIDE quotes still trigger because the strip only removes INSIDE-quote
# content.

# Pattern 1a: pipe → shell binary. Admits three prefix shapes before the
# shell name:
#   (a) Wrapper words: env, exec, command, builtin, nohup, sudo, timeout,
#       stdbuf, unbuffer, nice, ionice, chrt, taskset, setsid, time, xargs.
#       Each wrapper may take short args (e.g., `timeout 10`, `nice -n 5`,
#       `stdbuf -o0`, `xargs -n1`) before the shell binary (Opus + Gemini
#       R3 HIGH — wrapper list too narrow).
#   (b) VAR=value env-var assignment tokens (`| env FOO=bar bash`).
#   (c) Optional leading backslash on the shell binary itself (`| \bash`).
# The scan is pre-normalized for inline backslash escapes (`b\ash → bash`)
# so Gemini R3 CRITICAL's backslash-obfuscated pipe variants are caught
# (`echo evil | b\ash`, `\b\a\s\h`, etc.).
# Wrapper-arg token shape: flag (`-x`, `--long`), number (`10`, `5s`), or
# (R5 Gemini R4) a single optional positional arg to cover wrappers like
# `sudo -u root bash` and `xargs -I {} bash` where the arg is neither a
# flag nor a number. The positional-arg group is `?`-quantified so zero-
# arg invocations (`sudo bash`) still match via regex backtracking.
# Residual: wrapper binaries not in this list and not matching VAR=val
# (e.g., `coproc` as a rare bash builtin) would slip past; acceptable
# because the wrapper list covers every common host utility that can
# prefix a shell invocation.
PIPE_TO_SHELL_PATTERN='\|[[:blank:]]*((/?[^|&;"'"'"'`[:blank:]()]*/)?(env|exec|command|builtin|nohup|sudo|timeout|stdbuf|unbuffer|nice|ionice|chrt|taskset|setsid|time|xargs)([[:blank:]]+(-[-_A-Za-z0-9]+|[0-9]+[smhd]?))*([[:blank:]]+[^-|&;"'"'"'`[:blank:]()]+)?[[:blank:]]+|[A-Za-z_][A-Za-z0-9_]*=[^[:blank:]|]*[[:blank:]]+)*\\?(/?[^|&;"'"'"'`[:blank:]()]*/)?(bash|sh|zsh|dash|ksh)([[:blank:]]|$)'
for PIPE_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  # Normalize inline backslash escapes before the shell-binary regex so
  # `| b\ash`, `| \b\a\s\h` cannot hide behind bash's quote-removal.
  PIPE_NORMALIZED=$(printf '%s' "$PIPE_BASE" | sed 's/\\\(.\)/\1/g')
  if printf '%s' "$PIPE_NORMALIZED" | tr '\n' ' ' | grep -qE "$PIPE_TO_SHELL_PATTERN"; then
    echo 'DENIED: piping into a shell binary (| bash, | env bash, | sudo bash, | timeout bash, backslash-bash, etc.) feeds arbitrary code to the shell via stdin, bypassing rules 11b/11c/11d. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
    exit 2
  fi
done

# Pattern 1b: pipe → QUOTED shell binary where the closing quote ends
# the command. Scan the RAW command — this is the one sub-rule that
# INTENTIONALLY looks inside quoted tokens, because bash treats
# `| "bash"` identically to `| bash` at command position. To keep
# this from false-positiving on literal-data quoted forms (e.g., a
# doc-search payload containing `| "bash" something`), we require the
# closing quote to be followed ONLY by blanks-then-end-of-command.
# Residual bypass: `| "bash" arg1` at end-of-line slips past this
# anchor. Documented in the header.
# R6: admit wrapper segments between pipe and quoted shell binary,
# symmetric with PIPE_TO_SHELL_PATTERN (Pattern 1a). Same wrapper list.
# Covers: | sudo "bash" / | xargs -I {} "bash" / | env FOO=bar 'bash' / etc.
PIPE_TO_QUOTED_SHELL_PATTERN='\|[[:blank:]]*((/?[^|&;"'"'"'`[:blank:]()]*/)?(env|exec|command|builtin|nohup|sudo|timeout|stdbuf|unbuffer|nice|ionice|chrt|taskset|setsid|time|xargs)([[:blank:]]+(-[-_A-Za-z0-9]+|[0-9]+[smhd]?))*([[:blank:]]+[^-|&;"'"'"'`[:blank:]()]+)?[[:blank:]]+|[A-Za-z_][A-Za-z0-9_]*=[^[:blank:]|]*[[:blank:]]+)*(/?[^|&;"'"'"'`[:blank:]()]*/)?["'"'"'](/?[^"'"'"']*/)?(bash|sh|zsh|dash|ksh)["'"'"'][[:blank:]]*$'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$PIPE_TO_QUOTED_SHELL_PATTERN"; then
  echo 'DENIED: piping into a quoted shell binary (| "bash", | '"'"'sh'"'"', etc.) has the same effect as unquoted and bypasses rules 11b/11c/11d. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
  exit 2
fi

# R13 (TODO-0079): close quoted-wrapper + quoted-shell pipe bypass. The
# unquoted PIPE_TO_SHELL_PATTERN scan on STRIPPED_A/STRIPPED_B erases
# both quoted tokens; PIPE_TO_QUOTED_SHELL_PATTERN's wrapper character
# class `[^|&;"'`[:blank:]()]*` excludes quote chars, so `| "sudo"
# "bash"` does not match the wrapper-segment alternation. This third
# pattern explicitly matches a quoted-wrapper segment + quoted-shell
# segment (path b per TODO-0079; preferred over widening the wrapper
# class to avoid ReDoS revalidation of the existing nested quantifiers).
# Wrapper segment admits the same wrapper alternation + same arg-token
# shape as PIPE_TO_SHELL_PATTERN; positional-arg admission preserved.
#
# Rev 2 fold: wrapper-segment alternation extended in three ways to close
# the convergent reviewer-flagged gaps:
#   (a) Quoted-token alternative for wrapper-args (-flag) and positional
#       admission, so `"sudo" "-u" "root" "bash"` (every token quoted)
#       does not bypass via the `[^"]+` / `[^-…]` exclusions of quote chars.
#   (b) VAR=val env-var-assignment arm at iteration level (parallel to the
#       quoted-wrapper-segment), mirroring PIPE_TO_SHELL_PATTERN:362's
#       `(wrapper|VAR=val)*` permissiveness. Closes `| "env" FOO=bar
#       BAZ=qux "bash"` (multi-VAR=val) and `| FOO=bar "sudo" "bash"`
#       (VAR=val at iteration head).
#   (c) Optional leading-backslash `\\?` before the shell-quoted group,
#       mirroring PIPE_TO_SHELL_PATTERN:362's `\\?(/?…)?(bash|…)`. Closes
#       the mechanical `| \"bash\"` form where a literal backslash escapes
#       the opening quote.
# Forward-pointer (OQ-3 deferred): if a fourth wrapper-related pattern
# lands, refactor the 16-keyword wrapper alternation into a shared shell
# variable and consolidate PIPE_TO_SHELL_PATTERN, PIPE_TO_QUOTED_SHELL_
# PATTERN, and this one. Today, three-way duplication is auditable by grep.
PIPE_TO_BOTH_QUOTED_PATTERN='\|[[:blank:]]*(("(/?[^"]*/)?(env|exec|command|builtin|nohup|sudo|timeout|stdbuf|unbuffer|nice|ionice|chrt|taskset|setsid|time|xargs)"|'"'"'(/?[^'"'"']*/)?(env|exec|command|builtin|nohup|sudo|timeout|stdbuf|unbuffer|nice|ionice|chrt|taskset|setsid|time|xargs)'"'"')([[:blank:]]+("[^"]*"|'"'"'[^'"'"']*'"'"'|-[-_A-Za-z0-9]+|[0-9]+[smhd]?))*([[:blank:]]+("[^"]*"|'"'"'[^'"'"']*'"'"'|[^-|&;"'"'"'`[:blank:]()]+))?[[:blank:]]+|[A-Za-z_][A-Za-z0-9_]*=[^[:blank:]|]*[[:blank:]]+)+\\?("(/?[^"]*/)?(bash|sh|zsh|dash|ksh)"|'"'"'(/?[^'"'"']*/)?(bash|sh|zsh|dash|ksh)'"'"')[[:blank:]]*$'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$PIPE_TO_BOTH_QUOTED_PATTERN"; then
  echo 'DENIED: piping into a quoted shell binary preceded by a quoted wrapper (| "sudo" "bash", | '"'"'env'"'"' '"'"'bash'"'"', etc.) bypasses the strip-based scan by hiding both the wrapper and shell name inside quotes. Write the command directly, or move multi-step logic into a script under scripts/ and allowlist the script path.' >&2
  exit 2
fi

# Pattern 2: here-string `<<<` — always a stdin-injection primitive
# when it appears outside quotes.
for HS_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  if printf '%s' "$HS_BASE" | grep -qE '<<<'; then
    echo 'DENIED: here-string (<<<) feeds arbitrary text to a command as stdin, potentially bypassing redirect (11b) / compound (11c) / shell-c (11d) hooks. Write the command directly or use the Write tool for file content.' >&2
    exit 2
  fi
done

# Pattern 3: heredoc `<<` — multi-line stdin block. Tightened from
# `<<[^<]` to require a heredoc tag starter so arithmetic expansions
# like `$(( 1 << 4 ))` (left-shift) do not false-positive. Heredoc
# tag starters are one of: `-` (tab-strip variant), `'`/`"` (quoted
# tag), `\` (escaped tag start), or an identifier character. Bash
# also admits whitespace between `<<` and the tag, so the pattern
# allows optional [[:space:]]*. The `|$` alternative catches the
# case where the dual-pass strip consumed a quoted tag (`<<'EOF'` →
# `<<` after strip), leaving nothing after `<<` in the scanned
# input — still indicates a heredoc was present.
HEREDOC_PATTERN='<<[[:space:]]*([-'"'"'"\\A-Za-z_]|$)'
for HD_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  # Strip arithmetic expansions `$((...))` and `((...))` before the heredoc
  # scan so bit-shift expressions like `$(( mask << shift ))` (where the
  # right operand is an identifier rather than a digit) do not trigger the
  # pattern's `[A-Za-z_]` tag-starter class. Nested arithmetic (e.g.,
  # `$(( (a+b) << c ))`) is NOT stripped by this simple regex — the `[^)]*`
  # body stops at the first `)`, so nested forms fall through to the
  # heredoc check and may false-positive. Nested arithmetic with bit-shift
  # in a Bash tool call is rare enough that this is an accepted trade-off.
  HD_CHECK=$(printf '%s' "$HD_BASE" | sed -E 's/\$\(\([^)]*\)\)//g; s/\(\([^)]*\)\)//g')
  if printf '%s' "$HD_CHECK" | grep -qE "$HEREDOC_PATTERN"; then
    echo 'DENIED: heredoc (<<) feeds a multi-line block to command stdin and may bypass redirect (11b) / compound (11c) / shell-c (11d) hooks. Use the Write tool for multi-line file content, or a script under scripts/ for multi-step logic.' >&2
    exit 2
  fi
done

# Pattern 4: shell binary directly consuming stdin via single `<`
# redirect (`bash <file.sh`, `bash 0<file.sh`, `bash <&3`). This is
# functionally equivalent to `cat file.sh | bash` and lets an agent
# execute arbitrary content it first staged via the Write tool. Args
# between the shell binary and the `<` are admitted (`bash -x <file`).
# Trailing class `([^<]|$)` so `bash <"pwn.sh"` (dual-pass strip leaves
# `bash <` at EOL) is caught (Gemini R3 HIGH #3). Pre-normalize inline
# backslash escapes to catch `b\ash <file` forms.
SHELL_STDIN_REDIR_PATTERN='(^|[;&|[:blank:]"'"'"'`(])(/?[^|&;"'"'"'`[:blank:]()]*/)?(bash|sh|zsh|dash|ksh)([[:blank:]]+[-_/.0-9A-Za-z=]+)*[[:blank:]]*[0-9]*<([^<]|$)'
for STDIN_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  STDIN_NORMALIZED=$(printf '%s' "$STDIN_BASE" | sed 's/\\\(.\)/\1/g')
  if printf '%s' "$STDIN_NORMALIZED" | tr '\n' ' ' | grep -qE "$SHELL_STDIN_REDIR_PATTERN"; then
    echo 'DENIED: feeding a file or fd into a shell via single-< stdin redirection (bash <file, bash 0<file, bash <&3) executes arbitrary content and bypasses rules 11b/11c/11d. Write the command directly, or run a tracked script under scripts/ that has been allowlisted.' >&2
    exit 2
  fi
done

# R12 (Gemini R11 CRITICAL): close the fully-quoted shell binary in stdin-
# redirect form (`"bash" <tmp/x.sh`, `'/bin/zsh' <pwn`). SHELL_STDIN_REDIR_
# PATTERN scans STRIPPED_A/STRIPPED_B which erase quoted tokens entirely,
# leaving ` <tmp/x.sh` with no shell binary to anchor on. This raw-quoted
# scan mirrors the structure of SHELL_C_PATTERN_RAW_QUOTED (R4 + R11
# inner-quote-path prefix) but anchors on `<` redirection instead of `-c`.
# The quoted arms are SELF-PROTECTING: closing quote must immediately
# follow the shell name, so `grep "bash <foo"` (single quoted literal)
# does not match. Trailing `[[:blank:]]*<[[:blank:]]*[^[:blank:]]` requires
# real content after `<` to avoid EOL false-positives on `echo "bash" -arg`.
SHELL_STDIN_REDIR_PATTERN_RAW_QUOTED='(^|[;&|[:blank:]`(])(/?[^|&;"'"'"'`[:blank:]()]*/)?("(/?[^"]*/)?(bash|sh|zsh|dash|ksh)"|'"'"'(/?[^'"'"']*/)?(bash|sh|zsh|dash|ksh)'"'"')[[:blank:]]*<[[:blank:]]*[^[:blank:]]'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$SHELL_STDIN_REDIR_PATTERN_RAW_QUOTED"; then
  echo 'DENIED: quoted shell binary with stdin redirection ("bash" <file, '"'"'sh'"'"' <file) bypasses the strip-based scan by hiding the shell name inside quotes. Write the command directly, or run a tracked script under scripts/ that has been allowlisted.' >&2
  exit 2
fi

# 11f. Block `source FILE` and `. FILE` builtins — these execute the
# contents of FILE in the current shell, with the same effect as
# `bash <FILE` (Pattern 4) but through a bash builtin instead of the
# shell binary. Attack: the agent writes `tmp/x.sh` via the Write tool
# and then runs `source tmp/x.sh`, bypassing 11b/11c/11d/11e entirely
# (Opus R3 MEDIUM scope finding).
#
# Two-layer scan:
#   (1) Dual-strip scan — catches unquoted `source FILE` / `. FILE`.
#       Pre-normalized for inline backslash escapes.
#   (2) Raw quoted-keyword scan — catches `"source" FILE` / `'source' FILE`
#       / `"." FILE`. Self-protecting: closing quote must be immediately
#       after the keyword, so `grep "source the config"` does not match.
#       R5 tightened: prefix excludes `[:blank:]` so `grep "source" FILE`
#       / `grep "." FILE` (search-term false-positive flagged by Opus R4)
#       no longer match. `[[:blank:]]*` after the prefix preserves
#       legitimate forms like `; "source" FILE`.
#
# Allowed forms: `./script.sh` (no blank after `.`), `. .` / `ls .`
# (no trailing file arg), `find . -name X` (`.` followed by flag arg).
SOURCE_PATTERN='(^|[;&|[:blank:]`(])(source|\.)[[:blank:]]+[^-[:blank:]]'
# R13 (TODO-0080): admit inner-quote-path prefix `(/?[^"]*/)?` (resp.
# single-quote equivalent) so absolute-path forms like `"/usr/bin/source"`
# / `"/usr/bin/."` are caught. Mirrors the R11 fix on SHELL_C_PATTERN_
# RAW_QUOTED:297. The `[[:blank:]]+[^-[:blank:]]` trailing-flag class is
# load-bearing: it gates legitimate `find "/some/dir/." -name X`-style
# usage where a `-flag` follows the quoted path (Rev 2 OQ-2 resolution).
SOURCE_PATTERN_RAW_QUOTED='(^|[;&|`(])[[:blank:]]*("(/?[^"]*/)?(source|\.)"|'"'"'(/?[^'"'"']*/)?(source|\.)'"'"')[[:blank:]]+[^-[:blank:]]'
for SRC_BASE in "$STRIPPED_A" "$STRIPPED_B"; do
  SRC_NORMALIZED=$(printf '%s' "$SRC_BASE" | sed 's/\\\(.\)/\1/g')
  if printf '%s' "$SRC_NORMALIZED" | tr '\n' ' ' | grep -qE "$SOURCE_PATTERN"; then
    echo 'DENIED: source / . FILE builtins execute the file contents in the current shell, bypassing rules 11b/11c/11d/11e the same way a shell-stdin redirect does. Write the command directly, or run a tracked script under scripts/ that has been allowlisted.' >&2
    exit 2
  fi
done
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$SOURCE_PATTERN_RAW_QUOTED"; then
  echo 'DENIED: quoted source / . ("source" / '"'"'.'"'"' etc.) bypasses the strip-based scan by hiding the keyword inside quotes. Write the command directly, or run a tracked script under scripts/ that has been allowlisted.' >&2
  exit 2
fi
# R5: catch the symmetric form where the filename is quoted rather than
# the keyword (`source "tmp/x.sh"`, `. 'payload'`). Strip erases the
# quoted filename, SOURCE_PATTERN's trailing `[^-[:blank:]]` class
# requires a real char and can't match nothing. Raw-quoted KEYWORD scan
# only fires on `"source"` / `'source'`. This new arm fires when the
# keyword is unquoted but the filename arg starts with a quote.
SOURCE_QUOTED_FILE_PATTERN='(^|[;&|`(])[[:blank:]]*(source|\.)[[:blank:]]+["'"'"']'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$SOURCE_QUOTED_FILE_PATTERN"; then
  echo 'DENIED: source / . with a quoted filename argument (source "FILE", . '"'"'FILE'"'"') bypasses the strip-based scan. Write the command directly, or run a tracked script under scripts/ that has been allowlisted.' >&2
  exit 2
fi

# Centralized gated container pattern — used by all rules below.
GATED_CONTAINERS='(python-cli|pytest-cli|repo-cli|agent-cli|infra-lint|ledger-dashboard)'

# --- Host Python execution block (Req-011) -----------------------------------
# Block direct python3/python execution on the host. Matches python anywhere
# in command including inside quotes (handles env python3, bash -c "python3",
# /usr/bin/python3, versioned binaries like python3.11, etc.)
# Boundary chars: start-of-line, ;, &, |, [:blank:] (space+tab),
# double-quote, single-quote, backtick, open-paren (catches
# $(python3 ...) and `python3 ...` subshells).
PYTHON_PATTERN='(^|[;&|[:blank:]"'"'"'`(])(\/?[^ "'"'"'`]*\/)?python[0-9.]*([[:space:]"'"'"'`)]|$)'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$PYTHON_PATTERN"; then
  echo "DENIED: direct python execution is not allowed. Use task wrappers (e.g., task run:adhoc -- tmp/script.py)." >&2
  exit 2
fi

# --- Host pytest execution block (Req-001, TODO-0076) -------------------------
# Block direct pytest/py.test execution on the host. The legitimate path is
# `task test:skills` which invokes pytest internally (invisible to this hook).
# Boundary chars match PYTHON_PATTERN convention above.
# Newline normalization (tr) prevents multiline JSON bypass (DD-5).
PYTEST_PATTERN='(^|[;&|[:blank:]"'"'"'`(])(\/?[^ "'"'"'`]*\/)?py\.?test([[:space:]"'"'"'`)]|$)'
if printf '%s' "$COMMAND" | tr '\n' ' ' | grep -qE "$PYTEST_PATTERN"; then
  echo "DENIED: direct pytest execution is not allowed. Use task test:skills." >&2
  exit 2
fi

# --- .venv/bin/ execution block -----------------------------------------------
# Block direct execution of any .venv/bin/ tool on the host. The venv exists
# for task test:skills (which invokes tools via Task, invisible to this hook).
# Agents must not run .venv/bin/ruff, .venv/bin/black, etc. directly.
if printf '%s' "$COMMAND" | tr '\n' ' ' | sed 's|/\./|/|g; s|//\+|/|g' | grep -qE '\.venv/bin/'; then
  echo "DENIED: direct .venv/bin/ execution is not allowed. Use task wrappers (e.g., task lint:staged)." >&2
  exit 2
fi

# Block chmod on .py files (prevents shebanged script execution).
# Catches: chmod +x, chmod a+x, chmod u+x, chmod 755, etc.
if printf '%s' "$COMMAND" | grep -qE 'chmod[[:space:]]+[0-7a-zA-Z+=-]+[[:space:]]+.*\.py'; then
  echo "DENIED: chmod on .py files is not allowed — prevents shebanged script execution." >&2
  exit 2
fi

# Skip non-docker/non-task commands early.
if ! printf '%s' "$COMMAND" | grep -qiE 'docker|docker-compose|task sh:'; then
  exit 0
fi

# Block PYTHON_GATE_DISABLED env-var injection in docker commands.
if printf '%s' "$COMMAND" | grep -qi "PYTHON_GATE_DISABLED"; then
  echo "DENIED: PYTHON_GATE_DISABLED env-var injection is not allowed." >&2
  exit 2
fi

# Block LINT_GATE_DISABLED env-var injection in docker commands.
if printf '%s' "$COMMAND" | grep -qi "LINT_GATE_DISABLED"; then
  echo "DENIED: LINT_GATE_DISABLED env-var injection is not allowed." >&2
  exit 2
fi

# 1-4. Block docker [compose] run/exec with gated containers.
if printf '%s' "$COMMAND" | grep -qE 'docker[[:space:]]+(compose[[:space:]]+)?(run|exec)[[:space:]]' && \
   printf '%s' "$COMMAND" | grep -qE "$GATED_CONTAINERS"; then
  echo "DENIED: direct docker access to gated container is not allowed. Use task wrappers." >&2
  exit 2
fi

# 5. Block --entrypoint override on gated containers.
if printf '%s' "$COMMAND" | grep -qE -- '--entrypoint' && \
   printf '%s' "$COMMAND" | grep -qE "$GATED_CONTAINERS"; then
  echo "DENIED: --entrypoint override on gated container is not allowed." >&2
  exit 2
fi

# 6. Block legacy docker-compose with gated containers.
if printf '%s' "$COMMAND" | grep -qE 'docker-compose[[:space:]]' && \
   printf '%s' "$COMMAND" | grep -qE "$GATED_CONTAINERS"; then
  echo "DENIED: direct docker-compose access to gated container is not allowed." >&2
  exit 2
fi

# 7. Block interactive shell tasks for gated containers.
if printf '%s' "$COMMAND" | grep -qE 'task[[:space:]]+sh:(python-cli|pytest-cli|repo-cli|agent-cli|infra-lint|ledger-dashboard)'; then
  echo "DENIED: interactive shell access to gated container is not allowed." >&2
  exit 2
fi

# 10. Block --user override on gated containers (only agent/agent:agent allowed).
#     Mirrors the tokenized check from block-terraform-escape.sh.
#     Defense-in-depth: primary gate (rules 1-4) already blocks direct access;
#     this catches --user root passed through task wrapper CLI_ARGS passthrough.
if printf '%s' "$COMMAND" | grep -qE "$GATED_CONTAINERS"; then
  NORMALIZED=$(printf '%s' "$COMMAND" | tr '\t' ' ' | sed 's/  */ /g' | tr -d "\"'")
  read -ra TOKENS <<< "$NORMALIZED"
  EXPECT_USER_VAL=false
  for i in "${!TOKENS[@]}"; do
    TOK="${TOKENS[$i]}"
    if [[ "$EXPECT_USER_VAL" == true ]]; then
      if ! printf '%s' "$TOK" | grep -qE '^agent(:agent)?$'; then
        echo "DENIED: --user '$TOK' on gated container is not allowed. Only '--user agent' is permitted." >&2
        exit 2
      fi
      EXPECT_USER_VAL=false
      continue
    fi
    if printf '%s' "$TOK" | grep -qE '^(--user|-u)='; then
      VAL="${TOK#*=}"
      if ! printf '%s' "$VAL" | grep -qE '^agent(:agent)?$'; then
        echo "DENIED: --user '$VAL' on gated container is not allowed. Only '--user agent' is permitted." >&2
        exit 2
      fi
    elif printf '%s' "$TOK" | grep -qE '^-u.+'; then
      VAL="${TOK#-u}"
      if ! printf '%s' "$VAL" | grep -qE '^agent(:agent)?$'; then
        echo "DENIED: --user '$VAL' on gated container is not allowed. Only '--user agent' is permitted." >&2
        exit 2
      fi
    elif [[ "$TOK" == "--user" || "$TOK" == "-u" ]]; then
      EXPECT_USER_VAL=true
    fi
  done
  if [[ "$EXPECT_USER_VAL" == true ]]; then
    echo "DENIED: --user with no value on gated container." >&2
    exit 2
  fi
fi

# 12. Block direct docker run with infra-lint image name (bypass compose).
if printf '%s' "$COMMAND" | grep -qE 'docker[[:space:]]+run[[:space:]]' && \
   printf '%s' "$COMMAND" | grep -qE 'brownfield-ai/infra-lint'; then
  echo "DENIED: direct docker run with infra-lint image is not allowed. Use task wrappers." >&2
  exit 2
fi

# 13. Block direct docker run with ledger-dashboard image name (bypass compose).
if printf '%s' "$COMMAND" | grep -qE 'docker[[:space:]]+run[[:space:]]' && \
   printf '%s' "$COMMAND" | grep -qE 'ledger-dashboard'; then
  echo "DENIED: direct docker run with ledger-dashboard image is not allowed. Use task wrappers." >&2
  exit 2
fi

exit 0
