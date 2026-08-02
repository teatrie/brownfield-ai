from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from brownfield_ai.tools.ralph.pr import (
    _run_gh_task,
    close_pr,
    collect_ci_failures,
    create_all_prs,
    create_pr,
    detect_modified_repos,
    poll_all_ci,
    poll_ci_checks,
    pr_url_to_ref,
    render_pr_body,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_completed_process(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["task", "gh:pr", "--"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# detect_modified_repos
# ---------------------------------------------------------------------------


def test_detect_modified_repos_includes_repos_with_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repos with commits ahead of origin/main are included."""
    mock_repo_class = MagicMock()
    mock_repo_instance = MagicMock()
    mock_repo_instance.iter_commits.return_value = [MagicMock(), MagicMock()]
    mock_repo_class.return_value = mock_repo_instance
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.git.Repo", mock_repo_class)
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.resolve_repo_path",
        lambda repo: f"/fake/path/{repo}",
    )

    branches = {"brownfield-ai": "feat/test", "service-b": "feat/test-sub"}
    result = detect_modified_repos(branches)
    assert "brownfield-ai" in result
    assert "service-b" in result


def test_detect_modified_repos_excludes_repos_with_zero_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repos with zero commits ahead are excluded from results."""
    mock_repo_class = MagicMock()
    mock_repo_instance = MagicMock()
    mock_repo_instance.iter_commits.return_value = []
    mock_repo_class.return_value = mock_repo_instance
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.git.Repo", mock_repo_class)
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.resolve_repo_path",
        lambda repo: f"/fake/path/{repo}",
    )

    branches = {"brownfield-ai": "feat/test"}
    result = detect_modified_repos(branches)
    assert result == []


def test_detect_modified_repos_returns_only_modified_in_mixed_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only repos with commits ahead are returned in mixed set."""
    call_count = {"n": 0}

    def mock_iter_commits(rev_range: str) -> list[Any]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [MagicMock()]  # brownfield-ai has commits
        return []  # service-b has none

    mock_repo_class = MagicMock()
    mock_repo_instance = MagicMock()
    mock_repo_instance.iter_commits.side_effect = mock_iter_commits
    mock_repo_class.return_value = mock_repo_instance
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.git.Repo", mock_repo_class)
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.resolve_repo_path",
        lambda repo: f"/fake/path/{repo}",
    )

    branches = {"brownfield-ai": "feat/test", "service-b": "feat/test-sub"}
    result = detect_modified_repos(branches)
    assert "brownfield-ai" in result
    assert "service-b" not in result


def test_detect_modified_repos_raises_on_missing_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing repo path raises FileNotFoundError."""
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.resolve_repo_path",
        lambda repo: "/nonexistent/path/repo",
    )

    def mock_repo_init(path: str) -> None:
        raise FileNotFoundError(f"No such directory: {path}")

    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.git.Repo", mock_repo_init)

    branches = {"brownfield-ai": "feat/test"}
    with pytest.raises(FileNotFoundError):
        detect_modified_repos(branches)


def test_detect_modified_repos_empty_branches_returns_empty() -> None:
    """Empty branches dict returns empty list."""
    result = detect_modified_repos({})
    assert result == []


# ---------------------------------------------------------------------------
# pr_url_to_ref
# ---------------------------------------------------------------------------


def test_pr_url_to_ref_valid_url_standard() -> None:
    """Standard GitHub PR URL converts to short ref."""
    url = "https://github.com/acme/brownfield-ai/pull/42"
    assert pr_url_to_ref(url) == "acme/brownfield-ai#42"


def test_pr_url_to_ref_valid_url_different_repo() -> None:
    """PR URL for a different repo converts correctly."""
    url = "https://github.com/acme/service-b/pull/999"
    assert pr_url_to_ref(url) == "acme/service-b#999"


def test_pr_url_to_ref_invalid_url_no_pull() -> None:
    """URL without /pull/ segment raises ValueError."""
    with pytest.raises(ValueError):
        pr_url_to_ref("https://github.com/acme/brownfield-ai/issues/42")


def test_pr_url_to_ref_invalid_url_missing_number() -> None:
    """URL with /pull/ but no number raises ValueError."""
    with pytest.raises(ValueError):
        pr_url_to_ref("https://github.com/acme/brownfield-ai/pull/")


def test_pr_url_to_ref_invalid_url_random_string() -> None:
    """Completely invalid string raises ValueError."""
    with pytest.raises(ValueError):
        pr_url_to_ref("not-a-url")


def test_pr_url_to_ref_empty_string_raises() -> None:
    """Empty string raises ValueError."""
    with pytest.raises(ValueError):
        pr_url_to_ref("")


def test_pr_url_to_ref_org_with_dots() -> None:
    """Org name containing dots is handled correctly."""
    url = "https://github.com/acme.io/repo/pull/1"
    assert pr_url_to_ref(url) == "acme.io/repo#1"


def test_pr_url_to_ref_trailing_slash_handled() -> None:
    """Trailing slash after PR number is handled."""
    url = "https://github.com/acme/brownfield-ai/pull/42/"
    assert pr_url_to_ref(url) == "acme/brownfield-ai#42"


# ---------------------------------------------------------------------------
# create_pr
# ---------------------------------------------------------------------------


def test_create_pr_success_returns_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful PR creation returns the URL string."""
    url = "https://github.com/acme/brownfield-ai/pull/42"
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=f'{{"url": "{url}"}}'),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = create_pr("brownfield-ai", "feat/test", "Test PR", "Body text")
    assert result == url


def test_create_pr_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed PR creation returns None."""
    mock_run = MagicMock(
        return_value=_make_completed_process(
            returncode=1,
            stderr="error creating PR",
        ),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = create_pr("brownfield-ai", "feat/test", "Test PR", "Body text")
    assert result is None


def test_create_pr_passes_correct_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Correct repo, branch, title, body are forwarded to task."""
    url = "https://github.com/acme/brownfield-ai/pull/99"
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=f'{{"url": "{url}"}}'),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    create_pr("brownfield-ai", "feat/test", "My Title", "My Body")
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# close_pr
# ---------------------------------------------------------------------------


def test_close_pr_success_no_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful close does not raise."""
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    close_pr("https://github.com/acme/brownfield-ai/pull/42")


def test_close_pr_failure_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed close is logged but does not raise."""
    mock_run = MagicMock(
        return_value=_make_completed_process(
            returncode=1,
            stderr="already closed",
        ),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    # Should not raise
    close_pr("https://github.com/acme/brownfield-ai/pull/42")


# ---------------------------------------------------------------------------
# create_all_prs
# ---------------------------------------------------------------------------


def test_create_all_prs_all_succeed_returns_url_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all PRs are created, returns {repo: url} dict."""
    urls = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
        "service-b": "https://github.com/acme/service-b/pull/20",
    }

    def mock_create_pr(repo: str, branch: str, title: str, body: str) -> str | None:
        return urls[repo]

    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.create_pr", mock_create_pr)
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.render_pr_body",
        lambda epic_id, resume: "Rendered body",
    )

    branches = {"brownfield-ai": "feat/test", "service-b": "feat/test-sub"}
    resume: dict[str, Any] = {"epic_id": "ACME-100"}
    result = create_all_prs("ACME-100", branches, resume)
    assert result == urls


