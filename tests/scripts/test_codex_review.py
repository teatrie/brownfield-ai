"""Tests for ``scripts/agent-cli/codex-review.sh``.

The wrapper takes its subject as ``REVIEW_TYPE=<enum>`` +
``DIFF_FILE=<tmp-or-agent-review-path>``. Covered behaviors:

- Req-003: EFFORT enum validation and -c override composition.
- Req-003: MEDIUM effort -> HIGH model_reasoning_effort; max collapses to xhigh.
- Req-017: xhigh-rejection fail-closed behavior and opt-in fallback.
- Req-019: non-default MODEL 429/503 -> gpt-5.3-codex + high retry.
- REVIEW_TYPE / DIFF_FILE argument validation; the template is hardcoded by
  the wrapper; every review type dispatches a plain
  ``codex exec --ephemeral``.
- Startup signal hygiene: an unwritable ``tmp/`` aborts fatally, and no
  signal from an earlier invocation survives into a run that completes
  without writing one of its own.
- Container-routing slug validation: ``WORKSPACE`` / ``REVIEW_SESSION_ID``
  must carry no path separators before they are interpolated into the
  artifact paths the run writes and deletes.
- Output-artifact hygiene: every attempt starts from a cleared ``-o`` file,
  so no attempt can return a predecessor's partial review as its verdict.
- Auth-failure cache invalidation and missing-binary handling.

All tests use a PATH-prepended fake ``codex`` shim that captures argv plus
stdin to a log file, and run the wrapper from a throwaway workspace root
under ``tmp_path`` so no invocation writes into the real repository.
``DIFF_FILE``-level path-containment tests live in
``tests/scripts/test_wrapper_sanitation.py`` and are not duplicated here.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

WORKSPACE: Path = Path(__file__).resolve().parents[2]
REVIEW_SCRIPT: str = str(WORKSPACE / "scripts" / "agent-cli" / "codex-review.sh")

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

# Companion helper for the sequence shim: writes the caller-scripted payload
# to whatever path the wrapper passed to ``-o``. The base shim writes no
# output artifact at all, so on its own it cannot express the two cases a
# retry has to keep apart — an attempt that leaves a partial file behind
# before failing, and an attempt that exits zero having written nothing. A
# blank payload for a call means that call writes nothing.
_SHIM_OUTPUT_HELPER: str = """import sys

payloads_path = sys.argv[1]
call_index = int(sys.argv[2])
argv = sys.argv[3:]
with open(payloads_path, encoding="utf-8") as fh:
    payloads = fh.read().splitlines()
payload = payloads[call_index] if call_index < len(payloads) else ""
if payload and "-o" in argv:
    with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as out:
        out.write(payload + "\\n")
"""


def _workspace_root(tmp_path: Path) -> Path:
    """Return (creating on first use) the throwaway workspace root to run from.

    The wrapper resolves everything it writes — the exit signal, the stderr
    capture, the combined prompt, the sanitized subject and the review output
    — relative to its CWD or to the git toplevel ``_review_sanitize_subject``
    anchors to. The root therefore carries a ``.git`` of its own so that
    ``git rev-parse --show-toplevel`` resolves to the root itself instead of
    walking up out of ``tmp_path``; a ``TMPDIR`` pointed inside the real
    checkout would otherwise route the whole artifact set into it, and no
    assertion here would notice. ``HEAD`` plus ``objects/`` and ``refs/`` are
    the minimum git accepts as a repository — a bare empty ``.git`` is
    rejected and discovery continues upward.

    Reviewer templates are symlinked rather than copied: the wrapper loads
    the real ones, which is what ``TestTemplateIsHardcoded`` observes. The
    default diff subject is provisioned here too, so ``_default_env`` only
    has to name it.
    """
    ws = tmp_path / "ws"
    if ws.exists():
        return ws
    (ws / "tmp").mkdir(parents=True)
    (ws / "agent-review").mkdir()
    git_dir = ws / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    prompts = ws / ".claude" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "reviewer").symlink_to(WORKSPACE / ".claude" / "prompts" / "reviewer")
    (ws / "tmp" / "qa-diff.txt").write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n")
    return ws


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


def _default_env(bin_dir: Path, tmp_path: Path, *, review_type: str = "diff") -> dict[str, str]:
    """Build the minimal env the wrapper needs to reach the shim.

    Supplies the required ``REVIEW_TYPE``/``DIFF_FILE`` pair, the host
    execution context (so the token guard + OAuth path is exercised), and
    a token so the token-missing guard does not short-circuit. ``DIFF_FILE``
    names the subject ``_workspace_root`` provisions, so it always exists;
    the validation tests override or drop the variable afterwards.
    """
    subject = _workspace_root(tmp_path) / "tmp" / "qa-diff.txt"
    return {
        "REVIEW_TYPE": review_type,
        "DIFF_FILE": str(subject),
        "CODEX_EXECUTION_CONTEXT": "host",
        "OPENAI_API_KEY": "test",
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }


def _read_exit_json(tmp_path: Path) -> dict[str, object]:
    """Read and parse the wrapper's ``tmp/codex-exit.json`` if it exists."""
    path = _workspace_root(tmp_path) / "tmp" / "codex-exit.json"
    if not path.exists():
        return {}
    parsed: dict[str, object] = json.loads(path.read_text())
    return parsed


