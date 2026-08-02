"""Lint reviewer prompt templates for invariant-block drift.

Reads the canonical invariant blocks from
``.claude/prompts/reviewer/_invariants.md`` and asserts byte-identical
copies in each reviewer template
(``.claude/prompts/reviewer/<type>.md`` for
``type in {diff, plan, spec, epic, spec-req-verification}``).

Also verifies the ``.codex/config.toml`` ``[profiles.reviewer.instructions]``
section contains zero numbered criteria — the 10-point criteria now
live only in the committed templates.

Exit codes:

* 0 — all invariant blocks match canonical, no stale criteria in TOML.
* 1 — one or more templates have drift, are missing an invariant
  block, or the TOML contains numbered criteria.

Run via the task wrapper (``task run:adhoc -- scripts/lint_reviewer_templates.py``)
or directly from CI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import defopt

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
INVARIANTS_PATH: Path = REPO_ROOT / ".claude" / "prompts" / "reviewer" / "_invariants.md"
TEMPLATES_DIR: Path = REPO_ROOT / ".claude" / "prompts" / "reviewer"
# Both the canonical dev-host config AND the container-bundled source are
# checked — `docker/agent-cli/codex-config.toml` is COPYed into
# `/home/agent/.codex/config.toml` during the agent-cli image build and is
# also consumed by `scripts/setup_codex_reviewer.sh` when provisioning a
# developer's host `~/.codex/config.toml`. If either drifts back to
# numbered criteria, container reviews and newly-provisioned host reviews
# would silently run stale duplicated instructions.
TOML_PATHS: tuple[Path, ...] = (
    REPO_ROOT / ".codex" / "config.toml",
    REPO_ROOT / "docker" / "agent-cli" / "codex-config.toml",
)


def _discover_template_names() -> tuple[str, ...]:
    """Enumerate committed reviewer templates under ``TEMPLATES_DIR``.

    Returns a sorted tuple of filename stems for every ``*.md`` file
    whose name does not begin with an underscore. The underscore prefix
    denotes shared/private files (e.g., ``_invariants.md``) that are
    not addressable as a ``REVIEW_TYPE``.

    Auto-discovery (TODO-0103) prevents the lint script from silently
    skipping a newly-added template whose stem was never added to a
    hardcoded list. The two other sync points — the ``REVIEW_TYPES``
    shell array in ``scripts/agent-cli/_review-common.sh`` and the
    ``TEMPLATE_NAMES`` tuple in ``tests/scripts/test_reviewer_templates.py``
    — remain hardcoded; the test tuple is cross-checked against this
    discovery (order-insensitive) by the test suite so drift surfaces
    as a failing assertion rather than a silently-unlinted file.

    Raises ``FileNotFoundError`` if ``TEMPLATES_DIR`` does not exist
    or contains zero non-underscore templates. Pre-TODO-0103 the
    hardcoded 5-tuple would have flagged each missing template as
    ``template missing: <path>`` at check-time; the explicit raise
    here restores that "configuration failure fails loudly" contract
    at module-load time for the auto-discovery path.
    """
    if not TEMPLATES_DIR.is_dir():
        raise FileNotFoundError(
            f"reviewer templates directory missing: {TEMPLATES_DIR}",
        )
    discovered = tuple(
        sorted(path.stem for path in TEMPLATES_DIR.glob("*.md") if not path.stem.startswith("_")),
    )
    if not discovered:
        raise FileNotFoundError(
            f"no reviewer templates found under {TEMPLATES_DIR} (looking for *.md files not prefixed with _)",
        )
    return discovered


TEMPLATE_NAMES: tuple[str, ...] = _discover_template_names()

INVARIANT_BLOCK_NAMES: tuple[str, ...] = (
    "preamble",
    "criteria",
    "adversarial-rigor",
)


def _normalize_block(body: str) -> str:
    """Normalize a delimited block body for byte-for-byte comparison.

    Strips trailing whitespace per line; collapses to a single trailing
    newline. Leading/trailing blank lines are preserved otherwise so
    that intentional blank lines inside blocks are not erased.
    """
    lines = body.splitlines()
    stripped = [ln.rstrip() for ln in lines]
    # Drop leading/trailing blank lines so a template with one blank
    # line between delimiters and content matches a canonical with none.
    while stripped and stripped[0] == "":
        stripped.pop(0)
    while stripped and stripped[-1] == "":
        stripped.pop()
    return "\n".join(stripped) + "\n"


def _extract_block(text: str, name: str) -> str | None:
    """Extract the body between ``<!-- INVARIANT:<name> start -->`` and
    ``<!-- INVARIANT:<name> end -->`` delimiters.

    Returns the normalized block body, or ``None`` if either delimiter
    is missing. Returns ``None`` (not an empty string) when the block
    is absent so callers can distinguish missing from empty.
    """
    start_marker = f"<!-- INVARIANT:{name} start -->"
    end_marker = f"<!-- INVARIANT:{name} end -->"
    pattern = re.compile(
        re.escape(start_marker) + r"(.*?)" + re.escape(end_marker),
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return None
    return _normalize_block(match.group(1))


def _load_canonical_blocks() -> dict[str, str]:
    """Load the canonical invariant blocks from ``_invariants.md``.

    Raises ``SystemExit(1)`` if the canonical file is missing or if any
    required block is absent.
    """
    if not INVARIANTS_PATH.is_file():
        print(
            f"lint-reviewer: canonical invariants file not found: {INVARIANTS_PATH}",
            file=sys.stderr,
        )
        sys.exit(1)
    text = INVARIANTS_PATH.read_text()
    canonical: dict[str, str] = {}
    for name in INVARIANT_BLOCK_NAMES:
        body = _extract_block(text, name)
        if body is None:
            print(
                f"lint-reviewer: canonical block '{name}' missing from {INVARIANTS_PATH}",
                file=sys.stderr,
            )
            sys.exit(1)
        canonical[name] = body
    return canonical


def _check_template(
    template_name: str,
    canonical: dict[str, str],
) -> list[str]:
    """Diff each canonical invariant block against the template copy.

    Returns a list of human-readable error messages (empty on match).
    """
    path = TEMPLATES_DIR / f"{template_name}.md"
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"template missing: {path}")
        return errors
    text = path.read_text()
    for block_name, canonical_body in canonical.items():
        actual = _extract_block(text, block_name)
        if actual is None:
            errors.append(
                f"{path}: missing INVARIANT:{block_name} block",
            )
            continue
        if actual != canonical_body:
            first_diff = _first_diff_line(canonical_body, actual)
            errors.append(
                f"{path}: INVARIANT:{block_name} drifted from canonical (first diff: {first_diff!r})",
            )
    return errors


def _first_diff_line(expected: str, actual: str) -> str:
    """Return a short description of the first diverging line."""
    e_lines = expected.splitlines()
    a_lines = actual.splitlines()
    for i, (e_line, a_line) in enumerate(zip(e_lines, a_lines), start=1):
        if e_line != a_line:
            return f"line {i}: expected {e_line!r} got {a_line!r}"
    if len(e_lines) != len(a_lines):
        return f"length mismatch: expected {len(e_lines)} lines, got {len(a_lines)} lines"
    return "identical (normalization disagreement)"


def _check_codex_toml_file(toml_path: Path) -> list[str]:
    """Assert one Codex TOML file has no stale numbered criteria.

    Either the ``[profiles.reviewer.instructions]`` section is absent
    entirely, or its body contains zero numbered list entries and zero
    criteria keyword substrings. The 10-point criteria must live only
    in the templates.
    """
    errors: list[str] = []
    if not toml_path.is_file():
        return errors
    text = toml_path.read_text()
    section_re = re.compile(
        r"^\[profiles\.reviewer\.instructions\]\s*$(.*?)(?=^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = section_re.search(text)
    if match is None:
        return errors
    section_body = match.group(1)
    numbered_line_re = re.compile(r"^\s*\d+\.\s", re.MULTILINE)
    if numbered_line_re.search(section_body):
        errors.append(
            f"{toml_path}: [profiles.reviewer.instructions] contains "
            "numbered criteria — criteria live in "
            ".claude/prompts/reviewer/_invariants.md only. See the "
            "pointer comment in config.toml.",
        )
    keyword_re = re.compile(r"owasp|credential leak|boy scout", re.IGNORECASE)
    if keyword_re.search(section_body):
        errors.append(
            f"{toml_path}: [profiles.reviewer.instructions] contains "
            "criteria keyword (OWASP / credential leak / Boy Scout) "
            "— criteria must not be duplicated here.",
        )
    return errors


def _check_codex_toml() -> list[str]:
    """Assert both tracked Codex TOML files have no stale numbered criteria."""
    errors: list[str] = []
    for toml_path in TOML_PATHS:
        errors.extend(_check_codex_toml_file(toml_path))
    return errors


def check_reviewer_templates() -> int:
    """Run all invariant and TOML checks; return process exit code."""
    canonical = _load_canonical_blocks()
    all_errors: list[str] = []
    for template_name in TEMPLATE_NAMES:
        all_errors.extend(_check_template(template_name, canonical))
    all_errors.extend(_check_codex_toml())
    if all_errors:
        for err in all_errors:
            print(f"lint-reviewer: {err}", file=sys.stderr)
        return 1
    print("lint-reviewer: all invariant blocks match canonical; TOML clean.")
    return 0


def main(*, fix_trailing_whitespace: bool = False) -> None:
    """CLI entry point.

    :param fix_trailing_whitespace: Reserved for future use — currently
        the lint is check-only. Present in the signature so future
        autofix support can land without breaking the CLI contract.
    """
    # fix_trailing_whitespace is structural placeholder — not implemented.
    del fix_trailing_whitespace
    sys.exit(check_reviewer_templates())


if __name__ == "__main__":
    defopt.run(main)