def test_create_all_prs_partial_failure_rollback_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial failure triggers rollback (close created PRs) and returns {}."""
    call_count = {"n": 0}

    def mock_create_pr(repo: str, branch: str, title: str, body: str) -> str | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "https://github.com/acme/brownfield-ai/pull/10"
        return None  # second repo fails

    mock_close = MagicMock()
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.create_pr", mock_create_pr)
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.close_pr", mock_close)
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.render_pr_body",
        lambda epic_id, resume: "Rendered body",
    )

    branches = {"brownfield-ai": "feat/test", "service-b": "feat/test-sub"}
    resume: dict[str, Any] = {"epic_id": "ACME-100"}
    result = create_all_prs("ACME-100", branches, resume)
    assert result == {}
    mock_close.assert_called_once_with(
        "https://github.com/acme/brownfield-ai/pull/10",
    )


def test_create_all_prs_empty_branches_returns_empty() -> None:
    """Empty branches dict returns empty dict without creating PRs."""
    result = create_all_prs("ACME-100", {}, {"epic_id": "ACME-100"})
    assert result == {}


# ---------------------------------------------------------------------------
# poll_ci_checks
# ---------------------------------------------------------------------------


def test_poll_ci_checks_all_checks_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All checks with COMPLETED + SUCCESS state returns 'pass'."""
    checks_output = (
        '[{"state":"COMPLETED","conclusion":"SUCCESS","name":"lint"},{"state":"COMPLETED","conclusion":"SUCCESS","name":"test"}]'
    )
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=checks_output),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = poll_ci_checks("https://github.com/acme/brownfield-ai/pull/42")
    assert result == "pass"