def _run_review(
    tmp_path: Path,
    env_overrides: dict[str, str],
    *,
    args: list[str] | None = None,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    """Execute the review script with a controlled environment.

    Tests pass an explicit ``PATH`` in ``env_overrides`` pointing at a shim.
    Never inherits the parent process env (determinism). The CWD is always
    the test's own workspace root — there is deliberately no override, so no
    test can direct the wrapper's writes at the real repository.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env: dict[str, str] = {
        "PATH": env_overrides.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        "HOME": str(home),
        # The wrapper's auth branch deletes this path outright, and the
        # wrapper's default resolves inside the real workspace tmp/ — the
        # developer's own preflight cache. Scoping it to tmp_path here
        # isolates every test by construction; the overlay below still lets a
        # cache-invalidation test point it somewhere it can observe.
        "PREFLIGHT_CACHE_FILE": str(tmp_path / "preflight-cache.json"),
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
        cwd=str(_workspace_root(tmp_path)),
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
        """Invoke the wrapper with the given EFFORT."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        if effort is not None:
            env["EFFORT"] = effort
        result = _run_review(tmp_path, env_overrides=env)
        return result, _read_shim_log(log)

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
        assert argv[argv.index("-c") + 1] == "model_reasoning_effort=high"

    def test_medium_maps_to_high(self, tmp_path: Path) -> None:
        """EFFORT=medium -> -c ...=high (MEDIUM tier at HIGH reasoning)."""
        result, records = self._run_with_effort(tmp_path, effort="medium")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-c") + 1] == "model_reasoning_effort=high"

    def test_xhigh_passthrough(self, tmp_path: Path) -> None:
        """EFFORT=xhigh -> -c ...=xhigh (raw passthrough)."""
        result, records = self._run_with_effort(tmp_path, effort="xhigh")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-c") + 1] == "model_reasoning_effort=xhigh"

    def test_max_collapses_to_xhigh(self, tmp_path: Path) -> None:
        """EFFORT=max collapses to -c ...=xhigh (ceiling collapse)."""
        result, records = self._run_with_effort(tmp_path, effort="max")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-c") + 1] == "model_reasoning_effort=xhigh"

    def test_low_rejected(self, tmp_path: Path) -> None:
        """EFFORT=low must be rejected — reviewer floor is MEDIUM tier (HIGH internal)."""
        result, records = self._run_with_effort(tmp_path, effort="low")
        assert result.returncode == 1
        assert "EFFORT" in result.stderr
        assert records == []

    def test_unset_effort_defaults_to_the_reviewer_floor(self, tmp_path: Path) -> None:
        """Unset EFFORT -> -c ...=high, the reviewer floor the enum enforces.

        Composing no -c would land the run on the CLI's own default, so the
        wrapper would refuse a named low tier while accepting no tier at all.
        """
        result, records = self._run_with_effort(tmp_path, effort=None)
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert "-c" in argv
        assert argv[argv.index("-c") + 1] == "model_reasoning_effort=high"


# ---------------------------------------------------------------------------
# Argument validation: REVIEW_TYPE / DIFF_FILE.
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
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        env.pop("REVIEW_TYPE")
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("signal") == "CODEX_ERROR"
        assert exit_json.get("error_class") == "arg_validation"

    def test_invalid_review_type_enum_rejected(self, tmp_path: Path) -> None:
        """REVIEW_TYPE=foo (not in enum) -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path, review_type="foo")
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("error_class") == "arg_validation"


class TestDiffFileValidation:
    """Wrapper rejects missing / empty / out-of-root DIFF_FILE."""

    def test_missing_diff_file_rejected(self, tmp_path: Path) -> None:
        """Unset DIFF_FILE -> arg_validation rejection, shim never called."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        env.pop("DIFF_FILE")
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("error_class") == "arg_validation"

    def test_nonexistent_diff_file_rejected(self, tmp_path: Path) -> None:
        """DIFF_FILE pointing at a missing path -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        env["DIFF_FILE"] = "tmp/does-not-exist.txt"
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("error_class") == "arg_validation"

    def test_zero_byte_diff_file_rejected(self, tmp_path: Path) -> None:
        """Zero-byte DIFF_FILE -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        empty = _workspace_root(tmp_path) / "tmp" / "empty-subject.txt"
        empty.touch()
        env["DIFF_FILE"] = str(empty)
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("error_class") == "arg_validation"

    def test_diff_file_outside_tmp_rejected(self, tmp_path: Path) -> None:
        """DIFF_FILE outside tmp/ or agent-review/ -> arg_validation rejection.

        The subject sits beside the workspace root rather than inside its
        ``tmp/``, which is the containment boundary the wrapper enforces.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        outside = tmp_path / "outside-the-root.txt"
        outside.write_text("evil\n")
        env["DIFF_FILE"] = str(outside)
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode != 0
        assert _read_shim_log(log) == []


class TestReviewTypeDispatch:
    """Every REVIEW_TYPE dispatches an ephemeral plain ``exec``.

    ``codex exec review`` takes its subject from the live working-tree diff,
    and its ``[PROMPT]`` argument carries no implicit-stdin clause — a piped
    prompt is discarded rather than read. The combined template + DIFF_FILE
    prompt on stdin is the sole subject channel for every review type, which
    means plain ``codex exec -p reviewer`` for every review type.

    ``--ephemeral`` is asserted on the same dispatch because retention is a
    property of it: the flag is what keeps the reviewed diff, the reviewer
    prompt and the agent's tool trace out of codex session storage. It rides
    on ``exec`` itself, so it does not depend on the subcommand chosen.

    The stdin assertion is what makes the argv shape mean something: an
    argv that omits ``review`` while delivering nothing on stdin is a
    reviewer running with no criteria and no subject, which the argv
    checks alone would accept.
    """

    _PREAMBLE_MARKER: str = "<!-- INVARIANT:preamble start -->"

    def _run(
        self,
        tmp_path: Path,
        *,
        review_type: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Invoke the wrapper with the given REVIEW_TYPE.

        Every type resolves its template through the workspace's symlinked
        ``.claude/prompts/reviewer/``, so the real ``<type>.md`` is loaded
        without the run touching the repository.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path, review_type=review_type)
        result = _run_review(tmp_path, env_overrides=env)
        return result, _read_shim_log(log)

    @pytest.mark.parametrize(
        "review_type",
        ["diff", "plan", "spec", "epic", "spec-req-verification"],
    )
    def test_every_review_type_dispatches_ephemeral_plain_exec_with_reviewer_profile(
        self,
        tmp_path: Path,
        review_type: str,
    ) -> None:
        result, records = self._run(tmp_path, review_type=review_type)
        assert result.returncode == 0, result.stderr
        assert records, "shim was not invoked"
        argv = records[0]["argv"]
        assert "review" not in argv, f"REVIEW_TYPE={review_type!r} must not invoke `review`; it discards the piped prompt. argv={argv!r}"
        assert "--base" not in argv, f"REVIEW_TYPE={review_type!r} must not pass --base; argv={argv!r}"
        assert "--ephemeral" in argv, (
            f"REVIEW_TYPE={review_type!r} must pass --ephemeral; without it the reviewed diff, the prompt and the tool trace persist to codex session storage. argv={argv!r}"
        )
        assert "-p" in argv and argv[argv.index("-p") + 1] == "reviewer"
        stdin_payload = records[0]["stdin"]
        assert self._PREAMBLE_MARKER in stdin_payload, (
            f"REVIEW_TYPE={review_type!r} must deliver the reviewer template on stdin — it is the sole subject channel, so a dispatch that pipes nothing reviews nothing. stdin={stdin_payload[:200]!r}"
        )
        assert "diff --git" in stdin_payload, (
            f"REVIEW_TYPE={review_type!r} must deliver the DIFF_FILE contents on stdin; stdin={stdin_payload[:200]!r}"
        )


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
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode == 0, result.stderr
        records = _read_shim_log(log)
        assert records, "shim was never invoked"
        # The stub reads stdin unconditionally; the real `review`
        # subcommand does not, so a stdin assertion against that
        # dispatch would pass while the prompt was being discarded.
        argv = records[0]["argv"]
        assert "review" not in argv, f"stdin is only a real channel on the plain `exec` dispatch; argv={argv!r}"
        # Template loaded from .claude/prompts/reviewer/diff.md and
        # concatenated with the sanitized subject.
        assert self._TEMPLATE_MARKER in records[0]["stdin"]
        # Subject data also present.
        assert "diff --git" in records[0]["stdin"]


class TestRoundValidation:
    """Wrapper rejects non-positive-integer ROUND before codex."""

    def test_round_zero_rejected(self, tmp_path: Path) -> None:
        """``--round 0`` -> arg_validation JSON, non-zero exit."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        result = _run_review(tmp_path, env_overrides=env, args=["--round", "0"])
        assert result.returncode == 1
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("signal") == "CODEX_ERROR", (
            f"every rejection path carries its own signal literal — there is no shared emitter — so no other rejection's assertion covers this one; got {exit_json!r}"
        )
        assert exit_json.get("error_class") == "arg_validation"

    def test_round_non_numeric_rejected(self, tmp_path: Path) -> None:
        """``--round abc`` -> arg_validation JSON, non-zero exit."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        result = _run_review(tmp_path, env_overrides=env, args=["--round", "abc"])
        assert result.returncode == 1
        assert _read_shim_log(log) == []


class TestRetiredFlagRejection:
    """``--base`` is not a wrapper flag; the parser's catch-all owns it.

    The dispatch tests assert ``--base`` is absent from the *codex* argv, which
    a wrapper that accepted the flag and dropped it would also satisfy. This
    asserts the stronger property: the wrapper refuses the invocation, and
    refuses it the way the enum and validation rejections report themselves —
    with an ``arg_validation`` signal a caller can read, not a bare exit code.
    """

    def test_base_flag_exits_with_usage_before_reaching_codex(self, tmp_path: Path) -> None:
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        result = _run_review(tmp_path, env_overrides=env, args=["--base", "main"])
        assert result.returncode == 1
        assert "Usage:" in result.stderr
        assert _read_shim_log(log) == [], "an unknown flag must abort before the CLI is invoked"
        assert _read_exit_json(tmp_path).get("error_class") == "arg_validation"


class TestUnwritableTmpAbortsWithAFatalDiagnostic:
    """An unwritable ``tmp/`` must abort at startup, saying so.

    ``tmp/codex-exit.json`` is the only channel the wrapper has for
    reporting an outcome, so a run that cannot write it has no way to
    report anything — including the fact that it could not report. Neither
    startup statement around the probe observes the condition: ``mkdir -p``
    succeeds on an existing directory whatever its mode, and ``rm -f``
    succeeds on an absent operand even under a read-only parent. Without an
    explicit write probe the run proceeds until the first write fails, and
    under ``set -e`` that is a bare non-zero exit with no message and no
    signal — indistinguishable from a crash.

    The chmod is safe here only because ``_workspace_root`` provisions a
    throwaway root under ``tmp_path``; the mode is restored before the
    assertions so the fixture teardown is never left a read-only tree.
    """

    @pytest.mark.skipif(
        os.geteuid() == 0,
        reason="root bypasses the write bit, so chmod cannot make tmp/ unwritable and the probe under test would succeed",
    )
    def test_unwritable_tmp_aborts_before_the_cli_with_a_writability_message(self, tmp_path: Path) -> None:
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        workspace_tmp = _workspace_root(tmp_path) / "tmp"
        original_mode = stat.S_IMODE(workspace_tmp.stat().st_mode)
        workspace_tmp.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            result = _run_review(tmp_path, env_overrides=env)
        finally:
            workspace_tmp.chmod(original_mode)
        assert result.returncode == 1, f"an unwritable tmp/ must abort with exit 1; got {result.returncode} with stderr={result.stderr!r}"
        assert "FATAL" in result.stderr and "not writable" in result.stderr, (
            f"the abort must name the condition — a bare non-zero exit from the first failed write leaves the caller with no verdict and no reason. stderr={result.stderr!r}"
        )
        assert _read_shim_log(log) == [], (
            "the run must abort before the CLI is invoked; a review whose outcome cannot be recorded must not be paid for"
        )


class TestStaleExitSignalCannotBeReadAsThisRunsVerdict:
    """A signal left by an earlier invocation must not outlive it.

    ``tmp/codex-exit.json`` is the wrapper's only machine-readable verdict,
    and a successful run writes nothing to it. A signal from an earlier
    invocation therefore stays on disk, and whoever reads it next attributes
    it to the run that just finished — a completed review sitting beside a
    ``CODEX_ERROR`` from an attempt that failed before it, distinguishable
    only by mtime. Clearing the file at startup is what prevents that, and it
    is observable only against a signal planted before the wrapper runs.
    """

    _STALE_CLASS: str = "signal_from_an_earlier_invocation"

    def _plant_stale_signal(self, tmp_path: Path) -> Path:
        """Write a prior-run signal carrying a class no path in this run emits.

        Planted after the workspace and env are built, so the harness's own
        setup cannot be what removes it and the assertion can only be
        satisfied by the wrapper itself.
        """
        path = _workspace_root(tmp_path) / "tmp" / "codex-exit.json"
        path.write_text(
            json.dumps({
                "signal": "CODEX_ERROR",
                "exit_code": 9,
                "retried": False,
                "error_class": self._STALE_CLASS,
                "stderr_excerpt": "left behind by an earlier invocation",
            })
            + "\n"
        )
        return path

    def test_successful_run_does_not_leave_a_prior_signal_readable(self, tmp_path: Path) -> None:
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        stale = self._plant_stale_signal(tmp_path)
        assert stale.exists(), "precondition: the stale signal must be on disk before the wrapper starts"
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode == 0, result.stderr
        assert _read_shim_log(log), "the CLI must have been reached; otherwise this is not the success path"
        assert not stale.exists(), (
            "a successful run writes no signal of its own, so the startup clear must have removed the earlier invocation's file outright; anything left on disk is readable as this run's verdict"
        )

    @pytest.mark.parametrize(
        ("extra_env", "first_stderr", "expected_notice"),
        [
            (
                {"MODEL": "gpt-5.4", "EFFORT": "high"},
                "Error: 429 Too Many Requests",
                "falling back to gpt-5.3-codex high",
            ),
            (
                {"EFFORT": "xhigh", "EFFORT_FALLBACK_ON_REJECT": "1"},
                "Error: unknown variant xhigh for model_reasoning_effort",
                "retrying once with EFFORT=high",
            ),
            ({}, "Error: connection timeout", ""),
        ],
        ids=["high_tier_fallback", "xhigh_fallback", "transient_retry"],
    )
    def test_a_run_that_succeeds_on_retry_does_not_leave_a_prior_signal_readable(
        self,
        tmp_path: Path,
        extra_env: dict[str, str],
        first_stderr: str,
        expected_notice: str,
    ) -> None:
        """Every exit that completes without a signal of its own must land on a cleared file.

        Three exits reach success only after the first call failed — the
        HIGH-tier fallback, the xhigh-rejection fallback and the transient
        retry — and each writes a signal on the failure branch it did not
        take, so on success it leaves ``tmp/codex-exit.json`` untouched
        exactly as the plain first-call success does. Each is driven here by
        a sequence shim scripted fail-then-succeed, with the failure stderr
        selecting which branch handles it; ``expected_notice`` pins that
        selection so a run that silently took a different path than the one
        it is named for cannot satisfy the planted-signal assertion by
        accident.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim_with_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=[first_stderr, ""],
            log_path=log,
        )
        env = _default_env(bin_dir, tmp_path)
        env.update(extra_env)
        stale = self._plant_stale_signal(tmp_path)
        assert stale.exists(), "precondition: the stale signal must be on disk before the wrapper starts"
        # The transient branch sleeps 5s before its retry.
        result = _run_review(tmp_path, env_overrides=env, timeout=40)
        assert result.returncode == 0, result.stderr
        records = _read_shim_log(log)
        assert len(records) == 2, (
            f"expected an initial call plus one retry, got {len(records)}; without both this is not the retry-success path"
        )
        if expected_notice:
            assert expected_notice in result.stderr, f"expected the run to take the branch under test; stderr={result.stderr!r}"
        else:
            assert "falling back to gpt-5.3-codex" not in result.stderr, (
                f"the transient row must reach success through the same-model retry, not the HIGH-tier fallback; stderr={result.stderr!r}"
            )
        assert not stale.exists(), (
            "this exit writes no signal of its own, so the earlier invocation's file must have been removed at startup; anything left on disk is readable as this run's verdict"
        )


