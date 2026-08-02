"""Tests for the agent-cli entrypoint.sh command allowlist and prompt-file validation.

Invokes the entrypoint shell script directly via subprocess on the host.
Allowed commands dispatch to /usr/local/bin/<cmd>.sh which does not exist
on the host, so allowed commands fail at exec time -- tests verify that the
entrypoint validation layer itself did not reject the command.  Blocked
commands are rejected by the entrypoint with exit 1 and "ERROR" in stderr.
"""

from __future__ import annotations

import glob
import subprocess
import tomllib
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
ENTRYPOINT = str(WORKSPACE / "docker" / "agent-cli" / "entrypoint.sh")

# TODO-0092 Phase A moved the adversarial-rigor / experiment-delegation
# block OUT of bridge agent bodies and INTO the canonical reviewer
# invariants file. Template content is lint-enforced against this
# source of truth (see scripts/lint_reviewer_templates.py +
# tests/scripts/test_reviewer_templates.py).
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
# 2. Prompt-file handling removed (TODO-0092 Phase A Commit 6)
# ---------------------------------------------------------------------------
# The ``--prompt-file`` parse+sandbox+export block was removed from the
# entrypoint because the task-driven wrapper contract now carries the
# subject via ``DIFF_FILE`` (validated by the inner wrapper against
# tmp/ and agent-review/ containment). The entrypoint is a thin
# command-allowlist dispatcher; argv pass-through covers remaining
# per-wrapper flags like ``--round`` and ``--model``.
#
# The prior ``TestPromptFileValidation`` class was deleted with this
# commit — each of its tests asserted a rejection path that is now the
# downstream wrapper's responsibility (containment validation happens
# in ``_review-common.sh::_review_validate_diff_file`` with
# regression coverage in ``tests/scripts/test_wrapper_sanitation.py``).
# Preserving the old tests would have required the entrypoint to keep
# the dead surface alive, defeating the cleanup.


# ---------------------------------------------------------------------------
# 3. Prompt template content (Req-008)
# ---------------------------------------------------------------------------


class TestPromptTemplateContent:
    """Verify the canonical reviewer invariants enforce experiment delegation.

    Under TODO-0092 Phase A the experiment-delegation / adversarial-rigor
    block is defined exactly once in ``.claude/prompts/reviewer/_invariants.md``
    and injected into each reviewer template (``diff``, ``plan``, ``spec``,
    ``epic``, ``spec-req-verification``) by the template-lint tooling.
    Per-family reviewer bridge agents (``copilot-reviewer.md``,
    ``gemini-reviewer.md``, ``codex-reviewer.md``) delegate the review
    criteria to these templates and no longer carry the clause inline —
    asserting on the bridge bodies would now be redundant with
    ``tests/scripts/test_reviewer_templates.py``.
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

    TODO-0092 Phase A Commit 6 deleted the
    ``[profiles.reviewer.instructions]`` section (role/focus with 10
    numbered criteria) from this file. Criteria now live in
    ``.claude/prompts/reviewer/_invariants.md`` (the canonical source
    piped to the reviewer via the wrapper's combined-prompt stdin
    channel). The lint rule in
    ``scripts/lint_reviewer_templates.py::_check_codex_toml`` walks
    this file alongside ``.codex/config.toml`` to prevent the
    criteria block from being re-introduced.
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

        Its re-introduction would duplicate the 10-point criteria now
        hosted in ``.claude/prompts/reviewer/_invariants.md`` and
        would be caught by the reviewer-template lint anyway — but an
        explicit assertion here catches the drift closer to its source.
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


class TestCodexReviewScript:
    """Test scripts/agent-cli/codex-review.sh error classification and artifact routing.

    Under the TODO-0092 Phase A contract the wrapper requires
    ``REVIEW_TYPE=<enum>`` + ``DIFF_FILE=<path under tmp/ or agent-review/>``
    before it will reach the token guard or codex invocation. The tests
    that previously got as far as the token / error-classification paths
    supply both via a shared ``tmp/qa-diff.txt`` fixture created in
    ``setup_method``.
    """

    REVIEW_SCRIPT = str(WORKSPACE / "scripts" / "agent-cli" / "codex-review.sh")
    QA_DIFF = WORKSPACE / "tmp" / "qa-diff.txt"

    def setup_method(self) -> None:
        """Clean shared artifacts and (re)create the standard diff subject."""
        exit_json = WORKSPACE / "tmp" / "codex-exit.json"
        if exit_json.exists():
            exit_json.unlink()
        self.QA_DIFF.parent.mkdir(exist_ok=True)
        self.QA_DIFF.write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n")

    def _run_review(
        self,
        args: list[str] | None = None,
        env_overrides: dict[str, str] | None = None,
        *,
        timeout: int = 10,
    ) -> subprocess.CompletedProcess[str]:
        """Run the review script with controlled environment.

        Defaults ``REVIEW_TYPE=diff`` + ``DIFF_FILE=tmp/qa-diff.txt`` so the
        wrapper clears its arg_validation gate and reaches the behavior
        under test. Callers can override either via ``env_overrides``.
        """
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(WORKSPACE / "tmp" / "codex-test-home"),
            "REVIEW_TYPE": "diff",
            "DIFF_FILE": str(self.QA_DIFF),
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
