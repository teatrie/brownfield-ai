"""Unit tests for scripts/findings_tracker.py.

Covers:
  - create()
  - update_status()
  - filter_unresolved()
  - filter_no_action_validated()
  - filter_doc_or_todo_validated()
  - load()
  - save()
  - parse_diff_markers()
  - marker_to_priority()
  - validated_finding_priority()
  - filter_active()
  - severity_rank()
  - merge_duplicate_findings()
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.findings_tracker import (
    create,
    filter_active,
    filter_doc_or_todo_validated,
    filter_no_action_validated,
    filter_unresolved,
    load,
    marker_to_priority,
    merge_duplicate_findings,
    parse_diff_markers,
    save,
    severity_rank,
    update_status,
    validated_finding_priority,
)

# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_finding_returns_dict_with_unresolved_status():
    finding = create(
        finding_id="F001",
        reviewer="alice",
        severity="significant",
        description="Missing input validation",
        round_num=1,
    )
    assert finding["status"] == "unresolved"


def test_create_finding_includes_all_fields():
    finding = create(
        finding_id="F002",
        reviewer="bob",
        severity="significant",
        description="Dead code branch",
        round_num=2,
    )
    assert finding["finding_id"] == "F002"
    assert finding["reviewer"] == "bob"
    assert finding["severity"] == "significant"
    assert finding["description"] == "Dead code branch"
    assert finding["round"] == 2
    assert "status" in finding
    assert "confidence" in finding
    assert finding["confidence"] == 0


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------


def test_update_finding_status_changes_to_resolved():
    findings = [
        create("F001", "alice", "significant", "Missing validation", 1),
        create("F002", "bob", "minor", "Style issue", 1),
    ]
    updated = update_status(findings, "F001", "resolved")
    f001 = next(f for f in updated if f["finding_id"] == "F001")
    assert f001["status"] == "resolved"


def test_update_finding_status_raises_on_unknown_id():
    findings = [create("F001", "alice", "significant", "Missing validation", 1)]
    with pytest.raises(ValueError):
        update_status(findings, "NONEXISTENT", "resolved")


# ---------------------------------------------------------------------------
# filter_unresolved
# ---------------------------------------------------------------------------


def test_filter_unresolved_returns_only_unresolved():
    findings = [
        create("F001", "alice", "significant", "Issue A", 1),
        create("F002", "bob", "minor", "Issue B", 1),
    ]
    # Manually resolve one so filter has something to exclude
    findings[0]["status"] = "resolved"
    result = filter_unresolved(findings)
    assert len(result) == 1
    assert result[0]["finding_id"] == "F002"


def test_filter_unresolved_empty_when_all_resolved():
    findings = [
        create("F001", "alice", "significant", "Issue A", 1),
    ]
    findings[0]["status"] = "resolved"
    result = filter_unresolved(findings)
    assert result == []


def test_filter_unresolved_handles_missing_status_field():
    # Legacy ledgers may omit the status field; filter_unresolved must
    # treat such entries as "unresolved" rather than raising KeyError.
    findings = [
        {"finding_id": "F001", "reviewer": "alice", "severity": "minor", "description": "Legacy entry", "round": 1, "confidence": 0},
    ]
    result = filter_unresolved(findings)
    assert len(result) == 1
    assert result[0]["finding_id"] == "F001"


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


def test_load_findings_returns_empty_list_for_missing_file(tmp_path: pathlib.Path):
    missing = tmp_path / "nonexistent.json"
    result = load(missing)
    assert result == []


def test_save_and_load_findings_round_trip(tmp_path: pathlib.Path):
    findings = [
        create("F001", "alice", "significant", "Round-trip test", 1),
        create("F002", "carol", "significant", "Second finding", 2),
    ]
    output_path = tmp_path / "findings.json"
    save(findings, output_path)
    loaded = load(output_path)
    assert len(loaded) == 2
    assert loaded[0]["finding_id"] == "F001"
    assert loaded[1]["finding_id"] == "F002"
    assert loaded[0]["status"] == "unresolved"


# ---------------------------------------------------------------------------
# parse_diff_markers
# ---------------------------------------------------------------------------

_DIFF_WITH_TODO = """\
diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
+    # TODO: fix this later
     pass
"""

_DIFF_WITH_FIXME = """\
diff --git a/bar.py b/bar.py
--- a/bar.py
+++ b/bar.py
@@ -5,3 +5,4 @@
 x = 1
+    # FIXME: broken logic
 y = 2
