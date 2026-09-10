"""Unit tests for scripts/verify_writing_style.py.

Covers:
  - LOCAL_ROOT — resolves to the repository root from scripts/, so the
    two tracked copies are reachable.
  - extract_block() — the heading-through-guard-terminator slice, and its
    three failure modes (no heading, no guard comment, unterminated guard).
  - find_guard_end() — the terminator scan that closes that slice.
  - normalize() — the two sanctioned differences it erases, and the
    protocol-side branch that leaves the rule pointer alone.
  - compare_blocks() — raises rather than exiting, and names the paths it
    was handed rather than the module constants.
  - main() — the translation of a divergence into exit code 1, each
    divergence the checker is meant to catch, and the translation of an
    extraction failure, an unreadable copy, or a copy that is not valid
    UTF-8 into the same FAIL line rather than a traceback.
  - defopt.run(main) — the shipped entry point.

The divergence tests repoint LOCAL_ROOT at a tmp_path fixture tree so a
failing pair can be constructed without touching the tracked copies.

One case stands apart from those. test_main_passes_against_the_tracked_copies
runs the checker against the real files, so it is a smoke test rather than a
mutation-catching one: it reports that the tree is consistent as it stands and
that the compared slice still spans at least TRACKED_BLOCK_FLOOR lines, but a
comparison bug that accepted everything would pass it. Read it as a check on
the tracked copies, not on the logic; the constructed pairs check the logic.
"""

from __future__ import annotations

from pathlib import Path

import defopt
import pytest

from scripts.verify_writing_style import (
    GUARD_END,
    GUARD_START,
    HEADING,
    LEAD_ONLY_IN_PROTOCOL,
    LOCAL_ROOT,
    POINTER_PROTOCOL,
    POINTER_RULE,
    PROTOCOL,
    RULE,
    BlockDivergence,
    compare_blocks,
    extract_block,
    find_guard_end,
    main,
    normalize,
)

SHARED_LINE = "- **No fluff adjectives** — state the change."
GUARD_LINE = f"{GUARD_START} of this block exist {GUARD_END}"

#: Lower bound on the compared slice, which spans 44 lines in the tracked
#: copies. Only the guard comment terminates that slice, and nothing anchors the
#: guard to the end of its section, so hoisting the guard — a plausible "put the
#: note at the top" edit — shortens the compared region while the checker still
#: reports PASS on whatever is left.
#:
#: 33 is the shortest slice a hoisted guard can leave, not the checker's
#: absolute minimum — only the heading, the pointer and the guard are required.
#: The guard-claim checks require the 'above'/'below' pointer to fall inside the
#: slice, and the pointer is line 19 of 44, so the earliest the guard can sit is
#: right after it: 19 lines of prose plus the guard's own 14. Hoisting the guard
#: any higher strands the pointer outside the slice and fails loudly instead.
#:
#: This floor therefore has to clear 33 to catch a hoist, and sits 5 above it.
#: The 6 lines of headroom under today's 44 absorb ordinary churn — three
#: two-line bullets can go before the floor reds, and added bullets never red it.
#: A rewrite that strips more guidance than that should red, and should update
#: this constant deliberately rather than by reflex.
TRACKED_BLOCK_FLOOR = 38


def _write_copy(root: Path, relative: str, body: list[str], *, guard: list[str] | None = None) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Heading above the block", "", HEADING, *body, "", *(guard or [GUARD_LINE]), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── LOCAL_ROOT tests ─────────────────────────────────────────────


def test_local_root_is_the_repository_root() -> None:
    assert LOCAL_ROOT == Path(__file__).resolve().parents[2]


def test_local_root_reaches_both_tracked_copies() -> None:
    assert (LOCAL_ROOT / PROTOCOL).is_file()
    assert (LOCAL_ROOT / RULE).is_file()


# ── extract_block tests ──────────────────────────────────────────


def test_extract_block_returns_the_heading_through_the_guard_terminator(tmp_path: Path) -> None:
    path = _write_copy(tmp_path, "sample.md", ["alpha", "beta"])

    assert extract_block(path) == [HEADING, "alpha", "beta", "", GUARD_LINE]


