"""Snapshot/restore for the real-checkout ``tmp/`` artifacts a wrapper run touches.

The reviewer-wrapper tests invoke shell scripts against the live repository
checkout, so a run writes the same ``tmp/`` paths a live review writes. The
mechanism here captures those paths before the run and rewrites them after, so
a test cannot leave a live artifact truncated, replaced, or deleted.

The managed path set is wrapper-specific and belongs with the wrapper's own
test module; only the generic mechanism lives here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path


class UnmanageableArtifactError(RuntimeError):
    """A managed path exists in a form the snapshot/restore cycle cannot reproduce."""


def isolate_artifacts(paths: Iterable[Path], prepare: Callable[[], None]) -> Iterator[None]:
    """Run ``prepare``, yield to the test, then restore every path in ``paths``.

    Drive this from a fixture with ``yield from``. The snapshot is the only step
    outside the protected region, and it mutates nothing. Every write,
    ``prepare``'s included, runs under the ``finally``, so a ``prepare`` that
    fails mid-write is still restored.

    Args:
        paths: the artifacts the guarded run creates or overwrites.
        prepare: per-wrapper setup, run once the snapshot is safely captured.
    """
    snapshot = snapshot_artifacts(paths)
    try:
        prepare()
        yield
    finally:
        restore_artifacts(snapshot)


def snapshot_artifacts(paths: Iterable[Path]) -> dict[Path, bytes | None]:
    """Capture each path's bytes, recording ``None`` for a path that is absent.

    Raises:
        UnmanageableArtifactError: a path is a symlink, or exists as something
            other than a regular file. Recording either as absent would have
            the restore unlink a directory or a developer's symlink.
    """
    snapshot: dict[Path, bytes | None] = {}
    for path in paths:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise UnmanageableArtifactError(f"not a regular file, refusing to manage: {path}")
        snapshot[path] = path.read_bytes() if path.is_file() else None
    return snapshot


def restore_artifacts(snapshot: Mapping[Path, bytes | None]) -> None:
    """Rewrite each path's snapshotted content, removing paths recorded absent.

    Contents only — mode and timestamps are not reproduced. Every path is
    attempted even after an earlier one fails, so one unwritable artifact
    cannot cost the rest.

    A path recorded as ``None`` was absent and is removed again — recreating it
    empty would itself corrupt a consumer that reads it as a review subject.

    Raises:
        ExceptionGroup: one or more paths could not be restored.
    """
    failures: list[OSError] = []
    for path, content in snapshot.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise ExceptionGroup("failed to restore tmp/ artifacts", failures)
