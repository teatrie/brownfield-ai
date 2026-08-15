"""Snapshot/restore for the real-checkout ``tmp/`` artifacts a wrapper run touches.

The reviewer-wrapper tests invoke shell scripts against the live repository
checkout, so a run writes the same ``tmp/`` paths a live review writes. The
mechanism here captures those paths before the run and rewrites them after, so
a test cannot leave a live artifact truncated, replaced, or deleted.

The managed path set is wrapper-specific and belongs with the wrapper's own
test module; only the generic mechanism lives here — including
``wrapper_tmp_paths``, which reads a wrapper's source so a suite can hold its
managed set against the paths the wrapper actually names.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import NamedTuple

# A ``tmp/`` path as a wrapper spells it: literal path characters, ``${VAR}``
# placeholders, and the ``$$`` of a PID-scoped name. Nothing else terminates a
# name, so a diagnostic string that ends at a bare ``tmp/`` yields no match.
_TMP_PATH_CHARS = r"(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$\$|[A-Za-z0-9._-])"
# Only a word character disqualifies the prefix, so ``mytmp/`` is skipped while
# an anchored ``${top}/tmp/...`` and a ``${VAR:-tmp/...}`` default are caught.
_TMP_PATH = re.compile(rf"(?<![A-Za-z0-9_])tmp/({_TMP_PATH_CHARS}+)")
_SHELL_COMMENT_LINE = re.compile(r"(?m)^[ \t]*#.*$")
_SHELL_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class UnmanageableArtifactError(RuntimeError):
    """A managed path exists in a form the snapshot/restore cycle cannot reproduce."""


class ArtifactState(NamedTuple):
    """The content and permission bits a restore has to reproduce."""

    content: bytes
    mode: int


def isolate_artifacts(paths: Iterable[Path], prepare: Callable[[], None]) -> Iterator[None]:
    """Run ``prepare``, yield to the test, then restore every path in ``paths``.

    Drive this from a fixture with ``yield from``. The snapshot is the only step
    outside the protected region, and it mutates nothing. Every write,
    ``prepare``'s included, runs under the ``finally``, so a ``prepare`` that
    fails mid-write is still restored.

    Args:
        paths: the artifacts the guarded run creates or overwrites.
        prepare: per-wrapper setup, run once the snapshot is safely captured.

    Yields:
        Once, with the snapshot captured and ``prepare`` applied.

    Raises:
        UnmanageableArtifactError: propagated from the snapshot, before
            ``prepare`` runs and before anything is written.
        ExceptionGroup: one or more paths could not be restored. A failed
            restore means live artifacts are still damaged, so it stays the
            active exception even when ``prepare`` also failed; that earlier
            failure is reachable on ``__context__`` and prints with the
            traceback.
    """
    snapshot = snapshot_artifacts(paths)
    try:
        prepare()
        yield
    finally:
        restore_artifacts(snapshot)


def snapshot_artifacts(paths: Iterable[Path]) -> dict[Path, ArtifactState | None]:
    """Capture each path's content and mode, recording ``None`` for a path that is absent.

    Args:
        paths: the artifacts to capture.

    Raises:
        UnmanageableArtifactError: a path is a symlink, or exists as something
            other than a regular file. Recording either as absent would have
            the restore unlink a directory or a developer's symlink; recording
            a symlink's dereferenced content would have the restore write
            through the link.
    """
    snapshot: dict[Path, ArtifactState | None] = {}
    for path in paths:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise UnmanageableArtifactError(f"not a regular file, refusing to manage: {path}")
        if not path.is_file():
            snapshot[path] = None
            continue
        snapshot[path] = ArtifactState(path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
    return snapshot


def restore_artifacts(snapshot: Mapping[Path, ArtifactState | None]) -> None:
    """Reinstate each path's snapshotted content and mode, removing paths recorded absent.

    Timestamps are not reproduced. Every path is attempted even after an
    earlier one fails, so one unwritable artifact cannot cost the rest.

    A path recorded as ``None`` was absent and is removed again — recreating it
    empty would itself corrupt a consumer that reads it as a review subject.

    Args:
        snapshot: the mapping ``snapshot_artifacts`` returned.

    Raises:
        ExceptionGroup: one or more paths could not be restored.
    """
    failures: list[OSError] = []
    for path, state in snapshot.items():
        try:
            if state is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                _replace_with_state(path, state)
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise ExceptionGroup("failed to restore tmp/ artifacts", failures)


def _replace_with_state(path: Path, state: ArtifactState) -> None:
    """Write ``state`` to a sibling temporary file and rename it onto ``path``.

    A direct write follows a symlink the guarded run installed at ``path`` and
    lands the snapshotted content on the link's target, possibly outside the
    managed tree. ``os.replace`` replaces the link itself. The temporary file
    shares the destination's directory so the rename stays on one filesystem.

    Args:
        path: the managed artifact to overwrite.
        state: the content and permission bits to reinstate.
    """
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".restore")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(state.content)
        temp_path.chmod(state.mode)
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def wrapper_tmp_paths(scripts: Iterable[Path], substitutions: Mapping[str, str]) -> set[str]:
    """Extract every ``tmp/`` path the given shell sources name, relative to ``tmp/``.

    Whole-line comments are dropped first, so usage banners and rationale notes
    that spell an artifact name do not register. What survives is a superset of
    the sources' writes: a read-only reference registers too and has to be
    managed or allow-listed like any other, which is the conservative direction
    for a guard on a managed set.

    Args:
        scripts: the shell sources to scan.
        substitutions: shell variable names mapped to the value the caller's
            run gives them, e.g. ``ROUND`` to the round id. A name left out
            stays literal, so it matches no managed path and surfaces as an
            uncovered entry rather than being silently dropped.
    """
    named: set[str] = set()
    for script in scripts:
        source = _SHELL_COMMENT_LINE.sub("", script.read_text())
        for match in _TMP_PATH.finditer(source):
            named.add(_SHELL_VAR.sub(lambda hit: substitutions.get(hit.group(1), hit.group(0)), match.group(1)))
    return named
