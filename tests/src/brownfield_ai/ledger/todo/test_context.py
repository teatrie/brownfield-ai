"""Tests for brownfield_ai.ledger.todo.context — capture_context and build_chromadb_document."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from brownfield_ai.ledger.todo.context import build_chromadb_document, capture_context

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# capture_context
# ---------------------------------------------------------------------------


def test_capture_context_extracts_epic_id_from_branch_regex(make_db) -> None:
    """Branch name matching _EPIC_ID_PATTERN populates active_epic_id."""
    with patch("brownfield_ai.ledger.todo.context.git") as mock_git:
        mock_repo = MagicMock()
        mock_repo.active_branch.name = "ACME-1234/my-feature"
        mock_repo.head.commit.diff.return_value = []
        mock_repo.iter_commits.return_value = []
        mock_git.Repo.return_value = mock_repo
        mock_git.InvalidGitRepositoryError = Exception
        mock_git.GitCommandError = Exception

        ctx = capture_context(make_db)

    assert ctx["git_branch"] == "ACME-1234/my-feature"
    assert ctx["active_epic_id"] == "ACME-1234"


def test_capture_context_falls_back_to_single_in_progress_epic(make_db) -> None:
    """When branch has no epic ID, falls back to single in_progress epic in DB."""
    db = make_db
    db.execute(
        "INSERT INTO epics (epic_id, status, priority, depends_on, title, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("ACME-FALLBACK", "in_progress", 5, "[]", "Fallback Epic", "2026-01-01", "2026-01-01"),
    )
    db.commit()

    with patch("brownfield_ai.ledger.todo.context.git") as mock_git:
        mock_repo = MagicMock()
        mock_repo.active_branch.name = "feature/plain-branch"
        mock_repo.head.commit.diff.return_value = []
        mock_repo.iter_commits.return_value = []
        mock_git.Repo.return_value = mock_repo
        mock_git.InvalidGitRepositoryError = Exception
        mock_git.GitCommandError = Exception

        ctx = capture_context(db)

    assert ctx["active_epic_id"] == "ACME-FALLBACK"


def test_capture_context_returns_null_epic_when_multiple_in_progress(make_db) -> None:
    """Multiple in_progress epics yield None for active_epic_id."""
    db = make_db
    for eid in ["ACME-AAA", "ACME-BBB"]:
        db.execute(
            "INSERT INTO epics (epic_id, status, priority, depends_on, title, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (eid, "in_progress", 5, "[]", f"Epic {eid}", "2026-01-01", "2026-01-01"),
        )
    db.commit()

    with patch("brownfield_ai.ledger.todo.context.git") as mock_git:
        mock_repo = MagicMock()
        mock_repo.active_branch.name = "feature/no-epic"
        mock_repo.head.commit.diff.return_value = []
        mock_repo.iter_commits.return_value = []
        mock_git.Repo.return_value = mock_repo
        mock_git.InvalidGitRepositoryError = Exception
        mock_git.GitCommandError = Exception

        ctx = capture_context(db)

    assert ctx["active_epic_id"] is None


def test_capture_context_includes_schema_version_and_notes(make_db) -> None:
    """Schema version 1 and user notes are always included."""
    with patch("brownfield_ai.ledger.todo.context.git") as mock_git:
        mock_repo = MagicMock()
        mock_repo.active_branch.name = "main"
        mock_repo.head.commit.diff.return_value = []
        mock_repo.iter_commits.return_value = []
        mock_git.Repo.return_value = mock_repo
        mock_git.InvalidGitRepositoryError = Exception
        mock_git.GitCommandError = Exception

        ctx = capture_context(make_db, notes="Some user notes")

    assert ctx["schema_version"] == 1
    assert ctx["notes"] == "Some user notes"


def test_capture_context_survives_subprocess_failure(make_db) -> None:
    """Git failures are handled gracefully with safe defaults."""
    with patch("brownfield_ai.ledger.todo.context.git") as mock_git:
        mock_git.InvalidGitRepositoryError = Exception
        mock_git.GitCommandError = Exception
        mock_git.Repo.side_effect = Exception("not a repo")

        ctx = capture_context(make_db)

    assert ctx["schema_version"] == 1
    assert ctx["git_branch"] is None
    assert ctx["modified_files"] == []


def test_capture_context_survives_broken_pipe_from_git_subprocess(make_db) -> None:
    """A ``BrokenPipeError`` from GitPython's helper process is not fatal.

    Patches only ``git.Repo`` so the real exception classes stay in place;
    aliasing them to ``Exception`` would catch everything and prove nothing.
    """
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "main"
    mock_repo.head.commit.diff.side_effect = BrokenPipeError(32, "Broken pipe")
    mock_repo.iter_commits.side_effect = BrokenPipeError(32, "Broken pipe")

    with patch("brownfield_ai.ledger.todo.context.git.Repo", return_value=mock_repo):
        ctx = capture_context(make_db)

    assert ctx["schema_version"] == 1
    assert ctx["git_branch"] == "main"
    assert ctx["modified_files"] == []
    assert ctx["recent_commits"] == []


def test_capture_context_survives_oserror_opening_repo(make_db) -> None:
    """An ``OSError`` while opening the repo degrades to empty git context."""
    with patch("brownfield_ai.ledger.todo.context.git.Repo", side_effect=OSError("stale file handle")):
        ctx = capture_context(make_db)

    assert ctx["schema_version"] == 1
    assert ctx["git_branch"] is None
    assert ctx["modified_files"] == []
    assert ctx["recent_commits"] == []


def test_capture_context_survives_broken_pipe_reading_active_branch(make_db) -> None:
    """A ``BrokenPipeError`` from ``active_branch`` still yields a usable snapshot.

    ``PropertyMock`` is required so the error is raised on attribute access; a
    plain ``side_effect`` would only fire on a call. As with the test above, only
    ``git.Repo`` is patched — aliasing the real exception classes would make the
    assertions vacuous.
    """
    mock_repo = MagicMock()
    type(mock_repo).active_branch = PropertyMock(side_effect=BrokenPipeError(32, "Broken pipe"))
    mock_repo.head.commit.diff.side_effect = BrokenPipeError(32, "Broken pipe")
    mock_repo.iter_commits.side_effect = BrokenPipeError(32, "Broken pipe")

    with patch("brownfield_ai.ledger.todo.context.git.Repo", return_value=mock_repo):
        ctx = capture_context(make_db)

    assert ctx["schema_version"] == 1
    assert ctx["git_branch"] is None
    assert ctx["modified_files"] == []
    assert ctx["recent_commits"] == []


def test_capture_context_propagates_unlinked_cwd(make_db) -> None:
    """An unlinked working directory is a broken process state, not a degradation."""
    with patch("brownfield_ai.ledger.todo.context.os.getcwd", side_effect=FileNotFoundError(2, "No such file or directory")):
        with pytest.raises(FileNotFoundError):
            capture_context(make_db)


def _dying_commit_stream() -> Iterator[MagicMock]:
    """Yield one commit, then fail — mimics a ``git rev-list`` stream dying mid-read."""
    yield MagicMock(hexsha="a" * 40, summary="first")
    raise BrokenPipeError(32, "Broken pipe")


def test_capture_context_discards_partially_streamed_commits(make_db) -> None:
    """A mid-stream ``iter_commits`` failure yields no commits, not a truncated prefix.

    Unlike the ``side_effect`` tests above, which raise at call time, this uses a
    generator that fails only after yielding — the one shape that distinguishes an
    all-or-nothing comprehension from an incremental append loop. Patches only
    ``git.Repo`` so the real exception classes stay in place.
    """
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "main"
    mock_repo.head.commit.diff.return_value = []
    mock_repo.iter_commits.return_value = _dying_commit_stream()

    with patch("brownfield_ai.ledger.todo.context.git.Repo", return_value=mock_repo):
        ctx = capture_context(make_db)

    assert ctx["git_branch"] == "main"
    assert ctx["recent_commits"] == []


# ---------------------------------------------------------------------------
# build_chromadb_document
# ---------------------------------------------------------------------------


def test_build_chromadb_document_includes_title_and_description() -> None:
    """Title and description appear in the document text."""
    ctx = {"notes": "", "modified_files": []}
    result = build_chromadb_document("Fix bug", "A description", ctx)
    assert "Fix bug" in result
    assert "A description" in result


def test_build_chromadb_document_includes_modified_files() -> None:
    """Modified files are newline-delimited in the document."""
    ctx = {"notes": "", "modified_files": ["src/main.py", "tests/test_main.py"]}
    result = build_chromadb_document("Title", "Desc", ctx)
    assert "src/main.py" in result
    assert "tests/test_main.py" in result
