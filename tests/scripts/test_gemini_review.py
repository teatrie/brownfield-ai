"""Tests for ``scripts/agent-cli/gemini-review.sh`` (TODO-0092 Phase A contract).

Covers the EFFORT/model composition and error-handling behaviors that remain
after the wrapper contract migrated from caller-supplied prompt files to
``REVIEW_TYPE=<enum>`` + ``DIFF_FILE=<tmp-or-agent-review-path>``:

- Req-005: EFFORT alias composition (Pro + Flash tiers + fallback rewrite).
- Req-005: EFFORT enum strictness — ``low`` and ``minimal`` are rejected.
- Req-005: MEDIUM effort -> HIGH internal thinking; xhigh/max collapse to HIGH.
- Req-019: Pro-tier 429/503 -> flash-high single-shot retry.
- New contract: REVIEW_TYPE / DIFF_FILE argument validation.
- Auth-failure cache invalidation and missing-binary handling.

Tests install a PATH-prepended fake ``gemini`` shim that logs argv and
stdin for each invocation. ``DIFF_FILE``-level path-containment tests live
in ``tests/scripts/test_wrapper_sanitation.py`` and are not duplicated
here.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

WORKSPACE: Path = Path(__file__).resolve().parents[2]
REVIEW_SCRIPT: str = str(WORKSPACE / "scripts" / "agent-cli" / "gemini-review.sh")

# Standard diff-subject filename used across tests. The wrapper's
# _review_validate_diff_file helper only accepts files realpath-contained
# under the workspace's ``tmp/`` or ``agent-review/`` directories, so the
# per-test pytest ``tmp_path`` cannot host the subject file.
_QA_DIFF_PATH: Path = WORKSPACE / "tmp" / "qa-diff.txt"


_SHIM_HELPER: str = """import json
import sys

log_path = sys.argv[1]
argv = sys.argv[2:]
try:
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read()
    else:
        stdin_content = ""
except (OSError, ValueError):
    stdin_content = ""
