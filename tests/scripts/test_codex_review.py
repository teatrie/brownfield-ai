"""Tests for ``scripts/agent-cli/codex-review.sh`` (TODO-0092 Phase A contract).

Covers behaviors that remain after the wrapper contract migrated from the
caller-supplied ``PROMPT_FILE`` / legacy per-round prompt path to
``REVIEW_TYPE=<enum>`` + ``DIFF_FILE=<tmp-or-agent-review-path>``:

- Req-003: EFFORT enum validation and -c override composition.
- Req-003: MEDIUM effort -> HIGH model_reasoning_effort; max collapses to xhigh.
- Req-017: xhigh-rejection fail-closed behavior and opt-in fallback.
- Req-019: non-default MODEL 429/503 -> gpt-5.3-codex + high retry.
- New contract: REVIEW_TYPE / DIFF_FILE argument validation; template is
  hardcoded by the wrapper.
- Auth-failure cache invalidation and missing-binary handling.

All tests use a PATH-prepended fake ``codex`` shim that captures argv plus
stdin to a log file. ``DIFF_FILE``-level path-containment tests live in
``tests/scripts/test_wrapper_sanitation.py`` and are not duplicated here.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

WORKSPACE: Path = Path(__file__).resolve().parents[2]
REVIEW_SCRIPT: str = str(WORKSPACE / "scripts" / "agent-cli" / "codex-review.sh")

# Standard diff-subject filename used across tests. The wrapper's
# _review_validate_diff_file helper only accepts files realpath-contained
# under the workspace's ``tmp/`` or ``agent-review/`` directories.
_QA_DIFF_PATH: Path = WORKSPACE / "tmp" / "qa-diff.txt"


_SHIM_HELPER: str = """import json
import sys

log_path = sys.argv[1]
argv = sys.argv[2:]
# sys.stdin may be closed/terminal; read only if piped (select-style guard).
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
    """Install a fake ``codex`` shim at ``tmp_path/bin/codex``.

    The shim delegates JSON-lines logging to a sibling python helper
    (``_shim_helper.py``) to sidestep deep shell-escape nesting. Writes one
    record per invocation capturing argv and stdin, then exits ``exit_code``
    after optionally emitting ``stderr_text`` on stderr.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "_shim_helper.py"
    helper_path.write_text(_SHIM_HELPER)
    log_file = log_path if log_path is not None else (tmp_path / "codex-calls.log")
    stderr_line = ""
    if stderr_text:
        escaped = stderr_text.replace("'", "'\\''")
        stderr_line = f"printf '%s\\n' '{escaped}' >&2\n"
    shim_body = f'#!/usr/bin/env bash\nset -eu\npython3 {helper_path!s} {log_file!s} "$@"\n{stderr_line}exit {exit_code}\n'
    shim = bin_dir / "codex"
    shim.write_text(shim_body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _read_shim_log(log_path: Path) -> list[dict]:
    """Parse the shim's JSON-lines log into a list of records."""
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
    """Create the standard diff subject file under the workspace ``tmp/``."""
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
        "CODEX_EXECUTION_CONTEXT": "host",
        "OPENAI_API_KEY": "test",
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }


def _read_exit_json() -> dict:
    """Read and parse the wrapper's ``tmp/codex-exit.json`` if it exists."""
    path = WORKSPACE / "tmp" / "codex-exit.json"
    if not path.exists():
        return {}
    parsed: dict = json.loads(path.read_text())
    return parsed


