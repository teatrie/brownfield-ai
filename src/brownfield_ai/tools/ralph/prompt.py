"""Jinja2 template rendering for ralph headless session prompts.

Loads and renders the ``session_prompt.md.j2`` template that is injected
into each ``claude -p`` invocation as the headless session prompt.
"""

from typing import Any, cast

import jinja2

from brownfield_ai.tools.ralph.templates import get_template

# re-export for external imports
__all__ = ["render_session_prompt", "render_ci_fix_prompt", "load_template"]


def load_template() -> jinja2.Template:
    """Load the session prompt template from the ``templates/`` directory.

    Uses a Jinja2 ``FileSystemLoader`` rooted at the ``templates/``
    directory adjacent to this module.

    Returns:
        The compiled Jinja2 template for session prompt rendering.

    Raises:
        jinja2.TemplateNotFound: If ``session_prompt.md.j2`` is missing.
    """
    return cast(jinja2.Template, get_template("session_prompt.md.j2"))


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def render_session_prompt(
    epic_id: str,
    sub_plan: dict[str, Any],
    attempt: int,
    *,
    branches: dict[str, str],
    resume_json: str,
    completed_waves: list[str],
    failures: list[dict[str, Any]] | None = None,
    escalation_floor: str = "",
) -> str:
    """Render the headless session prompt from the Jinja2 template.

    Args:
        epic_id: The epic identifier.
        sub_plan: Sub-plan dict with ``"label"`` and ``"waves"`` keys.
        attempt: Current attempt number (1-3).
        branches: Repo-to-branch mapping.
        resume_json: JSON string of resume context from ledger.
        completed_waves: List of wave IDs already completed.
        failures: Prior attempt failure artifacts (each body truncated
            to 500 chars). Defaults to empty list.
        escalation_floor: Minimum tier for agent-team escalation.

    Returns:
        Rendered prompt markdown string.
    """
    if failures is None:
        failures = []
    truncated_failures = _truncate_failure_bodies(failures)
    template = load_template()
    wave_range = ",".join(sub_plan.get("waves", []))
    rendered: str = template.render(
        epic_id=epic_id,
        sub_plan_label=sub_plan.get("label", ""),
        wave_range=wave_range,
        attempt=attempt,
        branches=branches,
        resume_json=resume_json,
        completed_waves=",".join(completed_waves) if completed_waves else "none",
        failures=truncated_failures,
        escalation_floor=escalation_floor,
    )
    return rendered


def render_ci_fix_prompt(
    epic_id: str,
    *,
    branches: dict[str, str],
    pr_urls: dict[str, str],
    failures: list[dict[str, str]],
    attempt: int,
    escalation_floor: str = "",
    max_attempts: int = 3,
) -> str:
    """Render the CI fix session prompt from the Jinja2 template.

    Args:
        epic_id: The epic identifier.
        branches: Repo-to-branch mapping.
        pr_urls: Repo-to-PR-URL mapping.
        failures: List of failure dicts with ``name``, ``log_url``,
            and ``repo`` keys.
        attempt: Current CI fix attempt number.
        escalation_floor: Minimum tier for agent-team escalation.
        max_attempts: Maximum number of CI fix attempts.

    Returns:
        Rendered CI fix prompt markdown string.
    """
    template = get_template("ci_fix_prompt.md.j2")
    rendered: str = template.render(
        epic_id=epic_id,
        branches=branches,
        pr_urls=pr_urls,
        failures=failures,
        attempt=attempt,
        escalation_floor=escalation_floor,
        max_attempts=max_attempts,
    )
    return rendered


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAILURE_BODY_MAX_CHARS: int = 500


def _truncate_failure_bodies(
    failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Truncate each failure artifact body to the maximum character limit.

    Args:
        failures: List of failure dicts, each potentially containing a
            ``"body"`` key with lengthy text.

    Returns:
        Copy of the failures list with bodies truncated.
    """
    truncated: list[dict[str, Any]] = []
    for failure in failures:
        entry = dict(failure)
        body = str(entry.get("body", ""))
        if len(body) > _FAILURE_BODY_MAX_CHARS:
            entry["body"] = body[:_FAILURE_BODY_MAX_CHARS] + "... [truncated]"
        truncated.append(entry)
    return truncated
