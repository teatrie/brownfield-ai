"""Placement + verb-led-prefix + identifier-binding guards for the Artifact-Type Introduction Checklist.

Enforces TODO-0159 / RVW-002 follow-up Req-B01 + Req-B02:
- The new ``- **Artifact-Type Introduction Checklist**:`` sibling
  subsection in ``docs/planning_protocol.md`` MUST sit between the
  Requirements Traceability Map post-table wrap-up sentence
  (``These three tables form the **Requirements Traceability Map**.``)
  and the ``4. **Plan Checkpoint**:`` step (anchors discovered at
  runtime — no hardcoded line-number constants). Anchoring on the
  wrap-up sentence rather than the residual-risk heading guards
  against future regressions placing the checklist between the
  ``**Accepted Residual Risks (Mandatory)**:`` heading and the table
  rows (per codex-R3 F-R3-placement-anchor-weak).
- Every list bullet under the new subsection MUST begin with one of the
  four verb-led sentinel prefixes (``Add to ``, ``Touch ``,
  ``Add test mirror at ``, or ``Update dashboard mirrors at ``), AND
  each of the four prefixes MUST appear at least once across the
  bullets — guarding against future edits that silently drop a touch
  point.
- Each verb-led bullet MUST contain its required identifier substrings
  (``SANITIZED_ARTIFACT_TYPES`` / ``constants.py`` for ``Add to ``;
  ``get_resume_context`` / ``queries.py`` for ``Touch ``;
  ``test_sanitize.py`` / ``test_queries.py`` for ``Add test mirror at``;
  ``types.ts`` / ``tooltips.ts`` / ``TimelineFilter.tsx`` for
  ``Update dashboard mirrors at ``) — guarding against rename-drift
  that would weaken the prefix-only assertion.

Note on subsection style: the planning_protocol.md §2 step 3 block uses
bold-labeled sibling bullets (e.g., ``- **Requirements Traceability Map
(Mandatory)**:``) rather than ``###`` headings, because step 3 lives
inside an ordered list and an embedded ``###`` heading would break
markdownlint MD029 numbering for steps 4-9. The fourth sibling adopts
the same bold-label style; the regex below matches that anchor.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "planning_protocol.md"

CHECKLIST_HEADING_PATTERN = re.compile(r"^\s*-\s+(?:<a [^>]*></a>)?\*\*Artifact-Type Introduction Checklist\*\*:")
# Anchor on the post-table wrap-up sentence rather than the
# `**Accepted Residual Risks (Mandatory)**:` heading itself — the
# checklist must sit AFTER the residual-risk table rows, not between
# the heading and the table body (codex-R3 F-R3-placement-anchor-weak).
RTM_TABLES_WRAPUP_PATTERN = re.compile(r"^\s*These three tables form the \*\*Requirements Traceability Map\*\*\.")
PLAN_CHECKPOINT_PATTERN = re.compile(r"^4\. \*\*Plan Checkpoint\*\*:")
NESTED_LIST_ITEM_PATTERN = re.compile(r"^\s+-\s+(.+)$")
SIBLING_OR_SECTION_BREAK_PATTERN = re.compile(r"^(#{1,6} |\d+\. |\s{0,4}-\s+\*\*)")
ALLOWED_PREFIXES = (
    "Add to ",
    "Touch ",
    "Add test mirror at ",
    "Update dashboard mirrors at ",
)

REQUIRED_TOKENS_PER_PREFIX: dict[str, tuple[str, ...]] = {
    "Add to ": ("SANITIZED_ARTIFACT_TYPES", "constants.py"),
    "Touch ": ("get_resume_context", "queries.py"),
    "Add test mirror at ": ("test_sanitize.py", "test_queries.py"),
    "Update dashboard mirrors at ": (
        "types.ts",
        "tooltips.ts",
        "TimelineFilter.tsx",
    ),
}


def _doc_lines() -> list[str]:
    return DOC_PATH.read_text(encoding="utf-8").splitlines()


def _find_line_index(lines: list[str], pattern: re.Pattern[str]) -> int:
    for index, line in enumerate(lines):
        if pattern.match(line):
            return index
    raise AssertionError(
        f"Pattern {pattern.pattern!r} not found in {DOC_PATH}; no hardcoded line constants — anchor must be discoverable at runtime."
    )


def test_placement_within_draft_step() -> None:
    lines = _doc_lines()
    wrapup_line = _find_line_index(lines, RTM_TABLES_WRAPUP_PATTERN)
    checkpoint_line = _find_line_index(lines, PLAN_CHECKPOINT_PATTERN)
    heading_line = _find_line_index(lines, CHECKLIST_HEADING_PATTERN)
    assert wrapup_line < heading_line < checkpoint_line, (
        f"Artifact-Type Introduction Checklist anchor at line {heading_line + 1} "
        f"must lie strictly between the Requirements Traceability Map wrap-up sentence (line {wrapup_line + 1}) "
        f"and Plan Checkpoint (line {checkpoint_line + 1})."
    )


def _collect_checklist_bullets(lines: list[str]) -> list[tuple[str, str]]:
    """Walk bullets under the checklist heading; return ``(matched_prefix, body)`` tuples.

    Raises ``AssertionError`` if a bullet does not match any allowed
    prefix — that is the verb-led-prefix invariant from Req-B01.
    """
    heading_line = _find_line_index(lines, CHECKLIST_HEADING_PATTERN)
    bullets: list[tuple[str, str]] = []
    for line in lines[heading_line + 1 :]:
        if SIBLING_OR_SECTION_BREAK_PATTERN.match(line):
            break
        match = NESTED_LIST_ITEM_PATTERN.match(line)
        if not match:
            continue
        body = match.group(1)
        matched_prefix = next((prefix for prefix in ALLOWED_PREFIXES if body.startswith(prefix)), None)
        assert matched_prefix is not None, (
            f"List item under Artifact-Type Introduction Checklist must begin with one of {ALLOWED_PREFIXES}: got {body!r}"
        )
        bullets.append((matched_prefix, body))
    return bullets


def test_items_use_verb_led_prefixes() -> None:
    bullets = _collect_checklist_bullets(_doc_lines())
    prefixes_seen: set[str] = {prefix for prefix, _ in bullets}
    allowed: set[str] = set(ALLOWED_PREFIXES)
    missing = allowed - prefixes_seen
    assert not missing, f"Artifact-Type Introduction Checklist MUST cover all Req-B01 touch points; missing prefixes: {sorted(missing)}"


def test_items_bind_required_identifiers() -> None:
    bullets = _collect_checklist_bullets(_doc_lines())
    for prefix, body in bullets:
        required_tokens = REQUIRED_TOKENS_PER_PREFIX[prefix]
        missing_tokens = [token for token in required_tokens if token not in body]
        assert not missing_tokens, (
            f"Checklist bullet starting with {prefix!r} must reference all required identifiers "
            f"{required_tokens}; missing: {missing_tokens}. Bullet: {body!r}"
        )