def _run_review(
    tmp_path: Path,
    env_overrides: dict[str, str],
    *,
    args: list[str] | None = None,
    timeout: int = 15,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the review script with a controlled environment.

    Tests pass an explicit ``PATH`` in ``env_overrides`` pointing at a shim.
    Never inherits the parent process env (determinism).
    Optional ``cwd`` override lets a test run the wrapper from a fake
    workspace root (used by the DIFF_FILE out-of-root rejection test).
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
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
# Req-003: EFFORT enum validation + -c override composition
# ---------------------------------------------------------------------------


class TestEffortEnumValidation:
    """Wrapper rejects EFFORT values outside {medium,high,xhigh,max}."""

    def _run_with_effort(
        self,
        tmp_path: Path,
        *,
        effort: str | None,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Invoke the wrapper with the given EFFORT under the new contract."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            if effort is not None:
                env["EFFORT"] = effort
            result = _run_review(tmp_path, env_overrides=env)
            return result, _read_shim_log(log)
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_minimal_rejected_before_codex_invocation(self, tmp_path: Path) -> None:
        """EFFORT=minimal must be rejected upfront (Req-N01); shim never called."""
        result, records = self._run_with_effort(tmp_path, effort="minimal")
        assert result.returncode == 1
        assert "EFFORT" in result.stderr
        assert records == []

    def test_unknown_value_rejected(self, tmp_path: Path) -> None:
        """EFFORT=bogus must be rejected upfront."""
        result, records = self._run_with_effort(tmp_path, effort="bogus")
        assert result.returncode == 1
        assert records == []

    def test_valid_effort_threads_c_override(self, tmp_path: Path) -> None:
        """EFFORT=high -> codex argv contains -c ...=high."""
        result, records = self._run_with_effort(tmp_path, effort="high")
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "-c" in argv
        assert argv[argv.index("-c") + 1] == "profiles.reviewer.model_reasoning_effort=high"

    def test_medium_maps_to_high(self, tmp_path: Path) -> None:
        """EFFORT=medium -> -c ...=high (MEDIUM tier at HIGH reasoning)."""
        result, records = self._run_with_effort(tmp_path, effort="medium")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-c") + 1] == "profiles.reviewer.model_reasoning_effort=high"

    def test_xhigh_passthrough(self, tmp_path: Path) -> None:
        """EFFORT=xhigh -> -c ...=xhigh (raw passthrough)."""
        result, records = self._run_with_effort(tmp_path, effort="xhigh")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-c") + 1] == "profiles.reviewer.model_reasoning_effort=xhigh"

    def test_max_collapses_to_xhigh(self, tmp_path: Path) -> None:
        """EFFORT=max collapses to -c ...=xhigh (ceiling collapse)."""
        result, records = self._run_with_effort(tmp_path, effort="max")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-c") + 1] == "profiles.reviewer.model_reasoning_effort=xhigh"

    def test_low_rejected(self, tmp_path: Path) -> None:
        """EFFORT=low must be rejected — reviewer floor is MEDIUM tier (HIGH internal)."""
        result, records = self._run_with_effort(tmp_path, effort="low")
        assert result.returncode == 1
        assert "EFFORT" in result.stderr
        assert records == []

    def test_unset_effort_omits_c_override(self, tmp_path: Path) -> None:
        """Unset EFFORT must not inject a model_reasoning_effort -c override."""
        result, records = self._run_with_effort(tmp_path, effort=None)
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        for i, token in enumerate(argv):
            if token == "-c":
                assert "model_reasoning_effort" not in argv[i + 1]


# ---------------------------------------------------------------------------
# New-contract argument validation: REVIEW_TYPE / DIFF_FILE.
#
# DIFF_FILE path-containment (realpath, absolute-outside-tmp/, symlink
# escape, traversal, zero-byte) is covered exhaustively by
# tests/scripts/test_wrapper_sanitation.py against the shared
# _review_validate_diff_file helper. These tests focus on the wrapper's
# arg_validation JSON exit shape — i.e. that the validation failure
# surfaces as CODEX_ERROR + error_class=arg_validation, not as a crash.
# ---------------------------------------------------------------------------


class TestReviewTypeValidation:
    """Wrapper rejects missing / invalid REVIEW_TYPE before invoking codex."""

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
            assert exit_json.get("signal") == "CODEX_ERROR"
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
        empty = WORKSPACE / "tmp" / "empty-subject-for-codex-test.txt"
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


class TestReviewTypeDispatch:
    """The ``review --base`` subcommand must only fire for REVIEW_TYPE=diff.

    Regression gate for codex r1 P1-b / gemini r1 F6. ``codex review --base``
    critiques the live git diff against BASE_BRANCH and ignores stdin as a
    subject source. For non-diff review types (plan/spec/epic/
    spec-req-verification) the subject is a static artifact piped on stdin,
    so the wrapper must use plain ``codex exec -p reviewer`` for those.
    """

    def _run(
        self,
        tmp_path: Path,
        *,
        review_type: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Invoke the wrapper with the given REVIEW_TYPE against a fake ws.

        For non-diff types, the real template under
        ``.claude/prompts/reviewer/<type>.md`` is consumed via a symlinked
        ``.claude`` dir in the fake workspace so the wrapper's
        template-path lookup resolves without mutating the real repo.
        """
        fake_ws = tmp_path / "fake_ws"
        (fake_ws / "tmp").mkdir(parents=True)
        (fake_ws / "agent-review").mkdir()
        subject = fake_ws / "tmp" / "subject.txt"
        subject.write_text("subject body\n")
        claude_parent = fake_ws / ".claude" / "prompts"
        claude_parent.mkdir(parents=True)
        (claude_parent / "reviewer").symlink_to(WORKSPACE / ".claude" / "prompts" / "reviewer")
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env: dict[str, str] = {
            "REVIEW_TYPE": review_type,
            "DIFF_FILE": str(subject),
            "CODEX_EXECUTION_CONTEXT": "host",
            "OPENAI_API_KEY": "test",
            "PATH": f"{bin_dir}:/usr/bin:/bin",
        }
        result = _run_review(tmp_path, env_overrides=env, cwd=fake_ws)
        return result, _read_shim_log(log)

    def test_diff_invokes_review_subcommand(self, tmp_path: Path) -> None:
        """REVIEW_TYPE=diff -> codex argv contains ``review --base main``."""
        result, records = self._run(tmp_path, review_type="diff")
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "review" in argv, f"expected `review` subcommand for diff REVIEW_TYPE; argv={argv!r}"
        assert "--base" in argv
        assert argv[argv.index("--base") + 1] == "main"

    @pytest.mark.parametrize(
        "review_type",
        ["plan", "spec", "epic", "spec-req-verification"],
    )
    def test_non_diff_skips_review_subcommand(
        self,
        tmp_path: Path,
        review_type: str,
    ) -> None:
        """Non-diff types must NOT invoke the ``review`` subcommand.

        ``codex review --base`` would ignore the piped subject and
        critique the git diff instead. The wrapper must fall back to
        plain ``codex exec -p reviewer`` for these types.
        """
        result, records = self._run(tmp_path, review_type=review_type)
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "review" not in argv, f"REVIEW_TYPE={review_type!r} must not invoke `review`; argv={argv!r}"
        assert "--base" not in argv, f"REVIEW_TYPE={review_type!r} must not pass --base; argv={argv!r}"
        # Reviewer profile selector must still be present.
        assert "-p" in argv and argv[argv.index("-p") + 1] == "reviewer"


class TestReviewModeDispatch:
    """REVIEW_MODE={branch,fixture} controls the REVIEW_TYPE=diff path.

    TODO-0114: ``codex review --base`` triggers a live ``git diff
    $BASE_BRANCH..HEAD`` read and silently overrides a synthetic
    fixture DIFF_FILE. Fixture-driven smokes opt in via
    ``REVIEW_MODE=fixture`` to route through plain ``codex exec -p
    reviewer``, so the combined template+DIFF_FILE prompt on stdin is
    the sole subject channel — matching the Gemini/Copilot contract.
    """

    def _run(
        self,
        tmp_path: Path,
        *,
        review_mode: str | None,
        review_type: str = "diff",
        args: list[str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Invoke the wrapper with REVIEW_TYPE/REVIEW_MODE and optional extra args.

        For non-diff review types the subject is the real template under
        ``.claude/prompts/reviewer/<type>.md``, accessed via a symlinked
        ``.claude`` dir inside a fake workspace — matching the pattern
        used by ``TestReviewTypeDispatch._run``.
        """
        cwd: Path | None
        if review_type == "diff":
            _write_qa_diff()
            cwd = None
            subject_path = _QA_DIFF_PATH
        else:
            fake_ws = tmp_path / "fake_ws"
            (fake_ws / "tmp").mkdir(parents=True, exist_ok=True)
            (fake_ws / "agent-review").mkdir(exist_ok=True)
            subject_path = fake_ws / "tmp" / "subject.txt"
            subject_path.write_text("subject body\n")
            claude_parent = fake_ws / ".claude" / "prompts"
            if not claude_parent.exists():
                claude_parent.mkdir(parents=True)
                (claude_parent / "reviewer").symlink_to(WORKSPACE / ".claude" / "prompts" / "reviewer")
            cwd = fake_ws
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir, review_type=review_type)
            env["DIFF_FILE"] = str(subject_path)
            if review_mode is not None:
                env["REVIEW_MODE"] = review_mode
            result = _run_review(
                tmp_path,
                env_overrides=env,
                args=args,
                cwd=cwd,
            )
            return result, _read_shim_log(log)
        finally:
            # Fake-workspace cases are self-contained under tmp_path; only
            # the diff path writes to the real workspace tmp/ and needs
            # explicit cleanup.
            if review_type == "diff":
                _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_fixture_mode_skips_review_subcommand(self, tmp_path: Path) -> None:
        """REVIEW_MODE=fixture + diff -> plain ``codex exec -p reviewer``."""
        result, records = self._run(tmp_path, review_mode="fixture")
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "review" not in argv, f"REVIEW_MODE=fixture must not invoke `review`; argv={argv!r}"
        assert "--base" not in argv, f"REVIEW_MODE=fixture must not pass --base; argv={argv!r}"
        # Reviewer profile selector must still be present.
        assert "-p" in argv and argv[argv.index("-p") + 1] == "reviewer"

    @pytest.mark.parametrize(
        "review_type",
        ["plan", "spec", "epic", "spec-req-verification"],
    )
    def test_fixture_mode_noop_for_non_diff_types(
        self,
        tmp_path: Path,
        review_type: str,
    ) -> None:
        """REVIEW_MODE=fixture is a no-op for non-diff REVIEW_TYPEs.

        TODO-0121: non-diff types already skip ``review --base``; setting
        ``REVIEW_MODE=fixture`` on top must not change that (no double-gate
        inversion, no additional flags). Hardens the contract that the
        fixture gate applies only to REVIEW_TYPE=diff.
        """
        result, records = self._run(
            tmp_path,
            review_mode="fixture",
            review_type=review_type,
        )
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "review" not in argv, f"REVIEW_TYPE={review_type!r} + REVIEW_MODE=fixture must not invoke `review`; argv={argv!r}"
        assert "--base" not in argv, f"REVIEW_TYPE={review_type!r} + REVIEW_MODE=fixture must not pass --base; argv={argv!r}"
        assert "-p" in argv and argv[argv.index("-p") + 1] == "reviewer"

    def test_explicit_base_with_fixture_mode_emits_notice(self, tmp_path: Path) -> None:
        """``--base X`` + REVIEW_MODE=fixture -> stderr NOTICE; fixture dispatch unchanged.

        TODO-0120: when the caller passes ``--base`` explicitly and also
        selects fixture mode, the base value is silently ignored by the
        dispatch path. Surface that via a stderr NOTICE so the silent
        override is visible without changing behavior.
        """
        result, records = self._run(
            tmp_path,
            review_mode="fixture",
            args=["--base", "develop"],
        )
        assert result.returncode == 0, result.stderr
        assert "NOTICE" in result.stderr
        assert "--base" in result.stderr
        assert "REVIEW_MODE=fixture" in result.stderr
        # Dispatch path still routes through plain `codex exec -p reviewer`.
        assert records
        argv = records[0]["argv"]
        assert "review" not in argv
        assert "--base" not in argv

    def test_default_base_with_fixture_mode_no_notice(self, tmp_path: Path) -> None:
        """Unspecified ``--base`` (default ``main``) + fixture -> no NOTICE.

        The notice should fire only when the caller expressed explicit
        intent via ``--base <X>`` — a defaulted BASE_BRANCH did not
        express intent, so silent defaulting does not warrant a notice.
        """
        result, _ = self._run(tmp_path, review_mode="fixture")
        assert result.returncode == 0, result.stderr
        assert "NOTICE" not in result.stderr

    def test_explicit_base_main_with_fixture_mode_emits_notice(self, tmp_path: Path) -> None:
        """``--base main`` (explicit default value) + fixture -> NOTICE still fires.

        Guards against a future refactor that suppresses the notice when
        the explicit value happens to match the default. Passing ``--base
        main`` IS explicit intent (e.g., a caller scripting defensively)
        and the sentinel semantics must honor that.
        """
        result, records = self._run(
            tmp_path,
            review_mode="fixture",
            args=["--base", "main"],
        )
        assert result.returncode == 0, result.stderr
        assert "NOTICE" in result.stderr
        assert "--base main" in result.stderr
        # Dispatch path still routes through plain `codex exec -p reviewer`.
        assert records
        argv = records[0]["argv"]
        assert "review" not in argv
        assert "--base" not in argv

    @pytest.mark.parametrize(
        "review_type",
        ["plan", "spec", "epic", "spec-req-verification"],
    )
    def test_explicit_base_with_non_diff_type_emits_notice(
        self,
        tmp_path: Path,
        review_type: str,
    ) -> None:
        """``--base X`` + non-diff REVIEW_TYPE -> stderr NOTICE; argv still clean.

        TODO-0126: non-diff REVIEW_TYPEs (plan/spec/epic/spec-req-verification)
        always invoke plain ``codex exec -p reviewer`` — the ``review --base``
        subcommand is gated on REVIEW_TYPE=diff inside ``run_codex``. An
        explicit ``--base`` is therefore silently overridden in the non-diff
        path; surface that via a stderr NOTICE parallel to the fixture-mode
        notice so direct-invocation callers see the override.
        """
        # REVIEW_MODE left unset so the fixture branch does not steal
        # precedence — this test locks the non-diff branch specifically.
        result, records = self._run(
            tmp_path,
            review_mode=None,
            review_type=review_type,
            args=["--base", "develop"],
        )
        assert result.returncode == 0, result.stderr
        assert "NOTICE" in result.stderr
        assert "--base" in result.stderr
        assert f"REVIEW_TYPE={review_type}" in result.stderr
        # Dispatch path still routes through plain `codex exec -p reviewer`.
        assert records
        argv = records[0]["argv"]
        assert "review" not in argv
        assert "--base" not in argv

    @pytest.mark.parametrize(
        "review_type",
        ["plan", "spec", "epic", "spec-req-verification"],
    )
    def test_default_base_with_non_diff_type_no_notice(
        self,
        tmp_path: Path,
        review_type: str,
    ) -> None:
        """Unspecified ``--base`` + non-diff REVIEW_TYPE -> no NOTICE.

        Symmetric to ``test_default_base_with_fixture_mode_no_notice``: the
        notice should fire only when the caller expressed explicit intent
        via ``--base <X>``. A defaulted BASE_BRANCH did not express intent,
        so silent defaulting must not warrant a notice on the non-diff
        path either.
        """
        result, _ = self._run(
            tmp_path,
            review_mode=None,
            review_type=review_type,
        )
        assert result.returncode == 0, result.stderr
        assert "NOTICE" not in result.stderr

    @pytest.mark.parametrize(
        "review_type",
        ["plan", "spec", "epic", "spec-req-verification"],
    )
    def test_explicit_branch_mode_with_non_diff_and_base_emits_notice(
        self,
        tmp_path: Path,
        review_type: str,
    ) -> None:
        """Explicit ``REVIEW_MODE=branch`` + non-diff + ``--base`` -> non-diff NOTICE.

        TODO-0126 matrix completion: the sibling
        ``test_explicit_base_with_non_diff_type_emits_notice`` covers the
        *defaulted* ``REVIEW_MODE=branch`` path (``review_mode=None`` in
        the harness). This test locks the explicit-set form against a
        future refactor that might distinguish user-set from defaulted
        ``REVIEW_MODE`` (analogous to the ``BASE_BRANCH_EXPLICIT``
        sentinel). Current code paths are identical, so the assertion
        set matches the defaulted sibling.
        """
        result, records = self._run(
            tmp_path,
            review_mode="branch",
            review_type=review_type,
            args=["--base", "develop"],
        )
        assert result.returncode == 0, result.stderr
        assert "NOTICE" in result.stderr
        assert "--base" in result.stderr
        assert f"REVIEW_TYPE={review_type}" in result.stderr
        assert records
        argv = records[0]["argv"]
        assert "review" not in argv
        assert "--base" not in argv

    @pytest.mark.parametrize(
        "review_type",
        ["plan", "spec", "epic", "spec-req-verification"],
    )
    def test_fixture_precedence_when_both_override_conditions_hold(
        self,
        tmp_path: Path,
        review_type: str,
    ) -> None:
        """``--base X`` + ``REVIEW_MODE=fixture`` + non-diff -> fixture NOTICE wins.

        TODO-0126 precedence lock: when BOTH silent-override conditions
        hold (fixture mode AND non-diff REVIEW_TYPE), the inline ``if /
        elif`` in the wrapper routes only the fixture NOTICE — the non-
        diff NOTICE must NOT fire (two independent NOTICEs would be
        noise; inverting the order would surface the wrong primary
        cause). Guards against a refactor that converts the ``if/elif``
        to two independent ``if`` blocks or reverses the ordering.
        """
        result, _ = self._run(
            tmp_path,
            review_mode="fixture",
            review_type=review_type,
            args=["--base", "develop"],
        )
        assert result.returncode == 0, result.stderr
        # Fixture NOTICE fires (TODO-0120 substrings).
        assert "NOTICE" in result.stderr
        assert "REVIEW_MODE=fixture" in result.stderr
        # Non-diff NOTICE must NOT fire — precedence asserted.
        assert f"REVIEW_TYPE={review_type}" not in result.stderr

    def test_explicit_branch_mode_uses_review_subcommand(self, tmp_path: Path) -> None:
        """REVIEW_MODE=branch (explicit) + diff -> ``review --base main``."""
        result, records = self._run(tmp_path, review_mode="branch")
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "review" in argv
        assert "--base" in argv and argv[argv.index("--base") + 1] == "main"

    def test_unset_review_mode_defaults_to_branch(self, tmp_path: Path) -> None:
        """REVIEW_MODE unset + diff -> ``:-branch`` fallback invokes ``review --base main``."""
        result, records = self._run(tmp_path, review_mode=None)
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "review" in argv, f"expected `review` subcommand when REVIEW_MODE is unset; argv={argv!r}"
        assert "--base" in argv and argv[argv.index("--base") + 1] == "main"

    def test_invalid_review_mode_rejected(self, tmp_path: Path) -> None:
        """REVIEW_MODE=bogus -> arg_validation rejection before codex invocation."""
        result, records = self._run(tmp_path, review_mode="bogus")
        assert result.returncode != 0
        assert records == []
        exit_json = _read_exit_json()
        assert exit_json.get("signal") == "CODEX_ERROR"
        assert exit_json.get("error_class") == "arg_validation"


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
            result = _run_review(tmp_path, env_overrides=env)
            assert result.returncode == 0, result.stderr
            records = _read_shim_log(log)
            assert records, "shim was never invoked"
            # Template loaded from .claude/prompts/reviewer/diff.md and
            # concatenated with the sanitized subject.
            assert self._TEMPLATE_MARKER in records[0]["stdin"]
            # Subject data also present.
            assert "diff --git" in records[0]["stdin"]
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)


class TestRoundValidation:
    """Wrapper rejects non-positive-integer ROUND before codex."""

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

    def test_round_non_numeric_rejected(self, tmp_path: Path) -> None:
        """``--round abc`` -> arg_validation JSON, non-zero exit."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            result = _run_review(tmp_path, env_overrides=env, args=["--round", "abc"])
            assert result.returncode != 0
            assert _read_shim_log(log) == []
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)


class TestTokenAndSecretGuards:
    """Token-missing signal in non-host context without OPENAI_API_KEY."""

    def test_token_missing_emits_unavailable_signal(self, tmp_path: Path) -> None:
        """Non-host context without OPENAI_API_KEY -> CODEX_UNAVAILABLE, exit 0."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        try:
            env = _default_env(bin_dir)
            env.pop("OPENAI_API_KEY")
            env.pop("CODEX_EXECUTION_CONTEXT")
            result = _run_review(tmp_path, env_overrides=env)
            assert result.returncode == 0, result.stderr
            assert _read_shim_log(log) == []
            exit_json = _read_exit_json()
            assert exit_json.get("signal") == "CODEX_UNAVAILABLE"
            assert exit_json.get("reason") == "token_missing"
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)


