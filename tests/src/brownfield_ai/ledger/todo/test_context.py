"""Tests for brownfield_ai.ledger.todo.context — capture_context and build_chromadb_document."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from brownfield_ai.ledger.todo.context import build_chromadb_document, capture_context

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

    GitPython keeps a persistent ``cat-file --batch-check`` subprocess per repo.
    When git kills it — e.g. the dubious-ownership check firing on a CI runner
    whose checkout uid differs from the uid running the tests — the next write
    raises ``BrokenPipeError``. That is an ``OSError``, not a ``git.*`` error,
    so it escapes any except tuple listing only GitPython exceptions.

    Unlike ``test_capture_context_survives_subprocess_failure``, this patches
    only ``git.Repo`` so the real exception classes stay in place; aliasing them
    to ``Exception`` would catch everything and prove nothing.
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