class TestOutputFromAnEarlierAttemptCannotBeReadAsTheRetrysVerdict:
    """Every attempt must begin from a cleared ``-o`` artifact, not just the first.

    The output path is round-stamped, so it is reused across attempts within a
    run and across runs at the same round, and codex can exit zero without
    writing ``-o`` at all — the wrapper's closing non-empty check then reports
    on whatever happens to be at that path. A failing attempt that left a
    partial file behind is the dangerous case: unless the attempt that follows
    it clears the path first, the retry's success is credited with its
    predecessor's truncated review, and the run exits zero pointing at it.

    Each row drives one of the three places a retry re-enters the CLI. The
    scripted shim writes a partial file on the attempt that fails and nothing
    at all on the attempt that succeeds, which is the only shape that tells
    "cleared before the retry" apart from "the retry rewrote it anyway".
    """

    _EARLIER_ROUND_PAYLOAD: str = "verdict written at this path by an earlier run"
    _PARTIAL_PAYLOAD: str = "truncated verdict from the attempt that failed"

    @pytest.mark.parametrize(
        ("extra_env", "first_stderr"),
        [
            ({"MODEL": "gpt-5.4", "EFFORT": "high"}, "Error: 429 Too Many Requests"),
            ({"EFFORT": "xhigh", "EFFORT_FALLBACK_ON_REJECT": "1"}, "Error: unknown variant xhigh for model_reasoning_effort"),
            ({}, "Error: connection timeout"),
        ],
        ids=["high_tier_fallback", "xhigh_fallback", "transient_retry"],
    )
    def test_a_retry_that_writes_no_output_reports_empty_not_the_failed_attempts_file(
        self,
        tmp_path: Path,
        extra_env: dict[str, str],
        first_stderr: str,
    ) -> None:
        log = tmp_path / "calls.log"
        bin_dir = _install_shim_with_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=[first_stderr, ""],
            log_path=log,
            output_payloads=[self._PARTIAL_PAYLOAD, ""],
        )
        env = _default_env(bin_dir, tmp_path)
        env.update(extra_env)
        # Host routing, ROUND=1 — the path _default_env's context selects.
        output_file = _workspace_root(tmp_path) / "tmp" / "codex-review-output-1.md"
        output_file.write_text(self._EARLIER_ROUND_PAYLOAD + "\n")
        # The transient branch sleeps 5s before its retry.
        result = _run_review(tmp_path, env_overrides=env, timeout=40)
        assert result.returncode == 0, result.stderr
        records = _read_shim_log(log)
        assert len(records) == 2, (
            f"expected an initial call plus one retry, got {len(records)}; without both this is not the retry-success path"
        )
        surviving = output_file.read_text() if output_file.exists() else ""
        assert self._PARTIAL_PAYLOAD not in surviving, (
            f"the successful attempt wrote no output, so the failed attempt's partial file must have been cleared before it ran; surviving output={surviving!r}"
        )
        assert self._EARLIER_ROUND_PAYLOAD not in surviving, (
            f"an earlier run's review at the same round-stamped path must not be returned as this run's; surviving output={surviving!r}"
        )
        assert "Codex produced empty output" in result.stderr, (
            f"with nothing written by the successful attempt the run must report empty output; a warning-free exit means the non-empty check read someone else's file. stderr={result.stderr!r}"
        )

    def test_a_retry_that_writes_output_keeps_its_own(self, tmp_path: Path) -> None:
        log = tmp_path / "calls.log"
        bin_dir = _install_shim_with_sequence(
            tmp_path,
            exit_codes=[1, 0],
            stderr_texts=["Error: connection timeout", ""],
            log_path=log,
            output_payloads=[self._PARTIAL_PAYLOAD, "the verdict this run actually produced"],
        )
        env = _default_env(bin_dir, tmp_path)
        output_file = _workspace_root(tmp_path) / "tmp" / "codex-review-output-1.md"
        output_file.write_text(self._EARLIER_ROUND_PAYLOAD + "\n")
        result = _run_review(tmp_path, env_overrides=env, timeout=40)
        assert result.returncode == 0, result.stderr
        assert len(_read_shim_log(log)) == 2
        assert output_file.read_text().strip() == "the verdict this run actually produced", (
            "clearing before each attempt must not cost the successful attempt its own output"
        )
        assert "Codex produced empty output" not in result.stderr, (
            f"a run that produced output must not warn about empty output; stderr={result.stderr!r}"
        )


