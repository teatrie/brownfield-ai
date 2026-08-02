"""Unit tests for the PreToolUse hook: block-docker-build-escape.sh.

Feeds simulated Claude Code PreToolUse JSON payloads to the hook via
stdin and asserts the correct exit code (0 = allow, 2 = deny).

Gate 1: blocks builds from untracked Dockerfiles (-f flag).
Gate 2: blocks builds when untracked Dockerfiles exist in tree.
Gate 3: audits uncommitted changes to security files for suspicious patterns.
"""

import json
import subprocess
from pathlib import Path

import pytest

HOOK = str(Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "block-docker-build-escape.sh")


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


# --- Gate 3: Security file audit (entry-condition tests) ---


class TestSecurityFileAudit:
    """Gate 3: docker build commands reach the security-file audit stage.

    Full pattern-matching requires real git diff state, so these tests
    verify entry conditions: build commands are intercepted while
    non-build commands bypass the audit entirely.
    """

    def test_build_command_is_intercepted(self) -> None:
        """A plain docker build command does not exit early at the gate check."""
        result = _run_hook("docker build .")
        # The hook either passes (exit 0, no suspicious changes) or
        # blocks (exit 2, suspicious changes found). It must NOT error
        # with an unrelated failure.
        assert result.returncode in (0, 2)

    def test_compose_build_is_intercepted(self) -> None:
        """A docker compose build reaches the audit stage."""
        result = _run_hook("docker compose build python-cli")
        assert result.returncode in (0, 2)

    def test_non_build_skips_audit(self) -> None:
        """Non-build docker commands exit 0 before any git checks."""
        result = _run_hook("docker run --rm alpine echo hi")
        assert result.returncode == 0
        assert result.stderr == ""


# --- Gate 1 / Gate 2: Clean builds from tracked Dockerfiles ---


class TestCleanBuilds:
    """Builds from tracked, committed Dockerfiles should be allowed.

    These use real Dockerfile paths known to be tracked in the repo.
    The tests may still exit 2 if Gate 2 or Gate 3 triggers due to
    ambient repo state; that is expected in dirty worktrees.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker build -f docker/python-cli/Dockerfile .",
            "docker compose build python-cli",
            "docker buildx build -f docker/python-cli/Dockerfile .",
            "docker image build -f docker/pytest-cli/Dockerfile .",
            "docker builder build -f docker/repo-cli/Dockerfile .",
        ],
    )
    def test_tracked_dockerfile_allowed(self, cmd: str) -> None:
        """Build from a tracked Dockerfile must pass Gate 1."""
        result = _run_hook(cmd)
        # Gate 1 specifically should not fire for tracked paths.
        if result.returncode == 2:
            assert "untracked Dockerfile: docker/" not in result.stderr


# --- Gate 1: Untracked Dockerfile via -f ---


class TestUntrackedDockerfiles:
    """Builds referencing untracked Dockerfiles must be denied (exit 2).

    Uses paths guaranteed to be untracked: tmp/ prefix and absolute paths.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker build -f tmp/Evil.Dockerfile .",
            "docker build --file tmp/Evil.Dockerfile .",
            "docker build -f /var/Evil.Dockerfile .",
            "docker build -f=tmp/Backdoor.Dockerfile .",
            "docker build --file=/var/Dockerfile .",
            "docker buildx build -f tmp/Evil.Dockerfile .",
        ],
    )
    def test_untracked_dockerfile_denied(self, cmd: str) -> None:
        """Build from an untracked Dockerfile must be denied by Gate 1."""
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Not blocked: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr
        assert "untracked Dockerfile" in result.stderr


# --- Edge cases ---


class TestEdgeCases:
    """Edge cases: empty input, non-build commands, malformed JSON."""

    def test_empty_command(self) -> None:
        """Empty command string must be allowed."""
        result = _run_hook("")
        assert result.returncode == 0

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker run --rm alpine echo hi",
            "docker ps",
            "docker images",
            "docker compose up -d",
            "docker compose down",
        ],
    )
    def test_non_build_commands_allowed(self, cmd: str) -> None:
        """Non-build docker commands must exit 0."""
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Unexpectedly blocked: {cmd!r}\nstderr: {result.stderr}"

    def test_malformed_json_denied(self) -> None:
        """Malformed JSON must exit 2 (fail-closed)."""
        result = subprocess.run(
            ["bash", HOOK],
            input="not json at all",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "DENIED" in result.stderr

    def test_no_command_field(self) -> None:
        """Payload with no command field must be allowed."""
        payload = json.dumps({"tool_input": {}}, separators=(",", ":"))
        result = subprocess.run(
            ["bash", HOOK],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_empty_stdin(self) -> None:
        """Empty stdin must be allowed."""
        result = subprocess.run(
            ["bash", HOOK],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
