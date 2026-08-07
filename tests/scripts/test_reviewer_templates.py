"""Tests for ``scripts/lint_reviewer_templates.py`` and the committed
reviewer prompt templates under ``.claude/prompts/reviewer/``.

Invariants covered:

1. ``_invariants.md`` exists and exposes three named invariant blocks
   (``preamble``, ``criteria``, ``adversarial-rigor``).
2. All five template files exist (``diff.md``, ``plan.md``, ``spec.md``,
   ``epic.md``, ``spec-req-verification.md``).
3. Each template carries all three named invariant blocks, byte-identical
   (post-normalization) to the canonical source.
4. ``spec.md`` and ``spec-req-verification.md`` share invariant blocks
   but have distinct ``## Subject handling`` sections (non-invariant
   parity, per §5 R_A1 of the unified plan).
5. ``.codex/config.toml`` ``[profiles.reviewer.instructions]`` is absent
   or contains zero numbered criteria.
6. The lint script exits 0 on the current (clean) repo state.
7. The lint script catches deliberate invariant-block drift (introduced
   via a temporary copy, not via mutating the real template).
7b. The lint script catches deliberate numbered-criteria / keyword-
   criteria drift in the Codex TOML surfaces (``.codex/config.toml``
   and ``docker/agent-cli/codex-config.toml``), covered by
   parametrized cross-product of both paths and both detection axes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
INVARIANTS: Path = REPO_ROOT / ".claude" / "prompts" / "reviewer" / "_invariants.md"
TEMPLATES_DIR: Path = REPO_ROOT / ".claude" / "prompts" / "reviewer"
LINT_SCRIPT: Path = REPO_ROOT / "scripts" / "lint_reviewer_templates.py"
CODEX_TOML: Path = REPO_ROOT / ".codex" / "config.toml"
SKILL_PATH: Path = REPO_ROOT / ".claude" / "skills" / "diff-review" / "SKILL.md"
DIFF_TEMPLATE: Path = TEMPLATES_DIR / "diff.md"

SHARED_NAMES: tuple[str, ...] = (
    "diff-scope",
    "diff-dimensions",
)

TEMPLATE_NAMES: tuple[str, ...] = (
    "diff",
    "plan",
    "spec",
    "epic",
    "spec-req-verification",
)

INVARIANT_NAMES: tuple[str, ...] = (
    "preamble",
    "criteria",
    "adversarial-rigor",
)


def _extract(text: str, name: str) -> str | None:
    """Mirror of ``scripts/lint_reviewer_templates.py._extract_block``.

    Duplicated here intentionally so the test does not depend on the
    lint module's private API.
    """
    pattern = re.compile(
        re.escape(f"<!-- INVARIANT:{name} start -->") + r"(.*?)" + re.escape(f"<!-- INVARIANT:{name} end -->"),
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return None
    body = match.group(1)
    lines = [ln.rstrip() for ln in body.splitlines()]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _extract_subject_handling(text: str) -> str | None:
    """Return the contents of a template's ``## Subject handling`` section.

    The section runs from the header to the next blank line preceding the
    next invariant-block delimiter (the ``preamble`` already appeared
    before this section in the template layout, so the trailing anchor
    is ``<!-- INVARIANT:criteria start -->``).
    """
    pattern = re.compile(
        r"## Subject handling\s*\n(.*?)\n\s*<!-- INVARIANT:criteria start -->",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return None
    return match.group(1).strip()


# ---------------------------------------------------------------------------
# 1. Canonical invariants file present + parses.
# ---------------------------------------------------------------------------


def _extract_shared(text: str, name: str, *, blockquote: bool) -> str | None:
    """Mirror of ``lint_reviewer_templates._extract_shared``.

    Duplicated here intentionally, like ``_extract``, so the test does
    not depend on the lint module's private API.
    """
    pattern = re.compile(
        re.escape(f"<!-- SHARED:{name} start -->") + r"(.*?)" + re.escape(f"<!-- SHARED:{name} end -->"),
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return None
    body = match.group(1)
    if blockquote:
        body = "\n".join("" if ln == ">" else ln.removeprefix("> ") for ln in body.splitlines())
    lines = [ln.rstrip() for ln in body.splitlines()]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _stage_workspace(tmp_path: Path) -> Path:
    """Stage a minimal workspace the lint script can run against.

    Copies every committed reviewer template, the lint script, and the
    diff-review ``SKILL.md`` that owns the canonical ``SHARED:`` blocks.
    ``SKILL.md`` is required: the shared-block check is fail-closed, so a
    workspace missing it is a lint error rather than a skipped check.

    Returns the path of the staged lint script.
    """
    reviewer_dir = tmp_path / ".claude" / "prompts" / "reviewer"
    reviewer_dir.mkdir(parents=True)
    for source in TEMPLATES_DIR.iterdir():
        shutil.copy(source, reviewer_dir / source.name)
    skill_dir = tmp_path / ".claude" / "skills" / "diff-review"
    skill_dir.mkdir(parents=True)
    shutil.copy(SKILL_PATH, skill_dir / SKILL_PATH.name)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(LINT_SCRIPT, scripts_dir / LINT_SCRIPT.name)
    return scripts_dir / LINT_SCRIPT.name


def test_invariants_file_exists_and_parses() -> None:
    """``_invariants.md`` loads and carries all three named blocks."""
    assert INVARIANTS.is_file(), f"missing canonical file: {INVARIANTS}"
    text = INVARIANTS.read_text()
    for name in INVARIANT_NAMES:
        body = _extract(text, name)
        assert body is not None, f"canonical block {name!r} missing"
        assert body.strip(), f"canonical block {name!r} is empty"


# ---------------------------------------------------------------------------
# 2. All templates exist.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_template_file_exists(name: str) -> None:
    """Each of the 5 templates exists under ``.claude/prompts/reviewer``."""
    path = TEMPLATES_DIR / f"{name}.md"
    assert path.is_file(), f"missing template: {path}"


# ---------------------------------------------------------------------------
# 3. Byte-identical invariant blocks across templates.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_name", TEMPLATE_NAMES)
@pytest.mark.parametrize("block_name", INVARIANT_NAMES)
def test_template_invariant_matches_canonical(
    template_name: str,
    block_name: str,
) -> None:
    """Each template's invariant block matches the canonical source."""
    canonical = _extract(INVARIANTS.read_text(), block_name)
    assert canonical is not None
    template_text = (TEMPLATES_DIR / f"{template_name}.md").read_text()
    actual = _extract(template_text, block_name)
    assert actual is not None, f"{template_name}.md missing INVARIANT:{block_name} block"
    assert actual == canonical, f"{template_name}.md INVARIANT:{block_name} drifted from canonical"


