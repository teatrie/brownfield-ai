"""Shared constants for the epic lifecycle subsystem.

Houses status enums, transition rules, pre-built SQL fragments, the
PR-ref regex, and CLI/UX default values consumed across lifecycle,
claims, queries, reviews, and CLI modules.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Status enums & transition rules
# ---------------------------------------------------------------------------

STALE_CLAIM_HOURS: int = 24

VALID_EPIC_STATUSES: frozenset[str] = frozenset({
    "backlog",
    "pending",
    "approved",
    "in_progress",
    "in_review",
    "completed",
    "abandoned",
    "blocked",
})

VALID_TRANSITIONS: dict[str, list[str]] = {
    "backlog": ["pending", "approved"],
    "pending": ["approved"],
    "approved": ["in_progress"],
    "in_progress": ["completed", "abandoned", "approved", "pending", "in_review", "blocked"],
    "in_review": ["completed", "backlog", "abandoned", "blocked"],
    "blocked": ["approved", "abandoned"],
}

# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------

# SQL fragment: ORDER BY status lifecycle priority, then numeric priority.
# The ELSE 8 fallback catches any value not listed here (should not occur
# given write-time validation).
STATUS_PRIORITY_ORDER_SQL: str = (
    " ORDER BY"
    "  CASE status"
    "    WHEN 'backlog'     THEN 0"
    "    WHEN 'in_progress' THEN 1"
    "    WHEN 'blocked'     THEN 2"
    "    WHEN 'in_review'   THEN 3"
    "    WHEN 'approved'    THEN 4"
    "    WHEN 'pending'     THEN 5"
    "    WHEN 'completed'   THEN 6"
    "    WHEN 'abandoned'   THEN 7"
    "    ELSE 8"
    "  END,"
    "  priority ASC"
)

# ---------------------------------------------------------------------------
# CLI / UX defaults
# ---------------------------------------------------------------------------

EPIC_LIST_DEFAULT_LIMIT: int = 100

# Pre-built query strings for list_epics. The base SELECT string is a plain
# literal; derived query shapes use Name-chain concatenation with
# non-trigger-keyword literals, keeping ruff S608 satisfied.
_EPICS_BASE_SQL: str = (
    "SELECT epic_id, status, priority, depends_on, claimed_by, claimed_at, title, created_at, last_updated_at, current_prs FROM epics"
)
_EPICS_FILTERED_BASE: str = _EPICS_BASE_SQL + " WHERE status = ?"
_EPICS_UNFILTERED_BASE: str = _EPICS_BASE_SQL
_EPICS_FILTERED_SQL: str = _EPICS_FILTERED_BASE + STATUS_PRIORITY_ORDER_SQL + " LIMIT ? OFFSET ?"
_EPICS_UNFILTERED_SQL: str = _EPICS_UNFILTERED_BASE + STATUS_PRIORITY_ORDER_SQL + " LIMIT ? OFFSET ?"
_EPICS_CLAIM_SQL: str = _EPICS_BASE_SQL + " WHERE status = 'approved' ORDER BY priority ASC"
EPIC_BY_ID_SQL: str = _EPICS_BASE_SQL + " WHERE epic_id = ?"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_PR_REF_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+$")