class TestTokenAndSecretGuards:
    """The token guard fires only where both of its conditions hold.

    A missing ``OPENAI_API_KEY`` is unavailability only outside host context;
    under ``CODEX_EXECUTION_CONTEXT=host`` the CLI authenticates from its own
    OAuth store, so the same env is the ordinary local invocation. Both sides
    are pinned here because only the pair distinguishes the guard from a
    token check that ignores context — one that would report every local
    developer run as ``CODEX_UNAVAILABLE`` without ever reaching the CLI,
    while still satisfying the non-host case below.

    The secrets guard this class is also named for fires on a readable
    ``/app/.env``, an absolute path no fixture under ``tmp_path`` can create
    or displace.
    """

    def test_token_missing_emits_unavailable_signal(self, tmp_path: Path) -> None:
        """Non-host context without OPENAI_API_KEY -> CODEX_UNAVAILABLE, exit 0."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        env.pop("OPENAI_API_KEY")
        env.pop("CODEX_EXECUTION_CONTEXT")
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode == 0, result.stderr
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("signal") == "CODEX_UNAVAILABLE"
        assert exit_json.get("reason") == "token_missing"

    def test_host_context_reaches_the_cli_without_a_token(self, tmp_path: Path) -> None:
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        env.pop("OPENAI_API_KEY")
        result = _run_review(tmp_path, env_overrides=env)
        assert result.returncode == 0, result.stderr
        assert _read_shim_log(log), (
            "host context authenticates through the CLI's own OAuth store, so the run must reach codex with no token in the environment; an empty log is the guard firing on a run it does not own"
        )
        signal = _workspace_root(tmp_path) / "tmp" / "codex-exit.json"
        assert not signal.exists(), (
            "a host run that reaches the CLI and completes writes no signal of its own, so the startup clear must leave nothing behind; a file here — CODEX_UNAVAILABLE above all — is a verdict this run never reached"
        )


class TestOutputRouting:
    """Container vs host artifact routing (agent-review/ vs tmp/).

    The output path is observable through the shim's argv capture; the stderr
    capture is not — ``ERR_FILE`` is a shell redirection, so it reaches no
    argv and is observable only as the file it leaves on disk. Both
    directories exist in the test's own workspace root, so neither branch
    writes into the repo (which may also be read-only inside the pytest
    container).
    """

    def _run(
        self,
        tmp_path: Path,
        *,
        review_session_id: str | None = None,
        workspace: str | None = None,
        container_context: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Run the wrapper for routing assertions under either context."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        if container_context:
            env.pop("CODEX_EXECUTION_CONTEXT")
        if review_session_id:
            env["REVIEW_SESSION_ID"] = review_session_id
        if workspace:
            env["WORKSPACE"] = workspace
        result = _run_review(tmp_path, env_overrides=env)
        return result, _read_shim_log(log)

    def test_host_context_writes_to_tmp(self, tmp_path: Path) -> None:
        """``CODEX_EXECUTION_CONTEXT=host`` -> ``-o tmp/codex-review-output-<ROUND>.md``."""
        result, records = self._run(tmp_path)
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert "-o" in argv
        out_arg = argv[argv.index("-o") + 1]
        assert out_arg == "tmp/codex-review-output-1.md"
        err_file = _workspace_root(tmp_path) / "tmp" / "codex-review-err.txt"
        assert err_file.is_file(), (
            f"host mode must route the stderr capture into tmp/ — ERR_FILE is a shell redirection, so it reaches no argv and the -o assertion above cannot see it, while the agent-review/ check below stays green if it is renamed to any other tmp/ path. Presence is the whole of the check: `2>|` creates and truncates its target before the command is looked up, so a run that succeeds silently leaves the file empty and any non-empty assertion would fail on the ordinary green path. expected={err_file}"
        )
        assert list((_workspace_root(tmp_path) / "agent-review").iterdir()) == [], (
            "host mode must leave agent-review/ untouched — per docker-compose.yml the agent-cli service bind-mounts the host's ~/.brownfield-ai/agent-review onto /app/agent-review read-write while the checkout itself is mounted read-only, so a stderr capture routed there is host-persistent and shared with every other workspace using that mount rather than scoped to this run"
        )

    def test_container_context_writes_to_agent_review(self, tmp_path: Path) -> None:
        """Container context -> ``-o agent-review/<workspace>-codex-review-output-<session>.md``."""
        result, records = self._run(
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


class TestRoutingValuesMustBeSlugsBeforeTheyBecomePaths:
    """``WORKSPACE`` and ``REVIEW_SESSION_ID`` are rejected unless separator-free.

    Both are caller-supplied and both are interpolated into the container-mode
    artifact paths the run creates, writes and deletes — including the ``rm -f``
    that clears the output artifact before each attempt. The shared
    ``cli-args-to-env.sh`` shim admits ``/`` and ``.`` in values (``DIFF_FILE``
    needs them), so a traversal-shaped value arrives at the wrapper intact and
    the slug check here is the only thing standing between it and a delete
    aimed outside ``agent-review/``.

    The parametrized values are exactly the shapes that shim admits. The
    positive case is what stops the check from being "fixed" by narrowing it
    until the real container caller no longer routes.
    """

    _TRAVERSAL_VALUES: tuple[str, ...] = ("../evil", "a/b", "./x", "tmp/victim")

    def _run(
        self,
        tmp_path: Path,
        *,
        workspace: str | None = None,
        review_session_id: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        """Run the wrapper in container-routing mode, as ``TestOutputRouting`` does."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, tmp_path)
        env.pop("CODEX_EXECUTION_CONTEXT")
        if workspace is not None:
            env["WORKSPACE"] = workspace
        if review_session_id is not None:
            env["REVIEW_SESSION_ID"] = review_session_id
        result = _run_review(tmp_path, env_overrides=env)
        return result, _read_shim_log(log)

    def _assert_rejected(
        self,
        tmp_path: Path,
        result: subprocess.CompletedProcess[str],
        records: list[dict],
        *,
        variable: str,
        value: str,
    ) -> None:
        """Assert the run refused ``variable=value`` before spending a CLI call."""
        assert result.returncode != 0, f"{variable}={value!r} must abort; got exit 0 with stderr={result.stderr!r}"
        assert records == [], (
            f"{variable}={value!r} must be refused before the CLI is invoked — once codex runs, the interpolated path has already been created and cleared. records={records!r}"
        )
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("signal") == "CODEX_ERROR", f"{variable}={value!r} must report a readable signal; got {exit_json!r}"
        assert exit_json.get("error_class") == "arg_validation", (
            f"{variable}={value!r} must be classified as arg_validation so the caller can tell a rejected input from a failed review; got {exit_json!r}"
        )

    @pytest.mark.parametrize("value", _TRAVERSAL_VALUES)
    def test_traversal_shaped_workspace_is_rejected(self, tmp_path: Path, value: str) -> None:
        result, records = self._run(tmp_path, workspace=value)
        self._assert_rejected(tmp_path, result, records, variable="WORKSPACE", value=value)

    @pytest.mark.parametrize("value", _TRAVERSAL_VALUES)
    def test_traversal_shaped_review_session_id_is_rejected(self, tmp_path: Path, value: str) -> None:
        result, records = self._run(tmp_path, review_session_id=value)
        self._assert_rejected(tmp_path, result, records, variable="REVIEW_SESSION_ID", value=value)

    def test_slug_workspace_and_session_id_still_route_to_agent_review(self, tmp_path: Path) -> None:
        result, records = self._run(tmp_path, workspace="brownfield-ai", review_session_id="a1b2c3d4")
        assert result.returncode == 0, result.stderr
        assert records, "the legitimate container caller must still reach the CLI"
        argv = records[0]["argv"]
        assert argv[argv.index("-o") + 1] == "agent-review/brownfield-ai-codex-review-output-a1b2c3d4.md", (
            f"the hyphenated workspace name and the hex session id the container caller supplies must survive validation; argv={argv!r}"
        )


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
        """Install a simple fail-shim and run the wrapper."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(
            tmp_path,
            exit_code=1,
            stderr_text=stderr_text,
            log_path=log,
        )
        env = _default_env(bin_dir, tmp_path)
        env["EFFORT"] = "xhigh"
        if extra_env:
            env.update(extra_env)
        result = _run_review(tmp_path, env_overrides=env, timeout=30)
        return result, _read_shim_log(log)

    def test_xhigh_rejected_no_opt_in_fail_closed(self, tmp_path: Path) -> None:
        """xhigh rejected, opt-in unset -> non-zero exit, no retry."""
        result, records = self._run_with_xhigh_stderr(tmp_path, stderr_text=self._XHIGH_REJECT_STDERR)
        assert result.returncode != 0
        assert len(records) == 1, f"expected 1 shim call, got {len(records)}"
        assert _read_exit_json(tmp_path).get("error_class") == "xhigh_rejected"

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
        assert first_argv[first_argv.index("-c") + 1] == "model_reasoning_effort=xhigh"
        assert second_argv[second_argv.index("-c") + 1] == "model_reasoning_effort=high"
        assert not any("xhigh" in t for t in second_argv)
        assert _read_exit_json(tmp_path).get("error_class") == "xhigh_fallback_failed"

    def test_max_rejected_opt_in_retries_with_high(self, tmp_path: Path) -> None:
        """EFFORT=max (collapsed to xhigh) rejection also triggers opt-in retry."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(
            tmp_path,
            exit_code=1,
            stderr_text=self._XHIGH_REJECT_STDERR,
            log_path=log,
        )
        env = _default_env(bin_dir, tmp_path)
        env["EFFORT"] = "max"
        env["EFFORT_FALLBACK_ON_REJECT"] = "1"
        result = _run_review(tmp_path, env_overrides=env, timeout=30)
        assert result.returncode != 0
        records = _read_shim_log(log)
        assert len(records) == 2, f"expected 2 shim calls, got {len(records)}"
        assert "NOTICE" in result.stderr

    def test_non_xhigh_rejection_with_opt_in_still_fail_closed(self, tmp_path: Path) -> None:
        """Non-xhigh rejection with opt-in must not retry via the xhigh path.

        The opt-in narrowly targets the xhigh-reject class. Generic transient
        errors follow the transient-retry path (one retry).
        """
        result, records = self._run_with_xhigh_stderr(
            tmp_path,
            stderr_text="Error: connection timeout",
            extra_env={"EFFORT_FALLBACK_ON_REJECT": "1"},
        )
        assert result.returncode == 0, (
            f"an exhausted transient retry reports itself through the signal and exits 0; stderr={result.stderr!r}"
        )
        assert len(records) == 2, f"expected 2 shim calls (initial + transient retry), got {len(records)}"
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("signal") == "CODEX_ERROR"
        assert exit_json.get("error_class") == "transient"
        assert exit_json.get("retried") is True, (
            f"the retry the two shim calls prove happened must also be reported, or a caller reading retried:false re-dispatches into the same outage; got {exit_json!r}"
        )


