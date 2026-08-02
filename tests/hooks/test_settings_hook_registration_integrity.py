"""Integrity check for ``.claude/settings*.json`` hook registrations.

Every command-type hook path registered in any committed or local
settings file must resolve to an existing, executable file on disk.
Missing scripts are silently treated as no-ops by the harness, so a
rename or typo in the registered path can disable an entire rule set
without any runtime signal.

**Scope**: this test validates both ``.claude/settings.json`` (the
committed file, always checked) and ``.claude/settings.local.json``
(a per-developer override, checked when present). The Claude Code
harness merges the local file over the committed one at runtime, so
either file can silently disable a hook — the same TOCTOU regression
class in either location. System-level managed settings
(``/Library/Application Support/ClaudeCode/managed-settings*``) are
out of scope; this test is a repository-local guardrail, not a full
effective-config auditor.

**CI vs local reach**: ``settings.local.json`` is gitignored, so CI
runs this test against the committed file only. The local-file check
fires for developers running ``task test:staged`` / ``task
test:changed`` — catching the uncommitted-edit regression class at
the point it is introduced, which is the exact shape of the TOCTOU
that motivated this test.

Regression context: 2026-04-17, TODO-0083. An uncommitted
``settings.json`` edit rewrote the sandbox-prompt hook path
(``block-sandbox-prompt-patterns.sh``) to a non-existent filename,
silently disabling the entire ``$()`` / backtick / ``<(...)`` /
shell-loop / inline-``FILES=`` / leading-``printf``-``tee`` /
env-var-prefix / bash-``grep``-``rg``-``find`` deny rule set. This
test fails closed on that class of regression in either settings
file.
"""

from __future__ import annotations

import json
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_DIR = REPO_ROOT / ".claude"
COMMITTED_SETTINGS = SETTINGS_DIR / "settings.json"
LOCAL_SETTINGS = SETTINGS_DIR / "settings.local.json"


def _load_settings_files() -> list[tuple[Path, dict[str, Any]]]:
    """Parse every present settings file as ``(path, parsed_dict)`` tuples.

    ``settings.json`` is required (the test fails if it is missing or
    malformed). ``settings.local.json`` is optional — included only
    when the file exists on disk, since it is gitignored and may not
    be present in every checkout.
    """
    result: list[tuple[Path, dict[str, Any]]] = [
        (COMMITTED_SETTINGS, cast(dict[str, Any], json.loads(COMMITTED_SETTINGS.read_text()))),
    ]
    if LOCAL_SETTINGS.is_file():
        result.append((LOCAL_SETTINGS, cast(dict[str, Any], json.loads(LOCAL_SETTINGS.read_text()))))
    return result


def _iter_hook_commands(
    settings: dict[str, Any],
) -> Iterator[tuple[str, str]]:
    """Yield ``(lifecycle_event, command_string)`` for every command-type hook.

    Walks ``settings["hooks"][<event>][*]["hooks"][*]`` and emits only
    entries whose ``type`` field equals ``"command"``.
    """
    for event, matchers in settings.get("hooks", {}).items():
        for matcher in matchers:
            for entry in matcher.get("hooks", []):
                if entry.get("type") == "command":
                    yield event, entry["command"]


def _resolve(command: str) -> Path:
    """Resolve a registered hook command string to an absolute ``Path``.

    Expands ``$CLAUDE_PROJECT_DIR`` to the repo root. Hook commands are
    invoked directly by the harness (no shell), so ``$CLAUDE_PROJECT_DIR``
    is the only variable requiring substitution here.
    """
    return Path(command.replace("$CLAUDE_PROJECT_DIR", str(REPO_ROOT))).resolve()


class TestHookRegistrationIntegrity:
    """Every command-type hook path in ``settings*.json`` must be live on disk."""

    def test_settings_files_parse(self) -> None:
        """Guard against committing a malformed settings file (any variant)."""
        loaded = _load_settings_files()
        assert loaded, "No settings files loaded (settings.json must exist)"

    def test_every_registered_hook_exists(self) -> None:
        """Each registered hook command path must resolve to a regular file."""
        missing: list[str] = []
        for path, settings in _load_settings_files():
            for event, command in _iter_hook_commands(settings):
                resolved = _resolve(command)
                if not resolved.is_file():
                    missing.append(f"{path.name} :: {event} :: {command} -> {resolved}")
        assert not missing, (
            "Registered hook paths point to nonexistent files. The harness "
            "treats missing scripts as no-ops, silently disabling the hook. "
            f"Missing: {missing}"
        )

    def test_every_registered_hook_is_executable(self) -> None:
        """Each registered hook command path must carry the user-execute bit."""
        not_executable: list[str] = []
        for path, settings in _load_settings_files():
            for event, command in _iter_hook_commands(settings):
                resolved = _resolve(command)
                if not resolved.is_file():
                    continue
                if not resolved.stat().st_mode & stat.S_IXUSR:
                    not_executable.append(f"{path.name} :: {event} :: {command}")
        assert not not_executable, (
            f"Registered hooks exist but lack the user-execute bit and will fail at invocation time. Not executable: {not_executable}"
        )

    def test_at_least_one_hook_registered(self) -> None:
        """Sanity: committed ``settings.json`` must register at least one command hook.

        Catches an accidentally-emptied ``hooks`` section in the committed
        file, a regression class distinct from a path typo covered by the
        existence test. Scoped to the committed file only — a developer
        may legitimately run with ``settings.local.json`` disabling hooks
        for a narrow experiment, but the committed baseline must always
        register the repo's standard rule set.
        """
        _, committed_settings = _load_settings_files()[0]
        commands = list(_iter_hook_commands(committed_settings))
        assert commands, "No command-type hooks registered in settings.json"
