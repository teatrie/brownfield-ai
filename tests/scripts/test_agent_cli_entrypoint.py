"""Tests for the agent-cli entrypoint.sh allowlist and the scripts it dispatches to.

Invokes the entrypoint shell script directly via subprocess on the host.
Allowed commands dispatch to /usr/local/bin/<cmd>.sh which does not exist
on the host, so allowed commands fail at exec time -- tests verify that the
entrypoint validation layer itself did not reject the command.  Blocked
commands are rejected by the entrypoint with exit 1 and "ERROR" in stderr.
"""

from __future__ import annotations

import glob
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
ENTRYPOINT = str(WORKSPACE / "docker" / "agent-cli" / "entrypoint.sh")

# Canonical home of the adversarial-rigor / experiment-delegation block.
# Template content is lint-enforced against this source of truth (see
# scripts/lint_reviewer_templates.py + tests/scripts/test_reviewer_templates.py).
REVIEWER_INVARIANTS = WORKSPACE / ".claude" / "prompts" / "reviewer" / "_invariants.md"


def _run_entrypoint(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the entrypoint with the given arguments."""
    return subprocess.run(
        ["bash", ENTRYPOINT, *args],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(WORKSPACE),
    )


# ---------------------------------------------------------------------------
# 1. Command allowlist
# ---------------------------------------------------------------------------


class TestCommandAllowlist:
    """Verify entrypoint command dispatch: allowed vs blocked commands."""

    @pytest.mark.parametrize("cmd", ["copilot-review", "gemini-review", "codex-review", "preflight"])
    def test_allowed_command_not_rejected_by_allowlist(self, cmd: str) -> None:
        """Allowed commands must not trigger the allowlist error message."""
        result = _run_entrypoint(cmd)
        assert "unknown command" not in result.stderr

    @pytest.mark.parametrize(
        "cmd",
        ["bash", "sh", "node", "python3", "cat", "hack-something"],
    )
    def test_blocked_command_exits_1(self, cmd: str) -> None:
        """Non-allowlisted commands must exit 1 with ERROR in stderr."""
        result = _run_entrypoint(cmd)
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_empty_command_exits_1(self) -> None:
        """Empty command (no arguments) must exit 1 with ERROR in stderr."""
        result = _run_entrypoint()
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_random_string_blocked(self) -> None:
        """Arbitrary random string must be rejected."""
        result = _run_entrypoint("xyzzy-not-a-command")
        assert result.returncode == 1
        assert "ERROR" in result.stderr


# ---------------------------------------------------------------------------
# 2. Subject handling is not the entrypoint's concern
# ---------------------------------------------------------------------------
# The entrypoint is a thin command-allowlist dispatcher: it carries no
# ``--prompt-file`` parse/sandbox/export step, and per-wrapper flags such as
# ``--round`` and ``--model`` reach the wrapper by argv pass-through. The
# review subject travels as ``DIFF_FILE``, whose tmp/ and agent-review/
# containment is enforced downstream by
# ``_review-common.sh::_review_validate_diff_file`` and covered in
# ``tests/scripts/test_wrapper_sanitation.py`` — hence no tests here.


# ---------------------------------------------------------------------------
# 3. Prompt template content (Req-008)
# ---------------------------------------------------------------------------


class TestPromptTemplateContent:
    """Verify the canonical reviewer invariants enforce experiment delegation.

    The experiment-delegation / adversarial-rigor block is defined exactly
    once in ``.claude/prompts/reviewer/_invariants.md`` and injected into each
    reviewer template (``diff``, ``plan``, ``spec``, ``epic``,
    ``spec-req-verification``) by the template-lint tooling. Per-family
    reviewer bridge agents (``copilot-reviewer.md``, ``gemini-reviewer.md``,
    ``codex-reviewer.md``) delegate the review criteria to those templates and
    carry no inline copy, so the bridge bodies are not asserted on here —
    ``tests/scripts/test_reviewer_templates.py`` covers the injection.
    """

    def test_invariants_enforces_experiment_delegation(self) -> None:
        """``_invariants.md`` must contain the experiment-delegation clause.

        The bridge wrapper concatenates the resolved template (which
        includes this block verbatim via the lint-enforced invariant
        injection) with the sanitized subject before piping to the
        upstream CLI. Asserting on the canonical source proves the clause
        will reach every reviewer regardless of family.
        """
        content = REVIEWER_INVARIANTS.read_text()
        assert "do NOT run them" in content, "reviewer invariants must instruct the reviewer not to run experiments"
        assert "Orchestrator will delegate experimentation" in content, (
            "reviewer invariants must route experimentation through the Orchestrator"
        )


# ---------------------------------------------------------------------------
# 4. No bypass variable (Req-N02)
# ---------------------------------------------------------------------------


class TestNoBypassVariable:
    """Verify the entrypoint contains no emergency bypass variable."""

    def test_gate_disabled_absent(self) -> None:
        """GATE_DISABLED must not appear anywhere in entrypoint.sh."""
        content = Path(ENTRYPOINT).read_text()
        assert "GATE_DISABLED" not in content


# ---------------------------------------------------------------------------
# 5. Codex config TOML (Req-C01)
# ---------------------------------------------------------------------------


class TestCodexConfigToml:
    """Verify docker/agent-cli/codex-config.toml is valid TOML.

    The file carries no ``[profiles.reviewer.instructions]`` section: the 10
    numbered criteria live solely in
    ``.claude/prompts/reviewer/_invariants.md``, the canonical source piped to
    the reviewer over the wrapper's combined-prompt stdin channel. The lint
    rule in ``scripts/lint_reviewer_templates.py::_check_codex_toml`` walks
    this file alongside ``.codex/config.toml`` to keep a criteria block from
    being introduced here.
    """

    TOML_FILE = WORKSPACE / "docker" / "agent-cli" / "codex-config.toml"

    def test_valid_toml_syntax(self) -> None:
        """codex-config.toml must parse as valid TOML."""
        content = self.TOML_FILE.read_bytes()
        data = tomllib.loads(content.decode())
        assert "profiles" in data
        assert "reviewer" in data["profiles"]

    def test_reviewer_profile_has_model(self) -> None:
        """Reviewer profile must specify a model."""
        data = tomllib.loads(self.TOML_FILE.read_bytes().decode())
        reviewer = data["profiles"]["reviewer"]
        assert "model" in reviewer
        assert reviewer["model"] == "gpt-5.3-codex"

    def test_reviewer_profile_has_no_instructions_section(self) -> None:
        """The ``[profiles.reviewer.instructions]`` section MUST be absent.

        Adding it would duplicate the 10-point criteria hosted in
        ``.claude/prompts/reviewer/_invariants.md``. The reviewer-template
        lint would catch that too, but an explicit assertion here catches
        the drift closer to its source.
        """
        data = tomllib.loads(self.TOML_FILE.read_bytes().decode())
        reviewer = data["profiles"]["reviewer"]
        assert "instructions" not in reviewer, (
            "[profiles.reviewer.instructions] must not be present — criteria live in .claude/prompts/reviewer/_invariants.md only."
        )

    def test_pointer_comment_present(self) -> None:
        """The pointer comment must document where criteria live."""
        text = self.TOML_FILE.read_text()
        assert "_invariants.md" in text, "codex-config.toml must retain the pointer comment identifying the canonical criteria source."
        assert "template-lint" in text, "pointer comment must warn that the lint fails on re-introduced criteria."


# ---------------------------------------------------------------------------
# 6. Setup script (Req-C02)
# ---------------------------------------------------------------------------


class TestSetupCodexReviewer:
    """Test scripts/setup_codex_reviewer.sh across all three code paths."""

    SETUP_SCRIPT = str(WORKSPACE / "scripts" / "setup_codex_reviewer.sh")
    CANONICAL = WORKSPACE / "docker" / "agent-cli" / "codex-config.toml"

    def _run_setup(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """Run the setup script with the given environment."""
        full_env = {"PATH": "/usr/bin:/bin:/usr/local/bin", **env}
        return subprocess.run(
            ["bash", self.SETUP_SCRIPT],
            capture_output=True,
            text=True,
            timeout=10,
            env=full_env,
            cwd=str(WORKSPACE),
        )

    def test_fresh_install(self, tmp_path: Path) -> None:
        """Path 1: No existing config — copies canonical file."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        result = self._run_setup({"HOME": str(tmp_path)})
        assert result.returncode == 0
        config = codex_dir / "config.toml"
        assert config.exists()
        assert "[profiles.reviewer]" in config.read_text()

    def test_append_to_existing(self, tmp_path: Path) -> None:
        """Path 2: Existing config without [profiles.reviewer] — appends."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text('[settings]\ntheme = "dark"\n')
        result = self._run_setup({"HOME": str(tmp_path)})
        assert result.returncode == 0
        content = config.read_text()
        assert "[settings]" in content
        assert "[profiles.reviewer]" in content

    def test_update_existing_reviewer(self, tmp_path: Path) -> None:
        """Path 3: Existing config with [profiles.reviewer] — replaces."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text('[settings]\ntheme = "dark"\n\n[profiles.reviewer]\nmodel = "old-model"\n')
        result = self._run_setup({"HOME": str(tmp_path)})
        assert result.returncode == 0
        content = config.read_text()
        assert "[settings]" in content
        assert "[profiles.reviewer]" in content
        assert "gpt-5.3-codex" in content
        assert "old-model" not in content
        # Backup should exist
        assert (codex_dir / "config.toml.bak").exists()

    def test_update_existing_reviewer_with_subsections(self, tmp_path: Path) -> None:
        """Path 3: Existing config with reviewer + instructions subsection — replaces cleanly."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text(
            '[settings]\ntheme = "dark"\n\n'
            "[profiles.reviewer]\n"
            'model = "old-model"\n\n'
            "[profiles.reviewer.instructions]\n"
            'role = "Old Role"\n'
            'focus = "Old focus"\n'
        )
        result = self._run_setup({"HOME": str(tmp_path)})
        assert result.returncode == 0
        content = config.read_text()
        assert "[settings]" in content
        assert "[profiles.reviewer]" in content
        assert "gpt-5.3-codex" in content
        assert "old-model" not in content
        assert "Old Role" not in content
        assert "Old focus" not in content


# ---------------------------------------------------------------------------
# 7. Codex review script (Req-C03)
# ---------------------------------------------------------------------------
# The wrapper runs against the real checkout, so a run here writes six paths in
# the live tmp/: the codex-exit.json signal the bridge agent reads, the
# codex-review-err.txt diagnostic (which can hold hundreds of KB), the
# test-owned review subject, and the round-scoped output / combined-prompt /
# sanitized-subject trio. Every one is snapshotted and restored per test.

SUBJECT_ARTIFACT = "agent-cli-test-subject.txt"


class UnmanageableArtifactError(RuntimeError):
    """A managed path exists in a form the snapshot/restore cycle cannot reproduce."""


def _managed_artifacts(tmp_dir: Path, round_id: str) -> tuple[Path, ...]:
    """Return the tmp/ paths a codex-review run at ``round_id`` creates or overwrites.

    Names are those written by ``scripts/agent-cli/codex-review.sh`` and
    ``scripts/agent-cli/_review-common.sh``. Ordered by restore priority: the
    unsuffixed artifacts a live review shares with these tests come first.
    """
    return (
        tmp_dir / "codex-exit.json",
        tmp_dir / "codex-review-err.txt",
        tmp_dir / SUBJECT_ARTIFACT,
        tmp_dir / f"codex-review-output-{round_id}.md",
        tmp_dir / f"codex-combined-prompt-{round_id}.txt",
        tmp_dir / f"codex-subject-sanitized-{round_id}.txt",
    )


def _snapshot_artifacts(paths: Iterable[Path]) -> dict[Path, bytes | None]:
    """Capture each path's bytes, recording ``None`` for a path that is absent.

    Raises:
        UnmanageableArtifactError: a path is a symlink, or exists as something
            other than a regular file. Recording either as absent would have
            the restore unlink a directory or a developer's symlink.
    """
    snapshot: dict[Path, bytes | None] = {}
    for path in paths:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise UnmanageableArtifactError(f"not a regular file, refusing to manage: {path}")
        snapshot[path] = path.read_bytes() if path.is_file() else None
    return snapshot


def _restore_artifacts(snapshot: Mapping[Path, bytes | None]) -> None:
    """Rewrite each path's snapshotted content, removing paths recorded absent.

    Contents only — mode and timestamps are not reproduced. Every path is
    attempted even after an earlier one fails, so one unwritable artifact
    cannot cost the rest.

    A path recorded as ``None`` was absent and is removed again — recreating it
    empty would itself corrupt a consumer that reads it as a review subject.

    Raises:
        ExceptionGroup: one or more paths could not be restored.
    """
    failures: list[OSError] = []
    for path, content in snapshot.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise ExceptionGroup("failed to restore tmp/ artifacts", failures)


def _prepare_subject(tmp_dir: Path) -> None:
    """Clear the stale exit signal and write the subject the wrapper reviews."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "codex-exit.json").unlink(missing_ok=True)
    (tmp_dir / SUBJECT_ARTIFACT).write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n")


def _isolate_artifacts(tmp_dir: Path, round_id: str) -> Iterator[None]:
    """Set the subject up under ``tmp_dir``, then restore every managed artifact.

    The snapshot is the only step outside the protected region, and it mutates
    nothing. Every write, the setup's included, runs under the ``finally``, so
    a setup that fails mid-write is still restored.
    """
    snapshot = _snapshot_artifacts(_managed_artifacts(tmp_dir, round_id))
    try:
        _prepare_subject(tmp_dir)
        yield
    finally:
        _restore_artifacts(snapshot)


class TestCodexReviewScript:
    """Test scripts/agent-cli/codex-review.sh error classification and artifact routing.

    The wrapper requires ``REVIEW_TYPE=<enum>`` + ``DIFF_FILE=<path under
    tmp/ or agent-review/>`` before it will reach the token guard or the codex
    invocation, so every test here supplies both via the test-owned subject
    that ``_isolate_shared_artifacts`` creates. ``_review_validate_diff_file``
    constrains DIFF_FILE by containment, not by basename, so the subject needs
    no name a live review also uses.
    """

    REVIEW_SCRIPT = str(WORKSPACE / "scripts" / "agent-cli" / "codex-review.sh")
    SUBJECT_FILE = WORKSPACE / "tmp" / SUBJECT_ARTIFACT
    # Host-mode runs `rm -f tmp/codex-review-output-${ROUND}.md` against the real
    # checkout, so host-context tests must claim a round no live review occupies —
    # round 1 is the recovery artifact for a stranded bridge dispatch (CLAUDE.md §18).
    SACRIFICIAL_ROUND = "999"

    @pytest.fixture(autouse=True)
    def _isolate_shared_artifacts(self) -> Iterator[None]:
        """Snapshot the tmp/ artifacts these tests write, then restore them.

        Autouse covers every test in this class. An autouse fixture declared in
        an outer conftest is still ordered ahead of this one, so the capture
        leads this class's own writes and the wrapper runs it guards — not
        every write the session can make.
        """
        yield from _isolate_artifacts(WORKSPACE / "tmp", self.SACRIFICIAL_ROUND)

    def _run_review(
        self,
        args: list[str] | None = None,
        env_overrides: dict[str, str] | None = None,
        *,
        timeout: int = 10,
    ) -> subprocess.CompletedProcess[str]:
        """Run the review script with controlled environment.

        Defaults ``REVIEW_TYPE=diff`` + ``DIFF_FILE`` pointed at the fixture's
        subject so the wrapper clears its arg_validation gate and reaches the
        behavior under test. Callers can override either via ``env_overrides``.
        """
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(WORKSPACE / "tmp" / "codex-test-home"),
            "REVIEW_TYPE": "diff",
            "DIFF_FILE": str(self.SUBJECT_FILE),
            # The wrapper's auth branch deletes this path outright, and the
            # wrapper's default resolves inside the real workspace tmp/ — the
            # developer's own preflight cache. Naming a test-owned file keeps
            # it out of harm's way; the overlay below still lets a
            # cache-invalidation test point it somewhere it can observe.
            "PREFLIGHT_CACHE_FILE": str(WORKSPACE / "tmp" / "codex-test-preflight-cache.json"),
        }
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", self.REVIEW_SCRIPT, *(args or [])],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(WORKSPACE),
        )

    def test_token_guard_emits_unavailable(self) -> None:
        """Missing OPENAI_API_KEY in non-host context emits CODEX_UNAVAILABLE."""
        result = self._run_review()
        # Exit 0 — clean degradation, not an error
        assert result.returncode == 0
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "CODEX_UNAVAILABLE" in exit_json
        assert "token_missing" in exit_json

    def test_host_context_skips_token_guard(self) -> None:
        """CODEX_EXECUTION_CONTEXT=host bypasses token guard (OAuth path)."""
        # With host context but no codex binary, the script will fail at
        # the codex exec call — but it should NOT emit CODEX_UNAVAILABLE
        self._run_review(
            args=["--round", self.SACRIFICIAL_ROUND],
            env_overrides={"CODEX_EXECUTION_CONTEXT": "host"},
        )
        # It should proceed past the token guard (non-zero exit is expected
        # since codex binary doesn't exist in test env)
        exit_json_path = WORKSPACE / "tmp" / "codex-exit.json"
        if exit_json_path.exists():
            assert "CODEX_UNAVAILABLE" not in exit_json_path.read_text()

    def test_invalid_round_exits_with_error(self) -> None:
        """Invalid --round value exits 1 with error JSON."""
        result = self._run_review(
            args=["--round", "0"],
            env_overrides={"OPENAI_API_KEY": "test-key"},
        )
        assert result.returncode == 1
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "CODEX_ERROR" in exit_json
        assert "arg_validation" in exit_json

    def test_artifact_path_host_mode(self) -> None:
        """Host mode routes output to tmp/ (not agent-review/)."""
        # This test verifies the artifact path logic by checking that
        # the script attempts to write to tmp/ in host mode.
        # Since codex binary doesn't exist, it will fail at invocation,
        # but we can verify the path setup by checking error output.
        self._run_review(
            args=["--round", self.SACRIFICIAL_ROUND],
            env_overrides={
                "CODEX_EXECUTION_CONTEXT": "host",
                "OPENAI_API_KEY": "test-key",
            },
        )
        # The script should have tried to run codex (and failed),
        # but agent-review/ files should NOT exist in host mode
        agent_review_files = glob.glob(str(WORKSPACE / "agent-review" / "*codex*"))
        assert len(agent_review_files) == 0

    def test_auth_error_classification(self, tmp_path: Path) -> None:
        """Auth errors (401/403/unauthorized) are classified as 'auth'."""
        # Create a mock codex stub that exits 1 with auth error
        mock_codex = tmp_path / "codex"
        mock_codex.write_text('#!/usr/bin/env bash\necho "Error: 401 Unauthorized - invalid api key" >&2\nexit 1\n')
        mock_codex.chmod(0o755)
        result = self._run_review(
            args=["--round", self.SACRIFICIAL_ROUND],
            env_overrides={
                "CODEX_EXECUTION_CONTEXT": "host",
                "OPENAI_API_KEY": "test-key",
                "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/local/bin",
            },
        )
        assert result.returncode == 0  # Script exits 0 after writing signal
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "CODEX_ERROR" in exit_json
        assert '"error_class":"auth"' in exit_json or '"error_class": "auth"' in exit_json
        assert '"retried":false' in exit_json or '"retried": false' in exit_json

    def test_transient_error_retries(self, tmp_path: Path) -> None:
        """Transient errors (non-auth) get one retry before signaling."""
        # Create a mock codex stub that always exits 1 with transient error
        mock_codex = tmp_path / "codex"
        mock_codex.write_text('#!/usr/bin/env bash\necho "Error: connection timeout" >&2\nexit 1\n')
        mock_codex.chmod(0o755)
        result = self._run_review(
            args=["--round", self.SACRIFICIAL_ROUND],
            env_overrides={
                "CODEX_EXECUTION_CONTEXT": "host",
                "OPENAI_API_KEY": "test-key",
                "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/local/bin",
            },
            timeout=30,
        )
        assert result.returncode == 0
        exit_json = (WORKSPACE / "tmp" / "codex-exit.json").read_text()
        assert "CODEX_ERROR" in exit_json
        assert '"error_class":"transient"' in exit_json or '"error_class": "transient"' in exit_json
        assert '"retried":true' in exit_json or '"retried": true' in exit_json


