"""Integration tests for Docker container security hardening.

Validates that containers enforce read-only mounts, non-root execution,
entrypoint immutability, write-boundary isolation, and hook-level gate
bypass prevention. These tests run actual containers via ``docker compose``
and require the tool-profile images to be built.
"""

import json
import os
import subprocess
import time as time_mod
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

HOOK = str(REPO_ROOT / ".claude" / "hooks" / "block-container-escape.sh")

GATE_ENTRYPOINT = str(REPO_ROOT / "docker" / "shared" / "lint-gate-entrypoint.sh")

# When running inside pytest-cli, HOST_PWD and HOST_HOME are passed by the
# task alias so that sibling containers resolve volume mounts against the
# host filesystem instead of the container's /app.
_HOST_PWD = os.environ.get("HOST_PWD", "")
_HOST_HOME = os.environ.get("HOST_HOME", "")

COMPOSE_BASE: list[str] = ["docker", "compose"]
if _HOST_PWD:
    # Inside pytest-cli: compose file is at /app/, but relative paths in
    # volume mounts must resolve against the HOST filesystem for the daemon.
    COMPOSE_BASE += ["-f", "/app/docker-compose.yml", "--project-directory", _HOST_PWD]
COMPOSE_BASE += ["--profile", "tools"]


def _run_hook(command: str) -> subprocess.CompletedProcess[str]:
    """Invoke the PreToolUse hook with a simulated JSON payload on stdin."""
    payload = json.dumps({"tool_input": {"command": command}}, separators=(",", ":"))
    return subprocess.run(
        ["bash", HOOK],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _compose_run(
    service: str,
    *cmd: str,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a command in a compose service with entrypoint overridden to empty.

    When HOST_HOME is set (containerized execution), override HOME so that
    docker compose resolves ``~`` in volume mounts to the host home directory.
    """
    env = os.environ.copy()
    if _HOST_HOME:
        env["HOME"] = _HOST_HOME
    return subprocess.run(
        [*COMPOSE_BASE, "run", "--rm", "--entrypoint", "", service, *cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


# ---------------------------------------------------------------------------
# 1. Read-only mounts with writable tmp/
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReadOnlyMounts:
    """Validate that workspace root is :ro and tmp/ is :rw across containers."""

    @pytest.mark.parametrize(
        "service,write_path",
        [
            ("python-cli", "/app/test-write-blocked"),
            ("pytest-cli", "/app/test-write-blocked"),
            ("agent-cli", "/app/test-write-blocked"),
        ],
    )
    def test_root_mount_is_readonly(self, service: str, write_path: str) -> None:
        """Write to root mount (outside tmp/) must fail with read-only filesystem error."""
        result = _compose_run(service, "sh", "-c", f"touch {write_path}")
        assert result.returncode != 0
        assert "Read-only file system" in result.stderr

    @pytest.mark.parametrize(
        "service,tmp_path",
        [
            ("python-cli", "/app/tmp/test-write-ok"),
            ("pytest-cli", "/app/tmp/test-write-ok"),
            ("agent-cli", "/app/tmp/test-write-ok"),
        ],
    )
    def test_tmp_mount_is_writable(self, service: str, tmp_path: str) -> None:
        """Write to tmp/ must succeed."""
        result = _compose_run(service, "sh", "-c", f"touch {tmp_path} && rm {tmp_path}")
        assert result.returncode == 0

    def test_infra_lint_workspace_readonly(self) -> None:
        """Write to /workspace root in infra-lint must fail with read-only filesystem error."""
        result = _compose_run("infra-lint", "sh", "-c", "touch /workspace/test-write-blocked")
        assert result.returncode != 0

    def test_infra_lint_tmp_writable(self) -> None:
        """Write to /workspace/tmp in infra-lint must succeed."""
        result = _compose_run(
            "infra-lint",
            "sh",
            "-c",
            "touch /workspace/tmp/test-write-ok && rm /workspace/tmp/test-write-ok",
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# 2. Non-root user enforcement
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNonRootUser:
    """Validate all containers run as the ``agent`` user with immutable entrypoints."""

    @pytest.mark.parametrize(
        "service",
        [
            "python-cli",
            "pytest-cli",
            "agent-cli",
            "infra-lint",
            "repo-cli",
        ],
    )
    def test_runs_as_agent_user(self, service: str) -> None:
        """Container must execute commands as the ``agent`` user."""
        result = _compose_run(service, "whoami")
        assert result.stdout.strip() == "agent"

    @pytest.mark.parametrize(
        "service",
        [
            "python-cli",
            "pytest-cli",
            "agent-cli",
            "infra-lint",
            "repo-cli",
        ],
    )
    def test_entrypoint_not_writable_by_agent(self, service: str) -> None:
        """Agent user must not be able to overwrite the entrypoint script."""
        result = _compose_run(
            service,
            "sh",
            "-c",
            "echo hijack > /usr/local/bin/entrypoint.sh",
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# 3. Write-boundary isolation for agent-cli
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCopilotGeminiWriteBoundary:
    """Validate :ro mount blocks writes outside tmp/ for agent-cli."""

    def test_agent_cli_cannot_write_outside_tmp(self) -> None:
        """Verify :ro mount blocks writes outside tmp/ for agent-cli."""
        result = _compose_run("agent-cli", "sh", "-c", "echo test > /app/src/evil.py")
        assert result.returncode != 0
        assert "Read-only file system" in result.stderr


# ---------------------------------------------------------------------------
# 4. Gate-bypass env var blocked by hook
# ---------------------------------------------------------------------------


_GATE_ENV_VARS = "GATE_DISABLED"


@pytest.mark.integration
class TestGateBypassEnvVarBlocked:
    """Validate the PreToolUse hook blocks gate-disabled env-var injection."""

    @pytest.mark.parametrize(
        "var,container",
        [
            (f"PYTHON_{_GATE_ENV_VARS}=1", "python-cli"),
            (f"LINT_{_GATE_ENV_VARS}=1", "infra-lint"),
        ],
    )
    def test_gate_disabled_env_var_blocked_by_hook(self, var: str, container: str) -> None:
        """Hook must block ``-e *_GATE_DISABLED=1`` on gated containers."""
        cmd = f"docker compose run --rm -e {var} {container} echo hi"
        result = _run_hook(cmd)
        assert result.returncode == 2
        assert "DENIED" in result.stderr


# ---------------------------------------------------------------------------
# 5. Helm subcommand restriction in lint-gate-entrypoint.sh
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHelmSubcommandRestriction:
    """Validate the lint-gate entrypoint only permits ``helm template`` and ``helm lint``."""

    @pytest.mark.parametrize(
        "subcmd,should_pass",
        [
            ("helm template .", True),
            ("helm lint .", True),
            ("helm install foo .", False),
            ("helm repo add bar url", False),
        ],
    )
    def test_helm_subcommand_gate(self, subcmd: str, should_pass: bool) -> None:
        """Only ``helm template`` and ``helm lint`` are permitted by the entrypoint allowlist."""
        # NOTE: Uses OS /tmp/ intentionally — lint-gate-entrypoint.sh
        # hardcodes GATE_FILE_LINT="/tmp/.lint-gate-pass" for in-container
        # use. This test runs the entrypoint on the host and must match
        # the entrypoint's expected path. Exempt from CLAUDE.md rule 10.
        gate_artifact = Path("/tmp/.lint-gate-pass")
        ts = int(time_mod.time())
        gate_artifact.write_text(f"GATE_PASS={ts}:integration-test")
        try:
            result = subprocess.run(
                ["bash", GATE_ENTRYPOINT, *subcmd.split()],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if should_pass:
                # The command may fail because helm is not installed on the
                # host, but the entrypoint itself must not block it.
                assert "not in allowlist" not in result.stderr, f"Unexpectedly blocked: {subcmd}"
                assert "not allowed" not in result.stderr, f"Unexpectedly blocked: {subcmd}"
            else:
                assert result.returncode != 0
                blocked_phrases = ("not allowed", "not in allowlist", "not in the command allowlist")
                assert any(phrase in result.stderr for phrase in blocked_phrases), (
                    f"Expected blocking message for '{subcmd}', got: {result.stderr}"
                )
        finally:
            gate_artifact.unlink(missing_ok=True)