record = {"argv": argv, "stdin": stdin_content}
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\\n")
"""


def _install_shim(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    stderr_text: str = "",
    log_path: Path | None = None,
) -> Path:
    """Install a fake ``gemini`` shim at ``tmp_path/bin/gemini``.

    Delegates JSON-lines logging to a sibling python helper. Writes one
    record per invocation capturing argv and stdin, then exits ``exit_code``
    after optionally emitting ``stderr_text`` on stderr.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "_shim_helper.py"
    helper_path.write_text(_SHIM_HELPER)
    log_file = log_path if log_path is not None else (tmp_path / "gemini-calls.log")
    stderr_line = ""
    if stderr_text:
        escaped = stderr_text.replace("'", "'\\''")
        stderr_line = f"printf '%s\\n' '{escaped}' >&2\n"
    shim_body = f'#!/usr/bin/env bash\nset -eu\npython3 {helper_path!s} {log_file!s} "$@"\n{stderr_line}exit {exit_code}\n'
    shim = bin_dir / "gemini"
    shim.write_text(shim_body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _read_shim_log(log_path: Path) -> list[dict]:
    """Parse the shim's JSON-lines log."""
    if not log_path.exists():
        return []
    records: list[dict] = []
    for line in log_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        records.append(json.loads(stripped))
    return records


def _write_qa_diff() -> Path:
    """Create the standard diff subject file under the workspace ``tmp/``.

    The wrapper's ``_review_validate_diff_file`` helper realpath-contains
    the subject under ``$PWD/tmp/`` or ``$PWD/agent-review/``, so a
    pytest-managed ``tmp_path`` cannot host it.
    """
    _QA_DIFF_PATH.parent.mkdir(exist_ok=True)
    _QA_DIFF_PATH.write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n")
    return _QA_DIFF_PATH


def _default_env(bin_dir: Path, *, review_type: str = "diff") -> dict[str, str]:
    """Build the minimal env the wrapper needs to reach the shim.

    Supplies ``REVIEW_TYPE``/``DIFF_FILE`` for the new contract, the host
    execution context (so the token guard + OAuth path is exercised), and
    a token so the token-missing guard does not short-circuit.
    """
    return {
        "REVIEW_TYPE": review_type,
        "DIFF_FILE": str(_QA_DIFF_PATH),
        "GEMINI_EXECUTION_CONTEXT": "host",
        "GEMINI_API_KEY": "test",
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }


def _run_review(
    tmp_path: Path,
    env_overrides: dict[str, str],
    *,
    args: list[str] | None = None,
    timeout: int = 15,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the gemini review script with a controlled env.

    Creates a fake ``HOME/.gemini`` directory because ``run_gemini`` calls
    ``mkdir -p "$HOME/.gemini"`` unconditionally. Optional ``cwd`` lets a
    test run the wrapper from a fake workspace root (used by the DIFF_FILE
    containment tests that require a sibling of ``tmp/``).
    """
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {
        "PATH": env_overrides.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        "HOME": str(home),
    }
    for key, value in env_overrides.items():
        env[key] = value
    return subprocess.run(
        ["bash", REVIEW_SCRIPT, *(args or [])],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(cwd) if cwd is not None else str(WORKSPACE),
    )


# ---------------------------------------------------------------------------
# Req-005: EFFORT alias composition
# ---------------------------------------------------------------------------


class TestEffortAliasComposition:
    """EFFORT threads into the -m flag as <tier-shortname>-<effort>."""

    def _run_with_effort(
        self,
        tmp_path: Path,
        *,
        effort: str,
        model: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Invoke the wrapper with the given EFFORT/model under the new contract."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            env["EFFORT"] = effort
            env["GEMINI_MODEL"] = model
            result = _run_review(tmp_path, env_overrides=env)
            return result, _read_shim_log(log)
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_pro_plus_high_composes_pro_alias(self, tmp_path: Path) -> None:
        """Pro tier + EFFORT=high -> -m gemini-3.1-pro-high."""
        result, records = self._run_with_effort(tmp_path, effort="high", model="gemini-3.1-pro-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert "-m" in argv
        assert argv[argv.index("-m") + 1] == "gemini-3.1-pro-high"

    def test_flash_plus_medium_composes_flash_high(self, tmp_path: Path) -> None:
        """Flash tier + EFFORT=medium -> -m gemini-3-flash-high.

        MEDIUM tier collapses to HIGH internal thinking (model selection is
        what differs across tiers, not the internal effort setting).
        """
        result, records = self._run_with_effort(tmp_path, effort="medium", model="gemini-3-flash-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3-flash-high"

    def test_pro_plus_xhigh_collapses_to_pro_high(self, tmp_path: Path) -> None:
        """Pro tier + EFFORT=xhigh collapses to -m gemini-3.1-pro-high."""
        result, records = self._run_with_effort(tmp_path, effort="xhigh", model="gemini-3.1-pro-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3.1-pro-high"

    def test_pro_plus_max_collapses_to_pro_high(self, tmp_path: Path) -> None:
        """Pro tier + EFFORT=max collapses to -m gemini-3.1-pro-high."""
        result, records = self._run_with_effort(tmp_path, effort="max", model="gemini-3.1-pro-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3.1-pro-high"

    def test_fallback_transition_flash_plus_high(self, tmp_path: Path) -> None:
        """Caller invokes with GEMINI_MODEL=gemini-3-flash-preview (post-fallback).

        Exercises the Pro->Flash capacity fallback (Req-N03): the shortname
        lookup must recognize the Flash full name post-rewrite and produce
        ``gemini-3-flash-high``.
        """
        result, records = self._run_with_effort(tmp_path, effort="high", model="gemini-3-flash-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3-flash-high"

    def test_minimal_rejected_at_enum(self, tmp_path: Path) -> None:
        """``minimal`` is rejected at the EFFORT enum gate."""
        result, records = self._run_with_effort(tmp_path, effort="minimal", model="gemini-3-flash-preview")
        assert result.returncode != 0
        assert "EFFORT must be one of {medium,high,xhigh,max}" in result.stderr
        assert records == []

    def test_low_rejected_at_enum(self, tmp_path: Path) -> None:
        """``low`` is rejected upfront — reviewer floor is MEDIUM tier (HIGH internal)."""
        result, records = self._run_with_effort(tmp_path, effort="low", model="gemini-3.1-pro-preview")
        assert result.returncode != 0
        assert "EFFORT must be one of {medium,high,xhigh,max}" in result.stderr
        assert records == []


# ---------------------------------------------------------------------------
# New-contract argument validation: REVIEW_TYPE / DIFF_FILE.
#
# DIFF_FILE path-containment (realpath, absolute-outside-tmp/, symlink
# escape, traversal, zero-byte) is covered exhaustively by
# tests/scripts/test_wrapper_sanitation.py against the shared
# _review_validate_diff_file helper. These tests focus on the wrapper's
# arg_validation JSON exit shape — i.e. that the validation failure
# surfaces as GEMINI_ERROR + error_class=arg_validation, not as a crash.
# ---------------------------------------------------------------------------


def _read_exit_json() -> dict:
    """Read and parse the wrapper's ``tmp/gemini-exit.json`` if it exists."""
    path = WORKSPACE / "tmp" / "gemini-exit.json"
    if not path.exists():
        return {}
    parsed: dict = json.loads(path.read_text())
    return parsed


class TestReviewTypeValidation:
    """Wrapper rejects missing / invalid REVIEW_TYPE before invoking gemini."""

    def test_missing_review_type_rejected(self, tmp_path: Path) -> None:
        """Unset REVIEW_TYPE -> arg_validation JSON, non-zero exit, no shim call."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            env.pop("REVIEW_TYPE")
            result = _run_review(tmp_path, env_overrides=env)
            assert result.returncode != 0
            assert _read_shim_log(log) == []
            exit_json = _read_exit_json()
            assert exit_json.get("signal") == "GEMINI_ERROR"
            assert exit_json.get("error_class") == "arg_validation"
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_invalid_review_type_enum_rejected(self, tmp_path: Path) -> None:
        """REVIEW_TYPE=foo (not in enum) -> arg_validation rejection."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir, review_type="foo")
            result = _run_review(tmp_path, env_overrides=env)
            assert result.returncode != 0
            assert _read_shim_log(log) == []
            exit_json = _read_exit_json()
            assert exit_json.get("error_class") == "arg_validation"
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)


class TestDiffFileValidation:
    """Wrapper rejects missing / empty / out-of-root DIFF_FILE."""

    def test_missing_diff_file_rejected(self, tmp_path: Path) -> None:
        """Unset DIFF_FILE -> arg_validation rejection, shim never called."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir)
        env.pop("DIFF_FILE")
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json()
        assert exit_json.get("error_class") == "arg_validation"

    def test_nonexistent_diff_file_rejected(self, tmp_path: Path) -> None:
        """DIFF_FILE pointing at a missing path -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir)
        env["DIFF_FILE"] = "tmp/does-not-exist.txt"
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json()
        assert exit_json.get("error_class") == "arg_validation"

    def test_zero_byte_diff_file_rejected(self, tmp_path: Path) -> None:
        """Zero-byte DIFF_FILE -> arg_validation rejection."""
        empty = WORKSPACE / "tmp" / "empty-subject-for-gemini-test.txt"
        empty.parent.mkdir(exist_ok=True)
        empty.touch()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            env["DIFF_FILE"] = str(empty)
            result = _run_review(tmp_path, env_overrides=env)
            assert result.returncode != 0
            assert _read_shim_log(log) == []
            exit_json = _read_exit_json()
            assert exit_json.get("error_class") == "arg_validation"
        finally:
            empty.unlink(missing_ok=True)

    def test_diff_file_outside_tmp_rejected(self, tmp_path: Path) -> None:
        """DIFF_FILE outside tmp/ or agent-review/ -> arg_validation rejection.

        Runs the wrapper from a fake workspace so a sibling outside-root
        file is available in writable space.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        fake_ws = tmp_path / "fake_ws"
        (fake_ws / "tmp").mkdir(parents=True)
        outside = fake_ws / "evil.txt"
        outside.write_text("evil\n")
        env = _default_env(bin_dir)
        env["DIFF_FILE"] = str(outside)
        result = _run_review(tmp_path, env_overrides=env, cwd=fake_ws)
        assert result.returncode != 0
        assert _read_shim_log(log) == []


class TestTemplateIsHardcoded:
    """The reviewer template path is derived solely from REVIEW_TYPE.

    The wrapper ignores any caller-supplied prompt text; the template comes
    from ``.claude/prompts/reviewer/<REVIEW_TYPE>.md``. We observe this by
    asserting that a substring of the on-disk ``diff.md`` preamble appears
    in the stdin payload the shim received.
    """

    _TEMPLATE_MARKER: str = "The subject artifact follows immediately after this preamble"

    def test_stdin_contains_template_preamble(self, tmp_path: Path) -> None:
        """Shim stdin must include the hardcoded ``diff.md`` preamble text."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            env["EFFORT"] = "high"
            env["GEMINI_MODEL"] = "gemini-3.1-pro-preview"
            result = _run_review(tmp_path, env_overrides=env)
            assert result.returncode == 0, result.stderr
            records = _read_shim_log(log)
            assert records, "shim was never invoked"
            # Template loaded from .claude/prompts/reviewer/diff.md and
            # concatenated with the sanitized subject.
            assert self._TEMPLATE_MARKER in records[0]["stdin"]
            # Subject data also present (joined from the qa-diff fixture).
            assert "diff --git" in records[0]["stdin"]
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)


