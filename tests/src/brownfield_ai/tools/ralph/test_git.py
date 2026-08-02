from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import git as gitmodule
import pytest

from brownfield_ai.tools.ralph.git import (
    ensure_all_branches,
    ensure_branch,
    push_all_branches,
    push_branch,
    resolve_repo_path,
)

# ---------------------------------------------------------------------------
# resolve_repo_path
# ---------------------------------------------------------------------------


def test_resolve_repo_path_brownfield_ai() -> None:
    result = resolve_repo_path("brownfield-ai")
    assert "repos" not in result


def test_resolve_repo_path_other_repo() -> None:
    result = resolve_repo_path("service-b")
    assert "repos/service-b" in result


def test_resolve_repo_path_analytics() -> None:
    result = resolve_repo_path("analytics")
    assert "repos/analytics" in result


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_ref(name: str) -> MagicMock:
    """Create a mock git ref with a given name."""
    ref = MagicMock()
    ref.name = name
    return ref


def _mock_commit(hexsha: str = "abcd1234abcd1234") -> MagicMock:
    """Create a mock git commit."""
    commit = MagicMock()
    commit.hexsha = hexsha
    return commit


class _MockHeadsAccessor:
    """Dict-like mock that also supports iteration over branch refs."""

    def __init__(self, local_branches: list[str]) -> None:
        self._refs = [_mock_ref(b) for b in local_branches]
        self._heads: dict[str, MagicMock] = {}
        for b in local_branches:
            self._heads[b] = MagicMock()

    def __iter__(self) -> Any:
        return iter(self._refs)

    def __getitem__(self, key: str) -> MagicMock:
        return self._heads[key]


class _MockRefsAccessor:
    """List-like mock for remote refs supporting iteration."""

    def __init__(self, refs: list[str]) -> None:
        self._refs = [_mock_ref(r) for r in refs]

    def __iter__(self) -> Any:
        return iter(self._refs)


def _build_mock_repo(
    *,
    local_branches: list[str],
    remote_refs: list[str],
    head_commit_sha: str = "aaa11111",
    remote_commit_sha: str = "bbb22222",
    is_ancestor: bool = True,
) -> MagicMock:
    """Build a mock git.Repo with the given branch/remote state."""
    repo = MagicMock()

    # repo.branches and repo.heads share the same accessor
    heads_accessor = _MockHeadsAccessor(local_branches)
    repo.branches = heads_accessor
    repo.heads = heads_accessor

    # repo.remotes.origin
    origin = MagicMock()
    origin.refs = _MockRefsAccessor(remote_refs)
    origin.fetch = MagicMock()
    origin.push = MagicMock(return_value=[])
    repo.remotes.origin = origin

    # repo.head.commit
    local_commit = _mock_commit(head_commit_sha)
    repo.head = MagicMock()
    repo.head.commit = local_commit
    repo.head.reset = MagicMock()

    # repo.commit(remote_ref) returns the remote commit
    remote_commit = _mock_commit(remote_commit_sha)
    repo.commit = MagicMock(return_value=remote_commit)

    # repo.is_ancestor
    repo.is_ancestor = MagicMock(return_value=is_ancestor)

    # repo.create_head
    new_head = MagicMock()
    new_head.checkout = MagicMock()
    repo.create_head = MagicMock(return_value=new_head)

    return repo


# ---------------------------------------------------------------------------
# ensure_branch
# ---------------------------------------------------------------------------


def test_ensure_branch_missing_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_branch(str(tmp_path / "nonexistent"), "feat/test")