# ---------------------------------------------------------------------------
# 8. Shared-artifact isolation
# ---------------------------------------------------------------------------
# The isolation above is the only thing keeping the wrapper runs in section 7
# off the live tmp/ artifacts, and none of those tests observes it — so it can
# be removed with the suite still green. These tests are its lock. Every one
# works under tmp_path; none reads or writes the real checkout's tmp/.


class TestSharedArtifactIsolation:
    """Cover the snapshot/restore mechanism ``TestCodexReviewScript`` depends on."""

    def test_managed_set_matches_the_wrapper_artifacts(self, tmp_path: Path) -> None:
        assert _managed_artifacts(tmp_path, "7") == (
            tmp_path / "codex-exit.json",
            tmp_path / "codex-review-err.txt",
            tmp_path / "agent-cli-test-subject.txt",
            tmp_path / "codex-review-output-7.md",
            tmp_path / "codex-combined-prompt-7.txt",
            tmp_path / "codex-subject-sanitized-7.txt",
        )

    def test_snapshot_records_none_for_an_absent_path(self, tmp_path: Path) -> None:
        present = tmp_path / "codex-exit.json"
        present.write_bytes(b"live signal")
        absent = tmp_path / "codex-review-err.txt"
        snapshot = _snapshot_artifacts([present, absent])
        assert snapshot[present] == b"live signal"
        assert snapshot[absent] is None

    def test_restore_removes_a_path_the_run_created(self, tmp_path: Path) -> None:
        absent = tmp_path / "codex-exit.json"
        snapshot = _snapshot_artifacts([absent])
        absent.write_bytes(b"written by the run")
        _restore_artifacts(snapshot)
        assert not absent.exists()

    def test_restore_attempts_every_path_and_surfaces_the_failure(self, tmp_path: Path) -> None:
        blocked = tmp_path / "codex-exit.json"
        blocked.write_bytes(b"live signal")
        trailing = tmp_path / "codex-review-err.txt"
        trailing.write_bytes(b"live diagnostic")
        snapshot = _snapshot_artifacts([blocked, trailing])
        # A directory at the first path fails its write and leaves the second
        # one still clobbered unless every entry is attempted.
        blocked.unlink()
        blocked.mkdir()
        trailing.write_bytes(b"clobbered by the run")
        with pytest.raises(ExceptionGroup) as excinfo:
            _restore_artifacts(snapshot)
        assert len(excinfo.value.exceptions) == 1
        assert isinstance(excinfo.value.exceptions[0], OSError)
        assert trailing.read_bytes() == b"live diagnostic"

    def test_snapshot_refuses_a_directory(self, tmp_path: Path) -> None:
        # Docker creates a directory at any bind-mount target that is missing.
        occupied = tmp_path / "codex-exit.json"
        occupied.mkdir()
        with pytest.raises(UnmanageableArtifactError, match="codex-exit.json"):
            _snapshot_artifacts([occupied])

    def test_snapshot_refuses_a_dangling_symlink(self, tmp_path: Path) -> None:
        link = tmp_path / "codex-review-err.txt"
        link.symlink_to(tmp_path / "no-such-target.txt")
        with pytest.raises(UnmanageableArtifactError, match="codex-review-err.txt"):
            _snapshot_artifacts([link])

    def test_setup_failure_still_restores(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        signal = tmp_path / "codex-exit.json"
        signal.write_bytes(b"live signal")

        def _failing_setup(tmp_dir: Path) -> None:
            (tmp_dir / "codex-exit.json").unlink()
            raise RuntimeError("setup failed after its first write")

        monkeypatch.setattr(sys.modules[__name__], "_prepare_subject", _failing_setup)
        isolation = _isolate_artifacts(tmp_path, "7")
        with pytest.raises(RuntimeError, match="setup failed after its first write"):
            next(isolation)
        assert signal.read_bytes() == b"live signal"

    def test_class_fixture_restores_the_workspace_tmp_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.modules[__name__], "WORKSPACE", tmp_path)
        tmp_dir = tmp_path / "tmp"
        tmp_dir.mkdir()
        signal = tmp_dir / "codex-exit.json"
        signal.write_bytes(b"live signal")
        subject = tmp_dir / SUBJECT_ARTIFACT
        output = tmp_dir / f"codex-review-output-{TestCodexReviewScript.SACRIFICIAL_ROUND}.md"

        # pytest wraps a fixture in an object that refuses direct calls;
        # functools.update_wrapper leaves the generator at __wrapped__.
        fixture_body = TestCodexReviewScript.__dict__["_isolate_shared_artifacts"].__wrapped__
        isolation = fixture_body(TestCodexReviewScript())
        next(isolation)
        assert not signal.exists()
        assert subject.is_file()

        signal.write_bytes(b"written by the run")
        output.write_bytes(b"written by the run")
        with pytest.raises(StopIteration):
            next(isolation)

        assert signal.read_bytes() == b"live signal"
        assert not output.exists()
        assert not subject.exists()

    def test_isolation_fixture_is_autouse_with_no_setup_method(self) -> None:
        fixture = TestCodexReviewScript.__dict__["_isolate_shared_artifacts"]
        marker = getattr(fixture, "_fixture_function_marker", None)
        assert marker is not None, "pytest no longer exposes the fixture marker here — update this assertion"
        assert marker.autouse
        # A setup_method runs ahead of a class fixture, so any write it made
        # would land before the capture.
        assert "setup_method" not in vars(TestCodexReviewScript)
