"""Unit tests for the PreToolUse hook: block-terraform-escape.sh.

Feeds simulated Claude Code PreToolUse JSON payloads to the hook via
stdin and asserts the correct exit code (0 = allow, 2 = deny).
"""

import json
import subprocess
from pathlib import Path

import pytest

HOOK = str(Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "block-terraform-escape.sh")


def _run_hook(command: str) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a simulated PreToolUse JSON payload on stdin."""
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        ["bash", HOOK],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )


# --- Blocked patterns (exit 2) ---


class TestEntrypointOverride:
    """Rule 2: --entrypoint combined with infra-terraform."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker run --entrypoint /bin/sh infra-terraform echo hi",
            "docker run --entrypoint=/bin/bash infra-terraform",
            'bash -c "docker run --entrypoint /bin/sh infra-terraform"',
        ],
    )
    def test_blocked(self, cmd: str) -> None:
        result = _run_hook(cmd)
        assert result.returncode == 2
        assert "DENIED" in result.stderr


class TestUserRootEscalation:
    """Rule 3: --user/-u root/0 (user or group) combined with infra-terraform."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # Root user
            "docker run --user root infra-terraform echo hi",
            "docker run --user=root infra-terraform",
            "docker run --user 0 infra-terraform",
            "docker run --user=0 infra-terraform",
            "docker run -u root infra-terraform",
            "docker run -u 0 infra-terraform",
            "docker run -u0 infra-terraform",
            'docker run --user "root" infra-terraform',
            "docker run --user '0' infra-terraform",
            # Root group (user:group syntax)
            "docker run --user agent:root infra-terraform",
            "docker run --user agent:0 infra-terraform",
            "docker run --user 1000:0 infra-terraform",
            "docker run -u agent:root infra-terraform",
            # Root user AND group
            "docker run --user root:root infra-terraform",
            "docker run --user 0:0 infra-terraform",
        ],
    )
    def test_blocked(self, cmd: str) -> None:
        result = _run_hook(cmd)
        assert result.returncode == 2
        assert "DENIED" in result.stderr


class TestUserVariableIndirection:
    """--user with unresolved variables or unknown values on infra-terraform."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker run --user $USER infra-terraform",
            "docker run --user ${ROOT} infra-terraform",
            "docker run -u $(whoami) infra-terraform",
            "docker run --user `id -u` infra-terraform",
            "docker run --user nobody infra-terraform",
            "docker run --user 1000 infra-terraform",
            "docker run --user 1000:1000 infra-terraform",
        ],
    )
    def test_blocked(self, cmd: str) -> None:
        result = _run_hook(cmd)
        assert result.returncode == 2
        assert "DENIED" in result.stderr


class TestMultiFlagAndWhitespaceBypass:
    """Bypass attempts via multi-flag injection, multi-space, and substring false positives."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # Multi-flag: Docker uses last --user; hook must check ALL
            "docker run --user agent --user root infra-terraform",
            "docker run --user agent --user nobody infra-terraform",
            "docker run -u agent -u 0 infra-terraform",
            # Multi-space evasion
            "docker run --user  root infra-terraform",
            "docker run -u   0 infra-terraform",
            # Leading-zero numeric root
            "docker run --user 00 infra-terraform",
            "docker run --user 000 infra-terraform",
        ],
    )
    def test_blocked(self, cmd: str) -> None:
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Bypass not caught: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr


class TestTfExecInternal:
    """Rule 1: any reference to _tf_exec_internal."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker run _tf_exec_internal echo hi",
            "docker exec _tf_exec_internal echo hi",
            "echo _tf_exec_internal",
        ],
    )
    def test_blocked(self, cmd: str) -> None:
        result = _run_hook(cmd)
        assert result.returncode == 2
        assert "DENIED" in result.stderr


# --- Allowed patterns (exit 0) ---


class TestAllowedCommands:
    """Commands that must NOT be blocked."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker run --rm infra-terraform plan",
            "docker run --rm --user agent infra-terraform plan",
            "docker run --rm --user agent:agent infra-terraform plan",
            "docker run --rm -uagent infra-terraform plan",
            "docker run --rm -uagent:agent infra-terraform plan",
            "docker run --rm alpine echo hi",
            "docker run --rm --user root alpine echo hi",
            # False-positive regression: unrelated flags containing "user" substring
            "docker run --rm --name my-user-service --user agent infra-terraform plan",
            "docker run --rm --env FOO=user --user agent infra-terraform plan",
            "git commit -m 'fix something'",
            "ls -la",
            "task builders:tf-run",
        ],
    )
    def test_allowed(self, cmd: str) -> None:
        result = _run_hook(cmd)
        assert result.returncode == 0, f"Command unexpectedly blocked: {cmd}\nstderr: {result.stderr}"


class TestMultilineBypass:
    """Newline/continuation bypass attempts must still be caught."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "docker run \\\n--entrypoint /bin/sh \\\ninfra-terraform",
            "docker run\n--entrypoint /bin/sh\ninfra-terraform echo hi",
            "docker run \\\n--user root \\\ninfra-terraform",
            "docker run\n-u 0\ninfra-terraform",
        ],
    )
    def test_blocked(self, cmd: str) -> None:
        result = _run_hook(cmd)
        assert result.returncode == 2, f"Multiline bypass not caught: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr


class TestEmptyAndMissing:
    """Edge cases: empty command, missing field, empty JSON."""

    def test_empty_command(self) -> None:
        result = _run_hook("")
        assert result.returncode == 0

    def test_missing_field(self) -> None:
        payload = json.dumps({"tool_input": {}})
        result = subprocess.run(
            ["bash", HOOK],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_malformed_json(self) -> None:
        """Malformed JSON triggers the ERR trap — should exit 2 (fail closed)."""
        result = subprocess.run(
            ["bash", HOOK],
            input="not json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "DENIED" in result.stderr
