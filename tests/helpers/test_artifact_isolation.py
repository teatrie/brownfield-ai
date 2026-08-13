"""Tests for tests/helpers/artifact_isolation.py.

The wrapper suites that depend on this mechanism never observe it — it can be
removed with those suites still green — so these tests are its lock. Every one
works under ``tmp_path``; none reads or writes the real checkout's ``tmp/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.artifact_isolation import (
    UnmanageableArtifactError,
    isolate_artifacts,
    restore_artifacts,
    snapshot_artifacts,
)


class TestArtifactIsolation:
    """Cover the snapshot/restore mechanism the reviewer-wrapper fixtures build on."""

    def test_snapshot_records_none_for_an_absent_path(self, tmp_path: Path) -> None:
        present = tmp_path / "codex-exit.json"
        present.write_bytes(b"live signal")
        absent = tmp_path / "codex-review-err.txt"
        snapshot = snapshot_artifacts([present, absent])
        assert snapshot[present] == b"live signal"
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
