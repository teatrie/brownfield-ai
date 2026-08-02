"""Mechanical assertion that RVW-002 in-scope files contain no linter suppressions.

Per CLAUDE.md §4 (STRICTLY FORBIDDEN to use inline linter bypasses) and
RVW-002 plan §3 Req-NA04 (with the round-3 lifecycle-scaffolding
expansion to cover ``sanitize.py`` and ``queries.py``), the nine files
in this epic's source-touch zone MUST NOT carry the three suppression
styles forbidden by the project. Scope is intentionally enumerated — a
wildcard scan would match this very file's pattern fragments and
self-falsify the assertion.

The pattern keywords are assembled from short fragments at runtime so
this file's source bytes do not collide with ``ci/detect_bypasses.py``,
which scans every staged file for the same literals.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# RVW-002 source-touch zone (Req-NA04 + round-3 lifecycle expansion).
# This list is closed and intentionally excludes this very file — the grep
# below would otherwise match the pattern fragments it carries as string
# literals.
IN_SCOPE_FILES: tuple[str, ...] = (
    # Original Wave-1 source-touch zone (plan §4).
    "src/brownfield_ai/ledger/artifacts/constants.py",
    "scripts/findings_tracker.py",
    # Round-3 lifecycle-scaffolding expansion (codex-xhigh F1/F2 fixes).
    "src/brownfield_ai/ledger/artifacts/sanitize.py",
    "src/brownfield_ai/ledger/epics/queries.py",
    # Test mirrors for the in-scope source files above.
    "tests/src/brownfield_ai/ledger/artifacts/test_constants_new_types.py",
    "tests/src/brownfield_ai/ledger/artifacts/test_sanitize.py",
    "tests/src/brownfield_ai/ledger/epics/test_queries.py",
    "tests/scripts/test_findings_tracker_find_duplicates.py",
    "tests/scripts/test_ledger_artifact_types.py",
)

# Suppression keywords assembled from fragments so this source file does
# not embed the canonical literals (``ci/detect_bypasses.py`` would
# otherwise treat it as a violation). Order: ruff, mypy, shellcheck.
_SUPPRESSION_KEYWORDS: tuple[str, ...] = (
    "no" + "qa",
    "type" + ": ignore",
    "shellcheck " + "disable",
)

SUPPRESSION_PATTERN: re.Pattern[str] = re.compile(
    r"#\s*(" + "|".join(re.escape(k) for k in _SUPPRESSION_KEYWORDS) + r")",
    re.IGNORECASE,
)


@pytest.mark.parametrize("relpath", IN_SCOPE_FILES)
def test_in_scope_file_has_no_suppression_markers(relpath: str) -> None:
    path = REPO_ROOT / relpath
    assert path.exists(), f"In-scope file missing: {relpath}"
    text = path.read_text(encoding="utf-8")
    matches = SUPPRESSION_PATTERN.findall(text)
    assert matches == [], f"{relpath} contains forbidden linter suppressions: {matches}"
