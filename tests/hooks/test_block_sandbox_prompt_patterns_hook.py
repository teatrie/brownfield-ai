"""Unit tests for the PreToolUse hook: block-sandbox-prompt-patterns.sh.

Feeds simulated Claude Code PreToolUse JSON payloads to the hook via
stdin and asserts the correct exit code (0 = allow, 2 = deny).

The hook blocks Bash command patterns that trigger sandbox expansion or
process-substitution prompts in headless mode. Patterns are anchored to
command positions (start-of-string or after ``;``, ``&&``, ``||``,
``|``) so that quoted arguments to ``grep``/``rg``/``awk`` do not
false-positive.

Covered pattern families (one class per family):

- Shell for-loops and while-loops at command position.
- ``$?`` exit-code expansion in ``echo``/``printf`` commands.
- ``FILES="..."`` multi-file inline assignments.
- Leading ``printf``/``tee`` invocations.
- ``echo "VAR=$VAR"`` expansion patterns.
- ``<(...)`` and ``>(...)`` process substitution.
- ``$(...)`` command substitution.
- Backtick command substitution.
- Bash search tools (``grep``/``rg``/``find``) at command position.
- Inline env-var prefix before ``task`` (e.g., ``ROUND=3 task foo``).
- Commit message bypass for ``git commit`` and ``task git:commit``.
- Malformed hook input (empty / non-JSON) must fail closed.
- Smoke tests for commonly allowed commands.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOOK = str(Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "block-sandbox-prompt-patterns.sh")


def _run_hook(command: str) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a simulated PreToolUse JSON payload on stdin."""
    payload = json.dumps({"tool_input": {"command": command}}, separators=(",", ":"))
    return subprocess.run(
        ["bash", HOOK],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Shell loops
# ---------------------------------------------------------------------------


class TestForLoop:
    """Shell for-loops at command position must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "for f in *.py; do echo $f; done",
            "for x in a b c; do cat $x; done",
            "ls && for f in tmp/*; do rm $f; done",
        ],
    )
    def test_for_loop_denied(self, cmd: str) -> None:
        """Command-position for-loops trigger simple_expansion prompts."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr
        assert "for-loops" in result.stderr

    def test_for_inside_grep_argument_allowed(self) -> None:
        """A literal ``for x in y`` string inside a search argument is allowed."""
        # Use ripgrep (also blocked) replaced with awk; but awk will still
        # not match the for-loop pattern because it isn't a command-position
        # for-loop. However awk is not in the bash-search block list — the
        # only other block that may fire is grep. Use a plain echo guard
        # to avoid false-positives from the search-tools rule.
        result = _run_hook("echo 'for x in y should not trigger'")
        assert result.returncode == 0


class TestWhileLoop:
    """Shell while-loops at command position must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "while read line; do echo $line; done",
            "while true; do sleep 1; done",
            "cat file | while read l; do echo $l; done",
        ],
    )
    def test_while_loop_denied(self, cmd: str) -> None:
        """Command-position while-loops trigger simple_expansion prompts."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr
        assert "while-loops" in result.stderr


# ---------------------------------------------------------------------------
# Exit-code expansion
# ---------------------------------------------------------------------------


class TestExitCodeExpansion:
    """``echo``/``printf`` with ``$?`` expansion must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            'echo "EXIT=$?"',
            "echo exit-was $?",
            "printf 'code: %d' $?",
            'printf "%d\\n" $?',
        ],
    )
    def test_exit_code_expansion_denied(self, cmd: str) -> None:
        """``$?`` combined with echo/printf at command start is denied."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr


# ---------------------------------------------------------------------------
# FILES="a b c" multi-file assignment
# ---------------------------------------------------------------------------


class TestFilesMulti:
    """Multi-file ``FILES="..."`` inline assignment must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            'FILES="a.py b.py c.py" wc -l',
            'FILES="first.py second.py" make lint',
            'FILES="x y" cat',
        ],
    )
    def test_multi_file_assignment_denied(self, cmd: str) -> None:
        """A space-containing FILES="..." value trips the hook."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr


# ---------------------------------------------------------------------------
# Leading printf / tee
# ---------------------------------------------------------------------------


class TestLeadingPrintfTee:
    """Leading ``printf``/``tee`` invocations must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            'printf "%s" hello',
            'printf "%s\\n" "$var"',
            "tee file.log",
            "tee -a tmp/out.log",
        ],
    )
    def test_leading_printf_or_tee_denied(self, cmd: str) -> None:
        """printf/tee as the leading command trips the hook."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr

    def test_printf_inside_search_argument_allowed(self) -> None:
        """``printf`` as a literal inside a non-blocked leading command is allowed.

        ``grep`` would itself be blocked by the search-tools rule, so we
        use ``awk`` (not on the blocklist) to demonstrate the anchor.
        """
        result = _run_hook("awk '/printf/ {print}' file.py")
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# echo "VAR=$VAR"
# ---------------------------------------------------------------------------


class TestEchoVarExpansion:
    """``echo "VAR=$VAR"`` variable-expansion patterns must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            'echo "CI=$CI"',
            "echo VAR=$HOME",
            'echo "FOO=$BAR"',
        ],
    )
    def test_echo_var_expansion_denied(self, cmd: str) -> None:
        """echo followed by KEY=$VALUE is denied."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo 'hello world'",
            "echo done",
            'echo "no expansion here"',
        ],
    )
    def test_plain_echo_allowed(self, cmd: str) -> None:
        """Plain echo without VAR=$VAR tokens must be allowed."""
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Unexpectedly blocked: {cmd!r}\nstderr: {result.stderr}"


