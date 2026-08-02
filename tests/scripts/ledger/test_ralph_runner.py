from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts.ledger.ralph_runner import (
    EpicHeartbeat,
    _load_aws_credentials,
    create_and_set_prs,
    get_completed_waves,
    get_failures,
    main,
    monitor_and_fix_ci,
    run_epic,
    run_sub_plan,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_RESUME: dict[str, Any] = {
    "epic_id": "ACME-100",
    "plan_snapshot": {
        "metadata": {
            "sub_plans": "A:0,1|B:2,3",
            "branches": "brownfield-ai:feat/ACME-100",
            "title": "Test Epic",
        }
    },
}

_SUB_PLAN_A: dict[str, Any] = {"label": "A", "waves": ["0", "1"]}


def _pass_artifact(sub_plan: str = "A", attempt: int = 1) -> dict[str, Any]:
    return {
        "document": "All checks passed.",
        "metadata": {
            "verdict": "pass",
            "sub_plan": sub_plan,
            "attempt": str(attempt),
            "wave": "1",
            "step": "verify",
        },
    }


def _fail_artifact(sub_plan: str = "A", attempt: int = 1) -> dict[str, Any]:
    return {
        "document": "Test failure encountered.",
        "metadata": {
            "verdict": "fail",
            "sub_plan": sub_plan,
            "attempt": str(attempt),
            "wave": "0",
            "step": "impl",
            "agent_model": "opus",
            "effort_variant": "base",
            "exhausted_matrix_points": "opus:base",
        },
    }


def _blocked_artifact(sub_plan: str = "A", attempt: int = 1) -> dict[str, Any]:
    return {
        "document": "Plan flaw detected.",
        "metadata": {
            "verdict": "blocked",
            "sub_plan": sub_plan,
            "attempt": str(attempt),
        },
    }


def _apply_runner_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_exit_code: int = 0,
    exit_artifacts: list[dict[str, Any] | None] | None = None,
    resume: dict[str, Any] | None = None,
) -> dict[str, MagicMock]:
    """Apply common mocks for run_sub_plan and run_epic tests.

    Returns a dict of the mock objects for assertion.
    """
    mocks: dict[str, MagicMock] = {}

    # Mock run_claude_session
    mock_session = MagicMock(return_value=session_exit_code)
    monkeypatch.setattr("scripts.ledger.ralph_runner.run_claude_session", mock_session)
    mocks["run_claude_session"] = mock_session

    # Mock get_latest_session_exit (returns artifacts in sequence)
    if exit_artifacts is not None:
        artifacts_iter = iter(exit_artifacts)
        mock_exit = MagicMock(side_effect=lambda *a, **kw: next(artifacts_iter, None))
    else:
        mock_exit = MagicMock(return_value=None)
    monkeypatch.setattr("scripts.ledger.ralph_runner.get_latest_session_exit", mock_exit)
    mocks["get_latest_session_exit"] = mock_exit

    # Mock ledger operations
    mock_resume = MagicMock(return_value=resume or _RESUME)
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_resume", mock_resume)
    mocks["ledger_resume"] = mock_resume

    mock_touch = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_touch", mock_touch)
    mocks["ledger_touch"] = mock_touch

    mock_status = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_status", mock_status)
    mocks["ledger_status"] = mock_status

    # Mock git operations
    mock_ensure = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ensure_all_branches", mock_ensure)
    mocks["ensure_all_branches"] = mock_ensure

    mock_push = MagicMock(return_value=True)
    monkeypatch.setattr("scripts.ledger.ralph_runner.push_all_branches", mock_push)
    mocks["push_all_branches"] = mock_push

    # Mock ledger_filter for get_completed_waves
    mock_filter = MagicMock(return_value=[])
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_filter", mock_filter)
    mocks["ledger_filter"] = mock_filter

    # Mock _load_aws_credentials
    mock_creds = MagicMock(return_value={})
    monkeypatch.setattr("scripts.ledger.ralph_runner._load_aws_credentials", mock_creds)
    mocks["_load_aws_credentials"] = mock_creds

    # Mock get_failures to prevent iterator consumption by get_failures -> get_latest_session_exit chain
    mock_get_failures = MagicMock(return_value=[])
    monkeypatch.setattr("scripts.ledger.ralph_runner.get_failures", mock_get_failures)
    mocks["get_failures"] = mock_get_failures

    # Mock get_completed_waves to return empty list
    mock_completed = MagicMock(return_value=[])
    monkeypatch.setattr("scripts.ledger.ralph_runner.get_completed_waves", mock_completed)
    mocks["get_completed_waves"] = mock_completed

    # Mock _get_completed_waves_from_git to prevent real subprocess calls
    mock_git_waves = MagicMock(return_value=[])
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner._get_completed_waves_from_git",
        mock_git_waves,
    )
    mocks["_get_completed_waves_from_git"] = mock_git_waves

    # Mock render_session_prompt
    mock_render = MagicMock(return_value="rendered prompt")
    monkeypatch.setattr("scripts.ledger.ralph_runner.render_session_prompt", mock_render)
    mocks["render_session_prompt"] = mock_render

    # Mock PR + CI functions used by run_epic
    mock_detect = MagicMock(return_value=["brownfield-ai"])
    monkeypatch.setattr("scripts.ledger.ralph_runner.detect_modified_repos", mock_detect)
    mocks["detect_modified_repos"] = mock_detect

    mock_create_set = MagicMock(
        return_value={"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/1"},
    )
    monkeypatch.setattr("scripts.ledger.ralph_runner.create_and_set_prs", mock_create_set)
    mocks["create_and_set_prs"] = mock_create_set

    mock_monitor = MagicMock(return_value="all_green")
    monkeypatch.setattr("scripts.ledger.ralph_runner.monitor_and_fix_ci", mock_monitor)
    mocks["monitor_and_fix_ci"] = mock_monitor

    # Mock get_config to return defaults (prevents env-var lookups)
    mock_config = MagicMock(
        return_value={
            "session_timeout": 7200,
            "max_sessions": 9,
            "poll_interval": 300,
            "heartbeat_interval": 600,
        },
    )
    monkeypatch.setattr("scripts.ledger.ralph_runner.get_config", mock_config)
    mocks["get_config"] = mock_config

    # Mock EpicHeartbeat to prevent real daemon threads in unit tests
    mock_heartbeat_instance = MagicMock()
    mock_heartbeat_instance.__enter__ = MagicMock(return_value=mock_heartbeat_instance)
    mock_heartbeat_instance.__exit__ = MagicMock(return_value=None)
    mock_heartbeat_cls = MagicMock(return_value=mock_heartbeat_instance)
    monkeypatch.setattr("scripts.ledger.ralph_runner.EpicHeartbeat", mock_heartbeat_cls)
    mocks["EpicHeartbeat"] = mock_heartbeat_cls

    return mocks