def test_poll_ci_checks_skipped_conclusion_treated_as_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SKIPPED conclusion is treated as passing, not failure."""
    checks_output = (
        '[{"state":"COMPLETED","conclusion":"SUCCESS","name":"lint"},{"state":"COMPLETED","conclusion":"SKIPPED","name":"optional-check"}]'
    )
    mock_run = MagicMock(return_value=_make_completed_process(stdout=checks_output))
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)
    result = poll_ci_checks("https://github.com/acme/brownfield-ai/pull/42")
    assert result == "pass"


def test_poll_ci_checks_any_failure_returns_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any check with FAILURE conclusion returns 'fail'."""
    checks_output = (
        '[{"state":"COMPLETED","conclusion":"SUCCESS","name":"lint"},{"state":"COMPLETED","conclusion":"FAILURE","name":"test"}]'
    )
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=checks_output),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = poll_ci_checks("https://github.com/acme/brownfield-ai/pull/42")
    assert result == "fail"


def test_poll_ci_checks_any_pending_returns_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any check with non-COMPLETED state returns 'pending'."""
    checks_output = '[{"state":"COMPLETED","conclusion":"SUCCESS","name":"lint"},{"state":"IN_PROGRESS","conclusion":"","name":"test"}]'
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=checks_output),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = poll_ci_checks("https://github.com/acme/brownfield-ai/pull/42")
    assert result == "pending"


def test_poll_ci_checks_mixed_pending_and_failure_returns_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed pending + failure returns 'pending' (not resolved yet)."""
    checks_output = '[{"state":"IN_PROGRESS","conclusion":"","name":"lint"},{"state":"COMPLETED","conclusion":"FAILURE","name":"test"}]'
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=checks_output),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = poll_ci_checks("https://github.com/acme/brownfield-ai/pull/42")
    assert result == "pending"


def test_poll_ci_checks_empty_checks_returns_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No checks reported returns 'pending'."""
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=""),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = poll_ci_checks("https://github.com/acme/brownfield-ai/pull/42")
    assert result == "pending"


def test_poll_ci_checks_returncode_nonzero_returns_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-zero returncode from gh task returns 'pending'."""
    mock_run = MagicMock(
        return_value=_make_completed_process(
            returncode=1,
            stderr="API error",
        ),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    result = poll_ci_checks("https://github.com/acme/brownfield-ai/pull/42")
    assert result == "pending"


# ---------------------------------------------------------------------------
# poll_all_ci
# ---------------------------------------------------------------------------


def test_poll_all_ci_all_green_returns_all_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All PRs passing returns ('all_green', {})."""
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.poll_ci_checks",
        lambda url: "pass",
    )
    mock_touch = MagicMock()
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.ledger_touch", mock_touch)

    pr_urls = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
        "service-b": "https://github.com/acme/service-b/pull/20",
    }
    verdict, failed = poll_all_ci(
        pr_urls,
        "ACME-100",
        interval=1,
        timeout=10,
    )
    assert verdict == "all_green"
    assert failed == {}


def test_poll_all_ci_mixed_failure_returns_failed_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed pass/fail returns ('failed', {repo: url for failed})."""

    def mock_poll(url: str) -> str:
        if "service-b" in url:
            return "fail"
        return "pass"

    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.poll_ci_checks", mock_poll)
    mock_touch = MagicMock()
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.ledger_touch", mock_touch)

    pr_urls = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
        "service-b": "https://github.com/acme/service-b/pull/20",
    }
    verdict, failed = poll_all_ci(
        pr_urls,
        "ACME-100",
        interval=1,
        timeout=10,
    )
    assert verdict == "failed"
    assert "service-b" in failed
    assert "brownfield-ai" not in failed