# ---------------------------------------------------------------------------
# 4. spec.md and spec-req-verification.md share invariants but diverge on
#    the subject-handling section.
# ---------------------------------------------------------------------------


def test_spec_and_spec_req_verification_subject_handling_diverge() -> None:
    """``spec.md`` and ``spec-req-verification.md`` have distinct subject sections."""
    spec_text = (TEMPLATES_DIR / "spec.md").read_text()
    srv_text = (TEMPLATES_DIR / "spec-req-verification.md").read_text()
    spec_sh = _extract_subject_handling(spec_text)
    srv_sh = _extract_subject_handling(srv_text)
    assert spec_sh is not None, "spec.md missing Subject handling section"
    assert srv_sh is not None, "spec-req-verification.md missing Subject handling section"
    assert spec_sh != srv_sh, (
        "spec.md and spec-req-verification.md must have distinct Subject handling sections (invariants shared, subject handling divergent)"
    )


# ---------------------------------------------------------------------------
# 5. .codex/config.toml has no stale numbered criteria.
# ---------------------------------------------------------------------------


def test_codex_toml_has_no_numbered_criteria() -> None:
    """The ``[profiles.reviewer.instructions]`` section is absent or clean."""
    if not CODEX_TOML.is_file():
        pytest.skip(".codex/config.toml not present")
    text = CODEX_TOML.read_text()
    section = re.search(
        r"^\[profiles\.reviewer\.instructions\]\s*$(.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if section is None:
        return
    body = section.group(1)
    assert not re.search(r"^\s*\d+\.\s", body, re.MULTILINE), (
        "[profiles.reviewer.instructions] contains numbered criteria — criteria must live only in the committed templates."
    )
    assert not re.search(r"owasp|credential leak|boy scout", body, re.IGNORECASE), (
        "[profiles.reviewer.instructions] contains criteria keywords — move to templates."
    )


# ---------------------------------------------------------------------------
# 6. Lint script passes on clean repo.
# ---------------------------------------------------------------------------


def test_lint_script_passes_on_clean_repo() -> None:
    """Running the lint script against the committed state exits 0."""
    result = subprocess.run(
        [sys.executable, str(LINT_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"lint failed on clean repo: stdout={result.stdout!r} stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# 7. Lint script catches deliberate drift in a template.
# ---------------------------------------------------------------------------


def test_lint_script_detects_drift(tmp_path: Path) -> None:
    """Mutating a template copy triggers a non-zero exit with a clear message.

    Strategy: copy the committed ``.claude/prompts/reviewer/`` tree +
    ``scripts/lint_reviewer_templates.py`` into ``tmp_path``, mutate one
    template's ``criteria`` block, then invoke the script against the
    copy (by setting ``cwd`` to the copy root).
    """
    script_copy = _stage_workspace(tmp_path)
    reviewer_dir = tmp_path / ".claude" / "prompts" / "reviewer"

    # Mutate diff.md's criteria block — replace one line.
    diff_path = reviewer_dir / "diff.md"
    text = diff_path.read_text()
    drifted = text.replace(
        "Apply these 10 review criteria strictly:",
        "DRIFTED CRITERIA HEADER:",
        1,
    )
    diff_path.write_text(drifted)
    assert text != drifted, "drift mutation was a no-op — fix fixture"

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 1, (
        f"expected drift-detection failure; got exit {result.returncode}; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "criteria" in result.stderr, f"expected stderr to mention the drifted block name 'criteria'; got {result.stderr!r}"
    assert "diff.md" in result.stderr, f"expected stderr to identify the drifted template 'diff.md'; got {result.stderr!r}"


# ---------------------------------------------------------------------------
# 7b. Lint script catches deliberate drift in the Codex TOML surfaces.
# ---------------------------------------------------------------------------


_TOML_DRIFT_CASES: tuple[tuple[str, str, str, str], ...] = (
    (
        ".codex/config.toml",
        "numbered",
        "1. Check for security issues.",
        "numbered criteria",
    ),
    (
        ".codex/config.toml",
        "keyword",
        "Apply OWASP guidelines.",
        "criteria keyword",
    ),
    (
        "docker/agent-cli/codex-config.toml",
        "numbered",
        "1. Check for security issues.",
        "numbered criteria",
    ),
    (
        "docker/agent-cli/codex-config.toml",
        "keyword",
        "Apply OWASP guidelines.",
        "criteria keyword",
    ),
)


def _build_drifted_toml(payload: str) -> str:
    """Return a minimal TOML string whose instructions body carries ``payload``.

    The text anchors a ``[profiles.reviewer.instructions]`` header so the
    lint script's section regex matches. A preceding ``[profiles.reviewer]``
    block keeps the file parseable by standard TOML readers, though the
    lint itself operates on raw-text regex rather than a TOML AST.
    """
    return f'[profiles.reviewer]\nmodel = "gpt-5.3-codex"\n\n[profiles.reviewer.instructions]\nreview = """\n{payload}\n"""\n'


@pytest.mark.parametrize(
    ("toml_rel_path", "payload", "error_class"),
    [(rel, payload, err) for rel, _, payload, err in _TOML_DRIFT_CASES],
    ids=[f"{rel}:{axis}" for rel, axis, _, _ in _TOML_DRIFT_CASES],
)
def test_lint_script_detects_codex_toml_drift(
    tmp_path: Path,
    toml_rel_path: str,
    payload: str,
    error_class: str,
) -> None:
    """Drifted Codex TOML content triggers a lint failure naming the file.

    Both surfaces checked by ``_check_codex_toml_file`` (`.codex/config.toml`
    and `docker/agent-cli/codex-config.toml`) must fail on either
    numbered-criteria lines or criteria-keyword substrings inside the
    ``[profiles.reviewer.instructions]`` body. The test mirrors the
    fixture strategy of ``test_lint_script_detects_drift``: the real
    repo files are NEVER mutated; instead a tmp-path copy of the
    templates + lint script is built and the drifted TOML is written
    only under ``tmp_path``.
    """
    script_copy = _stage_workspace(tmp_path)

    toml_path = tmp_path / toml_rel_path
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    toml_path.write_text(_build_drifted_toml(payload))

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 1, (
        f"expected TOML-drift detection failure; got exit {result.returncode}; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert toml_rel_path in result.stderr, f"expected stderr to identify the drifted TOML path {toml_rel_path!r}; got {result.stderr!r}"
    assert error_class in result.stderr, f"expected stderr to mention error class {error_class!r}; got {result.stderr!r}"


# ---------------------------------------------------------------------------
# 7c. Diff-only SHARED blocks stay mirrored between SKILL.md and diff.md.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SHARED_NAMES)
def test_shared_block_present_in_both_copies(name: str) -> None:
    """Both the skill and the diff template carry every shared block."""
    skill_body = _extract_shared(SKILL_PATH.read_text(), name, blockquote=True)
    template_body = _extract_shared(DIFF_TEMPLATE.read_text(), name, blockquote=False)
    assert skill_body is not None, f"SHARED:{name} missing from {SKILL_PATH}"
    assert template_body is not None, f"SHARED:{name} missing from {DIFF_TEMPLATE}"


@pytest.mark.parametrize("name", SHARED_NAMES)
def test_shared_block_matches_after_blockquote_strip(name: str) -> None:
    """The two copies are identical once the skill's ``> `` prefix is removed.

    Bridge reviewers (codex/gemini/copilot) read only the template, while
    Claude reviewers read only the skill. If these drift, the two families
    review against different rubrics while the gate treats their verdicts
    as equivalent.
    """
    skill_body = _extract_shared(SKILL_PATH.read_text(), name, blockquote=True)
    template_body = _extract_shared(DIFF_TEMPLATE.read_text(), name, blockquote=False)
    assert skill_body == template_body, f"SHARED:{name} diverged between {SKILL_PATH.name} and {DIFF_TEMPLATE.name}"


def test_shared_dimensions_cover_items_11_through_21() -> None:
    """The dimensions block carries every diff-only numbered item.

    Guards the reason the block exists: items 1-10 live in the shared
    ``criteria`` invariant, so 11-21 are exactly what the template would
    otherwise be missing.
    """
    body = _extract_shared(DIFF_TEMPLATE.read_text(), "diff-dimensions", blockquote=False)
    assert body is not None, "diff-dimensions block missing"
    for item in range(11, 22):
        assert re.search(rf"^{item}\. ", body, re.MULTILINE), f"item {item} missing from the diff-dimensions block"


def test_lint_script_detects_shared_block_drift(tmp_path: Path) -> None:
    """Mutating the template's shared block fails the lint.

    Mutation check: without this the guard could pass vacuously (e.g. if
    both extractions returned ``None`` and compared equal).
    """
    script_copy = _stage_workspace(tmp_path)
    diff_path = tmp_path / ".claude" / "prompts" / "reviewer" / "diff.md"

    text = diff_path.read_text()
    drifted = text.replace(
        "11. Runtime infrastructure dependencies",
        "11. DRIFTED infrastructure dependencies",
        1,
    )
    assert text != drifted, "drift mutation was a no-op — fix fixture"
    diff_path.write_text(drifted)

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 1, (
        f"expected shared-block drift detection; got exit {result.returncode}; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "diff-dimensions" in result.stderr, f"expected stderr to name the drifted shared block; got {result.stderr!r}"


def test_lint_script_detects_duplicate_shared_block(tmp_path: Path) -> None:
    """A second ``SHARED:`` marker pair fails the lint rather than being ignored.

    Extraction stops at the first match, so a duplicated pair would carry
    unchecked — potentially contradictory — prompt content past a clean lint.
    """
    script_copy = _stage_workspace(tmp_path)
    diff_path = tmp_path / ".claude" / "prompts" / "reviewer" / "diff.md"

    text = diff_path.read_text()
    diff_path.write_text(
        f"{text}\n<!-- SHARED:diff-dimensions start -->\ncontradictory instructions\n<!-- SHARED:diff-dimensions end -->\n",
    )

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 1, f"expected duplicate-marker detection; got exit {result.returncode}; stderr={result.stderr!r}"
    assert "appears 2 times" in result.stderr, f"expected stderr to report the duplicate count; got {result.stderr!r}"


def test_lint_script_detects_duplicate_invariant_block(tmp_path: Path) -> None:
    """The duplicate-marker guard covers INVARIANT blocks too, not just SHARED."""
    script_copy = _stage_workspace(tmp_path)
    plan_path = tmp_path / ".claude" / "prompts" / "reviewer" / "plan.md"

    text = plan_path.read_text()
    plan_path.write_text(
        f"{text}\n<!-- INVARIANT:criteria start -->\ndivergent criteria\n<!-- INVARIANT:criteria end -->\n",
    )

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 1, f"expected duplicate-marker detection; got exit {result.returncode}; stderr={result.stderr!r}"
    assert "appears 2 times" in result.stderr, f"expected stderr to report the duplicate count; got {result.stderr!r}"


def test_lint_script_detects_escaped_blockquote_in_skill(tmp_path: Path) -> None:
    """A shared-block line that loses its ``> `` prefix fails the lint.

    Regression guard for a real edit hazard: dropping the prefix ends the
    reviewer prompt blockquote in Markdown, yet the stripped text still
    compares equal to the template copy — so without this check the lint
    would pass on a prompt that no longer delivers that instruction.
    """
    script_copy = _stage_workspace(tmp_path)
    skill_path = tmp_path / ".claude" / "skills" / "diff-review" / "SKILL.md"

    text = skill_path.read_text()
    escaped = text.replace(
        "> 11. Runtime infrastructure dependencies",
        "11. Runtime infrastructure dependencies",
        1,
    )
    assert text != escaped, "prefix removal was a no-op — fix fixture"
    skill_path.write_text(escaped)

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 1, f"expected escaped-blockquote detection; got exit {result.returncode}; stderr={result.stderr!r}"
    assert "blockquote prefix" in result.stderr, f"expected stderr to name the blockquote failure; got {result.stderr!r}"


def test_lint_script_detects_missing_shared_block(tmp_path: Path) -> None:
    """Deleting a shared marker pair from the template fails the lint."""
    script_copy = _stage_workspace(tmp_path)
    diff_path = tmp_path / ".claude" / "prompts" / "reviewer" / "diff.md"

    text = diff_path.read_text()
    stripped = text.replace("<!-- SHARED:diff-scope start -->", "", 1)
    assert text != stripped, "marker removal was a no-op — fix fixture"
    diff_path.write_text(stripped)

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 1, f"expected missing-block detection; got exit {result.returncode}; stderr={result.stderr!r}"
    assert "diff-scope" in result.stderr, f"expected stderr to name the missing shared block; got {result.stderr!r}"


# ---------------------------------------------------------------------------
# 8. TODO-0103 — lint script auto-enumerates TEMPLATE_NAMES.
# ---------------------------------------------------------------------------


def test_lint_template_names_matches_committed_templates() -> None:
    """The lint script's discovered TEMPLATE_NAMES equals the committed tree.

    Prevents drift between the lint script's auto-discovery
    (``_discover_template_names``) and the test file's independent
    TEMPLATE_NAMES tuple. If a new template is added to
    ``.claude/prompts/reviewer/``, both this test's tuple and the
    lint script's discovery must resolve to the same set — if they
    diverge, the new template would be silently unasserted by the
    tests above.
    """
    from scripts.lint_reviewer_templates import TEMPLATE_NAMES as LINT_TEMPLATE_NAMES

    expected = tuple(sorted(TEMPLATE_NAMES))
    assert LINT_TEMPLATE_NAMES == expected, (
        f"lint_reviewer_templates.TEMPLATE_NAMES={LINT_TEMPLATE_NAMES!r} "
        f"does not match test tuple sorted={expected!r}. Update the test "
        "tuple when adding a template, or fix the lint-script discovery."
    )


def test_lint_script_detects_new_template_without_source_edit(tmp_path: Path) -> None:
    """Auto-enumeration picks up a new template file added to the dir.

    Strategy: copy the lint script and the canonical ``_invariants.md``
    into a fake workspace, add ONE new template ``newtype.md`` that
    carries valid invariant blocks, then invoke the script. The lint
    must exit 0 (no drift) AND its stdout-confirmation must reflect
    that ``newtype`` was discovered and checked (evidenced by no
    ``template missing`` error in stderr and a successful exit).

    Regression guard: without auto-enumeration (the pre-TODO-0103 hardcoded
    tuple), adding ``newtype.md`` to the repo would leave the lint script
    silently unaware of the new file. Post-TODO-0103, discovery is
    directory-driven, so a new template is automatically in-scope for
    invariant-block checks.
    """
    script_copy = _stage_workspace(tmp_path)
    reviewer_dir = tmp_path / ".claude" / "prompts" / "reviewer"

    # Fabricate a new template by cloning diff.md under a new stem.
    # Because we clone an already-canonical template, all three
    # invariant blocks carry through verbatim; the lint must pass.
    new_template = reviewer_dir / "newtype.md"
    new_template.write_text((reviewer_dir / "diff.md").read_text())

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"expected lint to pass after auto-discovering newtype.md; "
        f"exit={result.returncode}; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "template missing" not in result.stderr, f"auto-discovery should have picked up newtype.md; stderr={result.stderr!r}"


def test_lint_script_ignores_underscore_prefixed_files(tmp_path: Path) -> None:
    """Auto-enumeration skips ``_*.md`` (shared fragments, not review types).

    Regression guard: ``_invariants.md`` itself must NEVER be treated
    as a review type. If discovery accidentally included underscore-
    prefixed files, the lint would attempt to find invariant blocks
    inside the canonical invariants file (circular) — causing spurious
    errors or false clean exits depending on the block-extraction
    behavior. Lock the skip rule in place.
    """
    script_copy = _stage_workspace(tmp_path)
    reviewer_dir = tmp_path / ".claude" / "prompts" / "reviewer"

    # Add an underscore-prefixed non-template file that, if it were
    # discovered as a REVIEW_TYPE, would fail lint (no invariant blocks).
    (reviewer_dir / "_stray.md").write_text("not a template; should be skipped.\n")

    result = subprocess.run(
        [sys.executable, str(script_copy)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"underscore-prefixed file must be skipped by discovery; exit={result.returncode}; stderr={result.stderr!r}"
    )
    assert "_stray" not in result.stderr, f"_stray.md should not appear in any lint error; stderr={result.stderr!r}"
