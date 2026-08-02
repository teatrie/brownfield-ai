"""Context capture and ChromaDB document building for TODOs.

Provides functions to auto-capture git context snapshots and construct
ChromaDB document text from TODO fields.
"""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import re

import git

from brownfield_ai.ledger.artifacts.constants import REDACTION_PATTERNS
from brownfield_ai.ledger.todo.constants import _EPIC_ID_PATTERN


def capture_context(db: sqlite3.Connection, *, notes: str = "") -> dict[str, Any]:
    """Auto-capture git context snapshot for a new TODO.

    Runs git commands to detect the current branch, modified files, and
    recent commits. Extracts an epic ID from the branch name via regex,
    falling back to querying the epics table for a single in-progress epic.

    Args:
        db: SQLite database connection for epic fallback query.
        notes: Optional free-text notes to include in the snapshot.

    Returns:
        Context snapshot matching schema v1 with keys
        ``schema_version``, ``git_branch``, ``active_epic_id``,
        ``modified_files``, ``recent_commits``, and ``notes``.

        Git context is best-effort: if git is unavailable, refuses to answer, or
        its helper subprocess dies, the corresponding fields degrade to ``None``
        / empty lists rather than raising, and callers cannot distinguish a
        degraded snapshot from a genuinely clean tree. When ``git_branch``
        degrades to ``None``, ``active_epic_id`` falls through to the
        single-in-progress-epic DB query.
    """
    git_branch: str | None = None
    modified_files: list[str] = []
    recent_commits: list[dict[str, str]] = []
    repo: git.Repo | None = None

    # Git context is best-effort — a TODO must still be capturable when git is
    # unavailable or refuses to answer. ``OSError`` is caught alongside the
    # GitPython errors because GitPython keeps a persistent ``cat-file
    # --batch-check`` subprocess: if git kills it (e.g. the dubious-ownership
    # check firing when the checkout uid differs from the running uid, as on CI
    # runners) the next write to its stdin raises ``BrokenPipeError``, an
    # ``OSError`` subclass, rather than a ``git.*`` error.

    # Git branch. ``os.getcwd()`` is hoisted out of the try because its own
    # ``FileNotFoundError`` (an ``OSError``) means the process's working directory
    # was unlinked — a broken process state unrelated to the GitPython rationale
    # above, and one that must not be silently swallowed here.
    cwd = os.getcwd()
    try:
        repo = git.Repo(cwd, search_parent_directories=True)
        git_branch = repo.active_branch.name
    except (git.InvalidGitRepositoryError, git.GitCommandError, TypeError, OSError):
        pass

    # Modified files
    if repo is not None:
        try:
            diffs = repo.head.commit.diff(None)
            modified_files = [str(d.a_path or d.b_path) for d in diffs if (d.a_path or d.b_path)]
        except (git.GitCommandError, ValueError, AttributeError, OSError):
            pass

    # Recent commits. ``iter_commits`` is a generator over a ``git rev-list``
    # stream, so a failure partway through would otherwise leave a truncated list
    # bound. Collect into a local and only bind on success, mirroring the
    # all-or-nothing semantics ``modified_files`` gets from its comprehension.
    if repo is not None:
        try:
            collected = [{"sha": commit.hexsha, "message": str(commit.summary)} for commit in repo.iter_commits(max_count=2)]
        except (git.GitCommandError, ValueError, OSError):
            pass
        else:
            recent_commits = collected

    # Epic ID detection: regex from branch name first
    active_epic_id: str | None = None
    if git_branch:
        match: re.Match[str] | None = _EPIC_ID_PATTERN.search(git_branch)
        if match:
            active_epic_id = match.group(0)

    # Fallback: single in_progress epic
    if active_epic_id is None:
        try:
            rows = db.execute("SELECT epic_id FROM epics WHERE status = 'in_progress'").fetchall()
            if len(rows) == 1:
                active_epic_id = rows[0]["epic_id"]
        except sqlite3.Error:
            pass

    return {
        "schema_version": 1,
        "git_branch": git_branch,
        "active_epic_id": active_epic_id,
        "modified_files": modified_files,
        "recent_commits": recent_commits,
        "notes": notes,
    }


def build_chromadb_document(
    title: str,
    description: str,
    context_dict: dict[str, Any],
) -> str:
    """Build a newline-delimited ChromaDB document from TODO fields.

    Extracts ``notes`` and ``modified_files`` from the context snapshot
    dict. Applies ``REDACTION_PATTERNS`` to notes before inclusion.
    Commit SHAs are excluded from the document.

    Args:
        title: The TODO title.
        description: The TODO description.
        context_dict: Decoded context snapshot dictionary.

    Returns:
        Newline-delimited document string for ChromaDB storage.
    """
    notes = context_dict.get("notes", "")
    modified_files = context_dict.get("modified_files", [])

    # Redact secrets/PII from notes
    redacted_notes = notes
    for pattern in REDACTION_PATTERNS:
        redacted_notes = pattern.sub("[REDACTED]", redacted_notes)

    files_text = "\n".join(modified_files) if modified_files else ""
    return f"{title}\n{description}\n{redacted_notes}\n{files_text}"