# ---------------------------------------------------------------------------
# Process substitution <(...) >(...)
# ---------------------------------------------------------------------------


class TestProcessSubstitution:
    """Process substitution must be denied regardless of command position."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "diff <(cat a) <(cat b)",
            "cmd > >(logger)",
            "awk '{print}' <(echo hi)",
        ],
    )
    def test_process_substitution_denied(self, cmd: str) -> None:
        """Any ``<(`` or ``>(`` token trips the hook."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr
        assert "process_substitution" in result.stderr


# ---------------------------------------------------------------------------
# Command substitution $(...)
# ---------------------------------------------------------------------------


class TestCommandSubstitution:
    """Dollar-paren command substitution must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            'foo "$(cat file)"',
            "foo $(date)",
            'task ledger:save "$(jq . tmp/a.json)"',
            'task ledger:save -- --content "$(jq . tmp/a.json)"',
        ],
    )
    def test_dollar_paren_denied(self, cmd: str) -> None:
        """Any ``$(`` token trips the hook."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr


# ---------------------------------------------------------------------------
# Backtick substitution
# ---------------------------------------------------------------------------


class TestBacktickSubstitution:
    """Backtick command substitution must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo `date`",
            "ls `pwd`",
            "awk `printf foo`",
        ],
    )
    def test_backtick_denied(self, cmd: str) -> None:
        """Any backtick character trips the hook."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr
        assert "backtick" in result.stderr


# ---------------------------------------------------------------------------
# Bash search tools (grep / rg / find)
# ---------------------------------------------------------------------------


class TestBashSearchTools:
    """Direct ``grep``/``rg``/``find`` invocations must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "grep pattern file.py",
            "grep -r foo src/",
            "rg needle src/",
            "find . -name '*.py'",
            "find . -type f",
        ],
    )
    def test_bash_search_denied(self, cmd: str) -> None:
        """grep/rg/find at command position are denied."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr

    def test_grep_in_task_target_name_allowed(self) -> None:
        """A task target name containing ``grep`` is not a bash search invocation."""
        result = _run_hook("task grep-wrapper")
        assert result.returncode == 0, f"Unexpectedly blocked: stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# Inline env-var prefix before `task`
# ---------------------------------------------------------------------------


class TestEnvVarPrefixTask:
    """Inline env-var prefix before ``task`` invocations must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "ROUND=3 task foo",
            "FOO=1 BAR=2 task baz",
            "EFFORT=high task agent:review:gemini",
        ],
    )
    def test_env_prefix_task_denied(self, cmd: str) -> None:
        """``VAR=val task target`` form is denied — use CLI_ARGS instead."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}"
        assert "DENIED" in result.stderr
        assert "CLI_ARGS" in result.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            "task foo -- ROUND=3",
            "task agent:review:gemini -- ROUND=3 EFFORT=high",
            "task foo",
            "task lint:staged",
        ],
    )
    def test_plain_task_invocation_allowed(self, cmd: str) -> None:
        """Plain ``task target`` and ``task target -- KEY=val`` forms are allowed."""
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Unexpectedly blocked: {cmd!r}\nstderr: {result.stderr}"


# ---------------------------------------------------------------------------
# Commit message bypass
# ---------------------------------------------------------------------------


class TestCommitBypass:
    """``git commit``/``task git:commit`` bypass must be anchored to start."""

    @pytest.mark.parametrize(
        "cmd",
        [
            'git commit -m "plain message"',
            'git commit -m "body with $? and other text"',
            'task git:commit -m "multi-line\\nmessage"',
            '  git commit -m "leading whitespace"',
        ],
    )
    def test_commit_bypass_allows_otherwise_denied_patterns(self, cmd: str) -> None:
        """Commit commands bypass most pattern checks.

        Hα exception: `$()` / backtick raw-buffer rules still fire against
        commit bodies (they run BEFORE the bypass to close the nested-quote
        code-execution bypass — see ``TestCommitBodyCodeExecutionDenied``).
        """
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Commit bypass failed: {cmd!r}\nstderr: {result.stderr}"

    def test_commit_substring_does_not_bypass(self) -> None:
        """``echo "git commit"`` must NOT bypass — bypass is anchored to cmd start."""
        # ``echo "git commit $VAR"`` would trip the echo VAR=$VAR rule; use a
        # form that only exercises the commit-bypass anchoring — embed a
        # subshell in a non-commit leading command so we can see the bypass
        # is not applied.
        result = _run_hook('echo "git commit happened `date`"')
        assert result.returncode == 2, f"Commit-bypass must be anchored to command start — stderr: {result.stderr!r}"

    def test_compound_commit_does_not_bypass(self) -> None:
        """``foo && git commit`` must NOT fire the bypass.

        Under the previous ``CMD_START``-anchored bypass, a compound
        command with ``git commit`` as the second segment would fire the
        bypass, allowing the leading segment to escape every other deny
        rule. The true start-of-string anchor closes this hole — the
        leading segment ``for x in y`` is still denied.
        """
        result = _run_hook("for x in a b; do echo $x; done && git commit -m foo")
        assert result.returncode == 2, f"Compound commit command must not trigger bypass — stderr: {result.stderr!r}"

    def test_multiline_commit_does_not_bypass(self) -> None:
        """``evil\\ngit commit`` (multi-line) must NOT fire the bypass.

        Newline normalization folds the payload to one line before the
        anchor check. The start-of-string anchor then fails because the
        line begins with ``evil``, and the leading command is evaluated
        against the deny rules.
        """
        # A for-loop on the first line that would independently be denied.
        result = _run_hook("for f in a b; do echo $f; done\ngit commit -m foo")
        assert result.returncode == 2, f"Multi-line commit payload must not trigger bypass — stderr: {result.stderr!r}"

    def test_git_commit_prefix_collision_not_bypassed(self) -> None:
        """``git commit-foo`` (no trailing space) must NOT fire the bypass.

        The anchor requires a trailing ``[[:space:]]`` after ``git commit``
        so that longer command names sharing the prefix are not treated
        as commits.
        """
        # Fabricate a command where `git commit-foo` would otherwise pass
        # through. Use a token that trips another deny rule to verify the
        # hook still denies.
        result = _run_hook("git commit-foo `date`")
        assert result.returncode == 2, f"git commit-foo must not trigger commit bypass — stderr: {result.stderr!r}"

    # G2a — commit bypass must not apply to pipeline trailers. A leading
    # ``git commit`` / ``task git:commit`` followed by ``| <cmd>`` would
    # previously allow ``<cmd>`` to escape every downstream deny rule
    # (e.g., grep, tee) because the bypass exits before they run. The
    # bypass now end-anchors: any unquoted ``|`` in the command body
    # aborts the bypass and the full command is evaluated against the
    # deny rules.
    @pytest.mark.parametrize(
        "cmd",
        [
            'git commit -m "ok" | grep foo',
            "task git:commit -F tmp/msg | tee log",
            "git commit -m ok | rg pattern",
        ],
    )
    def test_commit_trailing_pipeline_denied(self, cmd: str) -> None:
        """Pipeline trailers on commit commands must be evaluated, not bypassed."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Commit command with pipeline trailer must be denied — cmd: {cmd!r}, stderr: {result.stderr!r}"
        assert "DENIED" in result.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            # Bare commit invocations must still bypass cleanly.
            'git commit -m "ok with spaces and $var"',
            "task git:commit -F tmp/msg",
            "git commit -m ok",
            # A pipe character safely inside double quotes is allowed:
            # bash does not tokenize it as a pipeline operator.
            'git commit -m "body with | inside quotes"',
        ],
    )
    def test_bare_commit_still_bypasses(self, cmd: str) -> None:
        """Plain commit invocations retain the bypass (no pipeline trailer)."""
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Bare commit invocation must still bypass — cmd: {cmd!r}, stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# Commit body code-execution vector (Hα / J1 regression coverage)
# ---------------------------------------------------------------------------
#
# Hα context: the commit fast-path bypass previously sat ABOVE the
# `$(...)` and backtick rules. That order reopened a code-execution
# vector for commit bodies — the bypass regex's `"[^"]*"` branch
# atomically swallows a quoted body like `"msg $(evil)"` (no `"` inside
# it), so the bypass fired and the `$(...)` rule never ran. bash
# tokenizes argv AFTER the PreToolUse hook returns, and `$()` inside
# double quotes IS expanded at that time, so `evil` would still execute
# at commit time.
#
# The r4 fix reorders the hook: the `$(...)` and backtick raw-buffer
# rules now run BEFORE the commit bypass. Any commit command containing
# those metachars — quoted or not, `git commit` or `task git:commit` —
# is rejected before the fast-path can exit. Commit messages do not
# legitimately need runtime `$()` / backticks; agents precompute dynamic
# values and pass literal strings.
#
# J1 context (r5): the `<(...)` process-substitution rule was left
# BELOW the commit bypass in r4. That re-opened an analogous
# code-execution vector in the unquoted form `git commit -m <(evil)`:
# every char of `<(evil)` matches the bypass regex's `[^|]` branch, so
# the bypass fired; bash then expanded `<(evil)` at argv tokenization
# (spawning a subshell that runs `evil`) before git saw its arguments.
# The r5 fix moves the `<(...)` rule above the commit bypass — same
# rationale and same ordering as `$()` / backticks. The quoted form
# `git commit -m "msg <(evil)"` stays bypassed because bash does not
# perform process substitution inside double quotes and
# COMMAND_ALL_STRIPPED already removes quoted content.


class TestCommitBodyCodeExecutionDenied:
    """Commit bodies containing ``$()``, backticks, or ``<(...)`` must be denied.

    The nested-quote bypass is now closed at a higher layer: the
    `$()`, backtick, and `<(...)` raw-buffer rules run BEFORE the
    commit-command fast-path, so commit messages cannot smuggle
    code-execution metacharacters regardless of quote nesting (for
    `$()` / backticks) or unquoted argv placement (for `<(...)`).
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            # Quoted `$()` inside -m body — the r3 BLOCKER case.
            'git commit -m "msg $(evil)"',
            # Quoted backtick variant — same class.
            'git commit -m "msg `evil`"',
            # Unquoted `$()` form — obvious case, must also deny.
            "git commit -m msg $(evil)",
            # Shim-routed variant (task git:commit) with KEY=val body.
            'task git:commit -- msg="body $(evil)"',
        ],
    )
    def test_commit_body_command_substitution_denied(self, cmd: str) -> None:
        """`$()` / backticks in a commit body are denied before the bypass."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Commit body code-exec must be denied: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            # J1: unquoted `<(evil)` as an argv to -m — bash spawns the
            # subshell at argv tokenization. Must be denied before the
            # commit bypass can exit.
            "git commit -m <(evil)",
            # J1: shim-routed unquoted form.
            "task git:commit -- msg=<(evil)",
            # J1: unquoted `<(...)` as a trailing extra argv.
            "git commit -m msg <(evil)",
        ],
    )
    def test_commit_body_process_substitution_denied(self, cmd: str) -> None:
        """Unquoted `<(...)` in a commit body is denied before the bypass.

        Runtime expansion of process substitution at argv tokenization
        time would otherwise spawn a subshell before git sees its
        arguments. The r5 reorder places the `<(...)` rule above the
        commit fast-path to close this vector.
        """
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Commit body `<(...)` must be denied: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr
        assert "process_substitution" in result.stderr

    def test_plain_commit_still_bypasses(self) -> None:
        """Regression-negative: a plain commit message still bypasses cleanly."""
        result = _run_hook('git commit -m "plain message"')
        assert result.returncode == 0, f"Plain commit must bypass: stderr={result.stderr!r}"

    def test_quoted_process_substitution_in_commit_body_bypasses(self) -> None:
        """Quoted `<(...)` in a commit body is allowed by the bypass.

        The quoted form `git commit -m "msg <(evil)"` is safe because
        bash does not perform process substitution inside double
        quotes — the `<(` tokens are literal argv characters. The
        `<(...)` rule scans COMMAND_ALL_STRIPPED (which removes quoted
        content), so it does not fire, and the commit bypass applies
        normally. This documents the quoted/unquoted asymmetry.
        """
        result = _run_hook('git commit -m "msg <(evil)"')
        assert result.returncode == 0, f"Quoted `<(...)` in commit body must bypass: stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# Quoted-literal false positives
# ---------------------------------------------------------------------------


class TestQuotedLiteralsNotFlagged:
    """Shell metacharacter patterns inside quoted literals must NOT fire
    for the rules whose trigger tokens are never shell-expanded.

    The rules covered here (``<(...)``, leading ``printf``/``tee``, bash
    ``grep``/``rg``/``find``) scan the all-quote-stripped buffer, so
    literal metacharacter occurrences inside either single- or
    double-quoted argument text are safe to ignore.

    IMPORTANT asymmetry: ``$(...)`` and backticks are handled differently
    — see ``TestCommandSubstitutionBypassClosed`` below. The earlier
    single-quote-strip form of those rules contained a real
    code-execution bypass (nested quotes inside double quotes hid
    ``$(...)`` from the SQ-stripped check while bash still expanded it
    at runtime), so those two rules now scan the raw normalized buffer
    and accept the cosmetic false positive on ``echo '$(date)'``. Agents
    should use the native Grep tool for content searches that need
    literal command-substitution or backtick metacharacters.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            # Single-quoted — safe to strip for these rules.
            "echo 'foo|grep bar'",
            "echo 'x && tee y'",
            "awk '/<(/{print}' file.txt",
            "echo 'find . -name foo'",
            "echo 'rg pattern src/'",
            "echo 'printf foo'",
            # Double-quoted for rules whose trigger is NOT a bash
            # expansion inside double quotes (<( is parsed only at
            # command-argument positions, not inside any quoting form).
            'echo "<(literal)"',
            'echo "find . -name foo"',
            'echo "rg pattern src/"',
            'echo "printf foo"',
        ],
    )
    def test_quoted_literal_allowed(self, cmd: str) -> None:
        """Metacharacter tokens inside quoted literals do not fire the hook."""
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Unexpectedly blocked quoted literal: {cmd!r}\nstderr: {result.stderr}"


