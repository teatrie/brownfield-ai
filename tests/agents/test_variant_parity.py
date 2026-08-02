"""Parity-pin contract for `.claude/agents/<name>-{high,xhigh,max}.md` variants.

For every effort-tier variant under `.claude/agents/`, this module asserts
that the variant preserves byte-parity with its base agent's body and
diverges only in the documented frontmatter slots (`name`, `description`,
`effort`). Drift between a variant and its base — or a variant whose
frontmatter `model_tier`/`tools:` no longer matches the base — has caused
silent regressions during prior diff-review runs (see the wrong-diff
incident in the tri-family review of TODO-0092 follow-ups). This test
catches those classes of bugs at static-analysis time.

The contract is deliberately narrow: it pins only the invariants that
make a variant *a variant of its base*, not the contents of either file.
Edits to a base agent's body propagate to its variants only when an
author explicitly mirrors them, so the test fails loudly when the base
moves and the variants stay still — exactly the signal the sync comment
(`<!-- Body must stay in sync with <base>.md ... -->`) is meant to
generate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

VARIANT_SUFFIXES = ("-high", "-xhigh", "-max")
VARIANT_EFFORT_BY_SUFFIX = {
    "-high": "high",
    "-xhigh": "xhigh",
    "-max": "max",
}

# Bridge-reviewer families have their own contract for variant tier
# selection (e.g., Gemini variants override `model_tier` to flip Flash
# vs Pro; Codex variants override via `-c profiles.reviewer.model_reasoning_effort`).
# Their parity pins live with the wrapper scripts under
# `scripts/agent-cli/`, not here. The claude-native code-review family
# is also excluded because its W1 envelope example (REVIEWER-ENVELOPE-001)
# embeds per-variant `agent_id` and `agent_effort_tier` that are
# load-bearing for emission shape — a byte-identical body across variants
# would either drop those values or document the wrong variant's tier.
# qa-standards joins the exclusion in W3 for the same reason: each variant
# carries its own envelope example whose `agent_id`/`agent_effort_tier`
# match the variant's frontmatter (per the REVIEWER-ENVELOPE-001 contract
# that the example envelope reflects the actual emission for that agent).
EXCLUDED_BASES = frozenset({
    "code-review",
    "codex-reviewer",
    "gemini-reviewer",
    "copilot-reviewer",
    "qa-standards",
})


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter dict, body string) for a markdown file with `---`-delimited YAML.

    The body includes everything after the closing `---` line, preserving
    leading/trailing whitespace verbatim — the parity check is byte-level.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        raise ValueError("expected frontmatter to begin with '---'")
    closing_idx = next(
        (i for i in range(1, len(lines)) if lines[i].rstrip() == "---"),
        None,
    )
    if closing_idx is None:
        raise ValueError("expected frontmatter to terminate with '---'")
    frontmatter_yaml = "".join(lines[1:closing_idx])
    body = "".join(lines[closing_idx + 1 :])
    parsed = yaml.safe_load(frontmatter_yaml) or {}
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter must parse as a mapping")
    return parsed, body


def _strip_sync_comment(body: str) -> str:
    """Remove the leading `<!-- Body must stay in sync with ... -->` marker, if present.

    Variants prepend this HTML comment immediately above the
    `**CRITICAL CONSTRAINT...**` block; bases do not. Stripping it
    yields a body that should match the base byte-for-byte when the
    sync invariant holds.

    Trailing-newline handling strips at most ONE newline after the
    closing `-->` to avoid eating an intentional blank line that the
    base also carries — `lstrip("\\n")` is greedy and would
    over-strip when both base and variant deliberately leave a blank
    line between the frontmatter and the body, producing a
    false-positive parity failure.
    """
    marker_prefix = "<!-- Body must stay in sync with "
    if not body.lstrip().startswith(marker_prefix):
        return body
    leading_ws_len = len(body) - len(body.lstrip())
    after_marker = body.lstrip()
    end_idx = after_marker.find("-->")
    if end_idx == -1:
        return body
    remainder = after_marker[end_idx + len("-->") :]
    if remainder.startswith("\n"):
        remainder = remainder[1:]
    return body[:leading_ws_len] + remainder


def _resolve_base_path(variant_path: Path) -> Path | None:
    """Map a variant path (e.g., `tdd-green-xhigh.md`) back to its base (`tdd-green.md`)."""
    stem = variant_path.stem
    for suffix in VARIANT_SUFFIXES:
        if stem.endswith(suffix):
            base_name = stem[: -len(suffix)]
            base_path = variant_path.with_name(f"{base_name}.md")
            return base_path if base_path.is_file() else None
    return None


def _discover_variants() -> list[Path]:
    """Return all variant `.md` files under `.claude/agents/`, excluding bridge families."""
    out: list[Path] = []
    for path in sorted(AGENTS_DIR.glob("*.md")):
        stem = path.stem
        suffix_match = next(
            (s for s in VARIANT_SUFFIXES if stem.endswith(s)),
            None,
        )
        if suffix_match is None:
            continue
        base_name = stem[: -len(suffix_match)]
        if base_name in EXCLUDED_BASES:
            continue
        out.append(path)
    return out


@pytest.fixture(scope="module")
def variant_paths() -> list[Path]:
    """Discover all in-scope variant files under `.claude/agents/`."""
    return _discover_variants()


def test_variant_discovery_finds_known_xhigh_files(variant_paths: list[Path]) -> None:
    """Sanity: the discovery walk finds at least the six in-scope Epic-2 xhigh variants.

    Locks in coverage so a future glob change cannot silently shrink the
    test surface to zero. ``qa-standards-xhigh.md`` is intentionally
    omitted: as of W3 of REVIEWER-ENVELOPE-001, ``qa-standards`` carries
    per-variant envelope examples whose `agent_id`/`agent_effort_tier`
    legitimately diverge, so the base joins :data:`EXCLUDED_BASES` and
    its variants drop out of the discovery set.
    """
    expected_xhigh = {
        "deep-researcher-xhigh.md",
        "general-purpose-xhigh.md",
        "planner-xhigh.md",
        "tdd-green-xhigh.md",
        "tdd-red-xhigh.md",
        "tdd-refactor-xhigh.md",
    }
    found_names = {p.name for p in variant_paths}
    missing = expected_xhigh - found_names
    assert not missing, f"expected xhigh variants missing from discovery: {sorted(missing)}"


def test_every_variant_has_resolvable_base(variant_paths: list[Path]) -> None:
    """Every `<name>-{high,xhigh,max}.md` must have a corresponding `<name>.md` base."""
    orphans: list[str] = []
    for variant in variant_paths:
        if _resolve_base_path(variant) is None:
            orphans.append(variant.name)
    assert not orphans, f"variants without a base agent: {orphans}"


def test_variant_frontmatter_contract(variant_paths: list[Path]) -> None:
    """Each variant must declare `effort: <suffix>`, preserve base `model_tier`, and preserve `tools:`.

    Required-key presence is asserted up front: a `None` returned by
    `dict.get()` would otherwise silently equal `None` on both sides
    when the frontmatter block is empty or missing the field, masking
    schema bugs. Treating absence as a contract violation prevents
    that silent pass.
    """
    required_keys = ("name", "description", "model_tier", "tools", "effort")
    failures: list[str] = []
    for variant in variant_paths:
        base = _resolve_base_path(variant)
        assert base is not None  # guarded by previous test
        v_meta, _ = _split_frontmatter(variant.read_text())
        b_meta, _ = _split_frontmatter(base.read_text())
        for key in required_keys:
            if key not in v_meta:
                failures.append(f"{variant.name}: missing required frontmatter key {key!r}")
        suffix = next(s for s in VARIANT_SUFFIXES if variant.stem.endswith(s))
        expected_effort = VARIANT_EFFORT_BY_SUFFIX[suffix]
        if v_meta.get("effort") != expected_effort:
            failures.append(f"{variant.name}: effort={v_meta.get('effort')!r}, expected {expected_effort!r}")
        if v_meta.get("model_tier") != b_meta.get("model_tier"):
            failures.append(f"{variant.name}: model_tier={v_meta.get('model_tier')!r} differs from base {b_meta.get('model_tier')!r}")
        if v_meta.get("tools") != b_meta.get("tools"):
            failures.append(f"{variant.name}: tools={v_meta.get('tools')!r} differs from base {b_meta.get('tools')!r}")
    assert not failures, "variant frontmatter drift:\n  " + "\n  ".join(failures)


def test_variant_body_matches_base_modulo_sync_comment(variant_paths: list[Path]) -> None:
    """Each variant body must equal its base body byte-for-byte after stripping the sync comment."""
    failures: list[str] = []
    for variant in variant_paths:
        base = _resolve_base_path(variant)
        assert base is not None
        _, v_body = _split_frontmatter(variant.read_text())
        _, b_body = _split_frontmatter(base.read_text())
        stripped = _strip_sync_comment(v_body)
        if stripped != b_body:
            failures.append(f"{variant.name}: body diverges from base after stripping sync comment")
    assert not failures, "variant body drift:\n  " + "\n  ".join(failures)
