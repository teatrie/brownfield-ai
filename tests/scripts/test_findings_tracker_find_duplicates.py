"""Unit tests for ``find_duplicates_by_anchor`` (RVW-002 Req-A03).

Covers seven cases per plan §3 Req-A03 row: empty input, no duplicates,
one anchor group, multiple groups, custom anchor keys via keyword,
first-seen ordering preservation within groups, and the keyword-only
guard that rejects positional ``anchor_keys`` (Fix-11).
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.findings_tracker import find_duplicates_by_anchor


def _finding(
    finding_id: str,
    file_path: str,
    line_range: str,
    severity: str = "minor",
    **extra: Any,
) -> dict[str, Any]:
    """Construct a minimal finding dict with optional extra keys."""
    return {
        "finding_id": finding_id,
        "file_path": file_path,
        "line_range": line_range,
        "severity": severity,
        **extra,
    }


def _findings_no_duplicates() -> list[dict[str, Any]]:
    """Three findings at three distinct anchors."""
    return [
        _finding("F1", "a.py", "10-12"),
        _finding("F2", "b.py", "20-22"),
        _finding("F3", "c.py", "30-32"),
    ]


def _findings_one_anchor_group() -> list[dict[str, Any]]:
    """Three findings sharing the same (file_path, line_range) anchor."""
    return [
        _finding("F1", "a.py", "10-12"),
        _finding("F2", "a.py", "10-12"),
        _finding("F3", "a.py", "10-12"),
    ]


def _findings_multiple_groups() -> list[dict[str, Any]]:
    """Six findings forming two anchor groups plus two singletons."""
    return [
        _finding("F1", "a.py", "10-12"),
        _finding("F2", "a.py", "10-12"),
        _finding("F3", "b.py", "20-22"),
        _finding("F4", "c.py", "30-32"),
        _finding("F5", "c.py", "30-32"),
        _finding("F6", "d.py", "40-42"),
    ]


def _findings_custom_anchor() -> list[dict[str, Any]]:
    """Four findings demonstrating ``anchor_keys=("rule_id",)`` regrouping."""
    return [
        _finding("F1", "a.py", "10-12", rule_id="R1"),
        _finding("F2", "b.py", "20-22", rule_id="R1"),
        _finding("F3", "c.py", "30-32", rule_id="R2"),
        _finding("F4", "d.py", "40-42", rule_id="R2"),
    ]


def test_a03_1_empty_input_returns_empty_list() -> None:
    assert find_duplicates_by_anchor([]) == []


def test_a03_2_no_duplicates_returns_empty_list() -> None:
    assert find_duplicates_by_anchor(_findings_no_duplicates()) == []


def test_a03_3_one_anchor_group_returns_single_group_of_three() -> None:
    groups = find_duplicates_by_anchor(_findings_one_anchor_group())
    assert groups == [["F1", "F2", "F3"]]


def test_a03_4_multiple_groups_excludes_singletons() -> None:
    groups = find_duplicates_by_anchor(_findings_multiple_groups())
    assert groups == [["F1", "F2"], ["F4", "F5"]]


def test_a03_5_custom_anchor_keys_keyword_regroups_by_rule_id() -> None:
    groups = find_duplicates_by_anchor(
        _findings_custom_anchor(),
        anchor_keys=("rule_id",),
    )
    assert groups == [["F1", "F2"], ["F3", "F4"]]


def test_a03_6_preserves_first_seen_ordering_within_group() -> None:
    findings = [
        _finding("Z", "a.py", "10-12"),
        _finding("M", "a.py", "10-12"),
        _finding("A", "a.py", "10-12"),
    ]
    groups = find_duplicates_by_anchor(findings)
    assert groups == [["Z", "M", "A"]]


def test_a03_7_positional_anchor_keys_raises_type_error() -> None:
    findings = _findings_no_duplicates()
    helper: Any = find_duplicates_by_anchor
    with pytest.raises(TypeError):
        helper(findings, ("file_path",))


def _create_shaped(finding_id: str) -> dict[str, Any]:
    # Mirror of findings_tracker.create() output (no file_path / no line_range).
    return {
        "finding_id": finding_id,
        "reviewer": "R",
        "severity": "minor",
        "description": "d",
        "round": 1,
        "status": "unresolved",
        "confidence": 0,
    }


def test_create_shaped_findings_with_no_anchor_fields_return_no_groups() -> None:
    # Vanilla findings_tracker.create() output carries no file_path/line_range,
    # so the default anchor would resolve to (None, None) for every entry.
    # Per the None-anchor skip contract, all such entries are excluded.
    create_shaped = [_create_shaped("F1"), _create_shaped("F2"), _create_shaped("F3")]
    assert find_duplicates_by_anchor(create_shaped) == []


def test_partial_anchor_findings_are_excluded_from_groups() -> None:
    # Findings missing one of two anchor keys are skipped entirely so
    # they cannot collapse into a synthetic (value, None) group.
    mixed = [
        _finding("F1", "a.py", "10-12"),
        {"finding_id": "F2", "file_path": "a.py", "severity": "minor"},
        {"finding_id": "F3", "file_path": "a.py", "severity": "minor"},
    ]
    assert find_duplicates_by_anchor(mixed) == []
