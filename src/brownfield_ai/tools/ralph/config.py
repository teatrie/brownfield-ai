"""Configuration and escalation logic for ralph headless epic runner.

Environment variable defaults and escalation floor computation for
retry attempts. The escalation matrix controls which model tier and
effort level are used when a sub-plan session fails and is retried.
"""

import os
from typing import Any

# ---------------------------------------------------------------------------
# Environment variable defaults
# ---------------------------------------------------------------------------

RALPH_SESSION_TIMEOUT_SECS: int = 7200
"""Default session timeout in seconds (2 hours)."""

RALPH_EPIC_MAX_SESSIONS: int = 9
"""Maximum sessions per epic (3 sub-plans x 3 attempts)."""

RALPH_POLL_INTERVAL_SECS: int = 300
"""Polling interval in seconds for the main loop (5 minutes)."""

RALPH_HEARTBEAT_INTERVAL_SECS: int = 600
"""Default heartbeat interval in seconds (10 minutes)."""


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------


def get_config() -> dict[str, int]:
    """Load ralph configuration from environment variables with defaults.

    Reads ``RALPH_SESSION_TIMEOUT_SECS``, ``RALPH_EPIC_MAX_SESSIONS``,
    ``RALPH_POLL_INTERVAL_SECS``, and ``RALPH_HEARTBEAT_INTERVAL_SECS``
    from the environment, falling back to the module-level defaults.

    Returns:
        Dict with keys ``session_timeout``, ``max_sessions``,
        ``poll_interval``, and ``heartbeat_interval`` as integer values.
    """
    return {
        "session_timeout": int(os.environ.get("RALPH_SESSION_TIMEOUT_SECS", str(RALPH_SESSION_TIMEOUT_SECS))),
        "max_sessions": int(os.environ.get("RALPH_EPIC_MAX_SESSIONS", str(RALPH_EPIC_MAX_SESSIONS))),
        "poll_interval": int(os.environ.get("RALPH_POLL_INTERVAL_SECS", str(RALPH_POLL_INTERVAL_SECS))),
        "heartbeat_interval": int(os.environ.get("RALPH_HEARTBEAT_INTERVAL_SECS", str(RALPH_HEARTBEAT_INTERVAL_SECS))),
    }


# ---------------------------------------------------------------------------
# Escalation floor logic
# ---------------------------------------------------------------------------


def default_floor(sub_plan: dict[str, Any]) -> str:
    """Return the default escalation floor for a sub-plan's first attempt.

    For attempt 1, no floor constraint is imposed --- the session uses
    whatever model/effort the plan specifies.

    Args:
        sub_plan: Sub-plan dict with ``"label"`` and ``"waves"`` keys.
            Currently unused but reserved for plan-specific overrides.

    Returns:
        Empty string (no floor constraint for attempt 1).
    """
    return ""


def bump_floor(attempt: int) -> str:
    """Compute the default escalation floor for a given retry attempt.

    The escalation matrix increases model tier and effort level as
    retries progress:

    +----------+---------------------+---------------------+
    | Attempt  | Default Model Floor | Default Effort Floor|
    +----------+---------------------+---------------------+
    | 1        | Per-plan            | base                |
    | 2        | Per-plan            | high                |
    | 3        | One tier up         | max                 |
    +----------+---------------------+---------------------+

    Args:
        attempt: The attempt number (1-based).

    Returns:
        Comma-separated ``"model,effort"`` string. Empty for attempt 1
        (defers to plan defaults).
    """
    if attempt <= 1:
        return ""
    if attempt == 2:
        return "per-plan,high"
    return "one-tier-up,max"
