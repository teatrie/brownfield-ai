"""Multi-repo branch management for ralph headless epic runner.

Uses GitPython for all git operations. Each epic may span multiple
repositories (e.g. brownfield-ai, service-b, analytics), each with its own
feature branch. This module ensures branches are checked out, up to
date, and pushed after session completion.
"""

import logging
from pathlib import Path

import git

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Workspace root detection
# ---------------------------------------------------------------------------

_WORKSPACE_ROOT: Path = Path(__file__).resolve().parents[4]
"""Workspace root: four levels up from src/brownfield_ai/tools/ralph/git.py."""


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_repo_path(repo: str) -> str:
    """Map a repo key to a local filesystem path.

    ``"brownfield-ai"`` maps to ``"."`` (workspace root). All other keys map
    to ``"repos/{repo}"``.

    Args:
        repo: The repo key (e.g. ``"brownfield-ai"``, ``"service-b"``).

    Returns:
        Absolute filesystem path as a string.
    """
    if repo == "brownfield-ai":
        return str(_WORKSPACE_ROOT)
    return str(_WORKSPACE_ROOT / "repos" / repo)


# ---------------------------------------------------------------------------
# Branch operations
# ---------------------------------------------------------------------------


def ensure_branch(repo_path: str, branch: str) -> None:
    """Ensure a repo's branch is checked out locally.

    Handles three cases:

    1. Branch exists locally --- checkout and fast-forward from remote.
    2. Branch exists on remote only --- create local tracking branch.
    3. Branch does not exist anywhere --- create from main (first sub-plan).

    Args:
        repo_path: Absolute path to the repository root.
        branch: The branch name to check out.

    Raises:
        FileNotFoundError: If *repo_path* does not exist.
        RuntimeError: If the branch has diverged (cannot fast-forward).
    """
    path = Path(repo_path)
    if not path.exists():
        raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

    repo = git.Repo(repo_path)

    # Fetch latest remote state
    origin = repo.remotes.origin
    origin.fetch()

    local_branches = [ref.name for ref in repo.branches]
    remote_ref = f"origin/{branch}"
    remote_exists = remote_ref in [ref.name for ref in repo.remotes.origin.refs]

    if branch in local_branches:
        _checkout_and_fast_forward(repo, branch, remote_ref, remote_exists)
    elif remote_exists:
        _create_tracking_branch(repo, branch, remote_ref)
    else:
        _create_from_main(repo, branch)


def _checkout_and_fast_forward(
    repo: git.Repo,
    branch: str,
    remote_ref: str,
    remote_exists: bool,
) -> None:
    """Checkout an existing local branch and fast-forward from remote.

    Args:
        repo: The GitPython Repo object.
        branch: Local branch name.
        remote_ref: Full remote ref (e.g. ``origin/feat/x``).
        remote_exists: Whether the remote ref exists.

    Raises:
        RuntimeError: If the branch has diverged and cannot fast-forward.
    """
    repo.heads[branch].checkout()
    if not remote_exists:
        logger.info("Branch '%s' exists locally but not on remote; skipping pull.", branch)
        return

    local_commit = repo.head.commit
    remote_commit = repo.commit(remote_ref)

    if local_commit == remote_commit:
        return

    if repo.is_ancestor(local_commit, remote_commit):
        repo.head.reset(remote_commit, working_tree=True)
        logger.info("Fast-forwarded '%s' to %s.", branch, remote_commit.hexsha[:8])
    else:
        raise RuntimeError(
            f"Branch '{branch}' has diverged from '{remote_ref}' "
            f"(local: {local_commit.hexsha[:8]}, "
            f"remote: {remote_commit.hexsha[:8]}). "
            "Cannot fast-forward."
        )


def _create_tracking_branch(
    repo: git.Repo,
    branch: str,
    remote_ref: str,
) -> None:
    """Create a local branch tracking an existing remote branch.

    Args:
        repo: The GitPython Repo object.
        branch: Local branch name to create.
        remote_ref: Full remote ref to track (e.g. ``origin/feat/x``).
    """
    remote_commit = repo.commit(remote_ref)
    new_branch = repo.create_head(branch, remote_commit)
    new_branch.checkout()
    logger.info("Created local branch '%s' tracking '%s'.", branch, remote_ref)


def _create_from_main(repo: git.Repo, branch: str) -> None:
    """Create a new branch from the main branch.

    Used for the first sub-plan when no branch exists yet.

    Args:
        repo: The GitPython Repo object.
        branch: The new branch name.
    """
    main_ref = _resolve_main_branch(repo)
    new_branch = repo.create_head(branch, main_ref)
    new_branch.checkout()
    logger.info("Created branch '%s' from '%s'.", branch, main_ref)


def _resolve_main_branch(repo: git.Repo) -> str:
    """Resolve the main branch ref, preferring remote origin/main.

    Args:
        repo: The GitPython Repo object.

    Returns:
        The resolved ref string (e.g. ``"origin/main"`` or ``"main"``).
    """
    remote_refs = [ref.name for ref in repo.remotes.origin.refs]
    if "origin/main" in remote_refs:
        return "origin/main"
    if "origin/master" in remote_refs:
        return "origin/master"
    local_branches = [ref.name for ref in repo.branches]
    if "main" in local_branches:
        return "main"
    if "master" in local_branches:
        return "master"
    return "HEAD"


def ensure_all_branches(branches: dict[str, str]) -> None:
    """Ensure all repos in the epic have their branches checked out.

    Args:
        branches: Mapping of repo key to branch name.

    Raises:
        FileNotFoundError: If any repo path does not exist.
        RuntimeError: If any branch has diverged.
    """
    for repo, branch in branches.items():
        repo_path = resolve_repo_path(repo)
        logger.info("Ensuring branch '%s' for repo '%s' at %s.", branch, repo, repo_path)
        ensure_branch(repo_path, branch)


# ---------------------------------------------------------------------------
# Push operations
# ---------------------------------------------------------------------------


def push_branch(repo_path: str, branch: str) -> bool:
    """Push committed work to remote.

    Args:
        repo_path: Absolute path to the repository root.
        branch: The branch name to push.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin
        push_info = origin.push(branch)
        for info in push_info:
            if info.flags & info.ERROR:
                logger.error(
                    "Push failed for '%s' in %s: %s",
                    branch,
                    repo_path,
                    info.summary,
                )
                return False
        logger.info("Pushed '%s' from %s.", branch, repo_path)
        return True
    except git.GitCommandError as exc:
        logger.error("Git push error for '%s' in %s: %s", branch, repo_path, exc)
        return False


def push_all_branches(
    branches: dict[str, str],
) -> bool:
    """Push all repo branches to remote. Stops on first failure.

    Args:
        branches: Mapping of repo key to branch name.

    Returns:
        ``True`` if all pushes succeeded, ``False`` otherwise.
    """
    for repo, branch in branches.items():
        repo_path = resolve_repo_path(repo)
        success = push_branch(repo_path, branch)
        if not success:
            logger.error(
                "Push failed for repo '%s' branch '%s'.",
                repo,
                branch,
            )
            return False
    return True
