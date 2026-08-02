"""CLI-surface tests for scripts/findings_tracker.py.

Phase B R_B1 expands the defopt dispatch from 2 subcommands to 11.
These tests exercise the full CLI contract end-to-end via runpy,
matching the plan's AC-B1 deliverable: every CLI subcommand is
reachable through ``python scripts/findings_tracker.py <sub>``.

Subcommands specified (kebab-case via defopt):
    - findings:create
    - findings:update-status
    - findings:filter --kind {active,no-action-validated,doc-or-todo-validated}
    - findings:load
    - findings:parse-diff-markers
    - findings:marker-priority       (renamed from marker_to_priority)
    - findings:validated-priority    (renamed from validated_finding_priority)
    - findings:merge-duplicates

Mutating CLIs take ``--in-path`` + ``--out-path`` (same path = in-place).
Read-only CLIs emit JSON to stdout.

These tests MUST fail at commit time — they describe a CLI surface
that the GREEN phase will implement. See TODO-0092 Phase B R_B1.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.findings_tracker import _collapse_repeated_flag

_SCRIPT_PATH: str = "scripts/findings_tracker.py"


def _invoke_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    """Run scripts/findings_tracker.py as ``__main__`` with the given argv.

    Uses :func:`runpy.run_path` so the defopt entrypoint executes exactly
    as if invoked from the shell. Captures stdout via the provided
    ``capsys`` fixture and returns the captured text.

    Args:
        argv: Command-line arguments excluding the script name itself
            (e.g. ``["findings:create", "--finding-id", "F001", ...]``).
        capsys: Pytest's capsys fixture used to drain stdout after
            defopt prints its JSON result.

    Returns:
        The captured stdout as a single string.
    """
    old_argv = sys.argv
    sys.argv = ["findings_tracker.py", *argv]
    try:
        runpy.run_path(_SCRIPT_PATH, run_name="__main__")
    finally:
        sys.argv = old_argv
    return capsys.readouterr().out


def _seed_ledger(path: Path, findings: list[dict[str, object]]) -> None:
    """Write a JSON findings ledger to ``path`` for tests that read it back.

    Args:
        path: Destination file path inside the test's tmp_path sandbox.
        findings: The finding dicts to serialise.
    """
    path.write_text(json.dumps(findings))


def _sample_finding(
    finding_id: str,
    *,
    severity: str = "minor",
    status: str = "unresolved",
    resolution: str | None = None,
) -> dict[str, object]:
    """Build a minimal finding dict mirroring ``create()``'s output shape.

    Args:
        finding_id: Unique identifier.
        severity: Severity string (defaults to ``"minor"``).
        status: Lifecycle status (defaults to ``"unresolved"``).
        resolution: Optional resolution label; when provided the
            field is added to the returned dict.

    Returns:
        A finding dict ready for ledger seeding.
    """
    f: dict[str, object] = {
        "finding_id": finding_id,
        "reviewer": "alice",
        "severity": severity,
        "description": f"Seed finding {finding_id}",
        "round": 1,
        "status": status,
        "confidence": 0,
    }
    if resolution is not None:
        f["resolution"] = resolution
    return f


# ---------------------------------------------------------------------------
# findings:create
# ---------------------------------------------------------------------------


def test_cli_create_writes_unresolved_finding_to_out_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    _seed_ledger(in_path, [])
    _invoke_cli(
        [
            "findings:create",
            "--finding-id",
            "F001",
            "--reviewer",
            "alice",
            "--severity",
            "significant",
            "--description",
            "Missing validation",
            "--round-num",
            "1",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    assert any(f["finding_id"] == "F001" and f["status"] == "unresolved" for f in data)


def test_cli_create_accepts_confidence_kwarg(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    _seed_ledger(in_path, [])
    _invoke_cli(
        [
            "findings:create",
            "--finding-id",
            "F002",
            "--reviewer",
            "bob",
            "--severity",
            "minor",
            "--description",
            "Style issue",
            "--round-num",
            "2",
            "--confidence",
            "7",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    f002 = next(f for f in data if f["finding_id"] == "F002")
    assert f002["confidence"] == 7


def test_cli_create_appends_to_existing_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(in_path, [_sample_finding("F000")])
    _invoke_cli(
        [
            "findings:create",
            "--finding-id",
            "F001",
            "--reviewer",
            "alice",
            "--severity",
            "minor",
            "--description",
            "Appended finding",
            "--round-num",
            "1",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    ids = {f["finding_id"] for f in data}
    assert ids == {"F000", "F001"}


def test_cli_create_treats_missing_in_path_as_empty_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "does-not-exist.json"
    out_path = tmp_path / "out.json"
    _invoke_cli(
        [
            "findings:create",
            "--finding-id",
            "F001",
            "--reviewer",
            "alice",
            "--severity",
            "minor",
            "--description",
            "From empty",
            "--round-num",
            "1",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    assert len(data) == 1
    assert data[0]["finding_id"] == "F001"


# ---------------------------------------------------------------------------
# findings:update-status
# ---------------------------------------------------------------------------


def test_cli_update_status_transitions_to_resolved(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(in_path, [_sample_finding("F001"), _sample_finding("F002")])
    _invoke_cli(
        [
            "findings:update-status",
            "--finding-id",
            "F001",
            "--new-status",
            "resolved",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    f001 = next(f for f in data if f["finding_id"] == "F001")
    assert f001["status"] == "resolved"


def test_cli_update_status_writes_resolution_metadata(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(in_path, [_sample_finding("F001")])
    _invoke_cli(
        [
            "findings:update-status",
            "--finding-id",
            "F001",
            "--new-status",
            "accepted",
            "--resolution",
            "no-action-validated",
            "--validators-count",
            "2",
            "--total-reviewers",
            "2",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    f001 = next(f for f in data if f["finding_id"] == "F001")
    assert f001["resolution"] == "no-action-validated"
    assert f001["validators_count"] == 2
    assert f001["total_reviewers"] == 2


def test_cli_update_status_raises_on_unknown_finding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(in_path, [_sample_finding("F001")])
    with pytest.raises((ValueError, SystemExit)):
        _invoke_cli(
            [
                "findings:update-status",
                "--finding-id",
                "NONEXISTENT",
                "--new-status",
                "resolved",
                "--in-path",
                str(in_path),
                "--out-path",
                str(out_path),
            ],
            capsys,
        )


# ---------------------------------------------------------------------------
# findings:filter --kind active
# ---------------------------------------------------------------------------


def test_cli_filter_active_returns_only_active(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    _seed_ledger(
        in_path,
        [
            _sample_finding("F001", status="unresolved"),
            _sample_finding("F002", status="resolved"),
            _sample_finding("F003", status="merged"),
        ],
    )
    out = _invoke_cli(
        [
            "findings:filter",
            "--kind",
            "active",
            "--in-path",
            str(in_path),
        ],
        capsys,
    )
    data = json.loads(out)
    ids = {f["finding_id"] for f in data}
    assert ids == {"F001"}


def test_cli_filter_active_all_unresolved(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    _seed_ledger(
        in_path,
        [_sample_finding("F001"), _sample_finding("F002")],
    )
    out = _invoke_cli(
        [
            "findings:filter",
            "--kind",
            "active",
            "--in-path",
            str(in_path),
        ],
        capsys,
    )
    data = json.loads(out)
    assert len(data) == 2


# ---------------------------------------------------------------------------
# findings:filter --kind no-action-validated
# ---------------------------------------------------------------------------


def test_cli_filter_no_action_validated_returns_matching(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    _seed_ledger(
        in_path,
        [
            _sample_finding("F001", resolution="no-action-validated"),
            _sample_finding("F002", resolution="doc-or-todo-validated"),
            _sample_finding("F003"),
        ],
    )
    out = _invoke_cli(
        [
            "findings:filter",
            "--kind",
            "no-action-validated",
            "--in-path",
            str(in_path),
        ],
        capsys,
    )
    data = json.loads(out)
    assert [f["finding_id"] for f in data] == ["F001"]


# ---------------------------------------------------------------------------
# findings:filter --kind doc-or-todo-validated
# ---------------------------------------------------------------------------


def test_cli_filter_doc_or_todo_validated_returns_matching(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    _seed_ledger(
        in_path,
        [
            _sample_finding("F001", resolution="no-action-validated"),
            _sample_finding("F002", resolution="doc-or-todo-validated"),
        ],
    )
    out = _invoke_cli(
        [
            "findings:filter",
            "--kind",
            "doc-or-todo-validated",
            "--in-path",
            str(in_path),
        ],
        capsys,
    )
    data = json.loads(out)
    assert [f["finding_id"] for f in data] == ["F002"]


# ---------------------------------------------------------------------------
# findings:filter --kind <unknown>
# ---------------------------------------------------------------------------


def test_cli_filter_unknown_kind_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    _seed_ledger(in_path, [_sample_finding("F001")])
    with pytest.raises((ValueError, SystemExit)):
        _invoke_cli(
            [
                "findings:filter",
                "--kind",
                "bogus-kind",
                "--in-path",
                str(in_path),
            ],
            capsys,
        )


# ---------------------------------------------------------------------------
# findings:load
# ---------------------------------------------------------------------------


def test_cli_load_returns_json_array(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    _seed_ledger(in_path, [_sample_finding("F001"), _sample_finding("F002")])
    out = _invoke_cli(
        ["findings:load", "--in-path", str(in_path)],
        capsys,
    )
    data = json.loads(out)
    assert [f["finding_id"] for f in data] == ["F001", "F002"]


def test_cli_load_empty_for_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "does-not-exist.json"
    out = _invoke_cli(
        ["findings:load", "--in-path", str(in_path)],
        capsys,
    )
    data = json.loads(out)
    assert data == []


# ---------------------------------------------------------------------------
# findings:parse-diff-markers
# ---------------------------------------------------------------------------

_SAMPLE_DIFF_TODO: str = """\
diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
+    # TODO: implement this
     pass
