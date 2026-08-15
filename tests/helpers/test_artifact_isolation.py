"""Tests for tests/helpers/artifact_isolation.py.

The wrapper suites that depend on this mechanism never observe it — it can be
removed with those suites still green — so these tests are its lock. Every one
works under ``tmp_path``; none reads or writes the real checkout's ``tmp/``.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from helpers.artifact_isolation import (
    UnmanageableArtifactError,
    isolate_artifacts,
    restore_artifacts,
    snapshot_artifacts,
    wrapper_tmp_paths,
)


class TestArtifactIsolation:
    """Cover the snapshot/restore mechanism the reviewer-wrapper fixtures build on."""

    def test_snapshot_records_none_for_an_absent_path(self, tmp_path: Path) -> None:
        present = tmp_path / "codex-exit.json"
        present.write_bytes(b"live signal")
        absent = tmp_path / "codex-review-err.txt"
        snapshot = snapshot_artifacts([present, absent])
        present_state = snapshot[present]
        assert present_state is not None
        assert present_state.content == b"live signal"
        assert snapshot[absent] is None

    def test_restore_removes_a_path_the_run_created(self, tmp_path: Path) -> None:
        absent = tmp_path / "codex-exit.json"
        snapshot = snapshot_artifacts([absent])
        absent.write_bytes(b"written by the run")
        restore_artifacts(snapshot)
        assert not absent.exists()

    def test_restore_attempts_every_path_and_surfaces_the_failure(self, tmp_path: Path) -> None:
        blocked = tmp_path / "codex-exit.json"
        blocked.write_bytes(b"live signal")
        trailing = tmp_path / "codex-review-err.txt"
        trailing.write_bytes(b"live diagnostic")
        snapshot = snapshot_artifacts([blocked, trailing])
        # A directory at the first path fails its write and leaves the second
        # one still clobbered unless every entry is attempted.
        blocked.unlink()
        blocked.mkdir()
        trailing.write_bytes(b"clobbered by the run")
        with pytest.raises(ExceptionGroup) as excinfo:
            restore_artifacts(snapshot)
        assert len(excinfo.value.exceptions) == 1
        assert isinstance(excinfo.value.exceptions[0], OSError)
        assert trailing.read_bytes() == b"live diagnostic"

    def test_snapshot_refuses_a_directory(self, tmp_path: Path) -> None:
        # Docker creates a directory at any bind-mount target that is missing.
        occupied = tmp_path / "codex-exit.json"
        occupied.mkdir()
        with pytest.raises(UnmanageableArtifactError, match="codex-exit.json"):
            snapshot_artifacts([occupied])

    def test_snapshot_refuses_a_dangling_symlink(self, tmp_path: Path) -> None:
        link = tmp_path / "codex-review-err.txt"
        link.symlink_to(tmp_path / "no-such-target.txt")
        with pytest.raises(UnmanageableArtifactError, match="codex-review-err.txt"):
            snapshot_artifacts([link])

    def test_snapshot_refuses_a_symlink_to_a_live_file(self, tmp_path: Path) -> None:
        # A resolvable link is the dangerous one: accepting it would capture
        # the target's content by dereference and restore straight through it.
        target = tmp_path / "developers-own-notes.md"
        target.write_bytes(b"live artifact")
        link = tmp_path / "codex-review-err.txt"
        link.symlink_to(target)
        with pytest.raises(UnmanageableArtifactError, match="codex-review-err.txt"):
            snapshot_artifacts([link])
        assert target.read_bytes() == b"live artifact"

    def test_restore_replaces_a_symlink_planted_after_the_snapshot(self, tmp_path: Path) -> None:
        managed = tmp_path / "codex-exit.json"
        managed.write_bytes(b"live signal")
        snapshot = snapshot_artifacts([managed])
        outside = tmp_path / "elsewhere" / "victim.txt"
        outside.parent.mkdir()
        outside.write_bytes(b"nothing to do with the run")
        managed.unlink()
        managed.symlink_to(outside)
        restore_artifacts(snapshot)
        assert outside.read_bytes() == b"nothing to do with the run"
        assert not managed.is_symlink()
        assert managed.read_bytes() == b"live signal"

    def test_restore_reinstates_the_original_mode(self, tmp_path: Path) -> None:
        managed = tmp_path / "codex-exit.json"
        managed.write_bytes(b"live signal")
        managed.chmod(0o600)
        snapshot = snapshot_artifacts([managed])
        managed.unlink()
        managed.write_bytes(b"written by the run")
        managed.chmod(0o644)
        restore_artifacts(snapshot)
        assert stat.S_IMODE(managed.stat().st_mode) == 0o600

    def test_restore_recreates_a_parent_the_run_removed(self, tmp_path: Path) -> None:
        managed = tmp_path / "tmp" / "codex-exit.json"
        managed.parent.mkdir()
        managed.write_bytes(b"live signal")
        snapshot = snapshot_artifacts([managed])
        managed.unlink()
        managed.parent.rmdir()
        restore_artifacts(snapshot)
        assert managed.read_bytes() == b"live signal"

    def test_setup_failure_still_restores(self, tmp_path: Path) -> None:
        signal = tmp_path / "codex-exit.json"
        signal.write_bytes(b"live signal")

        def _failing_setup() -> None:
            signal.unlink()
            raise RuntimeError("setup failed after its first write")

        isolation = isolate_artifacts([signal], _failing_setup)
        with pytest.raises(RuntimeError, match="setup failed after its first write"):
            next(isolation)
        assert signal.read_bytes() == b"live signal"

    def test_setup_failure_and_restore_failure_both_survive(self, tmp_path: Path) -> None:
        signal = tmp_path / "codex-exit.json"
        signal.write_bytes(b"live signal")

        def _failing_setup() -> None:
            signal.unlink()
            signal.mkdir()
            raise RuntimeError("setup failed after its first write")

        isolation = isolate_artifacts([signal], _failing_setup)
        # The restore failure is the one that means the live artifact is still
        # damaged, so it stays active; the setup failure rides on __context__.
        with pytest.raises(ExceptionGroup) as excinfo:
            next(isolation)
        assert isinstance(excinfo.value.exceptions[0], OSError)
        assert isinstance(excinfo.value.__context__, RuntimeError)
        assert str(excinfo.value.__context__) == "setup failed after its first write"

    def test_restore_runs_after_the_guarded_body(self, tmp_path: Path) -> None:
        signal = tmp_path / "codex-exit.json"
        signal.write_bytes(b"live signal")
        created = tmp_path / "codex-review-output-7.md"
        isolation = isolate_artifacts([signal, created], lambda: signal.write_bytes(b"written by setup"))
        next(isolation)
        assert signal.read_bytes() == b"written by setup"

        created.write_bytes(b"written by the run")
        with pytest.raises(StopIteration):
            next(isolation)

        assert signal.read_bytes() == b"live signal"
        assert not created.exists()


class TestWrapperTmpPaths:
    """Cover the source scan the wrapper suites hold their managed sets against."""

    def _write_script(self, tmp_path: Path, body: str) -> Path:
        """Write ``body`` to a throwaway shell source and return its path."""
        script = tmp_path / "fake-review.sh"
        script.write_text(body)
        return script

    def test_literal_and_templated_paths_are_named(self, tmp_path: Path) -> None:
        script = self._write_script(
            tmp_path,
            'OUTPUT_FILE="tmp/codex-review-output-${ROUND}.md"\n'
            "rm -f tmp/codex-exit.json\n"
            'out="${top}/tmp/${reviewer}-subject-sanitized-${suffix}.txt"\n',
        )
        named = wrapper_tmp_paths([script], {"ROUND": "7", "suffix": "7", "reviewer": "codex"})
        assert named == {
            "codex-review-output-7.md",
            "codex-exit.json",
            "codex-subject-sanitized-7.txt",
        }

    def test_comment_lines_and_bare_mentions_are_skipped(self, tmp_path: Path) -> None:
        script = self._write_script(
            tmp_path,
            "# Output written to tmp/codex-review-output-<ROUND>.md.\n"
            "  # Signals written to tmp/codex-exit.json.\n"
            'echo "FATAL: tmp/ is not writable" >&2\n'
            "mkdir -p tmp\n"
            'tmp_real=$(_review_realpath "$PWD/tmp")\n',
        )
        assert wrapper_tmp_paths([script], {}) == set()

    def test_a_pid_scoped_name_is_named_verbatim(self, tmp_path: Path) -> None:
        script = self._write_script(tmp_path, 'WRITE_PROBE="tmp/.codex-write-probe.$$"\n')
        assert wrapper_tmp_paths([script], {}) == {".codex-write-probe.$$"}

    def test_a_default_inside_a_parameter_expansion_is_named(self, tmp_path: Path) -> None:
        script = self._write_script(tmp_path, 'rm -f "${PREFLIGHT_CACHE_FILE:-tmp/.codex-preflight-cache.json}"\n')
        assert wrapper_tmp_paths([script], {}) == {".codex-preflight-cache.json"}

    def test_an_unsubstituted_variable_stays_literal(self, tmp_path: Path) -> None:
        # An uncovered placeholder must surface as an unmanaged entry, never
        # collapse into a name that happens to match something managed.
        script = self._write_script(tmp_path, 'OUTPUT_FILE="tmp/codex-review-output-${ROUND}.md"\n')
        assert wrapper_tmp_paths([script], {}) == {"codex-review-output-${ROUND}.md"}

    def test_an_unrelated_directory_suffix_is_not_named(self, tmp_path: Path) -> None:
        script = self._write_script(tmp_path, "cp mytmp/report.md other/\n")
        assert wrapper_tmp_paths([script], {}) == set()