def test_ensure_branch_local_exists_fast_forward(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_repo = _build_mock_repo(
        local_branches=["feat/test", "main"],
        remote_refs=["origin/feat/test", "origin/main"],
        head_commit_sha="aaa11111",
        remote_commit_sha="bbb22222",
        is_ancestor=True,
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    ensure_branch(str(repo_dir), "feat/test")

    mock_repo.heads["feat/test"].checkout.assert_called_once()
    mock_repo.head.reset.assert_called_once()


def test_ensure_branch_local_exists_already_up_to_date(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    same_commit = _mock_commit("same1234")
    mock_repo = _build_mock_repo(
        local_branches=["feat/test"],
        remote_refs=["origin/feat/test"],
    )
    mock_repo.head.commit = same_commit
    mock_repo.commit = MagicMock(return_value=same_commit)
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    ensure_branch(str(repo_dir), "feat/test")

    mock_repo.heads["feat/test"].checkout.assert_called_once()
    mock_repo.head.reset.assert_not_called()


def test_ensure_branch_remote_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_repo = _build_mock_repo(
        local_branches=["main"],
        remote_refs=["origin/feat/test", "origin/main"],
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    ensure_branch(str(repo_dir), "feat/test")

    mock_repo.create_head.assert_called_once()
    call_args = mock_repo.create_head.call_args
    assert call_args[0][0] == "feat/test"


def test_ensure_branch_new_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_repo = _build_mock_repo(
        local_branches=["main"],
        remote_refs=["origin/main"],
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    ensure_branch(str(repo_dir), "feat/new")

    mock_repo.create_head.assert_called_once()
    call_args = mock_repo.create_head.call_args
    assert call_args[0][0] == "feat/new"
    assert call_args[0][1] == "origin/main"


def test_ensure_branch_diverged_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_repo = _build_mock_repo(
        local_branches=["feat/test"],
        remote_refs=["origin/feat/test"],
        head_commit_sha="aaa11111",
        remote_commit_sha="bbb22222",
        is_ancestor=False,
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    with pytest.raises(RuntimeError, match="diverged"):
        ensure_branch(str(repo_dir), "feat/test")


# ---------------------------------------------------------------------------
# push_branch
# ---------------------------------------------------------------------------


def test_push_branch_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_repo = MagicMock()
    push_info_item = MagicMock()
    push_info_item.flags = 0
    push_info_item.ERROR = 1024
    mock_repo.remotes.origin.push.return_value = [push_info_item]
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    result = push_branch(str(repo_dir), "feat/test")
    assert result is True


def test_push_branch_error_returns_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_repo = MagicMock()
    push_info_item = MagicMock()
    push_info_item.flags = 1024
    push_info_item.ERROR = 1024
    push_info_item.summary = "rejected"
    mock_repo.remotes.origin.push.return_value = [push_info_item]
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    result = push_branch(str(repo_dir), "feat/test")
    assert result is False


def test_push_branch_git_command_error_returns_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_repo = MagicMock()
    mock_repo.remotes.origin.push.side_effect = gitmodule.GitCommandError("push", "error")
    monkeypatch.setattr("brownfield_ai.tools.ralph.git.git.Repo", lambda path: mock_repo)

    result = push_branch(str(repo_dir), "feat/test")
    assert result is False


# ---------------------------------------------------------------------------
# push_all_branches
# ---------------------------------------------------------------------------


def test_push_all_branches_stops_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    call_log: list[str] = []

    def mock_push(repo_path: str, branch: str) -> bool:
        call_log.append(repo_path)
        if "service-b" in repo_path:
            return False
        return True

    monkeypatch.setattr("brownfield_ai.tools.ralph.git.push_branch", mock_push)

    branches = {
        "service-b": "feat/test",
        "analytics": "feat/test",
    }
    result = push_all_branches(branches)
    assert result is False
    assert len(call_log) == 1


def test_push_all_branches_all_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_push(repo_path: str, branch: str) -> bool:
        return True

    monkeypatch.setattr("brownfield_ai.tools.ralph.git.push_branch", mock_push)

    branches = {"brownfield-ai": "feat/a", "service-b": "feat/b"}
    result = push_all_branches(branches)
    assert result is True


def test_push_all_branches_no_ledger_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """push_all_branches must be side-effect-free: no ledger_status call on failure."""

    def mock_push(repo_path: str, branch: str) -> bool:
        return False

    monkeypatch.setattr("brownfield_ai.tools.ralph.git.push_branch", mock_push)

    result = push_all_branches({"brownfield-ai": "feat/x"})
    assert result is False


# ---------------------------------------------------------------------------
# ensure_all_branches
# ---------------------------------------------------------------------------


def test_ensure_all_branches_iterates_all(monkeypatch: pytest.MonkeyPatch) -> None:
    call_log: list[tuple[str, str]] = []

    def mock_ensure(repo_path: str, branch: str) -> None:
        call_log.append((repo_path, branch))

    monkeypatch.setattr("brownfield_ai.tools.ralph.git.ensure_branch", mock_ensure)

    branches = {"brownfield-ai": "feat/a", "service-b": "feat/b"}
    ensure_all_branches(branches)
    assert len(call_log) == 2
    repos_called = [path for path, _ in call_log]
    assert any("repos/service-b" in p for p in repos_called)
    assert any("repos" not in p for p in repos_called)
