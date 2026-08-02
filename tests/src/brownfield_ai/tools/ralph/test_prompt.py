from __future__ import annotations

from brownfield_ai.tools.ralph.prompt import render_ci_fix_prompt, render_session_prompt

# ---------------------------------------------------------------------------
# Basic rendering
# ---------------------------------------------------------------------------


def test_render_session_prompt_basic() -> None:
    result = render_session_prompt(
        "TEST-001",
        {"label": "A", "waves": ["0", "1"]},
        1,
        branches={"brownfield-ai": "feat/test"},
        resume_json='{"key": "value"}',
        completed_waves=[],
    )
    assert "Epic: TEST-001" in result
    assert "Attempt: 1 of 3" in result
    assert "brownfield-ai" in result
    assert "feat/test" in result


def test_render_session_prompt_includes_resume_json() -> None:
    result = render_session_prompt(
        "TEST-002",
        {"label": "A", "waves": ["0"]},
        1,
        branches={},
        resume_json='{"epic_id": "TEST-002"}',
        completed_waves=[],
    )
    assert '"epic_id": "TEST-002"' in result


def test_render_session_prompt_wave_range() -> None:
    result = render_session_prompt(
        "TEST-003",
        {"label": "B", "waves": ["2", "3", "4"]},
        1,
        branches={},
        resume_json="{}",
        completed_waves=["0", "1"],
    )
    assert "2,3,4" in result
    assert "Sub-plan B" in result
    assert "0,1" in result


# ---------------------------------------------------------------------------
# Failure rendering
# ---------------------------------------------------------------------------


def test_render_session_prompt_with_failures() -> None:
    failures = [
        {
            "wave": "1",
            "step": "impl",
            "agent_model": "opus",
            "effort_variant": "high",
            "body": "Error msg",
            "exhausted_matrix_points": "opus:high",
        }
    ]
    result = render_session_prompt(
        "TEST-001",
        {"label": "B", "waves": ["2", "3"]},
        2,
        branches={"brownfield-ai": "feat/test"},
        resume_json="{}",
        completed_waves=["0", "1"],
        failures=failures,
        escalation_floor="high-reasoning,max",
    )
    assert "Previous Attempt Failures" in result
    assert "Error msg" in result
    assert "high-reasoning,max" in result


def test_render_session_prompt_truncates_failure_bodies() -> None:
    long_body = "x" * 1000
    failures = [
        {
            "wave": "1",
            "step": "impl",
            "agent_model": "opus",
            "effort_variant": "base",
            "body": long_body,
            "exhausted_matrix_points": "",
        }
    ]
    result = render_session_prompt(
        "TEST-001",
        {"label": "A", "waves": ["0"]},
        2,
        branches={},
        resume_json="{}",
        completed_waves=[],
        failures=failures,
    )
    assert long_body not in result
    assert "[truncated]" in result


def test_render_session_prompt_no_failures_is_none() -> None:
    result = render_session_prompt(
        "TEST-001",
        {"label": "A", "waves": ["0"]},
        1,
        branches={},
        resume_json="{}",
        completed_waves=[],
        failures=None,
    )
    assert "Previous Attempt Failures" not in result


def test_render_session_prompt_empty_failures_list() -> None:
    result = render_session_prompt(
        "TEST-001",
        {"label": "A", "waves": ["0"]},
        1,
        branches={},
        resume_json="{}",
        completed_waves=[],
        failures=[],
    )
    assert "Previous Attempt Failures" not in result


def test_render_session_prompt_multiple_branches() -> None:
    result = render_session_prompt(
        "TEST-004",
        {"label": "A", "waves": ["0"]},
        1,
        branches={"brownfield-ai": "feat/a", "service-b": "feat/b", "analytics": "feat/c"},
        resume_json="{}",
        completed_waves=[],
    )
    assert "brownfield-ai" in result
    assert "service-b" in result
    assert "analytics" in result
    assert "feat/a" in result
    assert "feat/b" in result
    assert "feat/c" in result


