"""Lint reviewer prompt templates for invariant-block drift.

Reads the canonical invariant blocks from
``.claude/prompts/reviewer/_invariants.md`` and asserts byte-identical
copies in each reviewer template
(``.claude/prompts/reviewer/<type>.md`` for
``type in {diff, plan, spec, epic, spec-req-verification}``).

Also verifies that the ``[profiles.reviewer.instructions]`` section of
both reviewer TOMLs — ``.codex/config.toml`` and
``docker/agent-cli/codex-config.toml`` — contains zero numbered
criteria; the 10-point criteria live only in the committed templates.

Finally, asserts the ``SHARED:`` blocks carrying the diff-only review
dimensions are identical between ``.claude/skills/diff-review/SKILL.md``
and ``.claude/prompts/reviewer/diff.md``. Those dimensions cannot live in
the shared ``criteria`` invariant (they would leak into the plan, spec, and
epic templates), so they are mirrored instead — and a mirror without a
check drifts. The SKILL.md copy sits inside a Markdown blockquote, so its
``> `` prefix is stripped before comparison.

``--fix`` regenerates the ``diff.md`` mirror instead of checking it,
repairing the drift the check reports. The check alone cannot close the
loop: without a committed generator the mirror has to be hand-written in
lockstep with ``SKILL.md``. Regeneration reads the canonical
``_invariants.md`` and the ``SHARED:`` regions of ``SKILL.md`` — never
``diff.md`` itself — so a drifted mirror cannot seed its own replacement.

The output is written to ``tmp/diff_md_out/diff.md`` rather than in place:
``pytest-cli`` mounts the workspace read-only with ``tmp/`` read-write, so
the container cannot write the template directly. ``task
lint:reviewer-templates-fix`` runs this and then copies the result into
position on the host, keeping the container write surface unchanged.

Exit codes:

* 0 — all invariant blocks match canonical, shared blocks match, no
  stale criteria in TOML. Under ``--fix``: the mirror was regenerated.
* 1 — one or more templates have drift, are missing an invariant or
  shared block, or the TOML contains numbered criteria. Under ``--fix``:
  a source file was missing or lacked a required block.

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
# Both TOMLs are checked, but they differ in reach. `.codex/config.toml` is
# project-local, which codex loads nothing from: criteria drifting back in
# there reach no run, so it is a drift surface only. The agent-cli TOML is the
# user-level config that IS loaded, so drift there would silently run stale
# duplicated instructions on container and newly-provisioned host reviews.
# See docs/effort_tiers.md §"Where the Codex Effort Value Comes From".
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

#: Blocks mirrored between the diff-review skill and the diff template.
SHARED_BLOCK_NAMES: tuple[str, ...] = (
    "diff-scope",
    "diff-dimensions",
)
SKILL_PATH: Path = REPO_ROOT / ".claude" / "skills" / "diff-review" / "SKILL.md"
SHARED_TEMPLATE_PATH: Path = TEMPLATES_DIR / "diff.md"

#: Destination for ``--fix`` output. Under ``tmp/`` because the container
#: running this script mounts the workspace read-only.
FIX_OUTPUT_PATH: Path = REPO_ROOT / "tmp" / "diff_md_out" / "diff.md"

#: Scaffolding that belongs to neither an INVARIANT nor a SHARED region.
#: It is diff-template-specific prose with no second copy to drift against,
#: so regeneration carries it literally.
SUBJECT_HANDLING: str = """## Subject handling

