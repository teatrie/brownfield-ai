"""Tests for tests/helpers/wrapper_sources.py.

Each case writes a throwaway shell source under ``tmp_path`` and holds the
scan's output against it, so the rules the scan applies — comment stripping,
``${VAR}`` substitution, the ``$$`` of a PID-scoped name, the ``tmp/`` prefix
rule, and the union across sources — are pinned independently of any real
wrapper's current spelling.
"""

from __future__ import annotations

from pathlib import Path

from helpers.wrapper_sources import wrapper_tmp_paths


class TestWrapperTmpPaths:
    """Cover the source scan a wrapper suite holds its watch set against."""

    def _write_script(self, tmp_path: Path, body: str, *, name: str = "fake-review.sh") -> Path:
        """Write ``body`` to a throwaway shell source and return its path."""
        script = tmp_path / name
        script.write_text(body)
        return script

    def test_literal_and_templated_paths_are_named(self, tmp_path: Path) -> None:
        script = self._write_script(
            tmp_path,
            'OUTPUT_FILE="tmp/codex-review-output-${ROUND}.md"\n'
            "rm -f tmp/codex-exit.json\n"
            'out="${top}/tmp/${reviewer}-subject-sanitized-${suffix}.txt"\n',
        )
        named = wrapper_tmp_paths([script], {"ROUND": "7", "suffix": "7", "reviewer": "codex"})
        assert named == {
            "codex-review-output-7.md",
            "codex-exit.json",
            "codex-subject-sanitized-7.txt",
        }

    def test_comment_lines_and_bare_mentions_are_skipped(self, tmp_path: Path) -> None:
        script = self._write_script(
            tmp_path,
            "# Output written to tmp/codex-review-output-<ROUND>.md.\n"
            "  # Signals written to tmp/codex-exit.json.\n"
            'echo "FATAL: tmp/ is not writable" >&2\n'
            "mkdir -p tmp\n"
            'tmp_real=$(_review_realpath "$PWD/tmp")\n',
        )
        assert wrapper_tmp_paths([script], {}) == set()

    def test_a_pid_scoped_name_is_named_verbatim(self, tmp_path: Path) -> None:
        script = self._write_script(tmp_path, 'WRITE_PROBE="tmp/.codex-write-probe.$$"\n')
        assert wrapper_tmp_paths([script], {}) == {".codex-write-probe.$$"}

    def test_a_default_inside_a_parameter_expansion_is_named(self, tmp_path: Path) -> None:
        script = self._write_script(tmp_path, 'rm -f "${PREFLIGHT_CACHE_FILE:-tmp/.codex-preflight-cache.json}"\n')
        assert wrapper_tmp_paths([script], {}) == {".codex-preflight-cache.json"}

    def test_an_unsubstituted_variable_stays_literal(self, tmp_path: Path) -> None:
        # An uncovered placeholder must surface as an unwatched entry, never
        # collapse into a name that happens to match a watched one.
        script = self._write_script(tmp_path, 'OUTPUT_FILE="tmp/codex-review-output-${ROUND}.md"\n')
        assert wrapper_tmp_paths([script], {}) == {"codex-review-output-${ROUND}.md"}

    def test_an_unrelated_directory_suffix_is_not_named(self, tmp_path: Path) -> None:
        script = self._write_script(tmp_path, "cp mytmp/report.md other/\n")
        assert wrapper_tmp_paths([script], {}) == set()

    def test_every_source_contributes_to_the_named_set(self, tmp_path: Path) -> None:
        # The real scan pairs a wrapper with a shared _review-common.sh that
        # names one path, so a scan stopping at the first source drops it.
        wrapper = self._write_script(tmp_path, "rm -f tmp/codex-exit.json\n", name="fake-review.sh")
        common = self._write_script(
            tmp_path,
            'out="tmp/${reviewer}-subject-sanitized-${suffix}.txt"\n',
            name="fake-review-common.sh",
        )
        named = wrapper_tmp_paths([wrapper, common], {"reviewer": "codex", "suffix": "7"})
        assert named == {"codex-exit.json", "codex-subject-sanitized-7.txt"}