class TestOutputRouting:
    """Container vs host artifact routing (agent-review/ vs tmp/).

    Both tests run the wrapper from a throwaway fake workspace so the
    routing paths are observable via the shim's argv capture without
    touching the real repo directories (which may be read-only inside
    the pytest container).
    """

    def _run_in_fake_ws(
        self,
        tmp_path: Path,
        *,
        review_session_id: str | None = None,
        workspace: str | None = None,
        container_context: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Run the wrapper from a fake workspace root for routing assertions."""
        fake_ws = tmp_path / "fake_ws"
        (fake_ws / "tmp").mkdir(parents=True)
        (fake_ws / "agent-review").mkdir()
        subject = fake_ws / "tmp" / "qa-diff.txt"
        subject.write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n")
        claude_dir = fake_ws / ".claude" / "prompts" / "reviewer"
        claude_dir.parent.mkdir(parents=True)
        claude_dir.symlink_to(WORKSPACE / ".claude" / "prompts" / "reviewer")
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env: dict[str, str] = {
            "REVIEW_TYPE": "diff",
            "DIFF_FILE": str(subject),
            "OPENAI_API_KEY": "test",
            "PATH": f"{bin_dir}:/usr/bin:/bin",
        }
        if not container_context:
            env["CODEX_EXECUTION_CONTEXT"] = "host"
        if review_session_id:
            env["REVIEW_SESSION_ID"] = review_session_id
        if workspace:
            env["WORKSPACE"] = workspace
        result = _run_review(tmp_path, env_overrides=env, cwd=fake_ws)
        return result, _read_shim_log(log)

    def test_host_context_writes_to_tmp(self, tmp_path: Path) -> None:
        """``CODEX_EXECUTION_CONTEXT=host`` -> ``-o tmp/codex-review-output-<ROUND>.md``."""
        result, records = self._run_in_fake_ws(tmp_path)
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert "-o" in argv
        out_arg = argv[argv.index("-o") + 1]
        assert out_arg == "tmp/codex-review-output-1.md"

    def test_container_context_writes_to_agent_review(self, tmp_path: Path) -> None:
        """Container context -> ``-o agent-review/<workspace>-codex-review-output-<session>.md``."""
        result, records = self._run_in_fake_ws(
            tmp_path,
            review_session_id="test-session",
            workspace="brownfield-ai",
            container_context=True,
        )
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        out_arg = argv[argv.index("-o") + 1]
        assert out_arg == "agent-review/brownfield-ai-codex-review-output-test-session.md"


# ---------------------------------------------------------------------------
# Req-017: xhigh-rejection fail-closed + opt-in fallback
# ---------------------------------------------------------------------------


class TestXhighRejectionHandling:
    """Codex rejecting xhigh: default fail-closed; opt-in retries with high."""

    _XHIGH_REJECT_STDERR: str = "Error: unknown variant xhigh for model_reasoning_effort"

    def _run_with_xhigh_stderr(
        self,
        tmp_path: Path,
        *,
        stderr_text: str,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Install a simple fail-shim and run the wrapper under the new contract."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(
            tmp_path,
            exit_code=1,
            stderr_text=stderr_text,
            log_path=log,
        )
        env = _default_env(bin_dir)
        env["EFFORT"] = "xhigh"
        if extra_env:
            env.update(extra_env)
        try:
            result = _run_review(tmp_path, env_overrides=env, timeout=30)
            return result, _read_shim_log(log)
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_xhigh_rejected_no_opt_in_fail_closed(self, tmp_path: Path) -> None:
        """xhigh rejected, opt-in unset -> non-zero exit, no retry."""
        result, records = self._run_with_xhigh_stderr(tmp_path, stderr_text=self._XHIGH_REJECT_STDERR)
        assert result.returncode != 0
        assert len(records) == 1, f"expected 1 shim call, got {len(records)}"
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "xhigh_rejected" in exit_json

    def test_xhigh_rejected_opt_in_retries_with_high(self, tmp_path: Path) -> None:
        """xhigh rejected + opt-in -> retries with EFFORT=high once.

        Shim always fails so the retry also fails; we assert 2 shim calls
        and error_class transition to xhigh_fallback_failed.
        """
        result, records = self._run_with_xhigh_stderr(
            tmp_path,
            stderr_text=self._XHIGH_REJECT_STDERR,
            extra_env={"EFFORT_FALLBACK_ON_REJECT": "1"},
        )
        assert result.returncode != 0
        assert len(records) == 2, f"expected 2 shim calls, got {len(records)}"
        assert "NOTICE" in result.stderr
        first_argv = records[0]["argv"]
        second_argv = records[1]["argv"]
        assert any("xhigh" in t for t in first_argv)
        assert any("=high" in t for t in second_argv)
        assert not any("xhigh" in t for t in second_argv)
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "xhigh_fallback_failed" in exit_json

    def test_max_rejected_opt_in_retries_with_high(self, tmp_path: Path) -> None:
        """EFFORT=max (collapsed to xhigh) rejection also triggers opt-in retry."""
        _write_qa_diff()
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(
            tmp_path,
            exit_code=1,
            stderr_text=self._XHIGH_REJECT_STDERR,
            log_path=log,
        )
        try:
            env = _default_env(bin_dir)
            env["EFFORT"] = "max"
            env["EFFORT_FALLBACK_ON_REJECT"] = "1"
            result = _run_review(tmp_path, env_overrides=env, timeout=30)
            assert result.returncode != 0
            records = _read_shim_log(log)
            assert len(records) == 2, f"expected 2 shim calls, got {len(records)}"
            assert "NOTICE" in result.stderr
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_non_xhigh_rejection_with_opt_in_still_fail_closed(self, tmp_path: Path) -> None:
        """Non-xhigh rejection with opt-in must not retry via the xhigh path.

        The opt-in narrowly targets the xhigh-reject class. Generic transient
        errors follow the existing transient-retry path (one retry).
        """
        _, records = self._run_with_xhigh_stderr(
            tmp_path,
            stderr_text="Error: connection timeout",
            extra_env={"EFFORT_FALLBACK_ON_REJECT": "1"},
        )
        assert len(records) == 2, f"expected 2 shim calls (initial + transient retry), got {len(records)}"
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "transient" in exit_json
        assert "xhigh_fallback_failed" not in exit_json
        assert "xhigh_rejected" not in exit_json


# ---------------------------------------------------------------------------
# Req-019: non-default MODEL 429/503 -> gpt-5.3-codex high retry
# ---------------------------------------------------------------------------


def _install_shim_with_sequence(
    tmp_path: Path,
    *,
    exit_codes: list[int],
    stderr_texts: list[str],
    log_path: Path | None = None,
) -> Path:
    """Install a fake ``codex`` shim whose exit code + stderr varies per call.

    Writes each invocation's exit code and stderr to a sequence state file so
    the shim can mimic a server returning 429 first, then success on retry.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "_shim_helper.py"
    helper_path.write_text(_SHIM_HELPER)
    state_file = bin_dir / "call_counter.txt"
    state_file.write_text("0")
    codes_file = bin_dir / "exit_codes.txt"
    codes_file.write_text("\n".join(str(c) for c in exit_codes) + "\n")
    stderr_file = bin_dir / "stderr_lines.txt"
    stderr_file.write_text("\n".join(stderr_texts) + "\n")
    log_file = log_path if log_path is not None else (tmp_path / "codex-calls.log")
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
    shim = bin_dir / "codex"
    shim.write_text(shim_body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


class TestHighTier429_503Fallback:
    """Non-default MODEL 429/503 retries once with gpt-5.3-codex + high."""

    def _run_sequence(
        self,
        tmp_path: Path,
        *,
        exit_codes: list[int],
        stderr_texts: list[str],
        effort: str = "high",
        model: str | None = "gpt-5.4",
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
        env["EFFORT"] = effort
        if model is not None:
            env["MODEL"] = model
        if extra_env:
            env.update(extra_env)
        try:
            result = _run_review(tmp_path, env_overrides=env, timeout=timeout)
            return result, _read_shim_log(log)
        finally:
            _QA_DIFF_PATH.unlink(missing_ok=True)

    def test_gpt54_429_retries_with_medium_tier(self, tmp_path: Path) -> None:
        """MODEL=gpt-5.4 + 429 -> second call MODEL=gpt-5.3-codex + -c ...=high."""
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: 429 Too Many Requests", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gpt-5.3-codex high" in result.stderr
        assert len(records) == 2
        first_argv = records[0]["argv"]
        second_argv = records[1]["argv"]
        assert "gpt-5.4" in first_argv
        assert "gpt-5.3-codex" in second_argv
        idx = second_argv.index("-c") + 1
        assert second_argv[idx] == "profiles.reviewer.model_reasoning_effort=high"

    def test_gpt54_503_retries_with_medium_tier(self, tmp_path: Path) -> None:
        """MODEL=gpt-5.4 + 503 -> same retry path."""
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: 503 Service Unavailable", ""],
            effort="xhigh",
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gpt-5.3-codex high" in result.stderr
        assert len(records) == 2

    def test_gpt54_connection_timeout_retries_with_medium_tier(self, tmp_path: Path) -> None:
        """MODEL=gpt-5.4 + connection timeout -> HIGH-tier fallback, not generic transient retry.

        TODO-0104: connection-layer failures against a non-default HIGH-tier
        model must route through the HIGH->MEDIUM fallback. Retrying the same
        unreachable model burns the single transient-retry slot without
        changing the outcome.
        """
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: connection timeout", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gpt-5.3-codex high" in result.stderr
        assert "timeout" in result.stderr
        assert len(records) == 2
        second_argv = records[1]["argv"]
        assert "gpt-5.3-codex" in second_argv
        idx = second_argv.index("-c") + 1
        assert second_argv[idx] == "profiles.reviewer.model_reasoning_effort=high"

    def test_gpt54_connection_refused_retries_with_medium_tier(self, tmp_path: Path) -> None:
        """MODEL=gpt-5.4 + connection refused -> HIGH-tier fallback (network class).

        TODO-0104 companion to the timeout case: asserts the ``network``
        branch of the broadened regex + _status_hit taxonomy.
        """
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: connection refused", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gpt-5.3-codex high" in result.stderr
        assert "network" in result.stderr
        assert len(records) == 2

    def test_gpt54_504_retries_with_medium_tier(self, tmp_path: Path) -> None:
        """MODEL=gpt-5.4 + 504 Gateway Timeout -> HIGH-tier fallback (5xx class).

        TODO-0104: 502/504 join 429/503 in the retryable-at-another-model
        family. Asserts the ``5xx`` branch of the broadened _status_hit
        taxonomy.
        """
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: 504 Gateway Timeout", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gpt-5.3-codex high" in result.stderr
        assert "5xx" in result.stderr
        assert len(records) == 2

    @pytest.mark.parametrize(
        ("stderr_text", "expected_bucket"),
        [
            # TODO-0124: previously-untested tokens in the existing Gate-1 regex.
            ("Error: deadline exceeded", "timeout"),
            ("Error: i/o timeout", "timeout"),
            ("Error: 502 Bad Gateway", "5xx"),
            ("Error: unexpected end of stream", "network"),
            ("Error: socket hang up", "network"),
            # TODO-0123: new tokens added to the Gate-1 regex.
            ("Error: connection reset by peer", "network"),
            ("Error: broken pipe while writing", "network"),
            ("Error: tls handshake failure", "network"),
            ("Error: dns lookup failed for api.openai.com", "network"),
            ("Error: no route to host", "network"),
            ("Error: upstream connect error or disconnect/reset before headers", "network"),
            # Cascade canary: "504 Gateway Timeout" matches both `504` and
            # `timeout`. 5xx precedence over timeout is load-bearing — if the
            # cascade order flips, this row flips bucket and fails here.
            ("Error: 504 Gateway Timeout", "5xx"),
            # Older alternations previously covered only by status-code tests;
            # lock the text-only forms so a future regex refactor that drops
            # one of these alternations is caught.
            ("Error: 503 Service Unavailable", "503"),
            ("Error: rate limit exceeded", "429"),
            ("Error: too many requests", "429"),
            ("Error: service unavailable", "503"),
            ("Error: network error encountered", "network"),
        ],
        ids=[
            "deadline_exceeded",
            "io_timeout",
            "502_bad_gateway",
            "unexpected_end_of_stream",
            "socket_hang_up",
            "reset_by_peer",
            "broken_pipe",
            "tls_handshake",
            "dns_lookup",
            "no_route_to_host",
            "upstream_connect_error",
            "504_cascade_canary",
            "503_status",
            "rate_limit_text",
            "too_many_requests_text",
            "service_unavailable_text",
            "network_error_text",
        ],
    )
    def test_parametrized_retryable_tokens_trigger_fallback(
        self,
        tmp_path: Path,
        stderr_text: str,
        expected_bucket: str,
    ) -> None:
        """All retryable-at-another-model tokens route through the HIGH->MEDIUM fallback.

        Locks the _status_hit taxonomy per token so a future regex tweak
        that accidentally drops a token is caught at test time. Covers
        TODO-0123 (new gateway/TLS/DNS/Envoy tokens) and TODO-0124
        (previously-untested tokens in the existing regex).
        """
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=[stderr_text, ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gpt-5.3-codex high" in result.stderr
        assert expected_bucket in result.stderr, f"expected _status_hit bucket {expected_bucket!r} in stderr; got {result.stderr!r}"
        assert len(records) == 2
        second_argv = records[1]["argv"]
        assert "gpt-5.3-codex" in second_argv

    def test_default_model_429_no_fallback(self, tmp_path: Path) -> None:
        """MODEL unset (default gpt-5.3-codex) + 429 -> no fallback.

        Generic transient retry path still fires (one retry), so 2 calls;
        but the stderr NOTICE for HIGH->MEDIUM fallback must NOT appear.
        """
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1, 1],
            stderr_texts=[
                "Error: 429 Too Many Requests",
                "Error: 429 Too Many Requests",
            ],
            model=None,
        )
        # Transient classification + retry exhausted; exit 0 per wrapper behavior.
        assert "falling back to gpt-5.3-codex" not in result.stderr
        assert len(records) == 2  # initial + transient retry

    def test_gpt54_auth_error_no_fallback(self, tmp_path: Path) -> None:
        """MODEL=gpt-5.4 + 401 -> terminal auth failure; no HIGH-tier retry."""
        _, records = self._run_sequence(
            tmp_path,
            exit_codes=[1],
            stderr_texts=["Error: 401 Unauthorized: bad token"],
        )
        assert len(records) == 1  # auth failure is terminal, no retries
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "auth" in exit_json

    def test_auth_error_invalidates_preflight_cache(self, tmp_path: Path) -> None:
        """Auth failure at execution time MUST delete the preflight cache."""
        cache_file = tmp_path / "codex-preflight-cache.json"
        cache_file.write_text('{"mode":"local","codex":{"cli":true}}\n')
        self._run_sequence(
            tmp_path,
            exit_codes=[1],
            stderr_texts=["Error: 401 Unauthorized: bad token"],
            extra_env={"PREFLIGHT_CACHE_FILE": str(cache_file)},
        )
        assert not cache_file.exists(), "preflight cache should be invalidated after auth failure"

    def test_missing_binary_invalidates_preflight_cache(self, tmp_path: Path) -> None:
        """``command not found`` also invalidates the preflight cache."""
        cache_file = tmp_path / "codex-preflight-cache.json"
        cache_file.write_text('{"mode":"local","codex":{"cli":true}}\n')
        self._run_sequence(
            tmp_path,
            exit_codes=[127],
            stderr_texts=["bash: codex: command not found"],
            extra_env={"PREFLIGHT_CACHE_FILE": str(cache_file)},
        )
        assert not cache_file.exists(), "preflight cache should be invalidated after missing-binary failure"
