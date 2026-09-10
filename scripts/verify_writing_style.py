"""Verify the byte-identical pair inside the three-copy PR Writing Style set.

Three copies of the Writing Style block exist: `docs/pr_protocol.md`,
`.claude/rules/pr.artifacts.md`, and
`.github/instructions/pr.artifacts.instructions.md`. Only the first two are
byte-identical, and only modulo two sanctioned differences: (a) the
Collapsible Details Convention above/below pointer and (b) a lead sentence
carried only by `pr_protocol.md`. This checks that pair, which is the claim
the guard comment in each copy makes; a claim is only worth having if it is
checked. The compared slice runs from the heading through the guard comment's
closing marker, so the guard's claim about the guard itself is covered too.

The third copy is out of scope by design. It is a deliberately non-identical
mirror that normalizes to ASCII punctuation, spells out symbols, and describes
HTML tags in prose. Its other wording differences are intentional and must not
be resynced, so comparing it here would report drift that should not be fixed.

Read-only. Writes nothing; prints a per-line comparison and exits non-zero on
any unexpected divergence.

    task lint:writing-style
"""

from pathlib import Path

import defopt

LOCAL_ROOT = Path(__file__).resolve().parents[1]

PROTOCOL = "docs/pr_protocol.md"
RULE = ".claude/rules/pr.artifacts.md"

HEADING = "## Writing Style (Mandatory)"
GUARD_START = "<!-- THREE copies"
GUARD_END = "-->"

#: The lead sentence only `pr_protocol.md` carries, per the guard.
LEAD_ONLY_IN_PROTOCOL = (
    "Governs **every** PR body, description, and comment produced under this",
    "protocol — including ad-hoc calls made outside the `auto-pr` / `ship` skills.",
)

#: The single sanctioned wording difference: the above/below pointer.
POINTER_PROTOCOL = "  **Collapsible Details Convention** above."
POINTER_RULE = "  **Collapsible Details Convention** below."


class BlockDivergence(Exception):
    """A guard claim failed, or the blocks differ beyond the sanctioned differences."""


def compare_blocks(protocol_path: Path, rule_path: Path) -> int:
    """Compare the two Writing Style blocks and return the identical line count.

    :param protocol_path: The copy that carries the lead sentence and the
        'above' pointer.
    :param rule_path: The copy that carries the 'below' pointer.
    :returns: The number of lines matching once the two sanctioned differences
        are erased.
    :raises BlockDivergence: When a guard claim fails or the blocks diverge
        beyond the two sanctioned differences.
    :raises ValueError: Propagated from `extract_block` when either copy lacks
        the heading, the guard comment, or the guard's closing marker, or is
        not valid UTF-8.
    :raises OSError: Propagated from `extract_block` when either copy is
        missing or unreadable.
    """
    protocol_block = extract_block(protocol_path)
    rule_block = extract_block(rule_path)

    if not all(line in protocol_block for line in LEAD_ONLY_IN_PROTOCOL):
        msg = f"FAIL: {protocol_path} is missing the lead sentence the guard claims it carries"
        raise BlockDivergence(msg)
    if any(line in rule_block for line in LEAD_ONLY_IN_PROTOCOL):
        msg = f"FAIL: {rule_path} carries the lead sentence reserved for {protocol_path}"
        raise BlockDivergence(msg)
    if POINTER_RULE not in rule_block:
        msg = f"FAIL: {rule_path} is missing the expected 'below' pointer"
        raise BlockDivergence(msg)
    if POINTER_PROTOCOL not in protocol_block:
        msg = f"FAIL: {protocol_path} is missing the expected 'above' pointer"
        raise BlockDivergence(msg)

    left = normalize(protocol_block, is_protocol=True)
    right = normalize(rule_block, is_protocol=False)

    if left != right:
        report = [
            "FAIL: blocks diverge beyond the two sanctioned differences",
            "  positions count lines within the compared block, not within either file",
        ]
        for number, (a, b) in enumerate(zip(left, right), start=1):
            if a != b:
                report.append(f"  position {number}\n    {protocol_path}: {a!r}\n    {rule_path}: {b!r}")
        if len(left) != len(right):
            report.append(f"  length differs: {len(left)} vs {len(right)}")
        raise BlockDivergence("\n".join(report))

    return len(left)


def extract_block(path: Path) -> list[str]:
    """Return the Writing Style block's lines, heading through the guard's closing marker.

    :param path: The Markdown copy to slice.
    :returns: The block lines, guard comment included.
    :raises ValueError: When the heading, the guard comment, or the guard's
        closing marker is absent, or the copy is not valid UTF-8 — the decode
        failure surfaces as `UnicodeDecodeError`, a `ValueError` subclass.
    :raises OSError: When the copy is missing or unreadable.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        msg = f"{path}: not valid UTF-8: {exc}"
        raise ValueError(msg) from exc
    lines = text.splitlines()
    try:
        start = lines.index(HEADING)
    except ValueError as exc:
        msg = f"{path}: no {HEADING!r} heading"
        raise ValueError(msg) from exc
    for offset, line in enumerate(lines[start:], start=start):
        if line.startswith(GUARD_START):
            return lines[start : find_guard_end(path, lines, offset) + 1]
    msg = f"{path}: no {GUARD_START!r} guard after the heading"
    raise ValueError(msg)


def find_guard_end(path: Path, lines: list[str], guard_start: int) -> int:
    """Return the index of the line closing the guard comment.

    :param path: The Markdown copy the lines came from, for the error message.
    :param lines: Every line of that copy.
    :param guard_start: The index of the guard comment's opening line.
    :returns: The index of the first line at or after `guard_start` that ends
        the comment.
    :raises ValueError: When no line closes the guard comment.
    """
    for offset, line in enumerate(lines[guard_start:], start=guard_start):
        if line.endswith(GUARD_END):
            return offset
    msg = f"{path}: the {GUARD_START!r} guard has no closing {GUARD_END!r}"
    raise ValueError(msg)


def normalize(block: list[str], *, is_protocol: bool) -> list[str]:
    """Strip the two sanctioned differences so the remainder must match.

    :param block: The extracted block's lines, heading through guard.
    :param is_protocol: True for the copy carrying the lead sentence and the
        'above' pointer; False rewrites the 'below' pointer to the 'above' form.
    :returns: The lines with the lead sentence dropped and both pointers
        rendered identically.
    """
    kept = [line for line in block if line not in LEAD_ONLY_IN_PROTOCOL]
    if not is_protocol:
        return [POINTER_PROTOCOL if line == POINTER_RULE else line for line in kept]
    return kept


def main() -> None:
    """Check the two tracked Writing Style copies for unsanctioned drift.

    :raises SystemExit: A guard claim failed, the blocks diverge beyond the two
        sanctioned differences, a copy lacks the heading or guard comment the
        compared slice is cut from, or a copy cannot be read at all — moved,
        deleted, or not valid UTF-8.
    """
    try:
        identical = compare_blocks(LOCAL_ROOT / PROTOCOL, LOCAL_ROOT / RULE)
    except BlockDivergence as exc:
        print(exc)
        raise SystemExit(1) from exc
    except (ValueError, OSError) as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1) from exc
    print(f"PASS: {identical} lines identical after the two sanctioned differences")


if __name__ == "__main__":
    defopt.run(main)
