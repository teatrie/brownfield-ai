"""Tests for the codex reviewer setup script.

Covered here: ``scripts/setup_codex_reviewer.sh``, the derivation both CI test
routers reach this module through, and the containment of the ``bash`` child
this module spawns over a copy of the setup script.

Every setup run here starts from a directory under ``tmp_path``, against a copy
of the script inside a scratch checkout there. It arms an ``EXIT`` trap over
a ``BASH_SOURCE``-derived temp path before it branches, so spawning the
checked-in copy aims an ``rm -f`` at the live checkout on every code path,
whatever the CWD is -- and on the update path writes there as well. The
``grep`` spawn is given a ``cwd`` under ``tmp_path`` as well, so neither child
runs from the pytest process's own directory.

The environment each child receives is enumerated, never inherited. That is
credential containment first and path hygiene second: an inherited
environment would hand the script the pytest process's own credentials along
with ``PYTHONPATH`` and the rest of the session.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = WORKSPACE / "scripts" / "setup_codex_reviewer.sh"
CANONICAL_CONFIG = WORKSPACE / "docker" / "agent-cli" / "codex-config.toml"

# Read from the canonical rather than restated, so an assertion against it
# says the canonical was installed. A lone model bump there reaches this
# module in neither router, so a literal here would go stale uncaught.
_CANONICAL_REVIEWER_MODEL: str = tomllib.loads(CANONICAL_CONFIG.read_text(encoding="utf-8"))["profiles"]["reviewer"]["model"]

# System directories only, so no checkout-managed entry such as ``.venv/bin``
# can supply a binary to a spawned child.
_SPAWN_PATH = "/usr/bin:/bin:/usr/local/bin"

# Appended to the scratch copy of the canonical config, so a profile installed
# carrying it proves the setup script resolved CANONICAL inside the scratch
# checkout. A TOML comment, so the marked copy still parses.
_SCRATCH_CANONICAL_MARKER = "# scratch-checkout canonical"

# Carried only by the decoy canonical under the CWD, so a profile installed
# carrying it proves CANONICAL was resolved against the CWD instead.
_DECOY_CANONICAL_MARKER = "# decoy-cwd canonical"

# The two post-setup hints, verbatim.
_INSTALL_HINT = "Install Codex CLI: npm install -g @openai/codex"
_AUTH_HINT = "Set OPENAI_API_KEY or run 'codex login' for OAuth"

# Both ``grep -q`` sites in the script: the append-vs-replace discriminator
# (``elif``) and the post-install verification gate (``if``).
_GREP_SITE_RE = re.compile(r"^\s*(if|elif) ! grep -q '([^']*)'", re.MULTILINE)

# Path 3 fixtures. One cannot carry both awk directions: with an
# ``.instructions`` block between the reviewer keys and the next profile, a
# sed-range deletion stops at the subsection header and the next profile
# survives it, so the boundary direction needs a fixture without one.
_CONFIG_WITH_REVIEWER_SUBSECTION = (
    '[settings]\ntheme = "dark"\n\n'
    "[profiles.reviewer]\n"
    'model = "old-model"\n\n'
    "[profiles.reviewer.instructions]\n"
    'role = "Old Role"\n'
    'focus = "Old focus"\n'
)

# [profiles.reviewer_backup] has to stay immediately after the reviewer keys:
# an unrelated profile ahead of it clears ``skip`` first, so a widened
# character class in the awk would delete nothing extra and go unnoticed.
_CONFIG_WITH_ADJACENT_PROFILES = (
    '[settings]\ntheme = "dark"\n\n'
    "[profiles.reviewer]\n"
    'model = "old-model"\n'
    "[profiles.reviewer_backup]\n"
    'model = "backup-model"\n\n'
    "[profiles.other]\n"
    'model = "other-model"\n'
)

# The two CI test routers, checkout-relative. Neither names this module: both
# derive its path from the script it covers. Keep in step with
# ``router_harness.TEST_ROUTERS``, which holds the same pair as bare filenames.
_ROUTER_PATHS: tuple[str, str] = ("ci/test_staged.sh", "ci/test_changed.sh")

# The line each router's ``scripts/*`` branch builds its target on, verbatim.
# The target that line produces appears as a literal in neither file, so the
# derivation is the only thing a source-text check can hold them to.
_DERIVATION_LINE = 'test_file="tests/${dirname}/test_${basename}.py"'


def _scratch_root(tmp_path: Path) -> Path:
    """Return (creating on first use) the throwaway root the scratch checkout lives in.

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

    ``<root>/tmp/`` is deliberately not created here, so section 2 can assert
    the script's own ``mkdir -p`` created it.

    The early return sits *above* the canonical copy, so a second call leaves
    an already-provisioned canonical untouched -- and ``_run_setup`` makes that
    second call. Copying unconditionally instead would strip the marker the two
    cases below write beforehand: the one that asserts the marker fails, while
    ``test_fresh_install``'s byte comparison silently stops discriminating the
    scratch canonical from the checked-in one.
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


