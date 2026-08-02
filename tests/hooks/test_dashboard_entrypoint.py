"""Unit tests for the ledger-dashboard container entrypoint gate.

Invokes docker/dashboard/entrypoint.sh directly and asserts the correct
exit code (0 = allow, 1 = deny).
"""

import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = str(Path(__file__).resolve().parents[2] / "docker" / "dashboard" / "entrypoint.sh")


def _run_entrypoint(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the entrypoint script with the given arguments."""
    return subprocess.run(
        ["bash", ENTRYPOINT, *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestAllowed:
    """Commands that should be permitted."""

    def test_uvicorn_full_command(self) -> None:
        result = _run_entrypoint(
            "uvicorn",
            "services.dashboard.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8484",
        )
        # uvicorn will fail to import but entrypoint should exec it (not deny)
        # The key assertion is that it does NOT exit 1 with "DENIED"
        assert "DENIED" not in result.stderr

    def test_uvicorn_bare(self) -> None:
        result = _run_entrypoint("uvicorn")
        assert "DENIED" not in result.stderr


class TestBlocked:
    """Commands that must be denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            ("bash",),
            ("python3",),
            ("sh", "-c", "echo pwned"),
            ("cat", "/etc/passwd"),
            ("pip", "install", "evil"),
        ],
    )
    def test_denied(self, cmd: tuple[str, ...]) -> None:
        result = _run_entrypoint(*cmd)
        assert result.returncode == 1, f"Not blocked: {cmd!r}\nstderr: {result.stderr}"
        assert "DENIED" in result.stderr


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_no_arguments(self) -> None:
        result = _run_entrypoint()
        assert result.returncode == 1
        assert "DENIED" in result.stderr
