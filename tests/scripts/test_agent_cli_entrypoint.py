"""Tests for the agent-cli entrypoint allowlist and the codex reviewer setup.

Covered here: the ``docker/agent-cli/entrypoint.sh`` command allowlist and its
absence of a bypass variable, the canonical reviewer invariants the templates
inject, the ``docker/agent-cli/codex-config.toml`` reviewer profile,
``scripts/setup_codex_reviewer.sh``, and the containment of the two spawns
this module makes.

Allowed commands dispatch to ``/usr/local/bin/<cmd>.sh``. Only the agent-cli
image installs those wrappers; the environment these tests run in does not, so
an allowed command fails at exec time -- the assertions verify only that the
entrypoint's own validation layer did not reject it. Blocked commands are
rejected by the entrypoint with exit 1 and ``ERROR`` on stderr.

Every subprocess here runs from a throwaway root under ``tmp_path``, and the
setup script runs from a copy inside that root. It arms an ``EXIT`` trap over
a ``BASH_SOURCE``-derived temp path before it branches, so spawning the
checked-in copy aims an ``rm -f`` at the live checkout on every code path,
whatever the CWD is -- and on the update path writes there as well.

The environment each child receives is enumerated, never inherited. That is
credential containment first and path hygiene second: the entrypoint ``exec``s
an allowed command's wrapper, and an inherited environment would hand that
wrapper the pytest process's own credentials along with ``PYTHONPATH`` and the
rest of the session.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
ENTRYPOINT = str(WORKSPACE / "docker" / "agent-cli" / "entrypoint.sh")
SETUP_SCRIPT = WORKSPACE / "scripts" / "setup_codex_reviewer.sh"
CANONICAL_CONFIG = WORKSPACE / "docker" / "agent-cli" / "codex-config.toml"

# Canonical home of the adversarial-rigor / experiment-delegation block.
# Template content is lint-enforced against this source of truth (see
# scripts/lint_reviewer_templates.py + tests/scripts/test_reviewer_templates.py).
REVIEWER_INVARIANTS = WORKSPACE / ".claude" / "prompts" / "reviewer" / "_invariants.md"

# System directories only, so no checkout-managed entry such as ``.venv/bin``
# can supply a binary to a spawned child.
_SPAWN_PATH = "/usr/bin:/bin:/usr/local/bin"

# Appended to the scratch copy of the canonical config, so a profile installed
# carrying it proves the setup script resolved CANONICAL inside the scratch
# checkout. A TOML comment, so the marked copy still parses.
_SCRATCH_CANONICAL_MARKER = "# scratch-checkout canonical"


def _scratch_root(tmp_path: Path) -> Path:
    """Return (creating on first use) the throwaway root every spawn runs from.

    ``TestSpawnContainment`` asserts the root's depth below ``tmp_path``
    separately from its identity: an equality check against this function's own
    return value still passes once the root collapses into ``tmp_path``, so the
    parent check beside it is the only thing that would notice.
    """
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return root


def _scratch_checkout(tmp_path: Path) -> Path:
    """Mirror into the scratch root the checkout paths the setup script resolves.

    ``setup_codex_reviewer.sh`` derives ``CANONICAL`` and ``TEMP_FILE`` from
    ``${SCRIPT_DIR}/../``, never from its CWD, so the script has to live inside
    the root at the same checkout-relative path it occupies here: a copy at the
    root resolves ``CANONICAL`` into ``tmp_path``, which holds no
    ``docker/agent-cli`` tree, so the run fails loudly instead.

    ``<root>/tmp/`` is deliberately not created here: the script's own
    ``mkdir -p`` is its only creator, which is what keeps section 7's
    assertion on that directory from being vacuous.
    """
    root = _scratch_root(tmp_path)
    script = root / SETUP_SCRIPT.relative_to(WORKSPACE)
    if script.exists():
        return root
    script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SETUP_SCRIPT, script)
    canonical = root / CANONICAL_CONFIG.relative_to(WORKSPACE)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANONICAL_CONFIG, canonical)
    return root


def _capture_spawn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``subprocess.run`` with a recorder and return the kwargs it sees.

    The returned mapping is populated by the time the helper under test returns.
    """
    captured: dict[str, Any] = {}

    def _record(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _record)
    return captured


