"""Tests for ``scripts/agent-cli/_review-common.sh`` shared helpers.

Verifies:

* ``_review_validate_type`` rejects empty / unknown values and accepts
  each of ``{plan, spec, diff, epic, spec-req-verification}``.
* ``_review_validate_diff_file`` rejects empty paths, missing files,
  zero-size files, and paths outside ``tmp/`` / ``agent-review/``.
* ``_review_sanitize_subject`` strips ANSI escape sequences, null
  bytes, and low control characters.
* ``_review_template_path`` resolves the hardcoded template path under
  ``.claude/prompts/reviewer/``.

The helpers live in a shell file; the tests exercise them by sourcing
the file in a bash subshell and invoking the functions. ``subprocess``
is used because there is no Python-native equivalent for sourcing a
bash file (per CLAUDE.md §11 lang-python rule — acceptable here).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
REVIEW_COMMON: Path = REPO_ROOT / "scripts" / "agent-cli" / "_review-common.sh"


def _bash_eval(
    snippet: str,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Source ``_review-common.sh`` and run a one-shot bash snippet.

    :param snippet: the bash commands to run after sourcing the helper.
    :param cwd: working directory — the helper resolves ``$PWD/tmp``
        and ``$PWD/agent-review``, so CWD matters.
    :param env: optional env overrides merged onto a minimal base.
    """
    base_env: dict[str, str] = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C.UTF-8",
    }
    if env:
        base_env.update(env)
    full = f'. "{REVIEW_COMMON}"\n{snippet}\n'
    return subprocess.run(
        ["bash", "-c", full],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=base_env,
        timeout=15,
    )


def _make_repo_skeleton(root: Path) -> None:
    """Create ``tmp/`` and ``agent-review/`` dirs for realpath resolution."""
    (root / "tmp").mkdir()
    (root / "agent-review").mkdir()


# ---------------------------------------------------------------------------
# 1. _review_validate_type enum
# ---------------------------------------------------------------------------


class TestReviewValidateType:
    """REVIEW_TYPE enum validation."""

    def test_empty_rejected(self, tmp_path: Path) -> None:
        """Empty REVIEW_TYPE returns non-zero with a clear error."""
        _make_repo_skeleton(tmp_path)
        result = _bash_eval(
            "_review_validate_type",
            cwd=tmp_path,
            env={"REVIEW_TYPE": ""},
        )
        assert result.returncode != 0
        assert "REVIEW_TYPE is required" in result.stderr

    def test_unknown_rejected(self, tmp_path: Path) -> None:
        """Unknown REVIEW_TYPE value returns non-zero."""
        _make_repo_skeleton(tmp_path)
        result = _bash_eval(
            "_review_validate_type",
            cwd=tmp_path,
            env={"REVIEW_TYPE": "bogus"},
        )
        assert result.returncode != 0
        assert "not in" in result.stderr

    @pytest.mark.parametrize(
        "value",
        ["plan", "spec", "diff", "epic", "spec-req-verification"],
    )
    def test_each_valid_accepted(self, tmp_path: Path, value: str) -> None:
        """Each canonical value passes validation."""
        _make_repo_skeleton(tmp_path)
        result = _bash_eval(
            "_review_validate_type",
            cwd=tmp_path,
            env={"REVIEW_TYPE": value},
        )
        assert result.returncode == 0, f"REVIEW_TYPE={value!r} rejected: stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# 2/3. _review_validate_diff_file containment
# ---------------------------------------------------------------------------