# ---------------------------------------------------------------------------
# run_sub_plan
# ---------------------------------------------------------------------------


def test_run_sub_plan_passes_on_first_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[_pass_artifact()],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "pass"
    assert attempts == 1


def test_run_sub_plan_retries_on_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[
            _fail_artifact("A", 1),
            _pass_artifact("A", 2),
        ],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "pass"
    assert attempts == 2


def test_run_sub_plan_blocked_stops_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[_blocked_artifact()],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "blocked"
    assert attempts == 1


def test_run_sub_plan_missing_exit_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[None, None, None],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "blocked"
    assert attempts == 2


def test_run_sub_plan_exhausts_all_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[
            _fail_artifact("A", 1),
            _fail_artifact("A", 2),
            _fail_artifact("A", 3),
        ],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "fail"
    assert attempts == 3


def test_run_sub_plan_success_verdict_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Protocol ``session_exit`` verdict ``"success"`` is treated as pass."""
    success_artifact: dict[str, Any] = {
        "document": "All checks passed.",
        "metadata": {
            "verdict": "success",
            "sub_plan": "A",
            "attempt": "1",
        },
    }
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[success_artifact],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "pass"
    assert attempts == 1


def test_run_sub_plan_retry_verdict_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit ``"retry"`` verdict triggers retry, not immediate failure."""
    retry_artifact: dict[str, Any] = {
        "document": "Transient error.",
        "metadata": {
            "verdict": "retry",
            "sub_plan": "A",
            "attempt": "1",
        },
    }
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[retry_artifact, _pass_artifact("A", 2)],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "pass"
    assert attempts == 2