def test_extract_block_includes_every_line_of_a_multi_line_guard(tmp_path: Path) -> None:
    guard = [f"{GUARD_START} of this block exist:", "     second guard line", f"     third guard line {GUARD_END}"]
    path = _write_copy(tmp_path, "multiline.md", ["alpha"], guard=guard)

    assert extract_block(path) == [HEADING, "alpha", "", *guard]


def test_extract_block_raises_when_the_heading_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "no_heading.md"
    path.write_text("# Some other heading\n\ntext\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        extract_block(path)

    assert f"no {HEADING!r} heading" in str(excinfo.value)


def test_extract_block_raises_when_the_guard_comment_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "no_guard.md"
    path.write_text("\n".join([HEADING, "alpha", ""]), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        extract_block(path)

    assert f"no {GUARD_START!r} guard after the heading" in str(excinfo.value)


def test_extract_block_raises_when_the_guard_comment_is_unterminated(tmp_path: Path) -> None:
    path = tmp_path / "unterminated.md"
    path.write_text("\n".join([HEADING, "alpha", f"{GUARD_START} of this block exist:", "     unclosed"]), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        extract_block(path)

    assert f"guard has no closing {GUARD_END!r}" in str(excinfo.value)


# ── find_guard_end tests ─────────────────────────────────────────


def test_find_guard_end_returns_the_index_of_the_closing_line(tmp_path: Path) -> None:
    lines = [HEADING, f"{GUARD_START} of this block exist:", f"     closed {GUARD_END}", "after"]

    assert find_guard_end(tmp_path / "sample.md", lines, 1) == 2


def test_find_guard_end_raises_when_no_line_closes_the_comment(tmp_path: Path) -> None:
    lines = [HEADING, f"{GUARD_START} of this block exist:", "     unclosed"]

    with pytest.raises(ValueError) as excinfo:
        find_guard_end(tmp_path / "sample.md", lines, 1)

    assert f"guard has no closing {GUARD_END!r}" in str(excinfo.value)


# ── normalize tests ──────────────────────────────────────────────


def test_normalize_strips_the_lead_sentence_carried_only_by_the_protocol() -> None:
    assert normalize([*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE], is_protocol=True) == [SHARED_LINE]


def test_normalize_maps_the_rule_pointer_onto_the_protocol_pointer() -> None:
    assert normalize([SHARED_LINE, POINTER_RULE], is_protocol=False) == [SHARED_LINE, POINTER_PROTOCOL]


def test_normalize_leaves_the_rule_pointer_alone_in_a_protocol_block() -> None:
    assert normalize([SHARED_LINE, POINTER_RULE], is_protocol=True) == [SHARED_LINE, POINTER_RULE]


# ── compare_blocks tests ─────────────────────────────────────────


def test_compare_blocks_returns_the_identical_line_count(tmp_path: Path) -> None:
    protocol = _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    rule = _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])

    assert compare_blocks(protocol, rule) == 5


def test_compare_blocks_raises_instead_of_exiting_the_process(tmp_path: Path) -> None:
    protocol = _write_copy(tmp_path, PROTOCOL, [SHARED_LINE, POINTER_PROTOCOL])
    rule = _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])

    with pytest.raises(BlockDivergence) as excinfo:
        compare_blocks(protocol, rule)

    assert "missing the lead sentence" in str(excinfo.value)


def test_compare_blocks_names_the_paths_it_was_handed(tmp_path: Path) -> None:
    protocol = _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    rule = _write_copy(tmp_path, RULE, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_RULE])

    with pytest.raises(BlockDivergence) as excinfo:
        compare_blocks(protocol, rule)

    assert str(rule) in str(excinfo.value)
    assert str(protocol) in str(excinfo.value)


# ── main tests ───────────────────────────────────────────────────


def test_main_passes_against_the_tracked_copies(capsys: pytest.CaptureFixture[str]) -> None:
    main()

    out = capsys.readouterr().out
    assert out.startswith("PASS: ")
    assert int(out.removeprefix("PASS: ").split()[0]) >= TRACKED_BLOCK_FLOOR


def test_main_passes_when_only_the_sanctioned_differences_are_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    main()

    assert capsys.readouterr().out.startswith("PASS: ")


