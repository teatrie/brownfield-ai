"""Unit tests for scripts/agent-cli/preflight.sh and gemini-preflight-tiered.sh.

The context, fallback and timeout paths of gemini-review.sh are covered here
too. Every script is spawned from a throwaway root under ``tmp_path``: the
wrappers resolve the cache, signal and output artifacts they write relative to
their CWD, so a spawn inheriting the pytest process CWD writes into the real
repository.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

WORKSPACE: Path = Path(__file__).resolve().parents[2]
_AGENT_CLI_DIR: Path = WORKSPACE / "scripts" / "agent-cli"
PREFLIGHT_SCRIPT_PATH: Path = _AGENT_CLI_DIR / "preflight.sh"

# Absolute interpreter so callers can wipe PATH down to a controlled
# directory without losing the shell.
_BASH: str = shutil.which("bash") or "/bin/bash"


def _scratch_root(tmp_path: Path) -> Path:
    """Return (creating on first use) the throwaway root to spawn scripts from.

    Args:
        tmp_path: Test temp dir to place the root under.

    Returns:
        The scratch working directory for every subprocess in this module.

    The root sits one level below ``tmp_path`` so the mock bins, the scratch
    ``HOME`` and the explicitly-passed cache files stay outside the directory a
    wrapper can reach through CWD-relative writes.

    It carries no ``.git``, and neither may any ancestor: ``_review-common.sh``
    anchors to ``git rev-parse --show-toplevel`` whenever a worktree is found
    and writes into that toplevel instead of CWD. The tests here cover the
    unanchored branch, so the absence is asserted rather than assumed.
    """
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    _reject_git_ancestor(root)
    return root


def _reject_git_ancestor(root: Path) -> None:
    """Fail when ``root`` or any ancestor of it is a git worktree.

    Args:
        root: Scratch directory a script will be spawned from.

    Raises:
        RuntimeError: A ``.git`` entry exists at or above ``root``, which would
            route wrapper writes to that worktree instead of the scratch root.

    The lexical chain and the symlink-resolved chain are both walked: git
    discovers a worktree along the physical path, and on macOS ``tmp_path``
    arrives as ``/var/folders/...`` where ``/var`` links to ``/private/var``, so
    a lexical walk alone never inspects ``/private``.
    """
    resolved = root.resolve()
    seen: set[Path] = set()
    for candidate in (root, *root.parents, resolved, *resolved.parents):
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / ".git").exists():
            raise RuntimeError(f"scratch root {root} lies inside the git worktree at {candidate}")


def _scratch_home(tmp_path: Path) -> Path:
    """Return (creating on first use) a throwaway ``HOME`` for spawned scripts.

    Args:
        tmp_path: Test temp dir to place the home under.

    Returns:
        A writable directory outside the scratch root — gemini-review.sh
        creates ``$HOME/.gemini`` before invoking the CLI.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def _host_path() -> str:
    """Return the host ``PATH`` with every entry inside the real checkout dropped.

    Returns:
        A ``PATH`` value carrying the system tool directories the wrappers need
        and no directory derived from the repository root.
    """
    entries = os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)
    kept = [e for e in entries if e and not Path(e).is_relative_to(WORKSPACE)]
    return os.pathsep.join(kept) or "/usr/bin:/bin"


def _create_mock_cli(tmp_path: Path, name: str) -> None:
    """Create a mock CLI binary that prints a version."""
    mock_bin = tmp_path / name
    mock_bin.write_text(f"#!/bin/bash\necho '{name} v0.0.1-mock'\n")
    mock_bin.chmod(0o755)


def _preflight_env(tmp_path: Path, *, path: str, tokens: dict[str, str]) -> dict[str, str]:
    """Build the environment for a ``preflight.sh`` run.

    Args:
        tmp_path: Test temp dir supplying the scratch ``HOME``.
        path: Full ``PATH`` value the run should see.
        tokens: Token vars to set. A token var absent from this mapping is
            absent from the child environment whatever the host exports.

    Returns:
        Environment mapping for ``subprocess.run``.

    The mapping is closed — every key is enumerated here, none is inherited
    from ``os.environ``. That keeps ``GIT_DIR``, ``GIT_WORK_TREE`` and
    ``GIT_COMMON_DIR`` out of the child: they override git's ancestry-based
    worktree discovery, so a spawned script holding one would write into the
    real checkout despite the scratch CWD. ``PATH`` and the token vars read by
    indirect expansion are the script's whole read-set, so nothing is lost.
    """
    env: dict[str, str] = {
        "PATH": path,
        "HOME": str(_scratch_home(tmp_path)),
    }
    env.update(tokens)
    return env


