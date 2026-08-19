"""Tests for the agent-cli entrypoint allowlist and the codex reviewer setup.

Covered here: the ``docker/agent-cli/entrypoint.sh`` command allowlist, the
canonical reviewer invariants the templates inject, the
``docker/agent-cli/codex-config.toml`` reviewer profile, and
``scripts/setup_codex_reviewer.sh``. The wrappers the entrypoint dispatches to
are covered by their own modules under ``tests/scripts/``, not here.

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

    The root sits one level below ``tmp_path`` so a test's own scratch ``HOME``
    stays outside the directory a spawned script can reach through
    CWD-relative writes.
    """
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return root


def _scratch_checkout(tmp_path: Path) -> Path:
    """Mirror into the scratch root the checkout paths the setup script resolves.

    ``setup_codex_reviewer.sh`` derives ``CANONICAL`` and ``TEMP_FILE`` from
    ``${SCRIPT_DIR}/../``, never from its CWD, so re-rooting the spawn is not
    enough on its own — the script has to live inside the root at the same
    relative depth it occupies in the checkout. A copy at the root itself
    resolves both one level up, into ``tmp_path`` — which every caller of
    ``_run_setup`` hands the script as its ``HOME``, and which holds no
    ``docker/agent-cli`` tree because nothing here creates one. ``CANONICAL``
    would then name a file that does not exist, and the ``cp``/``cat`` reading
    it would fail under ``set -e``, so every case dies at its returncode
    assertion rather than silently relocating its writes.

    ``<root>/tmp/`` is deliberately not created here: the script's own
    ``mkdir -p`` is its only creator, which is what keeps section 7's
    assertion on that directory from being vacuous.
    """
    root = _scratch_root(tmp_path)
    script = root / "scripts" / SETUP_SCRIPT.name
    if script.exists():
        return root
    script.parent.mkdir(exist_ok=True)
    shutil.copy2(SETUP_SCRIPT, script)
    canonical = root / "docker" / "agent-cli" / CANONICAL_CONFIG.name
    canonical.parent.mkdir(parents=True)
    shutil.copy2(CANONICAL_CONFIG, canonical)
    return root


def _capture_spawn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``subprocess.run`` with a recorder and return the kwargs it sees.

    Neither script spawned by this module reports its CWD or its inherited
    environment through anything an end-state assertion could read, so the call
    itself is the only observable. The returned mapping is populated by the
    time the helper under test returns.
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
        """Run the scratch copy of the setup script with the given environment."""
        root = _scratch_checkout(tmp_path)
        return subprocess.run(
            ["bash", str(root / "scripts" / SETUP_SCRIPT.name)],
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": _SPAWN_PATH, **env},
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
# Three axes decide where a spawned script writes: its CWD, the tree its own
# BASH_SOURCE resolves from, and the environment it inherits. Neither script
# here reports any of them. entrypoint.sh is a pure case/exec dispatcher, and
# setup_codex_reviewer.sh names its TEMP_FILE off BASH_SOURCE but then moves
# that file away under an EXIT trap that removes it — so the file's absence
# afterwards is the same on fixed and unfixed code and proves nothing.
#
# CWD and the inherited environment are therefore locked by capturing the
# subprocess call, the only place either is observable. BASH_SOURCE is locked
# behaviorally, by a marker carried only by the scratch copy of the canonical
# config: it reaches the installed profile only if the script resolved
# CANONICAL inside the scratch checkout. That marker is the whole of the
# evidence today — CANONICAL and TEMP_FILE both derive from the same
# ${SCRIPT_DIR}/../, so anything that moves SCRIPT_DIR moves both and trips
# the marker first. The scratch tmp/ assertion beside it is defense in depth
# against a later script edit that decouples the two paths, after which it
# would be the only thing watching TEMP_FILE.


class TestSpawnContainment:
    """Verify no spawn in this module can write into the live checkout."""

    def test_entrypoint_runs_from_the_scratch_root_with_a_closed_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_spawn(monkeypatch)
        _run_entrypoint(tmp_path, "codex-review")
        cwd = Path(captured["cwd"]).resolve()
        assert cwd == _scratch_root(tmp_path).resolve()
        # Strictly below tmp_path, which doubles as the scratch HOME. Nothing
        # else catches the root collapsing into tmp_path: the equality above
        # goes green once the two paths coincide.
        assert cwd.parent == tmp_path.resolve()
        assert set(captured["env"]) == {"PATH"}

    def test_setup_runs_from_the_scratch_root_with_a_closed_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_spawn(monkeypatch)
        TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path)})
        cwd = Path(captured["cwd"]).resolve()
        assert cwd == _scratch_root(tmp_path).resolve()
        # Strictly below tmp_path, which this call also passes as HOME. Nothing
        # else catches the root collapsing into tmp_path: the equality above
        # goes green once the two paths coincide.
        assert cwd.parent == tmp_path.resolve()
        assert set(captured["env"]) == {"PATH", "HOME"}

    def test_setup_resolves_script_dir_inside_the_scratch_checkout(self, tmp_path: Path) -> None:
        root = _scratch_checkout(tmp_path)
        canonical = root / "docker" / "agent-cli" / CANONICAL_CONFIG.name
        canonical.write_text(f"{canonical.read_text()}\n{_SCRATCH_CANONICAL_MARKER}\n")
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        # Path 3 — the only branch that creates the TEMP_FILE directory.
        config = codex_dir / "config.toml"
        config.write_text('[profiles.reviewer]\nmodel = "old-model"\n')

        result = TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path)})

        assert result.returncode == 0
        # CANONICAL resolved to the marked copy, not the checked-in one.
        assert _SCRATCH_CANONICAL_MARKER in config.read_text()
        # TEMP_FILE's parent is created by the script; _scratch_checkout leaves it absent.
        assert (root / "tmp").is_dir()