def _run_entrypoint(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the entrypoint from the scratch root with the given arguments.

    ``entrypoint.sh`` writes nothing itself and resolves no path relative to
    either its CWD or ``BASH_SOURCE``. It does ``exec`` an allowed command's
    wrapper out of ``/usr/local/bin``, though, which a host carrying the
    agent-cli scripts would then run — so the child gets a closed environment
    and a CWD outside the checkout rather than the pytest process's own.
    """
    return subprocess.run(
        ["bash", ENTRYPOINT, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": _SPAWN_PATH},
        cwd=str(_scratch_root(tmp_path)),
    )


# ---------------------------------------------------------------------------
# 1. Command allowlist
# ---------------------------------------------------------------------------


class TestCommandAllowlist:
    """Verify entrypoint command dispatch: allowed vs blocked commands."""

    @pytest.mark.parametrize("cmd", ["copilot-review", "gemini-review", "codex-review", "preflight"])
    def test_allowed_command_not_rejected_by_allowlist(self, tmp_path: Path, cmd: str) -> None:
        """Allowed commands must not trigger the allowlist error message."""
        result = _run_entrypoint(tmp_path, cmd)
        assert "unknown command" not in result.stderr

    @pytest.mark.parametrize(
        "cmd",
        ["bash", "sh", "node", "python3", "cat", "hack-something"],
    )
    def test_blocked_command_exits_1(self, tmp_path: Path, cmd: str) -> None:
        """Non-allowlisted commands must exit 1 with ERROR in stderr."""
        result = _run_entrypoint(tmp_path, cmd)
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_empty_command_exits_1(self, tmp_path: Path) -> None:
        """Empty command (no arguments) must exit 1 with ERROR in stderr."""
        result = _run_entrypoint(tmp_path)
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_random_string_blocked(self, tmp_path: Path) -> None:
        """Arbitrary random string must be rejected."""
        result = _run_entrypoint(tmp_path, "xyzzy-not-a-command")
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

    def test_valid_toml_syntax(self) -> None:
        """codex-config.toml must parse as valid TOML."""
        content = CANONICAL_CONFIG.read_bytes()
        data = tomllib.loads(content.decode())
        assert "profiles" in data
        assert "reviewer" in data["profiles"]

    def test_reviewer_profile_has_model(self) -> None:
        """Reviewer profile must specify a model."""
        data = tomllib.loads(CANONICAL_CONFIG.read_bytes().decode())
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
        data = tomllib.loads(CANONICAL_CONFIG.read_bytes().decode())
        reviewer = data["profiles"]["reviewer"]
        assert "instructions" not in reviewer, (
            "[profiles.reviewer.instructions] must not be present — criteria live in .claude/prompts/reviewer/_invariants.md only."
        )

    def test_pointer_comment_present(self) -> None:
        """The pointer comment must document where criteria live."""
        text = CANONICAL_CONFIG.read_text()
        assert "_invariants.md" in text, "codex-config.toml must retain the pointer comment identifying the canonical criteria source."
        assert "template-lint" in text, "pointer comment must warn that the lint fails on re-introduced criteria."


# ---------------------------------------------------------------------------
# 6. Setup script (Req-C02)
# ---------------------------------------------------------------------------


class TestSetupCodexReviewer:
    """Test scripts/setup_codex_reviewer.sh across all three code paths.

    Every case runs the scratch copy ``_scratch_checkout`` provisions rather
    than the checked-in script. The ``EXIT`` trap that removes the
    cleaned-config temp file is armed ahead of the branch, so all three paths
    bind a ``TEMP_FILE`` under whichever tree the script was spawned from.
    """

    def _run_setup(self, tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """Run the scratch copy of the setup script with the given environment.

        ``PATH`` is applied last, so an override cannot reopen the search path.
        """
        root = _scratch_checkout(tmp_path)
        return subprocess.run(
            ["bash", str(root / SETUP_SCRIPT.relative_to(WORKSPACE))],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            env={**env, "PATH": _SPAWN_PATH},
            cwd=str(root),
        )

    def test_fresh_install(self, tmp_path: Path) -> None:
        """Path 1: No existing config — copies canonical file."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})
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
        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})
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
        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})
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
        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})
        assert result.returncode == 0
        content = config.read_text()
        assert "[settings]" in content
        assert "[profiles.reviewer]" in content
        assert "gpt-5.3-codex" in content
        assert "old-model" not in content
        assert "Old Role" not in content
        assert "Old focus" not in content


# ---------------------------------------------------------------------------
# 7. Spawn containment
# ---------------------------------------------------------------------------


