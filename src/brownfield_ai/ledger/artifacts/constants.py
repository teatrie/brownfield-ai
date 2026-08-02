"""Shared constants for the artifact subsystem.

Houses the artifact-type enum, collection names, truncation
thresholds, and secret/PII redaction patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Artifact-type enum
# ---------------------------------------------------------------------------

VALID_ARTIFACT_TYPES: frozenset[str] = frozenset({
    "plan_snapshot",
    "design_decision",
    "gate_verdict",
    "step_result",
    "wave_summary",
    "requirement_map",
    "pr_created",
    "pr_merged",
    "todo_linked",
    "ci_resolution",
    "pr_changes_required",
    "session_exit",
    "cross_family_dissent",
    "cross_family_dissent_resolved",
    "bridge_unavailable",
    "pre_pr_dissent_block",
})

# Artifact types whose body content is run through ``sanitize_content``
# (secret/PII redaction + head+tail truncation). The four dissent-lifecycle
# types carry reviewer prose, bridge identifiers, and operator email
# addresses, all of which need the same redaction treatment as
# ``step_result`` bodies.
SANITIZED_ARTIFACT_TYPES: frozenset[str] = frozenset({
    "step_result",
    "cross_family_dissent",
    "cross_family_dissent_resolved",
    "bridge_unavailable",
    "pre_pr_dissent_block",
})

# ---------------------------------------------------------------------------
# Collection names
# ---------------------------------------------------------------------------

COLLECTION_NAME: str = "execution_ledger"
EPICS_COLLECTION_NAME: str = "epics"

# ---------------------------------------------------------------------------
# Truncation thresholds
# ---------------------------------------------------------------------------

TRUNCATION_THRESHOLD: int = 5000
TRUNCATION_HEAD: int = 2500
TRUNCATION_TAIL: int = 2500

# ---------------------------------------------------------------------------
# --content-file containment + size cap
# ---------------------------------------------------------------------------

MAX_CONTENT_FILE_BYTES: int = 10 * 1024 * 1024
# Repo root anchor for --content-file containment. constants.py lives at
# src/brownfield_ai/ledger/artifacts/constants.py, so parents[4] is the repo root
# (brownfield-ai). Keep this comment: a package-layout change alters the parents[] count.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------
# Redaction patterns
# ---------------------------------------------------------------------------

SECRET_PATTERNS: list[str] = [
    r"AKIA[0-9A-Z]{16}",
    r"(?:AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN)\s*=\s*\S+",
    r"(?:password|token|secret|ssn|phone|email)\s*[=:]\s*\S+",
]

PII_PATTERNS: list[str] = [
    r"[^@\s]+@[^@\s]+\.[^@\s]+",
    r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
]

REDACTION_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in SECRET_PATTERNS + PII_PATTERNS]