def _decoy_cwd(tmp_path: Path) -> Path:
    """Create, outside the scratch checkout, a CWD holding a decoy canonical config.

    Under the scratch root a ``SCRIPT_DIR``-derived path and a CWD-relative one
    name the same file, so nothing run from there can tell the two apart.
    """
    cwd = tmp_path / "decoy"
    canonical = cwd / CANONICAL_CONFIG.relative_to(WORKSPACE)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(f'[profiles.reviewer]\nmodel = "decoy-model"\n{_DECOY_CANONICAL_MARKER}\n', encoding="utf-8")
    return cwd


def _stub_codex_bin(tmp_path: Path) -> Path:
    """Create under ``tmp_path`` a directory holding an executable ``codex`` stub.

    The body exits non-zero on purpose. ``command -v`` resolves the name
    against ``PATH`` and tests the execute bit without running the file, so the
    hint rows are unaffected -- but a probe rewritten to invoke the binary
    would see the failure and fire the install hint on all six
    ``codex-present`` rows. With an ``exit 0`` body that rewrite is invisible:
    the present rows suppress the hint either way.
    """
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "codex"
    stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    return bin_dir


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


def _grep_matches(
    pattern: str,
    body: str,
    tmp_path: Path,
    name: str,
) -> bool:
    """Report whether ``grep`` matches ``pattern`` in ``body``, held as ``name`` under ``tmp_path``.

    The real binary, not a Python ``re`` compile of the same string: the
    script's two sites are read as POSIX BREs by ``grep`` itself. An exit
    status outside 0 and 1 is a ``grep`` error -- an invalid pattern, or a file
    it could not read -- which fails here rather than being read as "no match".

    Callers name the scratch file rather than hand over a path, so the
    destination is derived here. Mirrors ``_decoy_cwd`` and ``_stub_codex_bin``,
    which likewise take ``tmp_path`` and derive their own.
    """
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    result = subprocess.run(
        ["grep", "-q", pattern, str(path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        # The enumerated _SPAWN_PATH the setup spawns are built from (two tests
        # compose a prefix ahead of it), rather than an inherited environment.
        env={"PATH": _SPAWN_PATH},
        cwd=str(tmp_path),
    )
    assert result.returncode in (0, 1), f"grep failed on {pattern!r} with exit {result.returncode}: {result.stderr.strip()}"
    return result.returncode == 0


def _assert_reviewer_table_declared_once(content: str) -> None:
    """Assert an installed config declares ``[profiles.reviewer]`` once and parses.

    Path 3 deletes the old section and appends the canonical one, so an awk
    that leaves the old header behind produces two declarations of the same
    table -- which every substring check on the result still passes. The count
    is asserted ahead of the parse, so that case reports the count rather than
    a decode error.
    """
    headers = [line for line in content.splitlines() if line.startswith("[profiles.reviewer]")]
    assert len(headers) == 1, f"expected exactly one [profiles.reviewer] header in the installed config, found {len(headers)}"
    assert "reviewer" in tomllib.loads(content)["profiles"]


# ---------------------------------------------------------------------------
# 1. Setup script
# ---------------------------------------------------------------------------


class TestSetupCodexReviewer:
    """Test scripts/setup_codex_reviewer.sh across all three code paths.

    Every case that runs the setup script uses the scratch copy
    ``_scratch_checkout`` provisions rather than the checked-in script. The
    ``EXIT`` trap that removes the cleaned-config temp file is armed ahead of
    the branch, so all three paths bind a ``TEMP_FILE`` under whichever tree
    the script copy lives in.
    """

    def _run_setup(
        self,
        tmp_path: Path,
        env: dict[str, str],
        *,
        path_prefix: Path | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the scratch copy of the setup script with the given environment.

        A ``PATH`` in ``env`` is discarded. ``path_prefix`` composes ahead of
        ``_SPAWN_PATH`` and must resolve under ``tmp_path``. ``cwd`` defaults to
        the scratch root and must likewise resolve under ``tmp_path``. ``HOME``
        is required in ``env`` and held to the same bound. All three are
        enforced here rather than at a call site, so no caller can hand the
        script a directory outside ``tmp_path``.
        """
        root = _scratch_checkout(tmp_path)
        contained = tmp_path.resolve()
        # Required rather than tolerated-if-absent: of the three contained
        # values, HOME is the one the script writes under.
        assert "HOME" in env, "env must set HOME: the script writes ${HOME}/.codex/config.toml and the .bak beside it"
        home = Path(env["HOME"])
        assert home.resolve().is_relative_to(contained), f"HOME {home} does not resolve under {tmp_path}"
        for label, candidate in (("path_prefix", path_prefix), ("cwd", cwd)):
            if candidate is not None:
                assert candidate.resolve().is_relative_to(contained), f"{label} {candidate} does not resolve under {tmp_path}"
        path = _SPAWN_PATH if path_prefix is None else f"{path_prefix}:{_SPAWN_PATH}"
        return subprocess.run(
            ["bash", str(root / SETUP_SCRIPT.relative_to(WORKSPACE))],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            env={**env, "PATH": path},
            cwd=str(root if cwd is None else cwd),
        )

    def test_fresh_install(self, tmp_path: Path) -> None:
        """Path 1: No existing config — copies the canonical file byte for byte."""
        root = _scratch_checkout(tmp_path)
        canonical = root / CANONICAL_CONFIG.relative_to(WORKSPACE)
        # Unmarked, the scratch and checked-in canonicals are identical copies
        # and the comparison below would not say which one was read.
        canonical.write_text(f"{canonical.read_text(encoding='utf-8')}\n{_SCRATCH_CANONICAL_MARKER}\n", encoding="utf-8")
        # ~/.codex is left absent, so the script's own mkdir -p has to create it.
        assert not (tmp_path / ".codex").exists()

        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})

        assert result.returncode == 0
        assert (tmp_path / ".codex" / "config.toml").read_bytes() == canonical.read_bytes()

    def test_append_to_existing(self, tmp_path: Path) -> None:
        """Path 2: Existing config without [profiles.reviewer] — appends."""
        root = _scratch_checkout(tmp_path)
        canonical = root / CANONICAL_CONFIG.relative_to(WORKSPACE)
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        original = b'[settings]\ntheme = "dark"\n'
        config.write_bytes(original)

        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})

        assert result.returncode == 0
        # Composition rather than startswith/endswith: dropping the separating
        # newline satisfies both of those and would go unnoticed.
        assert config.read_bytes() == original + b"\n" + canonical.read_bytes()
        assert not (codex_dir / "config.toml.bak").exists()

    def test_update_existing_reviewer(self, tmp_path: Path) -> None:
        """Path 3: Existing config with [profiles.reviewer] — replaces, backing up first."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        original = b'[settings]\ntheme = "dark"\n\n[profiles.reviewer]\nmodel = "old-model"\n'
        config.write_bytes(original)

        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})

        assert result.returncode == 0
        content = config.read_text(encoding="utf-8")
        assert "[settings]" in content
        assert "[profiles.reviewer]" in content
        assert _CANONICAL_REVIEWER_MODEL in content
        assert "old-model" not in content
        _assert_reviewer_table_declared_once(content)
        # Pre-run bytes: a backup taken after the rewrite holds the cleaned file.
        assert (codex_dir / "config.toml.bak").read_bytes() == original

    @pytest.mark.parametrize(
        ("existing", "must_be_gone", "surviving_bytes"),
        [
            pytest.param(
                _CONFIG_WITH_REVIEWER_SUBSECTION,
                ("Old Role", "Old focus"),
                b'[settings]\ntheme = "dark"\n\n',
                id="deletion-scope",
            ),
            pytest.param(
                _CONFIG_WITH_ADJACENT_PROFILES,
                (),
                b'[settings]\ntheme = "dark"\n\n[profiles.reviewer_backup]\nmodel = "backup-model"\n\n[profiles.other]\nmodel = "other-model"\n',
                id="boundary",
            ),
        ],
    )
    def test_update_replaces_only_the_reviewer_section(
        self,
        tmp_path: Path,
        existing: str,
        must_be_gone: tuple[str, ...],
        surviving_bytes: bytes,
    ) -> None:
        """Path 3: the skip zone covers the reviewer subsection and clears at the next profile.

        Neither case asserts ``[profiles.reviewer]`` is absent -- Path 3
        re-appends it. The deletion-scope case asserts the subsection's *keys*
        are gone rather than its header: a sed-range deletion eats the header
        and leaves the keys behind.

        ``surviving_bytes`` is what the awk leaves of ``existing``.
        ``test_update_existing_reviewer`` stays substring-only because its awk
        output composes to the deletion-scope bytes exactly; what it holds
        alone is the ``.bak`` contents.
        """
        root = _scratch_checkout(tmp_path)
        canonical = root / CANONICAL_CONFIG.relative_to(WORKSPACE)
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text(existing, encoding="utf-8")

        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})

        assert result.returncode == 0
        content = config.read_text(encoding="utf-8")
        assert "[settings]" in content
        assert "[profiles.reviewer]" in content
        assert _CANONICAL_REVIEWER_MODEL in content
        assert "old-model" not in content
        for token in must_be_gone:
            assert token not in content
        _assert_reviewer_table_declared_once(content)
        # Composition rather than substrings: dropping the separating newline
        # satisfies every check above and would go unnoticed.
        assert config.read_bytes() == surviving_bytes + b"\n" + canonical.read_bytes()

    def test_the_exit_trap_removes_a_temp_file_path_one_never_writes(self, tmp_path: Path) -> None:
        """The trap is armed ahead of the branch, so Path 1 clears a temp file it never wrote."""
        root = _scratch_checkout(tmp_path)
        canonical = root / CANONICAL_CONFIG.relative_to(WORKSPACE)
        # ``<root>/tmp/`` is characterized, not endorsed: the module docstring
        # calls a checkout-internal TEMP_FILE a hazard.
        temp_file = root / "tmp" / "codex-config-cleaned.toml"
        temp_file.parent.mkdir(parents=True)
        temp_file.write_text("stale\n", encoding="utf-8")

        result = self._run_setup(tmp_path, {"HOME": str(tmp_path)})

        assert result.returncode == 0
        config = tmp_path / ".codex" / "config.toml"
        # Path 1 discriminators: paths 2 and 3 both leave the prior config ahead
        # of the canonical bytes, and path 3 also writes a backup.
        assert not (config.parent / "config.toml.bak").exists()
        assert config.read_bytes() == canonical.read_bytes()
        assert not temp_file.exists()

    @pytest.mark.parametrize("auth_json", [None, "", '{"tokens": {}}'], ids=["auth-missing", "auth-empty", "auth-non-empty"])
    @pytest.mark.parametrize("api_key", [None, "sk-test"], ids=["no-api-key", "api-key"])
    @pytest.mark.parametrize("codex_on_path", [False, True], ids=["codex-absent", "codex-present"])
    def test_post_setup_hints_fire_exactly_on_their_conditions(
        self,
        tmp_path: Path,
        codex_on_path: bool,
        api_key: str | None,
        auth_json: str | None,
    ) -> None:
        """Both hints, over (codex on PATH) x (OPENAI_API_KEY) x (auth.json)."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        if auth_json is not None:
            (codex_dir / "auth.json").write_text(auth_json, encoding="utf-8")
        env = {"HOME": str(tmp_path)}
        if api_key is not None:
            env["OPENAI_API_KEY"] = api_key
        path_prefix: Path | None = None
        if codex_on_path:
            path_prefix = _stub_codex_bin(tmp_path)
        else:
            # _SPAWN_PATH names /usr/local/bin, where the Codex CLI installs, so
            # the absent rows are a claim about the environment. Fail loudly
            # rather than let them assert nothing.
            assert shutil.which("codex", path=_SPAWN_PATH) is None, (
                f"a codex binary is resolvable on {_SPAWN_PATH}, so the six codex-absent rows here assert nothing. They hold only "
                "because docker/pytest-cli/Dockerfile npm-installs @github/copilot and @google/gemini-cli and not @openai/codex; "
                "adding @openai/codex to that line, or an `npm install -g @openai/codex` following this script's own hint whose "
                "global prefix falls inside _SPAWN_PATH, breaks all six. Install the Codex CLI outside _SPAWN_PATH instead"
            )

        result = self._run_setup(tmp_path, env, path_prefix=path_prefix)

        assert result.returncode == 0
        assert result.stdout.count(_INSTALL_HINT) == (0 if codex_on_path else 1)
        assert result.stdout.count(_AUTH_HINT) == (1 if api_key is None and not auth_json else 0)

    def test_both_grep_sites_share_a_pattern_the_canonical_toml_matches(self, tmp_path: Path) -> None:
        """The append-vs-replace discriminator and the post-install gate stay coupled to the TOML."""
        sites = _GREP_SITE_RE.findall(SETUP_SCRIPT.read_text(encoding="utf-8"))
        assert len(sites) == 2, f"expected the append-vs-replace discriminator and the verification gate, found {sites}"
        keywords = [keyword for keyword, _ in sites]
        assert keywords == ["elif", "if"], f"expected the elif discriminator then the if gate, found {sites}"
        patterns = {pattern for _, pattern in sites}
        assert len(patterns) == 1, f"the two grep sites must test one pattern, found {sorted(patterns)}"
        pattern = patterns.pop()
        assert _grep_matches(pattern, CANONICAL_CONFIG.read_text(encoding="utf-8"), tmp_path, "canonical.toml"), (
            f"{pattern!r} matches nothing in {CANONICAL_CONFIG}"
        )
        subsection_only = '[profiles.reviewer.instructions]\nrole = "Old Role"\n'
        assert not _grep_matches(pattern, subsection_only, tmp_path, "subsection-only.toml"), (
            f"{pattern!r} matches a body whose only reviewer header is the [profiles.reviewer.instructions] subsection. Such a pattern sends a config that has no [profiles.reviewer] header down the replace path at the discriminator, and lets the verification gate report success over a config that never gained one. Every assertion above passes with the pattern mutated to 'profiles.reviewer' at both sites."
        )
        foreign_header_only = '[profilesXreviewer]\nmodel = "old-model"\n'
        assert not _grep_matches(pattern, foreign_header_only, tmp_path, "foreign-header-only.toml"), (
            f"{pattern!r} matches a body whose only header is [profilesXreviewer], so it leaves the dot unescaped. Such a pattern sends a config that has no [profiles.reviewer] header down the replace path at the discriminator, and lets the verification gate report success over a config that never gained one. The subsection probe above cannot see this: dropping the backslash keeps the `^` anchor and the `\\]`, so the mutated pattern still fails to match [profiles.reviewer.instructions] and every assertion before this one passes."
        )


# ---------------------------------------------------------------------------
# 2. Spawn containment and path resolution
# ---------------------------------------------------------------------------


class TestSpawnContainment:
    """Verify what contains the setup spawn this module makes.

    CWD, environment, stdin and the deadline are pinned against the captured
    ``subprocess.run`` kwargs, since the script reports none of them itself.
    ``HOME`` is the load-bearing value among them: ``setup_codex_reviewer.sh``
    derives ``${HOME}/.codex/config.toml`` and the ``.bak`` beside it, so a
    ``HOME`` that drifted back to the developer's own would aim every setup
    case at their live reviewer profile.

    ``stdin`` and ``timeout`` are forward guards against an edit that
    introduces a command reading the caller's stdin: nothing the script runs
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

    def test_a_composed_path_prefix_precedes_the_spawn_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Separate from the guard above, which a composed PATH would fail by construction."""
        captured = _capture_spawn(monkeypatch)
        prefix = _stub_codex_bin(tmp_path)
        TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path)}, path_prefix=prefix)
        entries = captured["env"]["PATH"].split(":")
        # Ahead of _SPAWN_PATH: composed behind it, an installed Codex CLI in
        # /usr/local/bin would win and the codex-present hint rows would prove
        # nothing about the stub.
        assert entries == [str(prefix), *_SPAWN_PATH.split(":")]

    def test_setup_resolves_script_dir_inside_the_scratch_checkout(self, tmp_path: Path) -> None:
        root = _scratch_checkout(tmp_path)
        canonical = root / CANONICAL_CONFIG.relative_to(WORKSPACE)
        canonical.write_text(f"{canonical.read_text(encoding='utf-8')}\n{_SCRATCH_CANONICAL_MARKER}\n", encoding="utf-8")
        cwd = _decoy_cwd(tmp_path)
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        # Path 3 — reads CANONICAL at the end of the update branch.
        config = codex_dir / "config.toml"
        config.write_text('[profiles.reviewer]\nmodel = "old-model"\n', encoding="utf-8")

        result = TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path)}, cwd=cwd)

        assert result.returncode == 0
        content = config.read_text(encoding="utf-8")
        # CANONICAL resolved to the marked copy, not to the decoy under the CWD.
        assert _SCRATCH_CANONICAL_MARKER in content
        assert _DECOY_CANONICAL_MARKER not in content

    def test_setup_creates_the_temp_file_parent_inside_its_own_tree(self, tmp_path: Path) -> None:
        root = _scratch_checkout(tmp_path)
        cwd = _decoy_cwd(tmp_path)
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        # Path 3 — the only branch that reaches the TEMP_FILE mkdir.
        (codex_dir / "config.toml").write_text('[profiles.reviewer]\nmodel = "old-model"\n', encoding="utf-8")
        # Asserted immediately before the spawn: TEMP_FILE's parent has to be
        # the script's own creation for the check after it to mean anything.
        # ``<root>/tmp/`` is characterized, not endorsed — see
        # test_the_exit_trap_removes_a_temp_file_path_one_never_writes.
        assert not (root / "tmp").exists()

        result = TestSetupCodexReviewer()._run_setup(tmp_path, {"HOME": str(tmp_path)}, cwd=cwd)

        assert result.returncode == 0
        assert (root / "tmp").is_dir()
        assert not (cwd / "tmp").exists()


# ---------------------------------------------------------------------------
# 3. Routing
# ---------------------------------------------------------------------------


class TestRoutingDerivation:
    """Pin the derivation both CI test routers reach this module through.

    ``scripts/setup_codex_reviewer.sh`` matches no literal in either router: it
    falls through to the ``scripts/*`` branch, which ``[ -f ]``-guards a
    derived ``tests/<dirname>/test_<basename>.py``, so a name that resolves to
    nothing routes no tests and still exits 0.

    Nothing here imports ``helpers.router_harness``, which carries the
    behavioural half: both routers fan a changed module under
    ``tests/helpers/`` out to ``tests/helpers/`` and ``tests/ci/`` only, so an
    import from ``tests/scripts/`` would be a dependency no router covers. Do
    not merge the two copies.

    Two accepted limitations, both deferred rather than blind. A deletion-only
    diff of this module reaches neither half: its path is derived rather than
    hard-coded, so neither router carries a literal that goes stale when it
    disappears -- but the behavioural half then fails (empty target list, False
    ``is_file()``) on either router's next edit and on the next change under
    ``tests/ci/`` or ``tests/helpers/``. A lone
    ``docker/agent-cli/codex-config.toml`` change reaches section 1's
    TOML-coupled assertion in neither router, and waits for the script's own
    next change. A full ``task test:scripts`` catches both.
    """

    def test_the_router_derivation_over_the_setup_script_names_this_module(self) -> None:
        """The derivation applied to the covered script resolves to this file's own path.

        The assertion that survives a rename, and the reason this half exists:
        move or rename this module and the derived name stops matching it while
        the routers go on deriving the old one.
        """
        covered = SETUP_SCRIPT.relative_to(WORKSPACE)
        source = covered.as_posix()
        # The routers' ``scripts/*`` derivation over this one constant: strip
        # the extension off the basename, map dashes to underscores, re-root
        # the source's own directory under ``tests/``.
        derived = f"tests/{covered.parent.as_posix()}/test_{covered.stem.replace('-', '_')}.py"
        own_path = Path(__file__).resolve().relative_to(WORKSPACE).as_posix()
        assert derived == own_path, (
            f"both routers derive {derived!r} from {source!r} and guard it with `[ -f ]`, but this module "
            f"lives at {own_path!r}; the derived name resolves to nothing, so a change to {source} routes no "
            "tests at all and the router still exits 0 — move this module back to the derived path, or "
            "rename the script it covers so the derivation lands on it again"
        )

    def test_both_routers_still_carry_the_derivation(self) -> None:
        """Each router still builds its ``scripts/*`` target out of the changed path.

        The other direction of the same pin: the case above holds this module
        to the name the routers derive, this one holds the routers to deriving
        it. Checked as source text rather than run, for the routing reason in
        the class docstring, and against the derivation rather than against
        ``tests/scripts/test_setup_codex_reviewer.py`` — that path is computed,
        so it is a literal in neither router and a search for it would fail.
        """
        source = SETUP_SCRIPT.relative_to(WORKSPACE).as_posix()
        for router in _ROUTER_PATHS:
            text = (WORKSPACE / router).read_text(encoding="utf-8")
            assert _DERIVATION_LINE in text, (
                f"{router} no longer builds its `scripts/*` target as {_DERIVATION_LINE} — a changed {source} "
                "then derives some other name, and the `[ -f ]` guard turns a name that resolves to nothing "
                "into an empty target list and a zero exit; restore the derivation, or update _DERIVATION_LINE "
                "to whatever replaced it and re-check that it still names this module"
            )