class TestReviewValidateDiffFile:
    """DIFF_FILE containment, existence, and non-empty checks."""

    def test_empty_path_rejected(self, tmp_path: Path) -> None:
        """Empty DIFF_FILE returns non-zero."""
        _make_repo_skeleton(tmp_path)
        result = _bash_eval(
            "_review_validate_diff_file",
            cwd=tmp_path,
            env={"DIFF_FILE": ""},
        )
        assert result.returncode != 0
        assert "DIFF_FILE is required" in result.stderr

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        """Non-existent path returns non-zero."""
        _make_repo_skeleton(tmp_path)
        result = _bash_eval(
            "_review_validate_diff_file",
            cwd=tmp_path,
            env={"DIFF_FILE": "tmp/does-not-exist.txt"},
        )
        assert result.returncode != 0

    def test_zero_size_file_rejected(self, tmp_path: Path) -> None:
        """Zero-size file returns non-zero."""
        _make_repo_skeleton(tmp_path)
        (tmp_path / "tmp" / "empty.txt").touch()
        result = _bash_eval(
            "_review_validate_diff_file",
            cwd=tmp_path,
            env={"DIFF_FILE": "tmp/empty.txt"},
        )
        assert result.returncode != 0

    def test_valid_tmp_file_accepted(self, tmp_path: Path) -> None:
        """A non-empty file under ``tmp/`` passes validation."""
        _make_repo_skeleton(tmp_path)
        (tmp_path / "tmp" / "subject.txt").write_text("diff content\n")
        result = _bash_eval(
            "_review_validate_diff_file",
            cwd=tmp_path,
            env={"DIFF_FILE": "tmp/subject.txt"},
        )
        assert result.returncode == 0, f"valid tmp/ file rejected: stderr={result.stderr!r}"

    def test_valid_agent_review_file_accepted(self, tmp_path: Path) -> None:
        """A non-empty file under ``agent-review/`` passes validation."""
        _make_repo_skeleton(tmp_path)
        (tmp_path / "agent-review" / "sub.txt").write_text("data\n")
        result = _bash_eval(
            "_review_validate_diff_file",
            cwd=tmp_path,
            env={"DIFF_FILE": "agent-review/sub.txt"},
        )
        assert result.returncode == 0

    def test_path_outside_workspace_rejected(self, tmp_path: Path) -> None:
        """A path resolving outside ``tmp/`` / ``agent-review/`` is rejected.

        We create a file in the test ``tmp_path`` root (a sibling of
        ``tmp/``), then point ``DIFF_FILE`` at it. The helper's realpath
        containment check should reject it.
        """
        _make_repo_skeleton(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("evil\n")
        result = _bash_eval(
            "_review_validate_diff_file",
            cwd=tmp_path,
            env={"DIFF_FILE": str(outside)},
        )
        assert result.returncode != 0
        assert "must resolve under" in result.stderr

    def test_absolute_path_rejected_when_agent_review_missing(
        self,
        tmp_path: Path,
    ) -> None:
        """Regression for codex r1 P1-a / gemini r1 F-n/a:

        When ``agent-review/`` does not exist in the CWD,
        ``_review_realpath "$PWD/agent-review"`` returns an empty
        string on at least macOS (BSD realpath). An empty ``ar_real``
        used in the case arm ``"${ar_real}"/*`` would degrade to
        ``/*`` — matching ANY absolute path and defeating the
        containment guard. The helper must substitute a sentinel so
        absolute outside-root paths are still rejected.
        """
        # Create tmp/ but NOT agent-review/ in the fake workspace root.
        (tmp_path / "tmp").mkdir()
        assert not (tmp_path / "agent-review").exists(), "test fixture precondition violated: agent-review/ should be absent"
        # Use pytest's separate tmp_path_factory-like fixture via an
        # additional location outside the fake workspace. tmp_path itself
        # is a leaf directory, so use a sibling via a scratch subdir.
        escape_dir = tmp_path.parent / "escape-fixture"
        escape_dir.mkdir(exist_ok=True)
        escape_target = escape_dir / "absolute-escape.txt"
        escape_target.write_text("gotcha\n")
        assert escape_target.is_absolute()
        result = _bash_eval(
            "_review_validate_diff_file",
            cwd=tmp_path,
            env={"DIFF_FILE": str(escape_target)},
        )
        assert result.returncode != 0, (
            f"absolute path outside tmp/ must be rejected even when agent-review/ is absent; stderr={result.stderr!r}"
        )
        assert "tmp/" in result.stderr, f"error message must mention tmp/ containment; got {result.stderr!r}"


# ---------------------------------------------------------------------------
# 4. _review_sanitize_subject strips ANSI / null / control chars.
# ---------------------------------------------------------------------------


def test_sanitize_subject_strips_ansi_and_controls(tmp_path: Path) -> None:
    """ANSI escapes, null bytes, and \\x01..\\x08 control chars are stripped.

    Also verifies the portable ``tr | sed`` implementation (B2 fix) runs
    cleanly on whichever host the test is executing on — this test runs
    in the pytest-cli (Linux) container in CI, but exercises the same
    bytes on a macOS dev host via the legacy / pre-fix code would have
    aborted with a BSD-sed range error. Post-fix, the command must
    succeed on both toolchains.
    """
    _make_repo_skeleton(tmp_path)
    # ANSI red + reset, null byte, control chars interleaved with text.
    raw = b"\x1b[31mred\x1b[0m normal text\nnull\x00byte and \x01\x02\x03\x04\x05\x06\x07\x08 control\n"
    subject = tmp_path / "tmp" / "dirty-subject.txt"
    subject.write_bytes(raw)
    result = _bash_eval(
        'out=$(_review_sanitize_subject gemini r1)\necho "SANITIZED_PATH=${out}"\ncat "${out}"\n',
        cwd=tmp_path,
        env={"DIFF_FILE": "tmp/dirty-subject.txt"},
    )
    assert result.returncode == 0, f"sanitize failed: stderr={result.stderr!r}"
    assert "SANITIZED_PATH=tmp/gemini-subject-sanitized-r1.txt" in result.stdout
    sanitized = (tmp_path / "tmp" / "gemini-subject-sanitized-r1.txt").read_bytes()
    assert b"\x1b" not in sanitized
    assert b"\x00" not in sanitized
    for byte in range(0x01, 0x09):
        assert bytes([byte]) not in sanitized, f"control byte 0x{byte:02x} survived sanitization"
    # Full ANSI CSI sequence stripped — bracket, params, and terminator gone.
    # (Regression guard against pipe-order bug where `tr` eats ESC before
    # `sed` matches the CSI pattern, leaving `[31m` bracket residue.)
    assert b"[31m" not in sanitized
    assert b"[0m" not in sanitized
    # Text content preserved.
    assert b"red" in sanitized
    assert b"normal text" in sanitized
    assert b"nullbyte" in sanitized  # null removed, adjacent text joined
    assert b"control" in sanitized


def test_sanitize_subject_preserves_tab_lf_cr(tmp_path: Path) -> None:
    """TAB (0x09), LF (0x0a), and CR (0x0d) must pass through unchanged.

    The portable ``tr`` range used by ``_review_sanitize_subject`` strips
    ``\\000-\\010``, ``\\013-\\014``, ``\\016-\\037`` — deliberately
    carving out TAB/LF/CR so multi-line diff subjects and tab-indented
    code blocks survive sanitation. VT (0x0b) and FF (0x0c) are still
    stripped alongside the rest of the C0 block.
    """
    _make_repo_skeleton(tmp_path)
    raw = b"tab\there\ncr\rmiddle\nvt\x0bstripped\nff\x0cstripped\n"
    subject = tmp_path / "tmp" / "byteset.txt"
    subject.write_bytes(raw)
    result = _bash_eval(
        'out=$(_review_sanitize_subject codex r2)\necho "SANITIZED_PATH=${out}"\n',
        cwd=tmp_path,
        env={"DIFF_FILE": "tmp/byteset.txt"},
    )
    assert result.returncode == 0, f"sanitize failed: stderr={result.stderr!r}"
    sanitized = (tmp_path / "tmp" / "codex-subject-sanitized-r2.txt").read_bytes()
    # Preserved bytes.
    assert b"\t" in sanitized, "TAB (0x09) must be preserved"
    assert b"\n" in sanitized, "LF (0x0a) must be preserved"
    assert b"\r" in sanitized, "CR (0x0d) must be preserved"
    assert b"tab\there" in sanitized
    assert b"cr\rmiddle" in sanitized
    # Stripped bytes.
    assert b"\x0b" not in sanitized, "VT (0x0b) must be stripped"
    assert b"\x0c" not in sanitized, "FF (0x0c) must be stripped"
    # Adjacent text survives with the stripped byte removed.
    assert b"vtstripped" in sanitized
    assert b"ffstripped" in sanitized


# ---------------------------------------------------------------------------
# 5. _review_template_path resolves the hardcoded path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "review_type,expected_suffix",
    [
        ("plan", ".claude/prompts/reviewer/plan.md"),
        ("spec", ".claude/prompts/reviewer/spec.md"),
        ("diff", ".claude/prompts/reviewer/diff.md"),
        ("epic", ".claude/prompts/reviewer/epic.md"),
        (
            "spec-req-verification",
            ".claude/prompts/reviewer/spec-req-verification.md",
        ),
    ],
)
def test_template_path_is_hardcoded(
    tmp_path: Path,
    review_type: str,
    expected_suffix: str,
) -> None:
    """``_review_template_path`` resolves to the hardcoded relative path.

    This exercises the non-worktree fallback: ``tmp_path`` on the pytest
    runner is outside any git repository (``/private/var/folders/...`` on
    macOS, ``/tmp/pytest-of-.../...`` on Linux CI), so ``git rev-parse
    --show-toplevel`` fails and the helper returns the CWD-relative path.
    The anchored branch is covered by
    ``test_template_path_is_anchored_to_repo_root_inside_worktree``.
    """
    _make_repo_skeleton(tmp_path)
    result = _bash_eval(
        "_review_template_path",
        cwd=tmp_path,
        env={"REVIEW_TYPE": review_type},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == expected_suffix


@pytest.mark.parametrize(
    "review_type",
    ["plan", "spec", "diff", "epic", "spec-req-verification"],
)
def test_template_path_is_anchored_to_repo_root_inside_worktree(
    tmp_path: Path,
    review_type: str,
) -> None:
    """``_review_template_path`` returns an absolute path when inside a worktree.

    Regression guard for TODO-0094: without the anchoring arm, a caller
    invoking the wrapper from a nested CWD would get a CWD-relative path
    pointing at a non-existent file. This test materializes a real
    (empty) git repo at ``tmp_path``, runs the helper with that CWD,
    and asserts the helper returns the absolute ``${top}/.claude/...``
    form. Without a companion test the anchored branch has zero direct
    coverage on the default test host (pytest ``tmp_path`` is outside
    any git ancestor by construction).
    """
    _make_repo_skeleton(tmp_path)
    init_result = subprocess.run(
        ["git", "init", "-q"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert init_result.returncode == 0, f"git init failed: {init_result.stderr!r}"
    result = _bash_eval(
        "_review_template_path",
        cwd=tmp_path,
        env={"REVIEW_TYPE": review_type},
    )
    assert result.returncode == 0, f"helper failed inside worktree: stderr={result.stderr!r}"
    out = result.stdout.strip()
    assert out.startswith("/"), f"expected absolute path, got {out!r}"
    assert out.endswith(f".claude/prompts/reviewer/{review_type}.md"), (
        f"expected suffix .claude/prompts/reviewer/{review_type}.md, got {out!r}"
    )
    # The prefix must be the realpath of the worktree root.
    tmp_real = Path(tmp_path).resolve()
    assert out == f"{tmp_real}/.claude/prompts/reviewer/{review_type}.md", f"anchored path should be ${{top}}/.claude/...; got {out!r}"


def test_sanitize_subject_returns_absolute_path_inside_worktree(tmp_path: Path) -> None:
    """``_review_sanitize_subject`` echoes an absolute path when anchored.

    Regression guard for the convergent review finding on TODO-0097:
    the helper writes output to ``${top}/tmp/...`` via ``cd`` but MUST
    echo an absolute path, otherwise a caller at a nested CWD would
    write-via-${top}/tmp but read-via-${PWD}/tmp (two different paths).
    """
    _make_repo_skeleton(tmp_path)
    init_result = subprocess.run(
        ["git", "init", "-q"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert init_result.returncode == 0, f"git init failed: {init_result.stderr!r}"
    (tmp_path / "tmp" / "subject.txt").write_bytes(b"content\n")
    result = _bash_eval(
        'out=$(_review_sanitize_subject gemini anchored)\necho "SANITIZED_PATH=${out}"\n',
        cwd=tmp_path,
        env={"DIFF_FILE": "tmp/subject.txt"},
    )
    assert result.returncode == 0, f"sanitize failed: stderr={result.stderr!r}"
    tmp_real = Path(tmp_path).resolve()
    expected = f"SANITIZED_PATH={tmp_real}/tmp/gemini-subject-sanitized-anchored.txt"
    assert expected in result.stdout, f"expected absolute echoed path; got stdout={result.stdout!r}"
    # And the file actually exists at that absolute path.
    written = tmp_real / "tmp" / "gemini-subject-sanitized-anchored.txt"
    assert written.is_file(), f"sanitized file missing at {written}"
