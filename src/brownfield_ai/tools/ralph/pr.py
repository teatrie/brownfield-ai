"""PR creation and CI monitoring for ralph headless epic runner.

Wraps ``task gh:pr`` CLI commands via subprocess for PR lifecycle management
and CI check polling. Subprocess is acceptable here because ``task`` is a
non-Python CLI with no SDK equivalent.
"""

import logging
import re
import subprocess
import time
from typing import Any, cast

import git

from brownfield_ai.tools.ralph.client import ledger_touch, parse_json_output
from brownfield_ai.tools.ralph.git import resolve_repo_path
from brownfield_ai.tools.ralph.templates import get_template

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CI conclusion classification
# ---------------------------------------------------------------------------

_PASSING_CONCLUSIONS: frozenset[str] = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
_FAILING_CONCLUSIONS: frozenset[str] = frozenset({"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_gh_task(
    args: list[str],
    *,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a ``task gh:pr`` command and return the result.

    Args:
        args: Arguments forwarded after ``task gh:pr --``.
        timeout: Maximum seconds to wait for the command. On expiry,
            returns a synthetic failed result instead of raising.

    Returns:
        The completed subprocess result.
    """
    cmd = ["task", "gh:pr", "--"] + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("gh task timed out after %ds: %s", timeout, cmd)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr=f"TimeoutExpired: command timed out after {timeout}s",
        )


# ---------------------------------------------------------------------------
# Repo detection
# ---------------------------------------------------------------------------


def detect_modified_repos(branches: dict[str, str]) -> list[str]:
    """Detect repos with commits ahead of origin/main.

    For each repo in the branches mapping, counts commits between
    ``origin/main`` and the feature branch. Repos with one or more
    commits are considered modified.

    Args:
        branches: Mapping of repo key to branch name.

    Returns:
        List of repo keys that have commits ahead of origin/main.

    Raises:
        FileNotFoundError: If a repo path does not exist.
    """
    modified: list[str] = []
    for repo, branch in branches.items():
        repo_path = resolve_repo_path(repo)
        r = git.Repo(repo_path)
        first_commit = next(iter(r.iter_commits(f"origin/main..{branch}")), None)
        if first_commit is not None:
            modified.append(repo)
    return modified


# ---------------------------------------------------------------------------
# PR URL parsing
# ---------------------------------------------------------------------------

_PR_URL_PATTERN = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$")


def pr_url_to_ref(url: str) -> str:
    """Convert a GitHub PR URL to a short ref.

    Parses ``https://github.com/{owner}/{repo}/pull/{number}`` into
    ``{owner}/{repo}#{number}``.

    Args:
        url: Full GitHub pull request URL.

    Returns:
        Short PR reference string (e.g. ``acme/brownfield-ai#42``).

    Raises:
        ValueError: If the URL is empty or does not match the expected
            GitHub PR URL pattern.
    """
    if not url:
        raise ValueError("Empty PR URL")
    match = _PR_URL_PATTERN.match(url)
    if not match:
        raise ValueError(f"Invalid PR URL: {url}")
    owner, repo, number = match.groups()
    return f"{owner}/{repo}#{number}"


# ---------------------------------------------------------------------------
# PR body rendering
# ---------------------------------------------------------------------------


def render_pr_body(epic_id: str, resume: dict[str, Any]) -> str:
    """Render the PR body from the Jinja2 template.

    Loads ``pr_body.md.j2`` from the templates directory and renders
    it with epic context from the resume.

    Args:
        epic_id: The epic identifier.
        resume: The full resume context from the ledger.

    Returns:
        Rendered PR body markdown string.
    """
    template = get_template("pr_body.md.j2")

    wave_summaries = resume.get("wave_summaries", [])
    gate_verdicts = resume.get("gate_verdicts", [])

    rendered: str = template.render(
        epic_id=epic_id,
        wave_summaries=wave_summaries,
        gate_verdicts=gate_verdicts,
    )
    return rendered


# ---------------------------------------------------------------------------
# PR creation and closing
# ---------------------------------------------------------------------------


def create_pr(
    repo: str,
    branch: str,
    title: str,
    body: str,
) -> str | None:
    """Create a pull request for a single repo.

    Args:
        repo: Repository name (e.g. ``brownfield-ai``).
        branch: Feature branch name.
        title: PR title.
        body: PR body text.

    Returns:
        The PR URL string on success, ``None`` on failure.
    """
    result = _run_gh_task([
        "create",
        "--repo",
        f"acme/{repo}",
        "--head",
        branch,
        "--base",
        "main",
        "--title",
        title,
        "--body",
        body,
        "--json",
        "url",
    ])
    if result.returncode != 0:
        logger.warning(
            "PR creation failed for %s: %s",
            repo,
            result.stderr.strip(),
        )
        return None
    try:
        data = parse_json_output(result.stdout)
        return cast(str, data["url"])
    except (ValueError, KeyError):
        logger.warning(
            "Could not parse PR URL from output: %s",
            result.stdout[:200],
        )
        return None


def close_pr(pr_url: str) -> None:
    """Close an existing pull request.

    Logs on failure but does not raise.

    Args:
        pr_url: Full GitHub PR URL to close.
    """
    result = _run_gh_task(["close", pr_url])
    if result.returncode != 0:
        logger.warning(
            "Failed to close PR %s: %s",
            pr_url,
            result.stderr.strip(),
        )


# ---------------------------------------------------------------------------
# Batch PR creation (all-or-nothing)
# ---------------------------------------------------------------------------


def create_all_prs(
    epic_id: str,
    branches: dict[str, str],
    resume: dict[str, Any],
) -> dict[str, str]:
    """Create PRs for all repos in ``branches`` with all-or-nothing rollback.

    Caller is responsible for filtering ``branches`` to only modified
    repos before calling this function. If any PR creation fails, all
    previously created PRs are closed and an empty dict is returned.

    Args:
        epic_id: The epic identifier.
        branches: Repo-to-branch mapping (pre-filtered to modified repos).
        resume: The full resume context from the ledger.

    Returns:
        Dict mapping repo key to PR URL. Empty dict on failure or
        if ``branches`` is empty.
    """
    if not branches:
        return {}

    title = resume.get("plan_snapshot", {}).get("metadata", {}).get("title", epic_id)
    body = render_pr_body(epic_id, resume)

    created: dict[str, str] = {}
    for repo, branch in branches.items():
        url = create_pr(repo, branch, title, body)
        if url is None:
            logger.warning(
                "PR creation failed for '%s'. Rolling back %d created PRs.",
                repo,
                len(created),
            )
            for rollback_url in created.values():
                close_pr(rollback_url)
            return {}
        created[repo] = url

    return created


# ---------------------------------------------------------------------------
# CI check polling
# ---------------------------------------------------------------------------


def poll_ci_checks(pr_url: str) -> str:
    """Poll CI check status for a single PR.

    Calls ``task gh:pr -- checks`` and parses the JSON array output.
    Each element is a dict with ``state``, ``conclusion``, and ``name``
    fields.

    Args:
        pr_url: Full GitHub PR URL to check.

    Returns:
        ``"pass"`` if all checks completed successfully,
        ``"fail"`` if any completed check failed,
        ``"pending"`` if any check is not yet completed or output is empty.
    """
    result = _run_gh_task([
        "checks",
        pr_url,
        "--json",
        "name,state,conclusion",
    ])
    if result.returncode != 0:
        logger.warning(
            "CI check query failed for %s: %s",
            pr_url,
            result.stderr.strip(),
        )
        return "pending"

    try:
        checks: list[dict[str, str]] = parse_json_output(result.stdout)
    except ValueError:
        return "pending"

    if not checks:
        return "pending"

    for check in checks:
        if check.get("state") != "COMPLETED":
            return "pending"

    for check in checks:
        if check.get("conclusion", "").upper() in _FAILING_CONCLUSIONS:
            return "fail"

    if all(check.get("conclusion", "").upper() in _PASSING_CONCLUSIONS for check in checks):
        return "pass"

    return "fail"


def poll_all_ci(
    pr_urls: dict[str, str],
    epic_id: str,
    *,
    interval: int,
    timeout: int,
) -> tuple[str, dict[str, str]]:
    """Poll CI checks for all PRs with timeout.

    Repeatedly checks all PRs until all pass, any fail (with none
    pending), or timeout is reached. Calls ``ledger_touch`` on each
    iteration to maintain the claim heartbeat.

    Args:
        pr_urls: Dict mapping repo to PR URL.
        epic_id: The epic identifier.
        interval: Seconds between polling iterations.
        timeout: Maximum seconds to poll before timing out.

    Returns:
        Tuple of ``(verdict, failed_dict)`` where verdict is
        ``"all_green"`` or ``"failed"`` and failed_dict maps repo
        keys to URLs for failed or non-passing PRs.
    """
    start = time.time()

    while True:
        ledger_touch(epic_id)

        statuses: dict[str, str] = {}
        for repo, url in pr_urls.items():
            statuses[repo] = poll_ci_checks(url)

        # Check if all pass
        if all(s == "pass" for s in statuses.values()):
            return ("all_green", {})

        # Check if any pending
        has_pending = any(s == "pending" for s in statuses.values())

        if not has_pending:
            # All resolved, some failed
            failed = {repo: pr_urls[repo] for repo, status in statuses.items() if status != "pass"}
            return ("failed", failed)

        # Check timeout
        elapsed = time.time() - start
        if elapsed >= timeout:
            non_pass = {repo: pr_urls[repo] for repo, status in statuses.items() if status != "pass"}
            return ("failed", non_pass)

        time.sleep(interval)


# ---------------------------------------------------------------------------
# CI failure collection
# ---------------------------------------------------------------------------


def collect_ci_failures(
    failed_prs: dict[str, str],
) -> list[dict[str, str]]:
    """Collect detailed failure information from CI checks.

    For each failed PR, queries check details and filters for those
    with ``FAILURE`` conclusion.

    Args:
        failed_prs: Dict mapping repo to PR URL for failed PRs.

    Returns:
        List of failure dicts with ``name``, ``log_url``, and ``repo``
        keys. Returns partial results on API errors.
    """
    if not failed_prs:
        return []

    failures: list[dict[str, str]] = []
    for repo, url in failed_prs.items():
        result = _run_gh_task([
            "checks",
            url,
            "--json",
            "name,state,conclusion,detailsUrl",
        ])
        if result.returncode != 0:
            logger.warning(
                "Failed to fetch checks for %s: %s",
                url,
                result.stderr.strip(),
            )
            continue

        try:
            checks: list[dict[str, str]] = parse_json_output(result.stdout)
        except ValueError:
            continue

        for check in checks:
            if check.get("conclusion", "").upper() == "FAILURE":
                failures.append({
                    "name": check.get("name", "unknown"),
                    "log_url": check.get("detailsUrl", ""),
                    "repo": repo,
                })

    return failures