class TestRoundValidation:
    """Wrapper rejects non-positive-integer ROUND values before gemini."""

    def test_round_zero_rejected(self, tmp_path: Path) -> None:
        """``--round 0`` -> arg_validation JSON, non-zero exit."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            result = _run_review(tmp_path, env_overrides=env, args=["--round", "0"])
            assert result.returncode != 0
            assert _read_shim_log(log) == []
            exit_json = _read_exit_json()
            assert exit_json.get("error_class") == "arg_validation"
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_round_negative_rejected(self, tmp_path: Path) -> None:
        """``--round -1`` -> arg_validation JSON, non-zero exit."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            # ``--round -1`` is parsed by the while loop but the numeric
            # regex gate rejects negative/zero.
            result = _run_review(tmp_path, env_overrides=env, args=["--round", "abc"])
            assert result.returncode != 0
            assert _read_shim_log(log) == []
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)


class TestTokenAndSecretGuards:
    """Token-missing / secrets-guard behaviors.

    The ``/app/.env`` FATAL guard only trips inside a container and is
    covered by a separate integration test; we verify the token-missing
    signal here (host OAuth path is exercised by every other test via
    ``GEMINI_EXECUTION_CONTEXT=host`` + ``GEMINI_API_KEY=test``).
    """

    def test_token_missing_emits_unavailable_signal(self, tmp_path: Path) -> None:
        """Non-host context without GEMINI_API_KEY -> GEMINI_UNAVAILABLE, exit 0."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            env.pop("GEMINI_API_KEY")
            env.pop("GEMINI_EXECUTION_CONTEXT")
            result = _run_review(tmp_path, env_overrides=env)
            assert result.returncode == 0, result.stderr
            assert _read_shim_log(log) == []
            exit_json = _read_exit_json()
            assert exit_json.get("signal") == "GEMINI_UNAVAILABLE"
            assert exit_json.get("reason") == "token_missing"
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)


class TestOutputRouting:
    """Container vs host artifact routing (agent-review/ vs tmp/).

    Both tests run the wrapper from a throwaway fake workspace so the
    routing paths are observable via the shim's stdout-capture file
    without touching the real repo directories (which may be read-only
    inside the pytest container).
    """

    def _run_in_fake_ws(
        self,
        tmp_path: Path,
        *,
        review_session_id: str | None = None,
        workspace: str | None = None,
        container_context: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        """Run the wrapper from a fake workspace root for routing assertions."""
        fake_ws = tmp_path / "fake_ws"
        (fake_ws / "tmp").mkdir(parents=True)
        (fake_ws / "agent-review").mkdir()
        # Subject path must be inside fake_ws/tmp/ for DIFF_FILE containment.
        subject = fake_ws / "tmp" / "qa-diff.txt"
        subject.write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n")
        # Template path — the wrapper resolves it relative to CWD, so the
        # template must be accessible from fake_ws. Symlink the real
        # .claude/prompts/reviewer/ tree into fake_ws.
        claude_dir = fake_ws / ".claude" / "prompts" / "reviewer"
        claude_dir.parent.mkdir(parents=True)
        claude_dir.symlink_to(WORKSPACE / ".claude" / "prompts" / "reviewer")
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env: dict[str, str] = {
            "REVIEW_TYPE": "diff",
            "DIFF_FILE": str(subject),
            "GEMINI_API_KEY": "test",
            "PATH": f"{bin_dir}:/usr/bin:/bin",
        }
        if not container_context:
            env["GEMINI_EXECUTION_CONTEXT"] = "host"
        if review_session_id:
            env["REVIEW_SESSION_ID"] = review_session_id
        if workspace:
            env["WORKSPACE"] = workspace
        result = _run_review(tmp_path, env_overrides=env, cwd=fake_ws)
        return result, fake_ws

    def test_host_context_writes_to_tmp(self, tmp_path: Path) -> None:
        """``GEMINI_EXECUTION_CONTEXT=host`` -> output under ``tmp/``."""
        result, fake_ws = self._run_in_fake_ws(tmp_path)
        assert result.returncode == 0, result.stderr
        assert (fake_ws / "tmp" / "gemini-review-output-1.md").exists()

    def test_container_context_writes_to_agent_review(self, tmp_path: Path) -> None:
        """Container context -> output under ``agent-review/`` with workspace/session id."""
        result, fake_ws = self._run_in_fake_ws(
            tmp_path,
            review_session_id="test-session",
            workspace="brownfield-ai",
            container_context=True,
        )
        assert result.returncode == 0, result.stderr
        expected = fake_ws / "agent-review" / "brownfield-ai-gemini-review-output-test-session.md"
        assert expected.exists(), "agent-review output not produced"


# ---------------------------------------------------------------------------
# Req-019: Pro-tier 429/503 -> flash-high MEDIUM-tier fallback
# ---------------------------------------------------------------------------


def _install_shim_with_sequence(
    tmp_path: Path,
    *,
    exit_codes: list[int],
    stderr_texts: list[str],
    log_path: Path | None = None,
) -> Path:
    """Install a fake ``gemini`` shim whose exit code + stderr varies per call.

    The shim writes the per-call exit_code to a state file on each invocation
    and consumes the sequence in order. If more calls come than the sequence
    length, the last entry is reused (mirrors steady-state failure).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "_shim_helper.py"
    helper_path.write_text(_SHIM_HELPER)
    state_file = bin_dir / "call_counter.txt"
    state_file.write_text("0")
    # Encode the sequences into separate files for the shell to look up.
    codes_file = bin_dir / "exit_codes.txt"
    codes_file.write_text("\n".join(str(c) for c in exit_codes) + "\n")
    stderr_file = bin_dir / "stderr_lines.txt"
    # Encode stderr lines one per line (literal '\\n' placeholders not expected).
    stderr_file.write_text("\n".join(stderr_texts) + "\n")
    log_file = log_path if log_path is not None else (tmp_path / "gemini-calls.log")
    shim_body = (
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'python3 {helper_path!s} {log_file!s} "$@"\n'
        f"_n=$(cat {state_file!s})\n"
        f"_exit=$(awk -v n=\"$_n\" 'NR==n+1' {codes_file!s})\n"
        f"_stderr=$(awk -v n=\"$_n\" 'NR==n+1' {stderr_file!s})\n"
        'if [ -z "$_exit" ]; then\n'
        f"  _exit=$(tail -n1 {codes_file!s})\n"
        f"  _stderr=$(tail -n1 {stderr_file!s})\n"
        "fi\n"
        f"echo $(( _n + 1 )) > {state_file!s}\n"
        'if [ -n "$_stderr" ]; then printf \'%s\\n\' "$_stderr" >&2; fi\n'
        'exit "$_exit"\n'
    )
    shim = bin_dir / "gemini"
    shim.write_text(shim_body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


class TestProTier429_503Fallback:
    """Pro-tier 429/503 retries once with gemini-3-flash-high."""

    def _run_sequence(
        self,
        tmp_path: Path,
        *,
        exit_codes: list[int],
        stderr_texts: list[str],
        extra_env: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Install a sequence-shim and invoke the wrapper under the new contract."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim_with_sequence(
            tmp_path,
            exit_codes=exit_codes,
            stderr_texts=stderr_texts,
            log_path=log,
        )
        env = _default_env(bin_dir)
        env["EFFORT"] = "high"
        env["GEMINI_MODEL"] = "gemini-3.1-pro-preview"
        if extra_env:
            env.update(extra_env)
        try:
            result = _run_review(tmp_path, env_overrides=env, timeout=timeout)
            return result, _read_shim_log(log)
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_pro_429_retries_with_flash_high(self, tmp_path: Path) -> None:
        """429 on Pro tier -> second call with -m gemini-3-flash-high, success."""
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: 429 Too Many Requests", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gemini-3-flash-high" in result.stderr
        assert len(records) == 2, f"expected 2 calls, got {len(records)}"
        assert "gemini-3.1-pro-high" in records[0]["argv"]
        assert "gemini-3-flash-high" in records[1]["argv"]

    def test_pro_503_retries_with_flash_high(self, tmp_path: Path) -> None:
        """503 on Pro tier -> second call with -m gemini-3-flash-high, success."""
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: 503 Service Unavailable", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gemini-3-flash-high" in result.stderr
        assert len(records) == 2
        assert "gemini-3-flash-high" in records[1]["argv"]

    def test_pro_429_flash_retry_also_fails_emits_fallback(self, tmp_path: Path) -> None:
        """429 on Pro tier + flash-high retry also 429 -> GEMINI_FALLBACK exit 3."""
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 1],
            stderr_texts=[
                "Error: 429 Too Many Requests",
                "Error: 429 quota exceeded",
            ],
        )
        assert result.returncode == 3, result.stderr
        assert len(records) == 2
        exit_json = (WORKSPACE / "tmp" / "gemini-exit.json").read_text()
        assert "GEMINI_FALLBACK" in exit_json

    def test_pro_auth_error_no_fallback(self, tmp_path: Path) -> None:
        """Non-429/503 error (auth) -> terminal; no flash-high retry; exit 3."""
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1],
            stderr_texts=["Error: 401 Unauthorized: bad token"],
        )
        assert result.returncode == 3
        assert len(records) == 1, f"expected 1 call (no retry), got {len(records)}"
        assert "falling back" not in result.stderr

    def test_auth_error_invalidates_preflight_cache(self, tmp_path: Path) -> None:
        """Auth failure at execution time MUST delete the preflight cache."""
        cache_file = tmp_path / "gemini-preflight-cache.json"
        cache_file.write_text('{"mode":"local","gemini":{"cli":true}}\n')
        self._run_sequence(
            tmp_path,
            exit_codes=[1],
            stderr_texts=["Error: 401 Unauthorized: bad token"],
            extra_env={"PREFLIGHT_CACHE_FILE": str(cache_file)},
        )
        assert not cache_file.exists(), "preflight cache should be invalidated after auth failure"

    def test_missing_binary_invalidates_preflight_cache(self, tmp_path: Path) -> None:
        """``command not found`` also invalidates the preflight cache."""
        cache_file = tmp_path / "gemini-preflight-cache.json"
        cache_file.write_text('{"mode":"local","gemini":{"cli":true}}\n')
        self._run_sequence(
            tmp_path,
            exit_codes=[127],
            stderr_texts=["bash: gemini: command not found"],
            extra_env={"PREFLIGHT_CACHE_FILE": str(cache_file)},
        )
        assert not cache_file.exists(), "preflight cache should be invalidated after missing-binary failure"