def test_run_sub_plan_missing_then_found_resets_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter resets when an artifact is found after a missing one."""
    _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[None, _fail_artifact("A", 2), None],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "fail"
    assert attempts == 3


def test_run_sub_plan_uses_recommended_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prior exit artifact ``recommended_floor`` overrides ``bump_floor``."""
    artifact_with_floor: dict[str, Any] = {
        "document": "Needs escalation.",
        "metadata": {
            "verdict": "fail",
            "sub_plan": "A",
            "attempt": "1",
            "recommended_floor": "high-reasoning,max",
        },
    }
    mocks = _apply_runner_mocks(
        monkeypatch,
        exit_artifacts=[artifact_with_floor, _pass_artifact("A", 2)],
    )
    status, attempts = run_sub_plan("ACME-100", _SUB_PLAN_A, _RESUME)
    assert status == "pass"
    assert attempts == 2

    # Verify attempt 2 used the recommended_floor from the prior artifact
    render_calls = mocks["render_session_prompt"].call_args_list
    assert len(render_calls) == 2
    # Second call (attempt 2) should have escalation_floor="high-reasoning,max"
    _, kwargs_2 = render_calls[1]
    assert kwargs_2.get("escalation_floor") == "high-reasoning,max"


# ---------------------------------------------------------------------------
# run_epic
# ---------------------------------------------------------------------------


def test_run_epic_blocks_on_sub_plan_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(monkeypatch)

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        if sub_plan["label"] == "A":
            return ("blocked", 1)
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    result = run_epic("ACME-100")
    assert result == "blocked"
    mocks["ledger_status"].assert_called_with("ACME-100", "blocked")


def test_run_epic_success_triggers_pr_and_review(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(monkeypatch)

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    result = run_epic("ACME-100")
    assert result == "completed"
    mocks["push_all_branches"].assert_called_once()
    mocks["create_and_set_prs"].assert_called_once()
    mocks["ledger_status"].assert_any_call("ACME-100", "in_review")
    # Last ledger_status call should be "completed"
    assert mocks["ledger_status"].call_args_list[-1].args == ("ACME-100", "completed")


def test_run_epic_no_plan_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(
        monkeypatch,
        resume={"epic_id": "ACME-100"},
    )

    result = run_epic("ACME-100")
    assert result == "blocked"
    mocks["ledger_status"].assert_called_with("ACME-100", "blocked")


def test_run_epic_no_sub_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_runner_mocks(
        monkeypatch,
        resume={"epic_id": "ACME-100", "plan_snapshot": {"metadata": {}}},
    )

    result = run_epic("ACME-100")
    assert result == "blocked"


def test_run_epic_branch_setup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(monkeypatch)
    mocks["ensure_all_branches"].side_effect = RuntimeError("branch diverged")

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    result = run_epic("ACME-100")
    assert result == "blocked"


def test_run_epic_push_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(monkeypatch)
    mocks["push_all_branches"].return_value = False

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    result = run_epic("ACME-100")
    assert result == "blocked"


def test_run_epic_push_failure_transitions_to_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_epic must call ledger_status blocked and push without epic_id on push failure."""
    mocks = _apply_runner_mocks(monkeypatch)
    mocks["push_all_branches"].return_value = False

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    result = run_epic("ACME-100")
    assert result == "blocked"

    # run_epic must explicitly transition to blocked when push fails
    mocks["ledger_status"].assert_called_with("ACME-100", "blocked")

    # push_all_branches must be called without epic_id (only branches arg)
    push_call_args = mocks["push_all_branches"].call_args
    assert push_call_args is not None
    positional_args = push_call_args[0]
    keyword_args = push_call_args[1]
    assert positional_args == ({"brownfield-ai": "feat/ACME-100"},)
    assert "epic_id" not in keyword_args


# ---------------------------------------------------------------------------
# create_and_set_prs
# ---------------------------------------------------------------------------


def test_create_and_set_prs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful PR creation returns {repo: url} dict and calls ledger_set_prs."""
    pr_urls = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
        "service-b": "https://github.com/acme/service-b/pull/20",
    }
    mock_create_all = MagicMock(return_value=pr_urls)
    monkeypatch.setattr("scripts.ledger.ralph_runner.create_all_prs", mock_create_all)

    mock_pr_url_to_ref = MagicMock(
        side_effect=lambda url: "acme/brownfield-ai#10" if "brownfield-ai" in url else "acme/service-b#20",
    )
    monkeypatch.setattr("scripts.ledger.ralph_runner.pr_url_to_ref", mock_pr_url_to_ref)

    mock_set_prs = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_set_prs", mock_set_prs)

    branches = {"brownfield-ai": "feat/ACME-100", "service-b": "feat/ACME-100-sub"}
    result = create_and_set_prs("ACME-100", branches, _RESUME)
    assert result == pr_urls
    mock_set_prs.assert_called_once()