class TestSpawnContainment:
    """Verify what contains the two spawns this module makes.

    CWD, environment, stdin and the deadline are pinned against the captured
    ``subprocess.run`` kwargs, since neither script reports any of them itself.
    ``HOME`` is the load-bearing value among them: ``setup_codex_reviewer.sh``
    derives ``${HOME}/.codex/config.toml`` and the ``.bak`` beside it, so a
    ``HOME`` that drifted back to the developer's own would aim every setup
    case at their live reviewer profile.

    ``stdin`` and ``timeout`` are forward guards against an edit that
    introduces a command reading the caller's stdin: nothing either script runs
    today does, and the pair keeps such an edit reporting rather than blocking
    on the session's terminal.

    ``PATH`` is compared against ``_SPAWN_PATH`` itself, so those comparisons
    move with the constant and cannot see its value change; its content is
    pinned separately below.

    The tree ``setup_codex_reviewer.sh`` resolves its own paths from is pinned
    behaviorally instead, by a marker carried only by the scratch copy of the
    canonical config.
    """

    # The directories ``_SPAWN_PATH`` may name, as a category rather than as a
    # copy of its current value. An allowlist rather than a check for entries
    # under ``WORKSPACE``: the checkout root is ``/app`` under pytest-cli and an
    # arbitrary path outside it on a host, so a WORKSPACE-relative predicate
    # would reject a ``/app/.venv/bin`` entry only when run in the container and
    # pass on the identical string here.
    _SYSTEM_BIN_DIRS: frozenset[str] = frozenset({"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin"})

    def test_entrypoint_runs_from_the_scratch_root_with_a_closed_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_spawn(monkeypatch)
        _run_entrypoint(tmp_path, "codex-review")
        cwd = Path(captured["cwd"]).resolve()
        assert cwd == _scratch_root(tmp_path).resolve()
        # Not redundant with the equality above — see _scratch_root.
        assert cwd.parent == tmp_path.resolve()
        assert captured["env"] == {"PATH": _SPAWN_PATH}
        assert captured["stdin"] is subprocess.DEVNULL
        assert captured["timeout"] == 10

    def test_setup_runs_from_the_scratch_root_with_a_closed_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_spawn(monkeypatch)
        TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path)})
        cwd = Path(captured["cwd"]).resolve()
        assert cwd == _scratch_root(tmp_path).resolve()
        # Not redundant with the equality above — see _scratch_root.
        assert cwd.parent == tmp_path.resolve()
        assert captured["env"] == {"PATH": _SPAWN_PATH, "HOME": str(tmp_path)}
        assert captured["stdin"] is subprocess.DEVNULL
        assert captured["timeout"] == 10

    def test_a_caller_supplied_path_cannot_reopen_the_setup_spawns_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_spawn(monkeypatch)
        TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path), "PATH": f"{tmp_path}:/usr/bin"})
        assert captured["env"]["PATH"] == _SPAWN_PATH

    def test_the_spawn_path_names_only_system_directories(self) -> None:
        outside = sorted(set(_SPAWN_PATH.split(":")) - self._SYSTEM_BIN_DIRS)
        assert outside == [], (
            f"_SPAWN_PATH must name system directories only; {outside} is not among them. A checkout-managed entry such as .venv/bin ahead of the system directories lets a spawned child resolve a binary out of the repository under test, and a relative or empty entry resolves one against the CWD instead. Neither env comparison above can see this: both are written against _SPAWN_PATH itself, so they move with whatever it is set to. Widening the allowlist is the deliberate step a genuinely new directory has to take."
        )

    def test_setup_resolves_script_dir_inside_the_scratch_checkout(self, tmp_path: Path) -> None:
        root = _scratch_checkout(tmp_path)
        canonical = root / CANONICAL_CONFIG.relative_to(WORKSPACE)
        canonical.write_text(f"{canonical.read_text()}\n{_SCRATCH_CANONICAL_MARKER}\n")
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        # Path 3 — the only branch that creates the TEMP_FILE directory.
        config = codex_dir / "config.toml"
        config.write_text('[profiles.reviewer]\nmodel = "old-model"\n')
        # TEMP_FILE's parent must be the script's own creation, not the fixture's.
        assert not (root / "tmp").exists()

        result = TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path)})

        assert result.returncode == 0
        # CANONICAL resolved to the marked copy, not the checked-in one.
        assert _SCRATCH_CANONICAL_MARKER in config.read_text()
        assert (root / "tmp").is_dir()