The subject is a unified `git diff` — review only the changed lines + necessary \
surrounding context; do not re-review untouched code, except per the Bounded \
exception below."""

RUBRIC_NOTE: str = """Criteria 1-10 below are the block shared with every reviewer template; \
11-21 are diff-only. They form one continuous rubric — the delimiters are indented \
into the adjacent list items so the numbering is not broken."""


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


def _extract_raw(text: str, name: str, *, namespace: str) -> str | None:
    """Extract the un-normalized body between a ``<!-- <namespace>:<name> ... -->`` pair.

    Returns ``None`` (not an empty string) when either delimiter is
    missing, so callers can distinguish absent from empty.
    """
    start_marker = f"<!-- {namespace}:{name} start -->"
    end_marker = f"<!-- {namespace}:{name} end -->"
    pattern = re.compile(
        re.escape(start_marker) + r"(.*?)" + re.escape(end_marker),
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return None
    return match.group(1)


def _duplicate_marker_error(
    text: str,
    name: str,
    *,
    namespace: str,
    source: Path,
) -> str | None:
    """Return an error message when a marker pair occurs more than once.

    Extraction stops at the first match, so a second ``start``/``end``
    pair would carry unchecked prompt content — divergent or even
    contradictory instructions that still lint clean. Both copies are fed
    to reviewers verbatim, so exactly one pair per block is required.
    """
    for suffix in ("start", "end"):
        marker = f"<!-- {namespace}:{name} {suffix} -->"
        count = text.count(marker)
        if count > 1:
            return (
                f"{source}: {namespace}:{name} {suffix} delimiter appears {count} times "
                "— exactly one pair is required, else only the first block is checked"
            )
    return None


def _blockquote_prefix_error(body: str, name: str, *, source: Path) -> str | None:
    """Return an error when a shared-block line has escaped the blockquote.

    ``_strip_blockquote`` passes an unprefixed line through unchanged, so a
    line that loses its ``> `` would still compare equal to the template
    copy and lint clean — while in Markdown the reviewer prompt blockquote
    has ended there and the instruction is no longer delivered as part of
    the prompt. Treat that as a lint error rather than normalizing it away.
    """
    # Drop exactly the two artifact lines the capture contributes — the
    # empty remainder of the start delimiter's own line, and the indentation
    # preceding the end delimiter — then hold every remaining line strictly.
    # Skipping all blank lines (or stripping all boundary newlines) would
    # defeat the check: an empty, un-prefixed line terminates a blockquote
    # in CommonMark, and it survives stripping identically in both copies,
    # so the parity comparison cannot see it either.
    lines = body.splitlines()
    if lines and lines[0] == "":
        lines.pop(0)
    # Drop the end delimiter's indentation ONLY when it is genuinely quoted.
    # Popping unconditionally would discard an escaped final instruction
    # whenever the closing delimiter also lost its prefix, letting both
    # errors through together.
    if lines and (lines[-1].startswith("> ") or lines[-1] == ">"):
        lines.pop()
    for number, line in enumerate(lines, start=1):
        if line.startswith("> ") or line == ">":
            continue
        return (
            f"{source}: SHARED:{name} line {number} lost its '> ' blockquote prefix ({line!r}) — the reviewer prompt blockquote ends there"
        )
    return None


def _strip_blockquote(body: str) -> str:
    """Remove one level of Markdown blockquote prefix from every line.

    The SKILL.md copy of each shared block lives inside the reviewer
    prompt blockquote; the template copy does not. Stripping ``> ``
    (and a bare ``>`` for blank lines) is what makes the two comparable.
    """
    lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("> "):
            lines.append(line[2:])
        elif line == ">":
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines)


def _extract_block(text: str, name: str) -> str | None:
    """Extract and normalize an ``INVARIANT:<name>`` block body."""
    raw = _extract_raw(text, name, namespace="INVARIANT")
    if raw is None:
        return None
    return _normalize_block(raw)


def _extract_shared(text: str, name: str, *, blockquote: bool) -> str | None:
    """Extract and normalize a ``SHARED:<name>`` block body.

    :param blockquote: Strip one blockquote level before normalizing,
        for the SKILL.md copy that carries a ``> `` prefix.
    """
    raw = _extract_raw(text, name, namespace="SHARED")
    if raw is None:
        return None
    return _normalize_block(_strip_blockquote(raw) if blockquote else raw)


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
        # The source of truth needs the same exactly-one-pair guarantee as
        # the templates: extraction takes the first match, so a second
        # contradictory block here would let every template lint clean
        # against a copy no one intended to be canonical.
        duplicate = _duplicate_marker_error(text, name, namespace="INVARIANT", source=INVARIANTS_PATH)
        if duplicate is not None:
            print(f"lint-reviewer: {duplicate}", file=sys.stderr)
            sys.exit(1)
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
        duplicate = _duplicate_marker_error(text, block_name, namespace="INVARIANT", source=path)
        if duplicate is not None:
            errors.append(duplicate)
            continue
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


def _skill_shared_errors(skill_text: str) -> dict[str, str]:
    """Return the first SKILL.md-side defect per shared block, keyed by name.

    Both the check path and the ``--fix`` path gate on this. Sharing one
    validator is the point rather than an incidental tidy-up: a malformed
    source that only the checker rejects would let ``--fix`` render from it,
    report success, and copy a template the checker then refuses — the
    repair command leaving the tree in the state it claims to have fixed.
    """
    errors: dict[str, str] = {}
    for name in SHARED_BLOCK_NAMES:
        duplicate = _duplicate_marker_error(skill_text, name, namespace="SHARED", source=SKILL_PATH)
        if duplicate is not None:
            errors[name] = duplicate
            continue
        raw = _extract_raw(skill_text, name, namespace="SHARED")
        if raw is None:
            errors[name] = f"{SKILL_PATH}: missing SHARED:{name} block"
            continue
        prefix_error = _blockquote_prefix_error(raw, name, source=SKILL_PATH)
        if prefix_error is not None:
            errors[name] = prefix_error
    return errors


def _check_shared_blocks() -> list[str]:
    """Assert each shared block matches between SKILL.md and the diff template.

    Returns a list of human-readable error messages (empty on match).
    """
    errors: list[str] = []
    for path in (SKILL_PATH, SHARED_TEMPLATE_PATH):
        if not path.is_file():
            errors.append(f"shared-block source missing: {path}")
    if errors:
        return errors
    skill_text = SKILL_PATH.read_text()
    template_text = SHARED_TEMPLATE_PATH.read_text()
    skill_errors = _skill_shared_errors(skill_text)
    for name in SHARED_BLOCK_NAMES:
        template_duplicate = _duplicate_marker_error(
            template_text,
            name,
            namespace="SHARED",
            source=SHARED_TEMPLATE_PATH,
        )
        skill_error = skill_errors.get(name)
        if skill_error is not None or template_duplicate is not None:
            if skill_error is not None:
                errors.append(skill_error)
            if template_duplicate is not None:
                errors.append(template_duplicate)
            continue
        expected = _extract_shared(skill_text, name, blockquote=True)
        actual = _extract_shared(template_text, name, blockquote=False)
        if expected is None:
            errors.append(f"{SKILL_PATH}: missing SHARED:{name} block")
        if actual is None:
            errors.append(f"{SHARED_TEMPLATE_PATH}: missing SHARED:{name} block")
        if expected is None or actual is None:
            continue
        if expected != actual:
            first_diff = _first_diff_line(expected, actual)
            errors.append(
                f"{SHARED_TEMPLATE_PATH}: SHARED:{name} drifted from {SKILL_PATH.name} (first diff: {first_diff!r})",
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
    all_errors.extend(_check_shared_blocks())
    all_errors.extend(_check_codex_toml())
    if all_errors:
        for err in all_errors:
            print(f"lint-reviewer: {err}", file=sys.stderr)
        return 1
    print(
        "lint-reviewer: all invariant blocks match canonical; shared diff blocks in sync; TOML clean.",
    )
    return 0


def render_diff_template(canonical: dict[str, str], skill_text: str) -> str:
    """Assemble the full ``diff.md`` body from its canonical sources.

    Pure: takes the canonical invariant bodies and the skill text, returns
    the file content. Nothing is read from the existing ``diff.md``, so a
    drifted mirror cannot influence its own regeneration.

    :param canonical: Normalized invariant bodies keyed by block name, as
        returned by ``_load_canonical_blocks``.
    :param skill_text: Full text of the diff-review ``SKILL.md``.
    :raises ValueError: When a ``SHARED:`` region is absent, has a duplicated
        marker pair, or carries a line that escaped the blockquote — the same
        defects the check path rejects, so a malformed source cannot be
        rendered into an apparently-clean template.
    """
    defects = _skill_shared_errors(skill_text)
    if defects:
        msg = "; ".join(defects[name] for name in SHARED_BLOCK_NAMES if name in defects)
        raise ValueError(msg)
    shared: dict[str, str] = {}
    for name in SHARED_BLOCK_NAMES:
        body = _extract_shared(skill_text, name, blockquote=True)
        if body is None:
            msg = f"{SKILL_PATH}: missing SHARED:{name} block"
            raise ValueError(msg)
        shared[name] = body
    scope = shared["diff-scope"]
    dimensions = shared["diff-dimensions"]

    sections: list[str] = []
    sections.append(f"<!-- INVARIANT:preamble start -->\n{canonical['preamble']}<!-- INVARIANT:preamble end -->")
    sections.append(SUBJECT_HANDLING)
    sections.append(f"<!-- SHARED:diff-scope start -->\n{scope}<!-- SHARED:diff-scope end -->")
    sections.append(RUBRIC_NOTE)
    # The criteria end delimiter and the dimensions start delimiter are
    # indented into item 10's content so items 1-10 and 11-21 stay one
    # ordered list; a delimiter at column 0 restarts numbering at "11.",
    # which markdownlint MD029 rejects. Delimiter indentation sits outside
    # the compared block bodies, so the parity checks are unaffected.
    sections.append(
        f"<!-- INVARIANT:criteria start -->\n{canonical['criteria']}"
        "    <!-- INVARIANT:criteria end -->\n\n"
        "    <!-- SHARED:diff-dimensions start -->\n"
        f"{dimensions}\n    <!-- SHARED:diff-dimensions end -->",
    )
    sections.append(
        f"<!-- INVARIANT:adversarial-rigor start -->\n{canonical['adversarial-rigor']}<!-- INVARIANT:adversarial-rigor end -->",
    )
    return "\n\n".join(sections) + "\n"


def regenerate_diff_template() -> int:
    """Write a freshly-rendered ``diff.md`` to ``FIX_OUTPUT_PATH``.

    Returns a process exit code. The caller (``task
    lint:reviewer-templates-fix``) copies the result into position on the
    host, because this process cannot write outside ``tmp/``.
    """
    if not SKILL_PATH.is_file():
        print(f"lint-reviewer: cannot regenerate, missing {SKILL_PATH}", file=sys.stderr)
        return 1
    canonical = _load_canonical_blocks()
    try:
        rendered = render_diff_template(canonical, SKILL_PATH.read_text())
    except ValueError as exc:
        print(f"lint-reviewer: {exc}", file=sys.stderr)
        return 1
    FIX_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIX_OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    changed = not SHARED_TEMPLATE_PATH.is_file() or SHARED_TEMPLATE_PATH.read_text() != rendered
    status = "differs from the committed copy" if changed else "matches the committed copy"
    print(f"lint-reviewer: wrote {FIX_OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(rendered.splitlines())} lines) — {status}.")
    return 0


def main(*, fix: bool = False) -> None:
    """CLI entry point.

    :param fix: Regenerate the ``diff.md`` mirror into ``tmp/diff_md_out/``
        instead of checking the committed copies.
    """
    if fix:
        sys.exit(regenerate_diff_template())
    sys.exit(check_reviewer_templates())


if __name__ == "__main__":
    defopt.run(main)