def test_main_fails_when_the_blocks_diverge_beyond_the_sanctioned_differences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, ["- **No fluff adjectives** — drifted wording.", POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL: blocks diverge beyond the two sanctioned differences" in out
    assert "  positions count lines within the compared block, not within either file" in out
    assert "  position 2\n" in out
    assert "drifted wording" in out


def test_main_reports_a_length_difference_between_the_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, "- An extra bullet.", POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "length differs: 6 vs 5" in capsys.readouterr().out


def test_main_fails_when_the_guard_comment_itself_drifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(
        tmp_path,
        RULE,
        [SHARED_LINE, POINTER_RULE],
        guard=[f"{GUARD_START} of this block exist, reworded inside the guard {GUARD_END}"],
    )
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL: blocks diverge beyond the two sanctioned differences" in out
    assert "reworded inside the guard" in out


def test_main_fails_when_the_protocol_drops_the_lead_sentence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "missing the lead sentence" in capsys.readouterr().out


@pytest.mark.parametrize("dropped", range(len(LEAD_ONLY_IN_PROTOCOL)))
def test_main_fails_when_the_protocol_drops_one_line_of_the_lead_sentence(
    dropped: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    survivors = [line for index, line in enumerate(LEAD_ONLY_IN_PROTOCOL) if index != dropped]
    _write_copy(tmp_path, PROTOCOL, [*survivors, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "missing the lead sentence" in capsys.readouterr().out


def test_main_fails_when_the_rule_carries_the_reserved_lead_sentence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "carries the lead sentence reserved for" in capsys.readouterr().out


@pytest.mark.parametrize("carried", range(len(LEAD_ONLY_IN_PROTOCOL)))
def test_main_fails_when_the_rule_carries_one_line_of_the_reserved_lead_sentence(
    carried: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [LEAD_ONLY_IN_PROTOCOL[carried], SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "carries the lead sentence reserved for" in capsys.readouterr().out


def test_main_fails_when_the_rule_loses_the_below_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_PROTOCOL])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "missing the expected 'below' pointer" in capsys.readouterr().out


def test_main_fails_when_the_protocol_loses_the_above_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE])
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "missing the expected 'above' pointer" in capsys.readouterr().out


def test_main_reports_a_renamed_heading_as_a_failure_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    renamed = tmp_path / PROTOCOL
    renamed.parent.mkdir(parents=True, exist_ok=True)
    renamed.write_text("## Writing Style\n\nalpha\n", encoding="utf-8")
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL: ")
    assert f"no {HEADING!r} heading" in out


def test_main_reports_a_missing_guard_comment_as_a_failure_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    unguarded = tmp_path / RULE
    unguarded.parent.mkdir(parents=True, exist_ok=True)
    unguarded.write_text("\n".join([HEADING, SHARED_LINE, POINTER_RULE, ""]), encoding="utf-8")
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL: ")
    assert f"no {GUARD_START!r} guard after the heading" in out


def test_main_reports_an_unterminated_guard_comment_as_a_failure_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(
        tmp_path,
        PROTOCOL,
        [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL],
        guard=[f"{GUARD_START} of this block exist:"],
    )
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL: ")
    assert f"guard has no closing {GUARD_END!r}" in out


def test_main_reports_a_missing_copy_as_a_failure_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL: ")
    assert PROTOCOL in out


def test_main_reports_a_non_utf8_copy_as_a_failure_line_naming_the_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    undecodable = tmp_path / PROTOCOL
    undecodable.parent.mkdir(parents=True, exist_ok=True)
    undecodable.write_bytes(b"\xff\xfe\x00\x01")
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL: ")
    assert str(undecodable) in out


# ── defopt entry point tests ─────────────────────────────────────


def test_defopt_run_passes_on_a_sanctioned_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, [SHARED_LINE, POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    defopt.run(main, argv=[])

    assert capsys.readouterr().out.startswith("PASS: ")


def test_defopt_run_exits_non_zero_on_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_copy(tmp_path, PROTOCOL, [*LEAD_ONLY_IN_PROTOCOL, SHARED_LINE, POINTER_PROTOCOL])
    _write_copy(tmp_path, RULE, ["- **No fluff adjectives** — drifted wording.", POINTER_RULE])
    monkeypatch.setattr("scripts.verify_writing_style.LOCAL_ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        defopt.run(main, argv=[])

    assert excinfo.value.code == 1
    assert "FAIL: blocks diverge beyond the two sanctioned differences" in capsys.readouterr().out