def test_create_and_set_prs_no_modified_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    """No modified repos returns empty dict."""
    mock_create_all = MagicMock(return_value={})
    monkeypatch.setattr("scripts.ledger.ralph_runner.create_all_prs", mock_create_all)

    branches = {"brownfield-ai": "feat/ACME-100"}
    result = create_and_set_prs("ACME-100", branches, _RESUME)
    assert result == {}


def test_create_and_set_prs_rollback_on_set_prs_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ledger_set_prs raises, close_pr is called on all created PRs."""
    pr_urls = {
        "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
    }
    mock_create_all = MagicMock(return_value=pr_urls)
    monkeypatch.setattr("scripts.ledger.ralph_runner.create_all_prs", mock_create_all)

    mock_pr_url_to_ref = MagicMock(return_value="acme/brownfield-ai#10")
    monkeypatch.setattr("scripts.ledger.ralph_runner.pr_url_to_ref", mock_pr_url_to_ref)

    mock_set_prs = MagicMock(side_effect=RuntimeError("ledger error"))
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_set_prs", mock_set_prs)

    mock_close = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.close_pr", mock_close)

    branches = {"brownfield-ai": "feat/ACME-100"}
    with pytest.raises(RuntimeError, match="ledger error"):
        create_and_set_prs("ACME-100", branches, _RESUME)

    mock_close.assert_called_once_with(
        "https://github.com/acme/brownfield-ai/pull/10",
    )


# ---------------------------------------------------------------------------
# monitor_and_fix_ci
# ---------------------------------------------------------------------------


def test_monitor_and_fix_ci_all_green(monkeypatch: pytest.MonkeyPatch) -> None:
    """All green CI returns 'all_green'."""
    mock_poll_all = MagicMock(return_value=("all_green", {}))
    monkeypatch.setattr("scripts.ledger.ralph_runner.poll_all_ci", mock_poll_all)

    pr_urls = {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"}
    branches = {"brownfield-ai": "feat/ACME-100"}
    result = monitor_and_fix_ci("ACME-100", pr_urls, branches)
    assert result == "all_green"


def test_monitor_and_fix_ci_failure_then_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    """First poll fails, fix session runs, second poll passes."""
    poll_count = {"n": 0}

    def mock_poll_all(
        pr_urls: dict[str, str],
        epic_id: str,
        *,
        interval: int,
        timeout: int,
    ) -> tuple[str, dict[str, str]]:
        poll_count["n"] += 1
        if poll_count["n"] == 1:
            return ("failed", {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"})
        return ("all_green", {})

    monkeypatch.setattr("scripts.ledger.ralph_runner.poll_all_ci", mock_poll_all)

    mock_collect = MagicMock(return_value=[{"name": "lint", "log_url": "https://ci/lint", "repo": "brownfield-ai"}])
    monkeypatch.setattr("scripts.ledger.ralph_runner.collect_ci_failures", mock_collect)

    mock_render_fix = MagicMock(return_value="fix prompt")
    monkeypatch.setattr("scripts.ledger.ralph_runner.render_ci_fix_prompt", mock_render_fix)

    mock_session = MagicMock(return_value=0)
    monkeypatch.setattr("scripts.ledger.ralph_runner.run_claude_session", mock_session)

    mock_push = MagicMock(return_value=True)
    monkeypatch.setattr("scripts.ledger.ralph_runner.push_all_branches", mock_push)

    mock_creds = MagicMock(return_value={})
    monkeypatch.setattr("scripts.ledger.ralph_runner._load_aws_credentials", mock_creds)

    mock_sleep = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.time.sleep", mock_sleep)

    pr_urls = {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"}
    branches = {"brownfield-ai": "feat/ACME-100"}
    result = monitor_and_fix_ci("ACME-100", pr_urls, branches)
    assert result == "all_green"
    mock_render_fix.assert_called_once()
    _, kwargs = mock_render_fix.call_args
    assert kwargs.get("escalation_floor") == ""


def test_monitor_and_fix_ci_passes_escalation_floor_on_attempt_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """render_ci_fix_prompt is called with escalation_floor='' on attempt 1 and 'per-plan,high' on attempt 2."""
    poll_count = {"n": 0}

    def mock_poll_all(
        pr_urls: dict[str, str],
        epic_id: str,
        *,
        interval: int,
        timeout: int,
    ) -> tuple[str, dict[str, str]]:
        poll_count["n"] += 1
        if poll_count["n"] < 3:
            return ("failed", {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"})
        return ("all_green", {})

    monkeypatch.setattr("scripts.ledger.ralph_runner.poll_all_ci", mock_poll_all)

    mock_collect = MagicMock(return_value=[{"name": "lint", "log_url": "https://ci/lint", "repo": "brownfield-ai"}])
    monkeypatch.setattr("scripts.ledger.ralph_runner.collect_ci_failures", mock_collect)

    mock_render_fix = MagicMock(return_value="fix prompt")
    monkeypatch.setattr("scripts.ledger.ralph_runner.render_ci_fix_prompt", mock_render_fix)

    mock_session = MagicMock(return_value=0)
    monkeypatch.setattr("scripts.ledger.ralph_runner.run_claude_session", mock_session)

    mock_push = MagicMock(return_value=True)
    monkeypatch.setattr("scripts.ledger.ralph_runner.push_all_branches", mock_push)

    mock_creds = MagicMock(return_value={})
    monkeypatch.setattr("scripts.ledger.ralph_runner._load_aws_credentials", mock_creds)

    mock_sleep = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.time.sleep", mock_sleep)

    pr_urls = {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"}
    branches = {"brownfield-ai": "feat/ACME-100"}
    result = monitor_and_fix_ci("ACME-100", pr_urls, branches)
    assert result == "all_green"
    assert mock_render_fix.call_count == 2
    _, kwargs_1 = mock_render_fix.call_args_list[0]
    assert kwargs_1.get("escalation_floor") == ""
    _, kwargs_2 = mock_render_fix.call_args_list[1]
    assert kwargs_2.get("escalation_floor") == "per-plan,high"


def test_monitor_and_fix_ci_exhausted_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """All fix attempts exhausted returns 'failed'."""
    mock_poll_all = MagicMock(
        return_value=("failed", {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"}),
    )
    monkeypatch.setattr("scripts.ledger.ralph_runner.poll_all_ci", mock_poll_all)

    mock_collect = MagicMock(return_value=[{"name": "test", "log_url": "https://ci/test", "repo": "brownfield-ai"}])
    monkeypatch.setattr("scripts.ledger.ralph_runner.collect_ci_failures", mock_collect)

    mock_render_fix = MagicMock(return_value="fix prompt")
    monkeypatch.setattr("scripts.ledger.ralph_runner.render_ci_fix_prompt", mock_render_fix)

    mock_session = MagicMock(return_value=0)
    monkeypatch.setattr("scripts.ledger.ralph_runner.run_claude_session", mock_session)

    mock_push = MagicMock(return_value=True)
    monkeypatch.setattr("scripts.ledger.ralph_runner.push_all_branches", mock_push)

    mock_creds = MagicMock(return_value={})
    monkeypatch.setattr("scripts.ledger.ralph_runner._load_aws_credentials", mock_creds)

    mock_sleep = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.time.sleep", mock_sleep)

    pr_urls = {"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"}
    branches = {"brownfield-ai": "feat/ACME-100"}
    result = monitor_and_fix_ci("ACME-100", pr_urls, branches)
    assert result == "failed"


# ---------------------------------------------------------------------------
# run_epic with new PR + CI flow
# ---------------------------------------------------------------------------


def test_run_epic_no_modified_repos_returns_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    """detect_modified_repos returns [] means run_epic returns 'completed'."""
    mocks = _apply_runner_mocks(monkeypatch)

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    mock_detect = MagicMock(return_value=[])
    monkeypatch.setattr("scripts.ledger.ralph_runner.detect_modified_repos", mock_detect)

    result = run_epic("ACME-100")
    assert result == "completed"
    mocks["create_and_set_prs"].assert_not_called()


def test_run_epic_in_review_only_after_set_prs_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """ledger_status('in_review') is called only after ledger_set_prs succeeds."""
    mocks = _apply_runner_mocks(monkeypatch)

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    mock_create_and_set = MagicMock(
        return_value={"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"},
    )
    monkeypatch.setattr("scripts.ledger.ralph_runner.create_and_set_prs", mock_create_and_set)

    mock_monitor = MagicMock(return_value="all_green")
    monkeypatch.setattr("scripts.ledger.ralph_runner.monitor_and_fix_ci", mock_monitor)

    result = run_epic("ACME-100")
    assert result == "completed"
    mocks["ledger_status"].assert_any_call("ACME-100", "in_review")
    # Last ledger_status call should be "completed"
    assert mocks["ledger_status"].call_args_list[-1].args == ("ACME-100", "completed")


def test_run_epic_ledger_touch_called_during_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """ledger_touch is called during CI polling to maintain claim."""
    mocks = _apply_runner_mocks(monkeypatch)

    def mock_run_sub_plan(
        epic_id: str,
        sub_plan: dict[str, Any],
        resume: dict[str, Any],
    ) -> tuple[str, int]:
        return ("pass", 1)

    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    mock_create_and_set = MagicMock(
        return_value={"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"},
    )
    monkeypatch.setattr("scripts.ledger.ralph_runner.create_and_set_prs", mock_create_and_set)

    mock_monitor = MagicMock(return_value="all_green")
    monkeypatch.setattr("scripts.ledger.ralph_runner.monitor_and_fix_ci", mock_monitor)

    run_epic("ACME-100")
    # ledger_touch must have been called at least once (during sub-plan execution)
    assert mocks["ledger_touch"].call_count >= 1


# ---------------------------------------------------------------------------
# get_completed_waves
# ---------------------------------------------------------------------------


def test_get_completed_waves_filters_by_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = [
        {"metadata": {"verdict": "pass", "wave": "0"}},
        {"metadata": {"verdict": "fail", "wave": "1"}},
        {"metadata": {"verdict": "pass", "wave": "2"}},
    ]

    def mock_filter(
        epic_id: str,
        *,
        artifact_type: str = "",
        sub_plan: str = "",
        attempt: str = "",
        verdict: str = "",
        artifact_status: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return artifacts

    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_filter", mock_filter)

    result = get_completed_waves("ACME-100")
    assert result == ["0", "2"]


def test_get_completed_waves_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = [
        {"metadata": {"verdict": "pass", "wave": "0"}},
        {"metadata": {"verdict": "pass", "wave": "0"}},
    ]

    def mock_filter(
        epic_id: str,
        *,
        artifact_type: str = "",
        sub_plan: str = "",
        attempt: str = "",
        verdict: str = "",
        artifact_status: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return artifacts

    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_filter", mock_filter)

    result = get_completed_waves("ACME-100")
    assert result == ["0"]


def test_get_completed_waves_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_filter(
        epic_id: str,
        *,
        artifact_type: str = "",
        sub_plan: str = "",
        attempt: str = "",
        verdict: str = "",
        artifact_status: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_filter", mock_filter)

    result = get_completed_waves("ACME-100")
    assert result == []


# ---------------------------------------------------------------------------
# get_failures
# ---------------------------------------------------------------------------


def test_get_failures_returns_empty_when_no_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner.get_latest_session_exit",
        MagicMock(return_value=None),
    )
    result = get_failures("ACME-100", _SUB_PLAN_A, 1)
    assert result == []


def test_get_failures_returns_empty_when_not_fail_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner.get_latest_session_exit",
        MagicMock(return_value=_pass_artifact()),
    )
    result = get_failures("ACME-100", _SUB_PLAN_A, 1)
    assert result == []


def test_get_failures_extracts_failure_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner.get_latest_session_exit",
        MagicMock(return_value=_fail_artifact()),
    )
    result = get_failures("ACME-100", _SUB_PLAN_A, 1)
    assert len(result) == 1
    assert result[0]["wave"] == "0"
    assert result[0]["step"] == "impl"
    assert result[0]["agent_model"] == "opus"
    assert result[0]["body"] == "Test failure encountered."


# ---------------------------------------------------------------------------
# _load_aws_credentials
# ---------------------------------------------------------------------------


def test_load_aws_credentials_parses_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creds_file = tmp_path / ".aws-credentials.env"
    creds_file.write_text("# comment\nAWS_ACCESS_KEY_ID=AKIATEST\nAWS_SECRET_ACCESS_KEY=secret123\n\nAWS_SESSION_TOKEN=tok456\n")
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner._AWS_CREDS_PATH",
        str(creds_file),
    )
    result = _load_aws_credentials()
    assert result == {
        "AWS_ACCESS_KEY_ID": "AKIATEST",
        "AWS_SECRET_ACCESS_KEY": "secret123",
        "AWS_SESSION_TOKEN": "tok456",
    }


def test_load_aws_credentials_missing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner._AWS_CREDS_PATH",
        "/nonexistent/path/.aws-creds.env",
    )
    result = _load_aws_credentials()
    assert result == {}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_with_epic_id(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run_epic = MagicMock(return_value="in_review")
    monkeypatch.setattr("scripts.ledger.ralph_runner.run_epic", mock_run_epic)

    main(epic_id="ACME-999")
    mock_run_epic.assert_called_once_with("ACME-999")


def test_main_once_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_poll = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner._poll_and_execute", mock_poll)

    main(once=True)
    mock_poll.assert_called_once()


def test_main_default_enters_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_loop = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ralph_loop", mock_loop)

    main()
    mock_loop.assert_called_once()


# ---------------------------------------------------------------------------
# get_completed_waves (ledger_filter migration)
# ---------------------------------------------------------------------------


def test_get_completed_waves_uses_ledger_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_filter = MagicMock(
        return_value=[
            {"metadata": {"verdict": "pass", "wave": "0"}},
        ]
    )
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_filter", mock_filter)

    result = get_completed_waves("ACME-100")
    mock_filter.assert_called_once_with("ACME-100", artifact_type="wave_summary")
    assert result == ["0"]


# ---------------------------------------------------------------------------
# run_epic shadow mode (ledger vs git wave detection)
# ---------------------------------------------------------------------------


def test_run_epic_shadow_mode_prefers_ledger_over_git(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(
        monkeypatch,
        session_exit_code=0,
        exit_artifacts=[_pass_artifact("B", 1)],
    )
    # Override get_completed_waves to return ledger-based waves
    mocks["get_completed_waves"].return_value = ["0", "1"]
    # Mock git-based detection to return different waves
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner._get_completed_waves_from_git",
        MagicMock(return_value=["0"]),
    )

    resume = {
        "epic_id": "ACME-100",
        "plan_snapshot": {
            "metadata": {
                "sub_plans": "A:0,1|B:2",
                "branches": "brownfield-ai:feat/ACME-100",
                "title": "Test Epic",
            }
        },
    }
    mocks["ledger_resume"].return_value = resume

    run_epic("ACME-100")
    # Sub-plan A (waves 0,1) should be skipped because ledger says both complete
    # Sub-plan B (wave 2) should be executed
    assert mocks["run_claude_session"].call_count == 1


def test_run_epic_falls_back_to_git_when_ledger_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(monkeypatch)
    # Ledger returns empty (already set by _apply_runner_mocks)
    assert mocks["get_completed_waves"].return_value == []
    # Git returns completed waves for both A waves
    mock_git_waves = MagicMock(return_value=["0", "1"])
    monkeypatch.setattr(
        "scripts.ledger.ralph_runner._get_completed_waves_from_git",
        mock_git_waves,
    )

    resume = {
        "epic_id": "ACME-100",
        "plan_snapshot": {
            "metadata": {
                "sub_plans": "A:0,1|B:2",
                "branches": "brownfield-ai:feat/ACME-100",
                "title": "Test Epic",
            }
        },
    }
    mocks["ledger_resume"].return_value = resume

    # Override run_sub_plan to isolate run_epic wave-skip logic from sub-plan internals
    mock_run_sub_plan = MagicMock(return_value=("pass", 1))
    monkeypatch.setattr("scripts.ledger.ralph_runner.run_sub_plan", mock_run_sub_plan)

    run_epic("ACME-100")
    # get_completed_waves must be called by run_epic for shadow mode (not just run_sub_plan internals)
    mocks["get_completed_waves"].assert_called_with("ACME-100")
    # Git fallback must have been invoked because ledger was empty
    mock_git_waves.assert_called_once()
    # Sub-plan A (waves 0,1) should be skipped via git fallback; only B runs
    assert mock_run_sub_plan.call_count == 1
    assert mock_run_sub_plan.call_args[0][1]["label"] == "B"


# ---------------------------------------------------------------------------
# EpicHeartbeat
# ---------------------------------------------------------------------------


def test_epic_heartbeat_calls_touch_periodically(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_touch = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_touch", mock_touch)

    with EpicHeartbeat("TEST-001", 0.05):
        time.sleep(0.15)

    assert mock_touch.call_count >= 2
    for call in mock_touch.call_args_list:
        assert call.args == ("TEST-001",)


def test_epic_heartbeat_stops_on_context_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_touch = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_touch", mock_touch)

    hb: EpicHeartbeat
    with EpicHeartbeat("TEST-002", 0.05) as hb:
        pass

    assert hb._thread is not None
    assert not hb._thread.is_alive()


def test_epic_heartbeat_survives_touch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_touch = MagicMock(side_effect=RuntimeError("ledger unavailable"))
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_touch", mock_touch)

    with EpicHeartbeat("TEST-003", 0.05):
        time.sleep(0.12)

    assert mock_touch.call_count >= 1


def test_epic_heartbeat_is_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_touch = MagicMock()
    monkeypatch.setattr("scripts.ledger.ralph_runner.ledger_touch", mock_touch)

    with EpicHeartbeat("TEST-004", 0.05) as hb:
        assert hb._thread is not None
        assert hb._thread.daemon is True


def test_run_epic_uses_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _apply_runner_mocks(
        monkeypatch,
        resume={"epic_id": "ACME-100", "plan_snapshot": {"metadata": {"sub_plans": "", "branches": ""}}},
    )

    run_epic("ACME-100")

    mocks["EpicHeartbeat"].assert_called_once_with("ACME-100", 600)
    mocks["EpicHeartbeat"].return_value.__enter__.assert_called_once()