# ---------------------------------------------------------------------------
# Req-019: non-default MODEL 429/503 -> gpt-5.3-codex high retry
# ---------------------------------------------------------------------------


def _install_shim_with_sequence(
    tmp_path: Path,
    *,
    exit_codes: list[int],
    stderr_texts: list[str],
    log_path: Path | None = None,
    output_payloads: list[str] | None = None,
) -> Path:
    """Install a fake ``codex`` shim whose exit code + stderr varies per call.

    Writes each invocation's exit code and stderr to a sequence state file so
    the shim can mimic a server returning 429 first, then success on retry.

    ``output_payloads`` optionally scripts what each call writes to its ``-o``
    path; a blank entry (or a call past the end of the list) writes nothing,
    which is what every other caller here gets.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "_shim_helper.py"
    helper_path.write_text(_SHIM_HELPER)
    output_line = ""
    if output_payloads is not None:
        output_helper_path = bin_dir / "_shim_output_helper.py"
        output_helper_path.write_text(_SHIM_OUTPUT_HELPER)
        payloads_file = bin_dir / "output_payloads.txt"
        payloads_file.write_text("\n".join(output_payloads) + "\n")
        output_line = f'python3 {output_helper_path!s} {payloads_file!s} "$_n" "$@"\n'
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
        f"{output_line}"
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
        """Install a sequence-shim and invoke the wrapper."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim_with_sequence(
            tmp_path,
            exit_codes=exit_codes,
            stderr_texts=stderr_texts,
            log_path=log,
        )
        env = _default_env(bin_dir, tmp_path)
        env["EFFORT"] = effort
        if model is not None:
            env["MODEL"] = model
        if extra_env:
            env.update(extra_env)
        result = _run_review(tmp_path, env_overrides=env, timeout=timeout)
        return result, _read_shim_log(log)

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
        assert second_argv[idx] == "model_reasoning_effort=high"

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

        Connection-layer failures against a non-default HIGH-tier model route
        through the HIGH->MEDIUM fallback: retrying the same unreachable model
        would burn the single transient-retry slot without changing the
        outcome.
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
        assert second_argv[idx] == "model_reasoning_effort=high"

    def test_gpt54_connection_refused_retries_with_medium_tier(self, tmp_path: Path) -> None:
        """MODEL=gpt-5.4 + connection refused -> HIGH-tier fallback (network class).

        Companion to the timeout case: asserts the ``network`` branch of the
        _status_hit taxonomy.
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

        502/504 belong to the retryable-at-another-model family alongside
        429/503. Asserts the ``5xx`` branch of the _status_hit taxonomy.
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
            ("Error: deadline exceeded", "timeout"),
            ("Error: i/o timeout", "timeout"),
            ("Error: 502 Bad Gateway", "5xx"),
            ("Error: unexpected end of stream", "network"),
            ("Error: socket hang up", "network"),
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
            # Text-only forms of the status alternations: a regex refactor
            # that drops one of them is caught here rather than only by the
            # status-code rows above.
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

        Locks the _status_hit taxonomy per token — gateway, TLS, DNS and
        Envoy shapes included — so a regex tweak that drops a token is
        caught at test time.
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
        assert second_argv[second_argv.index("-c") + 1] == "model_reasoning_effort=high"

    def test_default_model_429_no_fallback(self, tmp_path: Path) -> None:
        """MODEL unset (no -m passed) + 429 -> no HIGH-tier fallback.

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
        result, records = self._run_sequence(
            tmp_path,
            exit_codes=[1],
            stderr_texts=["Error: 401 Unauthorized: bad token"],
        )
        assert result.returncode == 0, f"a classified auth failure exits 0 having written its signal; stderr={result.stderr!r}"
        assert len(records) == 1  # auth failure is terminal, no retries
        exit_json = _read_exit_json(tmp_path)
        assert exit_json.get("signal") == "CODEX_ERROR"
        assert exit_json.get("error_class") == "auth"
        assert exit_json.get("retried") is False, (
            f"the auth path is terminal, so the single call it spent must be reported as unretried; got {exit_json!r}"
        )

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