# ---------------------------------------------------------------------------
# Nested-quote bypass closure ($( ) and backticks)
# ---------------------------------------------------------------------------


class TestCommandSubstitutionBypassClosed:
    """Nested-quote bypass for ``$(...)`` and backticks must be denied.

    Background: the earlier implementation of the ``$(...)`` and
    backtick rules scanned a single-quote-stripped buffer so that
    ``echo '$(date)'`` (a genuine literal inside single quotes) would
    not false-positive. That strip opens a real code-execution bypass:
    in ``echo " '$(evil)' "`` the outer ``"..."`` renders the inner
    ``'...'`` literal at the token-parse level, yet bash still expands
    ``$(evil)`` at runtime because ``$(...)`` is expanded inside double
    quotes regardless of what's literally adjacent to it. The sed-based
    SQ-strip cannot model that context, so the only safe implementation
    is to scan the raw normalized buffer for these two rules.

    The cosmetic false positive — denying ``echo '$(date)'`` — is
    accepted because the native Grep tool is the preferred path for
    content searches that need literal shell metacharacters.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            # G1: nested quote bypass — outer "..." makes the inner
            # '...' literal at token-parse but $() still expands at
            # runtime. Must be DENIED.
            "echo \" '$(evil)' \"",
            "echo \" '`evil`' \"",
        ],
    )
    def test_nested_quote_bypass_denied(self, cmd: str) -> None:
        """Nested single quotes inside double quotes do not hide ``$()`` / backticks."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Nested-quote bypass must be denied: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            # Accepted cosmetic false positive: single-quoted
            # ``$(date)`` is a genuine literal in bash, but the hook
            # denies it anyway because the SQ-strip-based distinction
            # is unsafe (see class docstring). Agents should use the
            # Grep tool for this kind of content search.
            "echo '$(date)'",
            "echo '`date`'",
        ],
    )
    def test_accepted_false_positive_denied(self, cmd: str) -> None:
        """Literal ``$()`` / backticks inside single quotes are denied (accepted FP)."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Accepted FP must still fire: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


class TestMalformedInput:
    """Malformed hook input must fail closed."""

    def test_empty_stdin_allowed(self) -> None:
        """Empty stdin is treated as a no-op and exits 0."""
        result = subprocess.run(
            ["bash", HOOK],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_non_json_stdin_denied(self) -> None:
        """Non-JSON stdin fails closed with exit 2."""
        result = subprocess.run(
            ["bash", HOOK],
            input="not json at all",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "DENIED" in result.stderr


# ---------------------------------------------------------------------------
# Smoke tests for commonly allowed commands
# ---------------------------------------------------------------------------


class TestAllowedCommands:
    """Commonly issued benign commands must pass the hook."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "task test:staged",
            "task lint:staged",
            "ls",
            "ls -la src/",
            "bash -n scripts/agent-cli/cli-args-to-env.sh",
            "task git:add scripts/foo.py",
        ],
    )
    def test_allowed(self, cmd: str) -> None:
        """Everyday allowed commands must not be blocked."""
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Unexpectedly blocked: {cmd!r}\nstderr: {result.stderr}"