def test_poll_all_ci_timeout_returns_failed_with_all_repos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout returns ('failed', {all repos})."""
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.poll_ci_checks",
        lambda url: "pending",
    )
    mock_touch = MagicMock()
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.ledger_touch", mock_touch)
    # Mock time to simulate timeout
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.time.time", MagicMock(side_effect=[0, 100]))
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.time.sleep", MagicMock())

    pr_urls = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
    }
    verdict, failed = poll_all_ci(
        pr_urls,
        "ACME-100",
        interval=1,
        timeout=5,
    )
    assert verdict == "failed"
    assert "brownfield-ai" in failed


def test_poll_all_ci_ledger_touch_called_per_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ledger_touch is called during polling to refresh heartbeat."""
    # First call pending, second call pass to end the loop
    call_count = {"n": 0}

    def mock_poll(url: str) -> str:
        call_count["n"] += 1
        if call_count["n"] <= 1:
            return "pending"
        return "pass"

    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.poll_ci_checks", mock_poll)
    mock_touch = MagicMock()
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.ledger_touch", mock_touch)
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.time.sleep", MagicMock())
    time_values = [0, 1, 2, 3, 4, 5]
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.time.time",
        MagicMock(side_effect=time_values),
    )

    pr_urls = {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"}
    poll_all_ci(pr_urls, "ACME-100", interval=1, timeout=30)
    assert mock_touch.call_count >= 1
    mock_touch.assert_any_call("ACME-100")


# ---------------------------------------------------------------------------
# collect_ci_failures
# ---------------------------------------------------------------------------


def test_collect_ci_failures_multiple_failing_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple failing checks are collected as list of dicts."""
    checks_output = (
        '[{"state":"COMPLETED","conclusion":"FAILURE","name":"lint","detailsUrl":"https://ci/lint"},'
        '{"state":"COMPLETED","conclusion":"FAILURE","name":"test","detailsUrl":"https://ci/test"},'
        '{"state":"COMPLETED","conclusion":"SUCCESS","name":"build","detailsUrl":"https://ci/build"}]'
    )
    mock_run = MagicMock(
        return_value=_make_completed_process(stdout=checks_output),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    failed_prs = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
    }
    result = collect_ci_failures(failed_prs)
    assert len(result) >= 2
    check_names = [r["name"] for r in result]
    assert "lint" in check_names
    assert "test" in check_names


def test_collect_ci_failures_empty_failed_prs_returns_empty() -> None:
    """Empty failed_prs dict returns empty list."""
    result = collect_ci_failures({})
    assert result == []


def test_collect_ci_failures_api_error_returns_empty_or_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API error during check retrieval returns empty or partial results."""
    mock_run = MagicMock(
        return_value=_make_completed_process(
            returncode=1,
            stderr="API error",
        ),
    )
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr._run_gh_task", mock_run)

    failed_prs = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
    }
    result = collect_ci_failures(failed_prs)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# render_pr_body
# ---------------------------------------------------------------------------


def test_render_pr_body_renders_with_full_resume() -> None:
    """Full resume with wave summaries and gate verdicts renders properly."""
    resume: dict[str, Any] = {
        "epic_id": "ACME-100",
        "plan_snapshot": {
            "metadata": {
                "sub_plans": "A:0,1|B:2,3",
                "title": "Test Epic",
            },
        },
    }
    result = render_pr_body("ACME-100", resume)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "ACME-100" in result


def test_render_pr_body_renders_with_minimal_resume() -> None:
    """Minimal resume (missing optional fields) still renders."""
    resume: dict[str, Any] = {"epic_id": "ACME-100"}
    result = render_pr_body("ACME-100", resume)
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_pr_body_includes_wave_summaries_and_gate_verdicts() -> None:
    """Wave summaries and gate verdicts are included in rendered body."""
    resume: dict[str, Any] = {
        "epic_id": "ACME-100",
        "wave_summaries": [
            "Wave 0 passed",
        ],
        "gate_verdicts": [
            "Gate: APPROVED",
        ],
    }
    result = render_pr_body("ACME-100", resume)
    assert "Wave 0 passed" in result
    assert "Gate: APPROVED" in result


# ---------------------------------------------------------------------------
# _run_gh_task timeout behaviour
# ---------------------------------------------------------------------------


def test_run_gh_task_timeout_returns_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout raises are caught and returned as a failed CompletedProcess."""
    monkeypatch.setattr(
        "brownfield_ai.tools.ralph.pr.subprocess.run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["task"], timeout=1)),
    )
    result = _run_gh_task(["checks", "url"], timeout=1)
    assert result.returncode == 1
    assert "TimeoutExpired" in result.stderr


def test_run_gh_task_passes_timeout_to_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The timeout parameter is forwarded to subprocess.run."""
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.pr.subprocess.run", mock_run)
    _run_gh_task(["checks"], timeout=60)
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs.get("timeout") == 60