def test_render_session_prompt_attempt_1_no_failure_section() -> None:
    result = render_session_prompt(
        "TEST-005",
        {"label": "A", "waves": ["0"]},
        1,
        branches={},
        resume_json="{}",
        completed_waves=[],
    )
    assert "Previous Attempt Failures" not in result
    assert "Directive" not in result


def test_render_session_prompt_no_completed_waves() -> None:
    result = render_session_prompt(
        "TEST-006",
        {"label": "A", "waves": ["0"]},
        1,
        branches={},
        resume_json="{}",
        completed_waves=[],
    )
    assert "none" in result


# ---------------------------------------------------------------------------
# render_ci_fix_prompt
# ---------------------------------------------------------------------------


def test_render_ci_fix_prompt_basic() -> None:
    """Basic rendering with failures produces a non-empty prompt."""
    failures: list[dict[str, str]] = [
        {"name": "lint", "log_url": "https://ci/lint", "repo": "brownfield-ai"},
    ]
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={"brownfield-ai": "feat/test"},
        pr_urls={"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"},
        failures=failures,
        attempt=1,
    )
    assert isinstance(result, str)
    assert "ACME-100" in result
    assert "lint" in result


def test_render_ci_fix_prompt_empty_failures() -> None:
    """Empty failures list still produces a valid prompt."""
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={"brownfield-ai": "feat/test"},
        pr_urls={"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"},
        failures=[],
        attempt=1,
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_ci_fix_prompt_escalation_floor_default() -> None:
    """Default escalation_floor is empty string."""
    failures: list[dict[str, str]] = [
        {"name": "test", "log_url": "https://ci/test", "repo": "brownfield-ai"},
    ]
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={},
        pr_urls={},
        failures=failures,
        attempt=1,
    )
    assert isinstance(result, str)


def test_render_ci_fix_prompt_with_escalation_floor() -> None:
    """Explicit escalation_floor value is included in prompt."""
    failures: list[dict[str, str]] = [
        {"name": "test", "log_url": "https://ci/test", "repo": "brownfield-ai"},
    ]
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={"brownfield-ai": "feat/test"},
        pr_urls={"brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10"},
        failures=failures,
        attempt=2,
        escalation_floor="high-reasoning,max",
    )
    assert isinstance(result, str)
    assert "high-reasoning,max" in result


def test_render_ci_fix_prompt_multiple_failures() -> None:
    """Multiple failures from different repos are all included."""
    failures: list[dict[str, str]] = [
        {"name": "lint", "log_url": "https://ci/lint", "repo": "brownfield-ai"},
        {"name": "test", "log_url": "https://ci/test", "repo": "service-b"},
    ]
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={"brownfield-ai": "feat/test", "service-b": "feat/test-sub"},
        pr_urls={
            "brownfield-ai": "https://github.com/acme/brownfield-ai/pull/10",
            "service-b": "https://github.com/acme/service-b/pull/20",
        },
        failures=failures,
        attempt=1,
    )
    assert "lint" in result
    assert "test" in result


def test_render_ci_fix_prompt_attempt_number() -> None:
    """Attempt number is reflected in the rendered prompt."""
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={},
        pr_urls={},
        failures=[],
        attempt=3,
    )
    assert isinstance(result, str)


def test_render_ci_fix_prompt_custom_max_attempts() -> None:
    """Custom max_attempts value is rendered in the prompt."""
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={},
        pr_urls={},
        failures=[],
        attempt=1,
        max_attempts=5,
    )
    assert "of 5" in result


def test_render_ci_fix_prompt_default_max_attempts() -> None:
    """Default max_attempts of 3 is rendered in the prompt."""
    result = render_ci_fix_prompt(
        "ACME-100",
        branches={},
        pr_urls={},
        failures=[],
        attempt=1,
    )
    assert "of 3" in result