"""

_SAMPLE_DIFF_MIXED: str = """\
diff --git a/bar.py b/bar.py
--- a/bar.py
+++ b/bar.py
@@ -5,3 +5,5 @@
 x = 1
+    # FIXME: wrong
+    # HACK: workaround
 y = 2
"""


def test_cli_parse_diff_markers_extracts_todo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diff_path = tmp_path / "sample.diff"
    diff_path.write_text(_SAMPLE_DIFF_TODO)
    out = _invoke_cli(
        ["findings:parse-diff-markers", "--diff-path", str(diff_path)],
        capsys,
    )
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["marker"].upper() == "TODO"
    assert "line_number" in data[0]


def test_cli_parse_diff_markers_extracts_multiple(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diff_path = tmp_path / "mixed.diff"
    diff_path.write_text(_SAMPLE_DIFF_MIXED)
    out = _invoke_cli(
        ["findings:parse-diff-markers", "--diff-path", str(diff_path)],
        capsys,
    )
    data = json.loads(out)
    markers = {r["marker"].upper() for r in data}
    assert markers == {"FIXME", "HACK"}


# ---------------------------------------------------------------------------
# findings:merge-duplicates
# ---------------------------------------------------------------------------


def test_cli_merge_duplicates_promotes_severity(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(
        in_path,
        [
            _sample_finding("F001", severity="minor"),
            _sample_finding("F002", severity="significant"),
        ],
    )
    _invoke_cli(
        [
            "findings:merge-duplicates",
            "--duplicate-ids",
            "F001",
            "--duplicate-ids",
            "F002",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    canonical = next(f for f in data if f["finding_id"] == "F001")
    merged = next(f for f in data if f["finding_id"] == "F002")
    assert canonical["severity"] == "significant"
    assert merged["status"] == "merged"
    assert merged["merged_into"] == "F001"


def test_cli_merge_duplicates_writes_merged_from_history(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(
        in_path,
        [
            _sample_finding("F001"),
            _sample_finding("F002"),
            _sample_finding("F003"),
        ],
    )
    _invoke_cli(
        [
            "findings:merge-duplicates",
            "--duplicate-ids",
            "F001",
            "--duplicate-ids",
            "F002",
            "--duplicate-ids",
            "F003",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    canonical = next(f for f in data if f["finding_id"] == "F001")
    assert canonical["merged_from"] == ["F002", "F003"]


def test_cli_merge_duplicates_rejects_single_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(in_path, [_sample_finding("F001")])
    with pytest.raises((ValueError, SystemExit)):
        _invoke_cli(
            [
                "findings:merge-duplicates",
                "--duplicate-ids",
                "F001",
                "--in-path",
                str(in_path),
                "--out-path",
                str(out_path),
            ],
            capsys,
        )


# ---------------------------------------------------------------------------
# findings:marker-priority (renamed from marker_to_priority)
# ---------------------------------------------------------------------------


def test_cli_marker_priority_hack_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _invoke_cli(
        ["findings:marker-priority", "--marker", "HACK"],
        capsys,
    )
    assert out.strip() == "2"


def test_cli_marker_priority_todo_returns_5(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _invoke_cli(
        ["findings:marker-priority", "--marker", "TODO"],
        capsys,
    )
    assert out.strip() == "5"


# ---------------------------------------------------------------------------
# findings:validated-priority (renamed from validated_finding_priority)
# ---------------------------------------------------------------------------


def test_cli_validated_priority_all_accepted_returns_4(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _invoke_cli(
        [
            "findings:validated-priority",
            "--validators-count",
            "2",
            "--total-reviewers",
            "2",
        ],
        capsys,
    )
    assert out.strip() == "4"


def test_cli_validated_priority_partial_returns_3(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _invoke_cli(
        [
            "findings:validated-priority",
            "--validators-count",
            "1",
            "--total-reviewers",
            "3",
        ],
        capsys,
    )
    assert out.strip() == "3"


def test_cli_validated_priority_orchestrator_only_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _invoke_cli(
        [
            "findings:validated-priority",
            "--validators-count",
            "0",
            "--total-reviewers",
            "2",
        ],
        capsys,
    )
    assert out.strip() == "2"


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------


def test_cli_create_then_update_then_filter_active(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [])
    _invoke_cli(
        [
            "findings:create",
            "--finding-id",
            "F001",
            "--reviewer",
            "alice",
            "--severity",
            "minor",
            "--description",
            "A",
            "--round-num",
            "1",
            "--in-path",
            str(ledger),
            "--out-path",
            str(ledger),
        ],
        capsys,
    )
    _invoke_cli(
        [
            "findings:create",
            "--finding-id",
            "F002",
            "--reviewer",
            "bob",
            "--severity",
            "minor",
            "--description",
            "B",
            "--round-num",
            "1",
            "--in-path",
            str(ledger),
            "--out-path",
            str(ledger),
        ],
        capsys,
    )
    _invoke_cli(
        [
            "findings:update-status",
            "--finding-id",
            "F001",
            "--new-status",
            "resolved",
            "--in-path",
            str(ledger),
            "--out-path",
            str(ledger),
        ],
        capsys,
    )
    out = _invoke_cli(
        ["findings:filter", "--kind", "active", "--in-path", str(ledger)],
        capsys,
    )
    data = json.loads(out)
    ids = {f["finding_id"] for f in data}
    assert ids == {"F002"}


def test_cli_create_then_merge_then_filter_active_excludes_merged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    _seed_ledger(
        ledger,
        [
            _sample_finding("F001", severity="minor"),
            _sample_finding("F002", severity="significant"),
            _sample_finding("F003", severity="minor"),
        ],
    )
    _invoke_cli(
        [
            "findings:merge-duplicates",
            "--duplicate-ids",
            "F001",
            "--duplicate-ids",
            "F002",
            "--in-path",
            str(ledger),
            "--out-path",
            str(ledger),
        ],
        capsys,
    )
    out = _invoke_cli(
        ["findings:filter", "--kind", "active", "--in-path", str(ledger)],
        capsys,
    )
    data = json.loads(out)
    ids = {f["finding_id"] for f in data}
    assert ids == {"F001", "F003"}


# ---------------------------------------------------------------------------
# Missing-file handling for read-only CLIs
# ---------------------------------------------------------------------------


def test_cli_filter_missing_file_returns_empty_array(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "never-written.json"
    out = _invoke_cli(
        ["findings:filter", "--kind", "active", "--in-path", str(in_path)],
        capsys,
    )
    assert json.loads(out) == []


def test_cli_load_missing_file_returns_empty_array(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "never-written.json"
    out = _invoke_cli(
        ["findings:load", "--in-path", str(in_path)],
        capsys,
    )
    assert json.loads(out) == []


# ---------------------------------------------------------------------------
# _collapse_repeated_flag — equals-form + subcommand gate (TODO-0108 / 0109)
# ---------------------------------------------------------------------------


def test_cli_merge_duplicates_accepts_equals_form(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger.json"
    _seed_ledger(
        in_path,
        [
            _sample_finding("F001", severity="minor"),
            _sample_finding("F002", severity="significant"),
        ],
    )
    _invoke_cli(
        [
            "findings:merge-duplicates",
            "--duplicate-ids=F001",
            "--duplicate-ids=F002",
            "--in-path",
            str(in_path),
            "--out-path",
            str(out_path),
        ],
        capsys,
    )
    data = json.loads(out_path.read_text())
    canonical = next(f for f in data if f["finding_id"] == "F001")
    merged = next(f for f in data if f["finding_id"] == "F002")
    assert canonical["severity"] == "significant"
    assert merged["status"] == "merged"
    assert merged["merged_into"] == "F001"


def test_collapse_repeated_flag_accepts_mixed_space_and_equals_form() -> None:
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids=F001",
        "--duplicate-ids",
        "F002",
        "--in-path",
        "tmp/x",
    ]
    result = _collapse_repeated_flag(
        argv,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert result == [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "F001",
        "F002",
        "--in-path",
        "tmp/x",
    ]


def test_collapse_repeated_flag_is_noop_on_non_matching_subcommand() -> None:
    # The gate MUST leave argv untouched when the subcommand differs, so
    # future flag-name collisions in sibling subcommands cannot corrupt
    # arguments intended for them.
    argv = [
        "findings:load",
        "--duplicate-ids",
        "F001",
        "--duplicate-ids",
        "F002",
    ]
    result = _collapse_repeated_flag(
        argv,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert result is argv
    # And the inverse: when the subcommand matches, collapse still works.
    argv_match = ["findings:merge-duplicates", *argv[1:]]
    collapsed = _collapse_repeated_flag(
        argv_match,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert collapsed == [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "F001",
        "F002",
    ]


def test_collapse_repeated_flag_trailing_bare_flag_fails_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # TODO-0128 (AC-9): a standalone bare ``--duplicate-ids`` with no
    # collapsible occurrence and no following token still exits 2.
    # Pre-closure this returned argv unchanged via the
    # ``first_index is None`` early-return; the closed-form contract
    # rejects it identically to the trailing-after-collapse case.
    argv = ["findings:merge-duplicates", "--duplicate-ids"]
    with pytest.raises(SystemExit) as exc_info:
        _collapse_repeated_flag(
            argv,
            "--duplicate-ids",
            subcommand="findings:merge-duplicates",
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err
    assert "--duplicate-ids" in captured.err


def test_collapse_repeated_flag_leading_bare_flag_with_value_succeeds() -> None:
    # §5 matrix Leading × Word value cell: ``[sub, --flag, F002, ...]``
    # is the canonical leading collapse and MUST succeed even though no
    # equals-form or prior space-form occurrence preceded it.
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "F002",
        "--in-path",
        "tmp/x",
    ]
    result = _collapse_repeated_flag(
        argv,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert result == [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "F002",
        "--in-path",
        "tmp/x",
    ]


def test_collapse_repeated_flag_leading_bare_flag_before_option_fails_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # TODO-0128 (AC-3): a leading bare ``--duplicate-ids`` followed by
    # ``--in-path`` exits 2 — symmetric to the mid-stream case. Pre-C2
    # this returned argv unchanged via the ``first_index is None``
    # early-return.
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "--in-path",
        "tmp/x.json",
    ]
    with pytest.raises(SystemExit) as exc_info:
        _collapse_repeated_flag(
            argv,
            "--duplicate-ids",
            subcommand="findings:merge-duplicates",
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err
    assert "--duplicate-ids" in captured.err


def test_collapse_repeated_flag_returns_argv_unchanged_when_flag_absent() -> None:
    # Post-loop ``if first_index is None: return argv`` still serves the
    # legitimate "no --flag token at all" case after C2's unconditional
    # exit — guards against a regression where C2 accidentally over-
    # closes the contract.
    argv = ["findings:merge-duplicates", "--in-path", "tmp/x.json"]
    result = _collapse_repeated_flag(
        argv,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert result is argv


def test_collapse_repeated_flag_empty_equals_form_preserves_empty_string() -> None:
    # Empty equals-form preserves empty string in collected values; downstream
    # validation in `merge_duplicate_findings` catches empty IDs. Pre-existing
    # symmetric behaviour with space-form `--flag ""`.
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids=",
        "--duplicate-ids=F001",
    ]
    result = _collapse_repeated_flag(
        argv,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert result == [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "",
        "F001",
    ]


def test_collapse_repeated_flag_trailing_bare_after_collapse_fails_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # TODO-0127 closed-form: a trailing bare --duplicate-ids appearing
    # after collapsed occurrences exits 2 with a wide stderr message
    # naming the flag and the corrective forms. The prior NOTICE-drop
    # branch (silent recovery on malformed argv) is removed.
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids=F001",
        "--duplicate-ids=F002",
        "--duplicate-ids",
    ]
    with pytest.raises(SystemExit) as exc_info:
        _collapse_repeated_flag(
            argv,
            "--duplicate-ids",
            subcommand="findings:merge-duplicates",
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err
    assert "--duplicate-ids" in captured.err


def test_collapse_repeated_flag_midstream_bare_flag_fails_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # TODO-0127 closed-form: a mid-stream bare --duplicate-ids followed
    # by --in-path exits 2 — the helper does not consume --in-path as a
    # value, and does not silently drop the bare token. Same wide
    # stderr message as the trailing case (AC-4 position-agnostic).
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids=F001",
        "--duplicate-ids",
        "--in-path",
        "tmp/x.json",
        "--out-path",
        "tmp/y.json",
    ]
    with pytest.raises(SystemExit) as exc_info:
        _collapse_repeated_flag(
            argv,
            "--duplicate-ids",
            subcommand="findings:merge-duplicates",
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err
    assert "--duplicate-ids" in captured.err


def test_collapse_repeated_flag_rejects_hyphen_prefix_space_form_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # C3 inversion: previously accepted, now rejected per closed-form
    # contract; see plan §6 C3. Operators needing -prefixed values use
    # --flag=-A1 (equals-form, AC-6).
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "-A1",
        "--duplicate-ids",
        "F002",
    ]
    with pytest.raises(SystemExit) as exc_info:
        _collapse_repeated_flag(
            argv,
            "--duplicate-ids",
            subcommand="findings:merge-duplicates",
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err
    assert "--duplicate-ids" in captured.err


def test_collapse_repeated_flag_rejects_hyphen_value_in_middle_position(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # §5 matrix Middle × Single-dash value: a -prefixed value mid-stream
    # exits 2 — symmetric to the leading-position case.
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids=F001",
        "--duplicate-ids",
        "-A1",
        "--in-path",
        "tmp/x",
    ]
    with pytest.raises(SystemExit) as exc_info:
        _collapse_repeated_flag(
            argv,
            "--duplicate-ids",
            subcommand="findings:merge-duplicates",
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err


def test_collapse_repeated_flag_rejects_hyphen_value_in_trailing_position(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # §5 matrix Trailing × Single-dash value: a -prefixed value at the
    # tail of argv exits 2.
    argv = [
        "findings:merge-duplicates",
        "--in-path",
        "tmp/x",
        "--duplicate-ids",
        "-A1",
    ]
    with pytest.raises(SystemExit) as exc_info:
        _collapse_repeated_flag(
            argv,
            "--duplicate-ids",
            subcommand="findings:merge-duplicates",
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err


def test_collapse_repeated_flag_equals_form_accepts_hyphen_value() -> None:
    # AC-6 escape hatch: equals-form (`--flag=-A1`) is unchanged across
    # C1 → C2 → C3 and continues to admit any value, including
    # -prefixed strings.
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids=-A1",
        "--in-path",
        "tmp/x",
    ]
    result = _collapse_repeated_flag(
        argv,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert result == [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "-A1",
        "--in-path",
        "tmp/x",
    ]


def test_collapse_repeated_flag_equals_form_mixed_with_space_form_admits_hyphen() -> None:
    # §5 closure: equals-form mixed with space-form, where only the
    # equals-form admits a -prefixed value. Demonstrates the contract
    # symmetry — the rule depends on token shape, not position.
    argv = [
        "findings:merge-duplicates",
        "--duplicate-ids=F001",
        "--duplicate-ids",
        "F002",
        "--duplicate-ids=-A1",
        "--in-path",
        "tmp/x",
    ]
    result = _collapse_repeated_flag(
        argv,
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    assert result == [
        "findings:merge-duplicates",
        "--duplicate-ids",
        "F001",
        "F002",
        "-A1",
        "--in-path",
        "tmp/x",
    ]


def test_cli_merge_duplicates_bare_flag_fails_closed_no_out_path_written(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # AC-11 end-to-end integration: a bare `--duplicate-ids` reaches the
    # helper via the CLI entrypoint, exits 2 *before* defopt parses the
    # argv, and never reaches the ledger save path. The load-bearing
    # assertion is that `out_path` does NOT exist on disk after the
    # call — pre-defopt failure cannot persist anything.
    in_path = tmp_path / "ledger.json"
    out_path = tmp_path / "ledger-out.json"
    _seed_ledger(
        in_path,
        [
            _sample_finding("F001", severity="minor"),
            _sample_finding("F002", severity="significant"),
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        _invoke_cli(
            [
                "findings:merge-duplicates",
                "--duplicate-ids",
                "--in-path",
                str(in_path),
                "--out-path",
                str(out_path),
            ],
            capsys,
        )
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires a non-option value" in captured.err
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# findings:apply-batch
# ---------------------------------------------------------------------------


def _write_batch(path: Path, ops: list[dict[str, object]]) -> None:
    """Write a list of op dicts to ``path`` as JSONL."""
    path.write_text("\n".join(json.dumps(op) for op in ops))


def test_apply_batch_empty_file_emits_empty_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    batch = tmp_path / "batch.jsonl"
    batch.write_text("")
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload == {"results": {}, "errors": []}


def test_apply_batch_create_appends_finding_to_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {
                "op": "create",
                "id": "f001-create",
                "args": {
                    "finding_id": "F001",
                    "reviewer": "alice",
                    "severity": "significant",
                    "description": "Missing validation",
                    "round_num": 1,
                    "confidence": 7,
                },
                "in_path": str(ledger),
                "out_path": str(ledger),
            }
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    assert payload["results"] == {"f001-create": {"status": "ok"}}
    on_disk = json.loads(ledger.read_text())
    assert any(f["finding_id"] == "F001" and f["confidence"] == 7 for f in on_disk)


def test_apply_batch_mixed_read_only_ops_collected_under_caller_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    _seed_ledger(
        ledger,
        [
            _sample_finding("F001", severity="significant"),
            _sample_finding("F002", status="resolved"),
        ],
    )
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "filter", "id": "active", "args": {"kind": "active"}, "in_path": str(ledger)},
            {"op": "validated-priority", "id": "vp-2-3", "args": {"validators_count": 2, "total_reviewers": 3}},
            {"op": "marker-priority", "id": "mp-todo", "args": {"marker": "TODO"}},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    assert [f["finding_id"] for f in payload["results"]["active"]] == ["F001"]
    assert payload["results"]["vp-2-3"] == 3
    assert payload["results"]["mp-todo"] == 5


def test_apply_batch_parse_diff_markers_caches_repeated_diff_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diff = tmp_path / "qa-diff.txt"
    diff.write_text("@@ -1,1 +1,1 @@\n+# TODO investigate\n+# FIXME later\n")
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "parse-diff-markers", "id": "first", "diff_path": str(diff)},
            {"op": "parse-diff-markers", "id": "second", "diff_path": str(diff)},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    assert payload["results"]["first"] == payload["results"]["second"]
    assert {m["marker"] for m in payload["results"]["first"]} == {"TODO", "FIXME"}


def test_apply_batch_blank_lines_and_comments_are_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    batch = tmp_path / "batch.jsonl"
    batch.write_text('\n# leading comment\n{"op": "marker-priority", "id": "mp", "args": {"marker": "HACK"}}\n\n# trailing comment\n')
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload == {"results": {"mp": 2}, "errors": []}


def test_apply_batch_default_id_uses_line_number_when_id_omitted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    batch = tmp_path / "batch.jsonl"
    batch.write_text('{"op": "marker-priority", "args": {"marker": "FIXME"}}\n{"op": "marker-priority", "args": {"marker": "TODO"}}\n')
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    assert payload["results"] == {"op-1": 3, "op-2": 5}


def test_apply_batch_fails_fast_on_unknown_op_returning_partial_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "marker-priority", "id": "ok-1", "args": {"marker": "TODO"}},
            {"op": "bogus", "id": "bad"},
            {"op": "marker-priority", "id": "skipped", "args": {"marker": "HACK"}},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {"ok-1": 5}
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["id"] == "bad"
    assert payload["errors"][0]["line"] == 2
    assert "Unknown op" in payload["errors"][0]["error"]


def test_apply_batch_records_malformed_json_line_with_line_number(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    batch = tmp_path / "batch.jsonl"
    batch.write_text('{"op": "marker-priority", "id": "ok", "args": {"marker": "TODO"}}\nthis-is-not-json\n')
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {"ok": 5}
    assert payload["errors"][0]["line"] == 2
    assert "malformed JSON" in payload["errors"][0]["error"]


def test_apply_batch_create_then_filter_in_one_call_sees_freshly_written_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Verifies in-batch ordering: a mutation followed by a read-only op
    # against the same ledger reflects the mutation. Mirrors the SKILL.md
    # Step 3.1 → Step 3.4 sequence within a single container call.
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {
                "op": "create",
                "id": "create-f1",
                "args": {
                    "finding_id": "F1",
                    "reviewer": "alice",
                    "severity": "minor",
                    "description": "x",
                    "round_num": 1,
                },
                "in_path": str(ledger),
                "out_path": str(ledger),
            },
            {"op": "filter", "id": "active-after", "args": {"kind": "active"}, "in_path": str(ledger)},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    assert [f["finding_id"] for f in payload["results"]["active-after"]] == ["F1"]


def test_apply_batch_propagates_library_validation_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # validators_count > total_reviewers raises ValueError in the library;
    # apply-batch surfaces it under errors[] without crashing.
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {
                "op": "validated-priority",
                "id": "bad",
                "args": {"validators_count": 5, "total_reviewers": 2},
            },
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {}
    assert payload["errors"][0]["id"] == "bad"
    assert "cannot exceed" in payload["errors"][0]["error"]


def test_apply_batch_rejects_non_dict_op_def_without_crashing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R1 finding (Gemini G1 / Codex C1):
    # a JSON line that parses to a list (or other non-dict) used to crash
    # the process via AttributeError on op_def.get(...).
    batch = tmp_path / "batch.jsonl"
    batch.write_text('{"op": "marker-priority", "id": "ok", "args": {"marker": "TODO"}}\n[1, 2, 3]\n')
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {"ok": 5}
    assert payload["errors"][0]["line"] == 2
    assert payload["errors"][0]["id"] is None
    assert payload["errors"][0]["op"] is None
    assert "must be a JSON object" in payload["errors"][0]["error"]


def test_apply_batch_rejects_non_dict_args_without_crashing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R1 finding (Gemini G1 / Codex C1):
    # args supplied as a list used to leak TypeError from the **args splat.
    batch = tmp_path / "batch.jsonl"
    _write_batch(batch, [{"op": "marker-priority", "id": "bad", "args": ["TODO"]}])
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {}
    assert payload["errors"][0]["id"] == "bad"
    assert payload["errors"][0]["op"] == "marker-priority"
    assert "args must be a JSON object" in payload["errors"][0]["error"]


def test_apply_batch_catches_typeerror_from_missing_required_kwarg(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R1 finding (Gemini G1 / Codex C1):
    # create(**{}) raises TypeError for missing finding_id; the batch must
    # surface it under errors[], not crash with an uncaught traceback.
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {
                "op": "create",
                "id": "incomplete",
                "args": {},
                "in_path": str(ledger),
                "out_path": str(ledger),
            }
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {}
    assert payload["errors"][0]["id"] == "incomplete"
    assert payload["errors"][0]["op"] == "create"
    # Atomic rollback: nothing was written.
    assert json.loads(ledger.read_text()) == []


def test_apply_batch_rejects_duplicate_caller_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R1 finding (Opus F2):
    # without explicit duplicate detection, the second op silently
    # clobbers the first result under the same id key.
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "marker-priority", "id": "shared", "args": {"marker": "TODO"}},
            {"op": "marker-priority", "id": "shared", "args": {"marker": "HACK"}},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {"shared": 5}
    assert payload["errors"][0]["id"] == "shared"
    assert "duplicate id" in payload["errors"][0]["error"]


def test_apply_batch_atomic_rollback_create_followed_by_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R1 findings (Gemini G2 + Opus F3):
    # under atomic semantics, a create that succeeds in-memory must NOT
    # persist to disk if a later op in the same batch fails. This makes
    # corrected re-runs safe — no duplicate-create on retry.
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {
                "op": "create",
                "id": "good-create",
                "args": {
                    "finding_id": "F1",
                    "reviewer": "alice",
                    "severity": "minor",
                    "description": "x",
                    "round_num": 1,
                },
                "in_path": str(ledger),
                "out_path": str(ledger),
            },
            {"op": "bogus", "id": "fails"},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {"good-create": {"status": "ok"}}
    assert payload["errors"][0]["id"] == "fails"
    # Critical assertion: the create did NOT persist, despite reporting "ok".
    # Atomic batch semantics — all-or-nothing.
    assert json.loads(ledger.read_text()) == []


def test_apply_batch_multi_create_persists_each_finding_exactly_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R1 finding (Gemini G2):
    # with the atomic ledger cache, three create ops should result in a
    # single end-of-batch save containing all three findings. The prior
    # per-op load/save was N+1; this test locks the new contract.
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {
                "op": "create",
                "id": f"create-F{i}",
                "args": {
                    "finding_id": f"F{i}",
                    "reviewer": "alice",
                    "severity": "minor",
                    "description": f"finding {i}",
                    "round_num": 1,
                },
                "in_path": str(ledger),
                "out_path": str(ledger),
            }
            for i in (1, 2, 3)
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    on_disk = json.loads(ledger.read_text())
    assert [f["finding_id"] for f in on_disk] == ["F1", "F2", "F3"]


def test_apply_batch_malformed_json_error_record_has_full_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R1 finding (Codex C2):
    # all error records must carry id/op/line/error (id/op = null when
    # the failure is pre-dispatch) so downstream consumers can rely on a
    # stable schema.
    batch = tmp_path / "batch.jsonl"
    batch.write_text("not-json-at-all\n")
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    record = payload["errors"][0]
    assert set(record.keys()) == {"id", "op", "line", "error"}
    assert record["id"] is None
    assert record["op"] is None
    assert record["line"] == 1


def test_apply_batch_diff_text_cache_avoids_re_reading_same_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression guard for tri-family R1 finding (Opus F1) AND
    # R2 finding (Codex C3): the prior assertion of equal results
    # would pass even without caching. Lock the actual cache contract
    # by counting Path.read_text invocations against the diff file.
    diff = tmp_path / "qa-diff.txt"
    diff.write_text("@@ -1,1 +1,1 @@\n+# TODO investigate\n")

    # Type-erase via Any so the wrapper can forward arbitrary signatures
    # without an inline mypy bypass (CLAUDE.md §4 forbids those).
    real_read_text: Any = Path.read_text
    diff_read_targets: list[str] = []

    def counting_read_text(self: Path, *args: Any, **kwargs: Any) -> Any:
        diff_read_targets.append(str(self.resolve()))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "parse-diff-markers", "id": "raw", "diff_path": str(diff)},
            {"op": "parse-diff-markers", "id": "dotted", "diff_path": str(diff.parent / "." / diff.name)},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    assert payload["results"]["raw"] == payload["results"]["dotted"]

    # Two parse-diff-markers ops referenced the same physical file via
    # different surface-spelling paths. With cache: 1 read. Without: 2.
    diff_reads = [p for p in diff_read_targets if p == str(diff.resolve())]
    assert len(diff_reads) == 1, f"diff file was read {len(diff_reads)}x; expected 1 (cache miss)"


def test_apply_batch_rejects_non_string_id_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R2 finding (Codex C1) and R3
    # finding (Codex R3-1): non-string ids must be rejected before
    # reaching the duplicate-id check, otherwise either the `in
    # results` check raises uncaught TypeError (list/dict) or
    # JSON-key collisions corrupt the output (int vs str).
    batch = tmp_path / "batch.jsonl"
    _write_batch(batch, [{"op": "marker-priority", "id": [1, 2], "args": {"marker": "TODO"}}])
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {}
    assert payload["errors"][0]["op"] == "marker-priority"
    assert payload["errors"][0]["line"] == 1
    assert "id must be a string" in payload["errors"][0]["error"]
    # The error record echoes the offending raw id value so the caller
    # can identify their bad input even though the runtime rejected it.
    assert payload["errors"][0]["id"] == [1, 2]


def test_apply_batch_omitted_id_with_dispatch_failure_echoes_synthesised_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Regression guard for tri-family R4 finding (Codex R4-1):
    # when the caller omits `id` and the op fails downstream of
    # validation, the error record must echo the synthesised default
    # `op-<line>` so it correlates with the would-have-been results
    # map key. R4's first-pass fix used op_def.get("id") for all error
    # records, which collapsed this case to `id: null` and broke the
    # documented default-id contract.
    batch = tmp_path / "batch.jsonl"
    # No id; bogus op triggers dispatch failure inside _apply_batch_op.
    _write_batch(batch, [{"op": "bogus-op-triggers-dispatch-failure"}])
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {}
    assert payload["errors"][0]["id"] == "op-1"
    assert payload["errors"][0]["op"] == "bogus-op-triggers-dispatch-failure"
    assert payload["errors"][0]["line"] == 1


def test_apply_batch_rejects_int_id_to_prevent_json_key_collision(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R3 finding (Codex R3-1):
    # if id=1 (int) and id="1" (str) both passed validation, the
    # results dict would serialise to JSON with two "1" keys (Python
    # treats them as distinct dict keys; JSON coerces both to the
    # same string key). Strict id-must-be-string validation prevents
    # the collision class entirely.
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "marker-priority", "id": "1", "args": {"marker": "TODO"}},
            {"op": "marker-priority", "id": 1, "args": {"marker": "HACK"}},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    # First op succeeds with the string id.
    assert payload["results"] == {"1": 5}
    # Second op rejected on the type check, never reaches duplicate detection.
    assert payload["errors"][0]["line"] == 2
    assert payload["errors"][0]["id"] == 1
    assert "id must be a string" in payload["errors"][0]["error"]


def test_apply_batch_divergent_in_out_paths_isolate_source_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R2 findings (Gemini G1 / Codex C2):
    # when in_path and out_path resolve to different files, a mutation
    # MUST NOT pollute the in_path cache. Two fan-out creates from the
    # same source must produce two distinct outputs, each carrying only
    # its own finding.
    source = tmp_path / "source.json"
    branch_a = tmp_path / "branch-a.json"
    branch_b = tmp_path / "branch-b.json"
    _seed_ledger(source, [])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {
                "op": "create",
                "id": "to-a",
                "args": {"finding_id": "F1", "reviewer": "alice", "severity": "minor", "description": "A-only", "round_num": 1},
                "in_path": str(source),
                "out_path": str(branch_a),
            },
            {
                "op": "create",
                "id": "to-b",
                "args": {"finding_id": "F2", "reviewer": "alice", "severity": "minor", "description": "B-only", "round_num": 1},
                "in_path": str(source),
                "out_path": str(branch_b),
            },
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []

    assert json.loads(source.read_text()) == [], "source ledger must remain untouched on fan-out"
    a_findings = json.loads(branch_a.read_text())
    b_findings = json.loads(branch_b.read_text())
    assert [f["finding_id"] for f in a_findings] == ["F1"]
    assert [f["finding_id"] for f in b_findings] == ["F2"]


def test_apply_batch_load_returns_snapshot_not_live_reference(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R2 finding (Gemini G1, temporal
    # leak): a `load` op followed by a `create` against the same ledger
    # must yield a load result that reflects the pre-create state, not
    # the end-of-batch state.
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "load", "id": "before", "in_path": str(ledger)},
            {
                "op": "create",
                "id": "writer",
                "args": {"finding_id": "F1", "reviewer": "alice", "severity": "minor", "description": "x", "round_num": 1},
                "in_path": str(ledger),
                "out_path": str(ledger),
            },
            {"op": "load", "id": "after", "in_path": str(ledger)},
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    assert payload["results"]["before"] == [], "load before create must not see the later mutation"
    assert [f["finding_id"] for f in payload["results"]["after"]] == ["F1"], "load after create must see the mutation"


def test_apply_batch_filter_returns_snapshot_isolated_from_later_update(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Companion to the load-snapshot test: filter results carry deep
    # copies of finding dicts so a later update-status against the same
    # finding does not retroactively mutate the earlier filter snapshot.
    ledger = tmp_path / "ledger.json"
    _seed_ledger(ledger, [_sample_finding("F1", severity="minor")])
    batch = tmp_path / "batch.jsonl"
    _write_batch(
        batch,
        [
            {"op": "filter", "id": "snapshot", "args": {"kind": "active"}, "in_path": str(ledger)},
            {
                "op": "update-status",
                "id": "resolve",
                "args": {"finding_id": "F1", "new_status": "resolved"},
                "in_path": str(ledger),
                "out_path": str(ledger),
            },
        ],
    )
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["errors"] == []
    snapshot = payload["results"]["snapshot"]
    assert snapshot[0]["status"] == "unresolved", "filter snapshot must not reflect the later resolve mutation"


def test_apply_batch_permission_error_on_diff_path_surfaces_as_structured_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression guard for tri-family R2 findings (Gemini G2 / Opus F3):
    # OSError siblings of FileNotFoundError (here: IsADirectoryError
    # from pointing diff_path at a directory) must surface under
    # errors[] without crashing the process.
    a_directory = tmp_path / "i-am-a-directory"
    a_directory.mkdir()
    batch = tmp_path / "batch.jsonl"
    _write_batch(batch, [{"op": "parse-diff-markers", "id": "bad-path", "diff_path": str(a_directory)}])
    out = _invoke_cli(["findings:apply-batch", "--batch-path", str(batch)], capsys)
    payload = json.loads(out)
    assert payload["results"] == {}
    assert payload["errors"][0]["id"] == "bad-path"
    assert payload["errors"][0]["op"] == "parse-diff-markers"