"""

_DIFF_WITH_HACK = """\
diff --git a/baz.py b/baz.py
--- a/baz.py
+++ b/baz.py
@@ -10,3 +10,4 @@
 z = 0
+    # HACK: temporary workaround
"""

_DIFF_WITH_XXX = """\
diff --git a/qux.py b/qux.py
--- a/qux.py
+++ b/qux.py
@@ -2,3 +2,4 @@
 a = 1
+    # XXX: investigate
"""

_DIFF_WITH_REMOVED_LINE = """\
diff --git a/rem.py b/rem.py
--- a/rem.py
+++ b/rem.py
@@ -1,3 +1,3 @@
-    # TODO: old note in removed line
+    # no marker here
"""

_DIFF_CONTEXT_ONLY = """\
diff --git a/ctx.py b/ctx.py
--- a/ctx.py
+++ b/ctx.py
@@ -1,3 +1,3 @@
     # TODO: this is a context line (no leading +)
"""

_DIFF_HEADER_LINE = """\
diff --git a/hdr.py b/hdr.py
--- a/hdr.py
+++ b/hdr.py
@@ -1,1 +1,1 @@
+++ b/hdr.py
"""

_DIFF_LOWERCASE_TODO = """\
diff --git a/low.py b/low.py
--- a/low.py
+++ b/low.py
@@ -1,2 +1,3 @@
 line
+    # todo: lowercase marker
+    # Todo: mixed-case marker
"""

_DIFF_NO_MARKERS = """\
diff --git a/clean.py b/clean.py
--- a/clean.py
+++ b/clean.py
@@ -1,2 +1,3 @@
 pass