def test_all_available(tmp_path: Path) -> None:
    for cli in ("copilot", "gemini"):
        _create_mock_cli(tmp_path, cli)

    env = _preflight_env(
        tmp_path,
        path=f"{tmp_path}:{_host_path()}",
        tokens={"COPILOT_GITHUB_TOKEN": "mock-token", "GEMINI_API_KEY": "mock-key"},
    )

    result = subprocess.run(
        [str(PREFLIGHT_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=_scratch_root(tmp_path),
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["copilot"]["cli"] is True
    assert data["copilot"]["token"] is True
    assert data["gemini"]["cli"] is True
    assert data["gemini"]["token"] is True


def test_missing_copilot_cli(tmp_path: Path) -> None:
    _create_mock_cli(tmp_path, "gemini")
    # Create isolated bin dir with only bash (no copilot)
    iso_bin = tmp_path / "iso_bin"
    iso_bin.mkdir()
    for cmd in ("bash", "command", "printf", "echo"):
        src = Path(f"/usr/bin/{cmd}")
        if src.exists():
            (iso_bin / cmd).symlink_to(src)

    env = _preflight_env(
        tmp_path,
        path=f"{tmp_path}:{iso_bin}",
        tokens={"COPILOT_GITHUB_TOKEN": "mock-token", "GEMINI_API_KEY": "mock-key"},
    )

    result = subprocess.run(
        [str(PREFLIGHT_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=_scratch_root(tmp_path),
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["copilot"]["cli"] is False
    assert data["gemini"]["cli"] is True


def test_missing_token(tmp_path: Path) -> None:
    _create_mock_cli(tmp_path, "copilot")

    env = _preflight_env(tmp_path, path=f"{tmp_path}:{_host_path()}", tokens={})

    result = subprocess.run(
        [str(PREFLIGHT_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=_scratch_root(tmp_path),
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["copilot"]["cli"] is True
    assert data["copilot"]["token"] is False


def test_no_clis_available(tmp_path: Path) -> None:
    env = _preflight_env(tmp_path, path=f"{tmp_path}:{_host_path()}", tokens={})

    result = subprocess.run(
        [str(PREFLIGHT_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=_scratch_root(tmp_path),
    )

    assert result.returncode == 1


def test_partial_availability(tmp_path: Path) -> None:
    _create_mock_cli(tmp_path, "gemini")
    iso_bin = tmp_path / "iso_bin"
    iso_bin.mkdir()
    for cmd in ("bash", "command", "printf", "echo"):
        src = Path(f"/usr/bin/{cmd}")
        if src.exists():
            (iso_bin / cmd).symlink_to(src)

    env = _preflight_env(
        tmp_path,
        path=f"{tmp_path}:{iso_bin}",
        tokens={"GEMINI_API_KEY": "mock-key"},
    )

    result = subprocess.run(
        [str(PREFLIGHT_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=_scratch_root(tmp_path),
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["gemini"]["cli"] is True
    assert data["gemini"]["token"] is True
    assert data["copilot"]["cli"] is False


# ── gemini-preflight-tiered.sh ───────────────────────────────────────

GEMINI_PREFLIGHT_SCRIPT_PATH: Path = _AGENT_CLI_DIR / "gemini-preflight-tiered.sh"


def _run_preflight(
    tmp_path: Path,
    *,
    env_override: dict[str, str] | None = None,
    mock_gemini_bin: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the gemini preflight script from a scratch CWD.

    Args:
        tmp_path: Test temp dir supplying the scratch CWD and ``HOME``. The
            script resolves its default cache path (``tmp/...``) relative to
            CWD, so the scratch root is what keeps a run whose test does not
            override ``PREFLIGHT_CACHE_FILE`` out of the real checkout.
        env_override: Extra env vars to set (merged with minimal base).
        mock_gemini_bin: If set, directory is prepended to PATH so a mock
            ``gemini`` binary is found by ``command -v gemini``.

    Returns:
        Completed process with captured stdout/stderr.

    Bash is invoked by absolute path so callers can wipe PATH down to a
    controlled directory without losing the interpreter — the host's
    PATH may include ``/usr/bin`` where ``gemini`` is preinstalled in the
    pytest-cli container.
    """
    env: dict[str, str] = {
        "PATH": _host_path(),
        "HOME": str(_scratch_home(tmp_path)),
        # Bypass the 24h preflight cache by default so every test sees
        # the live decision tree. Cache-specific tests opt back in by
        # overriding PREFLIGHT_FORCE.
        "PREFLIGHT_FORCE": "1",
    }
    if mock_gemini_bin is not None:
        env["PATH"] = f"{mock_gemini_bin}:{env['PATH']}"
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [_BASH, str(GEMINI_PREFLIGHT_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=_scratch_root(tmp_path),
    )


def _create_mock_gemini_preflight(tmp_path: Path) -> Path:
    """Create a mock gemini binary that does nothing.

    Args:
        tmp_path: Temporary directory for the mock binary.

    Returns:
        Path to the directory containing the mock binary.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock = bin_dir / "gemini"
    mock.write_text("#!/bin/bash\nexit 0\n")
    mock.chmod(mock.stat().st_mode | stat.S_IEXEC)
    return bin_dir


# Coreutils the preflight + cache machinery needs at runtime. Symlinked
# from the host into a controlled bin dir so tests can exercise the
# `command -v gemini` = false branch without losing access to `mkdir`,
# `mv`, `cat`, `stat`, etc. (the pytest-cli image installs both gemini
# and coreutils in /usr/bin, so directory-level exclusion is not enough).
_PREFLIGHT_RUNTIME_TOOLS = (
    "cat",
    "mkdir",
    "mv",
    "rm",
    "stat",
    "date",
    "dirname",
    "head",
    "tail",
    "grep",
    "sed",
    "tr",
    "test",
    "[",
    "expr",
)


def _isolated_bin_without_cli(tmp_path: Path, *, cli_names: tuple[str, ...]) -> Path:
    """Build a bin dir with coreutils symlinked but the named CLIs absent.

    Args:
        tmp_path: Test temp dir under which to place the bin.
        cli_names: CLIs that MUST NOT be discoverable via this bin
            (e.g., ``("gemini",)`` to test the no-local-CLI branch).

    Returns:
        Path to the constructed bin directory. Caller sets PATH to this
        path to give the script working coreutils minus the named CLIs.
    """
    bin_dir = tmp_path / "isolated_bin"
    bin_dir.mkdir()
    for tool in _PREFLIGHT_RUNTIME_TOOLS:
        src = shutil.which(tool)
        if src is None or Path(src).name in cli_names:
            continue
        (bin_dir / tool).symlink_to(src)
    return bin_dir


class TestLocalCliAvailable:
    """`gemini` on PATH -> mode=local. Auth is not verified by preflight."""

    def test_returns_local_mode(self, tmp_path: Path) -> None:
        bin_dir = _create_mock_gemini_preflight(tmp_path)
        # No GEMINI_API_KEY set — local CLI presence alone is enough.
        result = _run_preflight(tmp_path, mock_gemini_bin=bin_dir)
        assert result.returncode == 0
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["mode"] == "local"
        assert data["gemini"]["cli"] is True

    def test_local_mode_takes_precedence_over_api_key(self, tmp_path: Path) -> None:
        """If both local CLI and API key are present, prefer local."""
        bin_dir = _create_mock_gemini_preflight(tmp_path)
        result = _run_preflight(
            tmp_path,
            mock_gemini_bin=bin_dir,
            env_override={"GEMINI_API_KEY": "test-key"},
        )
        assert result.returncode == 0
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["mode"] == "local"


class TestContainerFallback:
    """No local `gemini`; GEMINI_API_KEY set -> mode=container."""

    def test_returns_container_mode(self, tmp_path: Path) -> None:
        # Isolated bin gives the script working coreutils but no `gemini`
        # so `command -v gemini` returns false and the API_KEY branch is
        # exercised.
        bin_dir = _isolated_bin_without_cli(tmp_path, cli_names=("gemini",))
        result = _run_preflight(
            tmp_path,
            env_override={
                "PATH": str(bin_dir),
                "GEMINI_API_KEY": "test-key",
            },
        )
        assert result.returncode == 0
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["mode"] == "container"
        assert data["gemini"]["cli"] is False
        assert data["gemini"]["api_key"] is True


class TestUnavailable:
    """No local `gemini`, no API key -> mode=none, exit 1."""

    def test_returns_none_mode_and_exit_1(self, tmp_path: Path) -> None:
        bin_dir = _isolated_bin_without_cli(tmp_path, cli_names=("gemini",))
        result = _run_preflight(tmp_path, env_override={"PATH": str(bin_dir)})
        assert result.returncode == 1
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["mode"] == "none"
        assert data["gemini"]["cli"] is False
        assert data["gemini"]["api_key"] is False


class TestJsonSchema:
    """All output variants use a consistent JSON schema."""

    def test_cli_key_present_in_all_modes(self, tmp_path: Path) -> None:
        bin_dir = _create_mock_gemini_preflight(tmp_path)
        result = _run_preflight(tmp_path, mock_gemini_bin=bin_dir)
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert "cli" in data["gemini"]
        assert "mode" in data


class TestCacheBehavior:
    """Successful preflight results are cached for 24h; `none` is not cached."""

    def test_cache_written_for_local_mode(self, tmp_path: Path) -> None:
        bin_dir = _create_mock_gemini_preflight(tmp_path)
        cache_file = tmp_path / "preflight-cache.json"
        result = _run_preflight(
            tmp_path,
            mock_gemini_bin=bin_dir,
            env_override={
                "PREFLIGHT_CACHE_FILE": str(cache_file),
                "PREFLIGHT_FORCE": "0",
            },
        )
        assert result.returncode == 0
        assert cache_file.exists()
        cached: dict[str, Any] = json.loads(cache_file.read_text())
        assert cached["mode"] == "local"

    def test_cache_hit_returns_cached_value_without_recheck(self, tmp_path: Path) -> None:
        """If the cache is fresh, the script returns it verbatim — even if
        the live state would differ. Proves the cache short-circuits the
        decision tree."""
        cache_file = tmp_path / "preflight-cache.json"
        # Pre-seed the cache with a value the live tree CANNOT produce
        # (no gemini on PATH, no API key) — proves it's served from cache.
        cache_file.write_text('{"mode":"local","gemini":{"cli":true,"cached_marker":"X"}}\n')
        bin_dir = _isolated_bin_without_cli(tmp_path, cli_names=("gemini",))
        result = _run_preflight(
            tmp_path,
            env_override={
                "PATH": str(bin_dir),
                "PREFLIGHT_CACHE_FILE": str(cache_file),
                "PREFLIGHT_FORCE": "0",
            },
        )
        assert result.returncode == 0
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["gemini"].get("cached_marker") == "X"

    def test_cache_expired_triggers_recheck(self, tmp_path: Path) -> None:
        """A cache file older than TTL must be ignored and a fresh result
        computed."""
        cache_file = tmp_path / "preflight-cache.json"
        cache_file.write_text('{"mode":"local","gemini":{"cli":true,"cached_marker":"X"}}\n')
        # Backdate the cache file to 2 seconds ago so a TTL of 1 second
        # treats it as expired.
        os.utime(cache_file, (cache_file.stat().st_atime - 2, cache_file.stat().st_mtime - 2))
        bin_dir = _isolated_bin_without_cli(tmp_path, cli_names=("gemini",))
        result = _run_preflight(
            tmp_path,
            env_override={
                "PATH": str(bin_dir),
                "GEMINI_API_KEY": "test-key",
                "PREFLIGHT_CACHE_FILE": str(cache_file),
                "PREFLIGHT_CACHE_TTL_SECONDS": "1",
                "PREFLIGHT_FORCE": "0",
            },
        )
        assert result.returncode == 0
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["mode"] == "container"
        assert "cached_marker" not in data["gemini"]

    def test_force_bypasses_cache(self, tmp_path: Path) -> None:
        """PREFLIGHT_FORCE=1 short-circuits the cache read even on a hit."""
        cache_file = tmp_path / "preflight-cache.json"
        cache_file.write_text('{"mode":"local","gemini":{"cli":true,"cached_marker":"X"}}\n')
        bin_dir = _isolated_bin_without_cli(tmp_path, cli_names=("gemini",))
        result = _run_preflight(
            tmp_path,
            env_override={
                "PATH": str(bin_dir),
                "GEMINI_API_KEY": "test-key",
                "PREFLIGHT_CACHE_FILE": str(cache_file),
                "PREFLIGHT_FORCE": "1",
            },
        )
        assert result.returncode == 0
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["mode"] == "container"
        assert "cached_marker" not in data["gemini"]

    def test_none_result_not_cached(self, tmp_path: Path) -> None:
        """`mode: none` must not be cached so a freshly-installed CLI is
        picked up immediately on the next call."""
        cache_file = tmp_path / "preflight-cache.json"
        bin_dir = _isolated_bin_without_cli(tmp_path, cli_names=("gemini",))
        result = _run_preflight(
            tmp_path,
            env_override={
                "PATH": str(bin_dir),
                "PREFLIGHT_CACHE_FILE": str(cache_file),
                "PREFLIGHT_FORCE": "0",
            },
        )
        assert result.returncode == 1
        data: dict[str, Any] = json.loads(result.stdout.strip())
        assert data["mode"] == "none"
        assert not cache_file.exists()


# ── gemini-review.sh context tests ─────────────────────────────────────

REVIEW_SCRIPT_PATH: Path = _AGENT_CLI_DIR / "gemini-review.sh"
# Canonical reviewer templates — the wrapper resolves
# ``.claude/prompts/reviewer/<REVIEW_TYPE>.md`` relative to CWD, so fake
# workspaces symlink this directory into place. Read-only: the wrapper only
# concatenates the template it resolves.
REAL_TEMPLATES_DIR: Path = WORKSPACE / ".claude" / "prompts" / "reviewer"


def _link_reviewer_templates(fake_ws: Path) -> None:
    """Symlink the canonical reviewer templates into a fake workspace.

    The wrapper's ``_review_template_path`` returns a relative path of
    the form ``.claude/prompts/reviewer/<REVIEW_TYPE>.md`` — the test
    workspace must resolve that path, so mirror the directory via symlink
    rather than copying each template file.
    """
    claude_dir = fake_ws / ".claude" / "prompts" / "reviewer"
    if claude_dir.exists() or claude_dir.is_symlink():
        return
    claude_dir.parent.mkdir(parents=True, exist_ok=True)
    claude_dir.symlink_to(REAL_TEMPLATES_DIR)


def _run_review_script(
    tmp_path: Path,
    *,
    env_override: dict[str, str] | None = None,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    """Run gemini-review.sh from a scratch CWD with a controlled environment.

    Args:
        tmp_path: Test temp dir supplying the scratch CWD and ``HOME``. The
            wrapper writes its exit signal, sanitized subject and review
            output relative to CWD.
        env_override: Extra env vars to merge with minimal base.
        timeout: Seconds to wait for the wrapper. Must exceed the wrapper's
            own ``GEMINI_TIMEOUT`` so its fallback path is observed rather
            than killed here.

    Returns:
        Completed process with captured stdout/stderr.
    """
    env: dict[str, str] = {
        "PATH": _host_path(),
        "HOME": str(_scratch_home(tmp_path)),
    }
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [_BASH, str(REVIEW_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=_scratch_root(tmp_path),
    )


class TestTokenGuardHostContext:
    """Token guard is bypassed when GEMINI_EXECUTION_CONTEXT=host."""

    def test_host_context_no_api_key_does_not_emit_unavailable(self, tmp_path: Path) -> None:
        """With GEMINI_EXECUTION_CONTEXT=host and no GEMINI_API_KEY,
        the script should NOT emit GEMINI_UNAVAILABLE — it proceeds
        past the token guard regardless of what happens later."""
        result = _run_review_script(
            tmp_path,
            env_override={
                "GEMINI_EXECUTION_CONTEXT": "host",
            },
        )
        # The token guard must NOT fire — no GEMINI_UNAVAILABLE in stdout
        assert "GEMINI_UNAVAILABLE" not in result.stdout

    def test_no_context_no_api_key_emits_unavailable(self, tmp_path: Path) -> None:
        """Without GEMINI_EXECUTION_CONTEXT and no GEMINI_API_KEY,
        the script should emit GEMINI_UNAVAILABLE.

        The wrapper validates ``REVIEW_TYPE``/``DIFF_FILE`` before the token
        guard, so the fake workspace must provide both (plus the reviewer
        templates).
        """
        root = _scratch_root(tmp_path)
        (root / "tmp").mkdir(exist_ok=True)
        (root / "tmp" / "qa-diff.txt").write_text("diff --git a/x b/x\n+a\n")
        _link_reviewer_templates(root)
        _run_review_script(
            tmp_path,
            env_override={
                "REVIEW_TYPE": "diff",
                "DIFF_FILE": "tmp/qa-diff.txt",
            },
        )
        exit_json = root / "tmp" / "gemini-exit.json"
        assert exit_json.exists(), "tmp/gemini-exit.json was not created"
        data: dict[str, Any] = json.loads(exit_json.read_text())
        assert data["signal"] == "GEMINI_UNAVAILABLE"
        assert data["reason"] == "token_missing"


# ── gemini-review.sh fallback + timeout tests ─────────────────────────


def _create_mock_gemini_slow_failure(bin_dir: Path) -> None:
    """Create a mock gemini CLI that writes an error to stderr and hangs."""
    mock = bin_dir / "gemini"
    mock.write_text('#!/bin/bash\necho "Attempt 1 failed with status 429." >&2\nsleep 30\n')
    mock.chmod(0o755)


def _create_mock_gemini_instant_failure(bin_dir: Path) -> None:
    """Create a mock gemini CLI that fails immediately with non-zero exit."""
    mock = bin_dir / "gemini"
    mock.write_text('#!/bin/bash\necho "401 Unauthorized" >&2\nexit 1\n')
    mock.chmod(0o755)


def _create_mock_gemini_success(bin_dir: Path) -> None:
    """Create a mock gemini CLI that succeeds immediately."""
    mock = bin_dir / "gemini"
    mock.write_text('#!/bin/bash\ncat -\necho "## Review Output"\necho "No issues found."\n')
    mock.chmod(0o755)


def _setup_review_workspace(tmp_path: Path) -> Path:
    """Provision the scratch root with the file structure gemini-review.sh needs.

    Args:
        tmp_path: Test temp dir holding the scratch root.

    Returns:
        The scratch root the wrapper runs from, so callers can assert against
        the artifacts it writes there.

    The wrapper's contract requires:
      * ``tmp/qa-diff.txt`` — the subject artifact the wrapper
        concatenates with its resolved template (caller-supplied prompt
        files are not part of the contract).
      * ``.claude/prompts/reviewer/`` — symlinked into the fake workspace
        so the wrapper can resolve ``diff.md`` (the hardcoded template
        path for ``REVIEW_TYPE=diff``).
    """
    root = _scratch_root(tmp_path)
    (root / "tmp").mkdir(exist_ok=True)
    diff = root / "tmp" / "qa-diff.txt"
    diff.write_text("diff --git a/foo.py b/foo.py\n+hello\n")
    _link_reviewer_templates(root)
    return root


class TestFallbackSignal:
    """Verify GEMINI_TIMEOUT and fallback exit code 3 for any failure."""

    def test_slow_failure_exits_3_with_fallback_signal(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _create_mock_gemini_slow_failure(bin_dir)
        root = _setup_review_workspace(tmp_path)

        result = _run_review_script(
            tmp_path,
            env_override={
                "PATH": f"{bin_dir}:{_host_path()}",
                "GEMINI_EXECUTION_CONTEXT": "host",
                "GEMINI_MODEL": "gemini-3.1-pro-preview",
                "GEMINI_TIMEOUT": "10",
                "REVIEW_TYPE": "diff",
                "DIFF_FILE": "tmp/qa-diff.txt",
                "ROUND": "1",
            },
            timeout=30,
        )
        assert result.returncode == 3, f"Expected exit 3 (fallback), got {result.returncode}. stderr: {result.stderr}"
        exit_json = root / "tmp" / "gemini-exit.json"
        assert exit_json.exists(), "tmp/gemini-exit.json not created"
        data: dict[str, Any] = json.loads(exit_json.read_text())
        assert data["signal"] == "GEMINI_FALLBACK"
        assert data["model"] == "gemini-3.1-pro-preview"
        assert "exit_code" in data

    def test_instant_failure_exits_3_with_fallback_signal(self, tmp_path: Path) -> None:
        """Instant exit (no hang) must still trigger fallback — no TOCTOU race."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _create_mock_gemini_instant_failure(bin_dir)
        root = _setup_review_workspace(tmp_path)

        result = _run_review_script(
            tmp_path,
            env_override={
                "PATH": f"{bin_dir}:{_host_path()}",
                "GEMINI_EXECUTION_CONTEXT": "host",
                "GEMINI_MODEL": "gemini-3.1-pro-preview",
                "GEMINI_TIMEOUT": "10",
                "REVIEW_TYPE": "diff",
                "DIFF_FILE": "tmp/qa-diff.txt",
                "ROUND": "1",
            },
            timeout=15,
        )
        assert result.returncode == 3, f"Expected exit 3 (fallback), got {result.returncode}. stderr: {result.stderr}"
        exit_json = root / "tmp" / "gemini-exit.json"
        assert exit_json.exists(), "tmp/gemini-exit.json not created"
        data: dict[str, Any] = json.loads(exit_json.read_text())
        assert data["signal"] == "GEMINI_FALLBACK"
        assert data["exit_code"] == 1

    def test_success_with_timeout_exits_0(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _create_mock_gemini_success(bin_dir)
        root = _setup_review_workspace(tmp_path)

        result = _run_review_script(
            tmp_path,
            env_override={
                "PATH": f"{bin_dir}:{_host_path()}",
                "GEMINI_EXECUTION_CONTEXT": "host",
                "GEMINI_MODEL": "gemini-3-flash-preview",
                "GEMINI_TIMEOUT": "10",
                "REVIEW_TYPE": "diff",
                "DIFF_FILE": "tmp/qa-diff.txt",
                "ROUND": "1",
            },
            timeout=15,
        )
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
        output = root / "tmp" / "gemini-review-output-1.md"
        assert output.exists(), "Output file not created"
        assert "No issues found" in output.read_text()

    def test_no_timeout_synchronous_failure_exits_3(self, tmp_path: Path) -> None:
        """With GEMINI_TIMEOUT=0, synchronous failure also exits 3."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _create_mock_gemini_instant_failure(bin_dir)
        root = _setup_review_workspace(tmp_path)

        result = _run_review_script(
            tmp_path,
            env_override={
                "PATH": f"{bin_dir}:{_host_path()}",
                "GEMINI_EXECUTION_CONTEXT": "host",
                "GEMINI_TIMEOUT": "0",
                "REVIEW_TYPE": "diff",
                "DIFF_FILE": "tmp/qa-diff.txt",
                "ROUND": "1",
            },
            timeout=15,
        )
        assert result.returncode == 3
        exit_json = root / "tmp" / "gemini-exit.json"
        assert exit_json.exists()
        data: dict[str, Any] = json.loads(exit_json.read_text())
        assert data["signal"] == "GEMINI_FALLBACK"

    def test_no_timeout_synchronous_success(self, tmp_path: Path) -> None:
        """With GEMINI_TIMEOUT=0, script uses synchronous mode."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _create_mock_gemini_success(bin_dir)
        root = _setup_review_workspace(tmp_path)

        result = _run_review_script(
            tmp_path,
            env_override={
                "PATH": f"{bin_dir}:{_host_path()}",
                "GEMINI_EXECUTION_CONTEXT": "host",
                "GEMINI_TIMEOUT": "0",
                "REVIEW_TYPE": "diff",
                "DIFF_FILE": "tmp/qa-diff.txt",
                "ROUND": "1",
            },
            timeout=15,
        )
        assert result.returncode == 0
        exit_json = root / "tmp" / "gemini-exit.json"
        assert not exit_json.exists(), "No exit signal expected on success"