+    x = 1
"""


def test_parse_diff_markers_finds_todo_in_added_line():
    results = parse_diff_markers(_DIFF_WITH_TODO)
    assert len(results) == 1
    assert results[0]["marker"].upper() == "TODO"


def test_parse_diff_markers_finds_fixme_in_added_line():
    results = parse_diff_markers(_DIFF_WITH_FIXME)
    assert len(results) == 1
    assert results[0]["marker"].upper() == "FIXME"


def test_parse_diff_markers_finds_hack_in_added_line():
    results = parse_diff_markers(_DIFF_WITH_HACK)
    assert len(results) == 1
    assert results[0]["marker"].upper() == "HACK"


def test_parse_diff_markers_finds_xxx_in_added_line():
    results = parse_diff_markers(_DIFF_WITH_XXX)
    assert len(results) == 1
    assert results[0]["marker"].upper() == "XXX"


def test_parse_diff_markers_ignores_removed_lines():
    results = parse_diff_markers(_DIFF_WITH_REMOVED_LINE)
    # The removed line starts with '-' and contains TODO — must not be matched
    assert all(results[i]["marker"].upper() != "TODO" for i in range(len(results)))
    # Only added lines (non-'# no marker') should have been scanned;
    # the added line has no marker, so results must be empty
    assert results == []


def test_parse_diff_markers_ignores_context_lines():
    # Context line (no leading + or -) with TODO must not be matched
    results = parse_diff_markers(_DIFF_CONTEXT_ONLY)
    assert results == []


def test_parse_diff_markers_ignores_diff_header_lines():
    # Lines starting with '+++' are diff headers and must be ignored
    results = parse_diff_markers(_DIFF_HEADER_LINE)
    assert results == []


def test_parse_diff_markers_case_insensitive():
    results = parse_diff_markers(_DIFF_LOWERCASE_TODO)
    assert len(results) == 2
    markers_upper = {r["marker"].upper() for r in results}
    assert markers_upper == {"TODO"}


def test_parse_diff_markers_returns_empty_for_no_markers():
    results = parse_diff_markers(_DIFF_NO_MARKERS)
    assert results == []


# ---------------------------------------------------------------------------
# marker_to_priority
# ---------------------------------------------------------------------------


def test_marker_to_priority_hack_returns_2():
    assert marker_to_priority("HACK") == 2


def test_marker_to_priority_xxx_returns_2():
    assert marker_to_priority("XXX") == 2


def test_marker_to_priority_fixme_returns_3():
    assert marker_to_priority("FIXME") == 3


def test_marker_to_priority_todo_returns_5():
    assert marker_to_priority("TODO") == 5


def test_marker_to_priority_case_insensitive():
    assert marker_to_priority("hack") == 2
    assert marker_to_priority("Hack") == 2
    assert marker_to_priority("fixme") == 3
    assert marker_to_priority("todo") == 5


def test_marker_to_priority_unknown_returns_default_5():
    assert marker_to_priority("UNKNOWN") == 5
    assert marker_to_priority("NOTE") == 5


# ---------------------------------------------------------------------------
# update_status with resolution kwargs
# ---------------------------------------------------------------------------


def test_update_status_with_resolution_sets_fields():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    update_status(
        findings,
        "F001",
        "accepted",
        resolution="no-action-validated",
        validators_count=2,
        total_reviewers=2,
    )
    f = findings[0]
    assert f["status"] == "accepted"
    assert f["resolution"] == "no-action-validated"
    assert f["validators_count"] == 2
    assert f["total_reviewers"] == 2


def test_update_status_with_doc_or_todo_validated_resolution():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    update_status(
        findings,
        "F001",
        "accepted",
        resolution="doc-or-todo-validated",
        validators_count=3,
        total_reviewers=3,
    )
    f = findings[0]
    assert f["status"] == "accepted"
    assert f["resolution"] == "doc-or-todo-validated"
    assert f["validators_count"] == 3
    assert f["total_reviewers"] == 3


def test_update_status_without_resolution_does_not_add_fields():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    update_status(findings, "F001", "resolved")
    f = findings[0]
    assert f["status"] == "resolved"
    assert "resolution" not in f


# ---------------------------------------------------------------------------
# filter_no_action_validated
# ---------------------------------------------------------------------------


def test_filter_no_action_validated_returns_matching():
    findings = [
        create("F001", "alice", "significant", "Issue A", 1),
        create("F002", "bob", "minor", "Issue B", 1),
    ]
    update_status(
        findings,
        "F001",
        "accepted",
        resolution="no-action-validated",
        validators_count=2,
        total_reviewers=2,
    )
    result = filter_no_action_validated(findings)
    assert len(result) == 1
    assert result[0]["finding_id"] == "F001"


def test_filter_no_action_validated_empty_when_none_match():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    result = filter_no_action_validated(findings)
    assert result == []


def test_filter_no_action_validated_ignores_other_resolutions():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    findings[0]["resolution"] = "code-change"
    result = filter_no_action_validated(findings)
    assert result == []


# ---------------------------------------------------------------------------
# filter_doc_or_todo_validated
# ---------------------------------------------------------------------------


def test_filter_doc_or_todo_validated_returns_matching():
    findings = [
        create("F001", "alice", "significant", "Issue A", 1),
        create("F002", "bob", "minor", "Issue B", 1),
    ]
    update_status(
        findings,
        "F001",
        "accepted",
        resolution="doc-or-todo-validated",
        validators_count=2,
        total_reviewers=2,
    )
    result = filter_doc_or_todo_validated(findings)
    assert len(result) == 1
    assert result[0]["finding_id"] == "F001"


def test_filter_doc_or_todo_validated_empty_when_none_match():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    result = filter_doc_or_todo_validated(findings)
    assert result == []


def test_filter_doc_or_todo_validated_ignores_other_resolutions():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    findings[0]["resolution"] = "no-action-validated"
    result = filter_doc_or_todo_validated(findings)
    assert result == []


def test_filter_doc_or_todo_validated_excludes_missing_resolution_key():
    findings = [create("F001", "alice", "significant", "Issue A", 1)]
    result = filter_doc_or_todo_validated(findings)
    assert result == []


# ---------------------------------------------------------------------------
# validated_finding_priority
# ---------------------------------------------------------------------------


def test_validated_finding_priority_all_accepted_returns_4():
    assert validated_finding_priority(validators_count=2, total_reviewers=2) == 4


def test_validated_finding_priority_partial_returns_3():
    assert validated_finding_priority(validators_count=1, total_reviewers=2) == 3


def test_validated_finding_priority_zero_validators_returns_2():
    assert validated_finding_priority(validators_count=0, total_reviewers=2) == 2


def test_validated_finding_priority_raises_on_negative_validators():
    with pytest.raises(ValueError, match="non-negative"):
        validated_finding_priority(validators_count=-1, total_reviewers=2)


def test_validated_finding_priority_raises_on_negative_total():
    with pytest.raises(ValueError, match="non-negative"):
        validated_finding_priority(validators_count=0, total_reviewers=-1)


def test_validated_finding_priority_raises_when_validators_exceed_total():
    with pytest.raises(ValueError, match="cannot exceed"):
        validated_finding_priority(validators_count=3, total_reviewers=2)


def test_validated_finding_priority_raises_on_zero_total_reviewers():
    with pytest.raises(ValueError, match="must be positive"):
        validated_finding_priority(validators_count=0, total_reviewers=0)


# ---------------------------------------------------------------------------
# create — confidence validation
# ---------------------------------------------------------------------------


def test_create_confidence_rejects_out_of_range():
    with pytest.raises(ValueError, match="confidence must be 0"):
        create(
            finding_id="F001",
            reviewer="alice",
            severity="minor",
            description="Test",
            round_num=1,
            confidence=11,
        )


def test_create_confidence_rejects_negative():
    with pytest.raises(ValueError, match="confidence must be 0"):
        create(
            finding_id="F001",
            reviewer="alice",
            severity="minor",
            description="Test",
            round_num=1,
            confidence=-1,
        )


def test_create_confidence_allows_zero():
    finding = create(
        finding_id="F001",
        reviewer="alice",
        severity="minor",
        description="Test",
        round_num=1,
        confidence=0,
    )
    assert finding["confidence"] == 0


def test_create_confidence_allows_valid_range():
    f1 = create(
        finding_id="F001",
        reviewer="alice",
        severity="minor",
        description="Test",
        round_num=1,
        confidence=1,
    )
    assert f1["confidence"] == 1

    f10 = create(
        finding_id="F002",
        reviewer="alice",
        severity="minor",
        description="Test",
        round_num=1,
        confidence=10,
    )
    assert f10["confidence"] == 10


# ---------------------------------------------------------------------------
# severity_rank
# ---------------------------------------------------------------------------


def test_severity_rank_critical():
    assert severity_rank("critical") == 4


def test_severity_rank_significant():
    assert severity_rank("significant") == 3


def test_severity_rank_minor():
    assert severity_rank("minor") == 2


def test_severity_rank_informational():
    assert severity_rank("informational") == 1


def test_severity_rank_unknown_returns_zero():
    assert severity_rank("unknown") == 0


def test_severity_rank_high_alias_returns_3():
    assert severity_rank("high") == 3


def test_severity_rank_medium_alias_returns_2():
    assert severity_rank("medium") == 2


def test_severity_rank_low_alias_returns_1():
    assert severity_rank("low") == 1


def test_severity_rank_high_alias_case_insensitive():
    assert severity_rank("HIGH") == 3


def test_severity_rank_medium_alias_case_insensitive():
    assert severity_rank("MEDIUM") == 2


def test_severity_rank_low_alias_case_insensitive():
    assert severity_rank("LOW") == 1


# ---------------------------------------------------------------------------
# merge_duplicate_findings
# ---------------------------------------------------------------------------


def test_merge_duplicates_promotes_severity():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "significant", "Issue A duplicate", 1),
    ]
    result = merge_duplicate_findings(findings, ["F001", "F002"])
    canonical = next(f for f in result if f["finding_id"] == "F001")
    merged = next(f for f in result if f["finding_id"] == "F002")
    assert canonical["severity"] == "significant"
    assert canonical["merged_from"] == ["F002"]
    assert merged["status"] == "merged"
    assert merged["merged_into"] == "F001"


def test_merge_duplicates_raises_on_single_id():
    findings = [create("F001", "alice", "minor", "Issue A", 1)]
    with pytest.raises(ValueError, match="at least 2"):
        merge_duplicate_findings(findings, ["F001"])


def test_merge_duplicates_raises_on_repeated_ids():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
    ]
    with pytest.raises(ValueError, match="repeated entries"):
        merge_duplicate_findings(findings, ["F001", "F001"])


def test_merge_duplicates_raises_on_missing_id():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "minor", "Issue B", 1),
    ]
    with pytest.raises(ValueError, match="not found"):
        merge_duplicate_findings(findings, ["F001", "F999"])


def test_merge_duplicates_raises_on_resolved_finding():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "minor", "Issue A", 1),
    ]
    findings[0]["status"] = "resolved"
    with pytest.raises(ValueError, match="non-unresolved"):
        merge_duplicate_findings(findings, ["F001", "F002"])


def test_merge_duplicates_raises_on_merged_status_canonical():
    # Regression guard: the non-unresolved check at the top of
    # merge_duplicate_findings must reject findings with status "merged"
    # (not just "resolved") when passed as the canonical argument.
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "minor", "Issue A dup", 1),
    ]
    findings[0]["status"] = "merged"
    with pytest.raises(ValueError, match="non-unresolved"):
        merge_duplicate_findings(findings, ["F001", "F002"])


def test_merge_duplicates_sequential_merge_appends_history():
    findings = [
        create("F001", "alice", "significant", "Issue A", 1),
        create("F002", "bob", "minor", "Issue B", 1),
        create("F003", "carol", "minor", "Issue C", 1),
    ]
    merge_duplicate_findings(findings, ["F001", "F002"])
    merge_duplicate_findings(findings, ["F001", "F003"])
    canonical = next(f for f in findings if f["finding_id"] == "F001")
    assert canonical["merged_from"] == ["F002", "F003"]
    assert canonical["severity"] == "significant"


def test_merge_duplicates_case_insensitive_severity_ranking():
    findings = [
        create("F001", "alice", "Minor", "Issue A", 1),
        create("F002", "bob", "SIGNIFICANT", "Issue A dup", 1),
    ]
    merge_duplicate_findings(findings, ["F001", "F002"])
    canonical = next(f for f in findings if f["finding_id"] == "F001")
    # The highest-ranked severity wins regardless of case; original string
    # case is preserved in the canonical.
    assert canonical["severity"] == "SIGNIFICANT"


def test_merge_duplicates_raises_on_previously_canonical_as_non_canonical():
    # Regression: merging a previously-canonical finding (one that already
    # has merged_from populated) as a non-canonical entry in a new merge
    # would orphan its children in a multi-hop chain. Guard must reject.
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "minor", "Issue A dup", 1),
        create("F003", "carol", "minor", "Issue A reshuffle", 1),
    ]
    merge_duplicate_findings(findings, ["F001", "F002"])
    # F001 is now canonical with merged_from=["F002"]
    with pytest.raises(ValueError, match="previously-canonical"):
        merge_duplicate_findings(findings, ["F003", "F001"])


def test_merge_duplicates_promotes_alias_severity_over_canonical():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "high", "Issue A duplicate", 1),
    ]
    result = merge_duplicate_findings(findings, ["F001", "F002"])
    canonical = next(f for f in result if f["finding_id"] == "F001")
    merged = next(f for f in result if f["finding_id"] == "F002")
    # "high" (rank 3) beats "minor" (rank 2); canonical preserves the
    # alias string "high", not the canonical equivalent "significant".
    assert canonical["severity"] == "high"
    assert canonical["merged_from"] == ["F002"]
    assert merged["status"] == "merged"
    assert merged["merged_into"] == "F001"


def test_merge_duplicates_single_call_three_ids():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "significant", "Issue A dup", 1, confidence=7),
        create("F003", "carol", "informational", "Issue A also dup", 1, confidence=3),
    ]
    result = merge_duplicate_findings(findings, ["F001", "F002", "F003"])
    canonical = next(f for f in result if f["finding_id"] == "F001")
    f002 = next(f for f in result if f["finding_id"] == "F002")
    f003 = next(f for f in result if f["finding_id"] == "F003")
    assert canonical["severity"] == "significant"
    assert canonical["confidence"] == 7
    assert canonical["merged_from"] == ["F002", "F003"]
    assert f002["status"] == "merged"
    assert f002["merged_into"] == "F001"
    assert f003["status"] == "merged"
    assert f003["merged_into"] == "F001"


# ---------------------------------------------------------------------------
# filter_active
# ---------------------------------------------------------------------------


def test_filter_active_excludes_resolved_and_merged():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "minor", "Issue B", 1),
        create("F003", "carol", "minor", "Issue C", 1),
    ]
    findings[0]["status"] = "resolved"
    findings[1]["status"] = "merged"
    result = filter_active(findings)
    assert len(result) == 1
    assert result[0]["finding_id"] == "F003"


def test_filter_active_returns_unresolved_only():
    findings = [
        create("F001", "alice", "minor", "Issue A", 1),
        create("F002", "bob", "significant", "Issue B", 1),
    ]
    result = filter_active(findings)
    assert len(result) == 2
    assert all(f["status"] == "unresolved" for f in result)


def test_filter_active_handles_missing_status_field():
    # Legacy ledgers may have findings without a status field. filter_active
    # must treat missing status as "unresolved" (default) and include them
    # as active, rather than raising KeyError.
    findings = [
        {"finding_id": "F001", "reviewer": "alice", "severity": "minor", "description": "Legacy entry", "round": 1, "confidence": 0},
    ]
    result = filter_active(findings)
    assert len(result) == 1
    assert result[0]["finding_id"] == "F001"
