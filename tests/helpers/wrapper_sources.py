"""Read a reviewer wrapper's shell sources for the ``tmp/`` paths they name.

A suite that watches a set of ``tmp/`` artifacts has to hold that set against
the paths the wrapper itself spells, or the set narrows silently as the wrapper
changes. ``wrapper_tmp_paths`` derives those paths from the sources, so a
wrapper that gains a literal ``tmp/`` name surfaces in the derivation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

# A ``tmp/`` path as a wrapper spells it: literal path characters, ``${VAR}``
# placeholders, and the ``$$`` of a PID-scoped name. Nothing else terminates a
# name, so a diagnostic string that ends at a bare ``tmp/`` yields no match.
_TMP_PATH_CHARS = r"(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$\$|[A-Za-z0-9._-])"
# Only a word character disqualifies the prefix, so ``mytmp/`` is skipped while
# an anchored ``${top}/tmp/...`` and a ``${VAR:-tmp/...}`` default are caught.
_TMP_PATH = re.compile(rf"(?<![A-Za-z0-9_])tmp/({_TMP_PATH_CHARS}+)")
_SHELL_COMMENT_LINE = re.compile(r"(?m)^[ \t]*#.*$")
_SHELL_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def wrapper_tmp_paths(scripts: Iterable[Path], substitutions: Mapping[str, str]) -> set[str]:
    """Extract the literal ``tmp/`` paths the given shell sources name, relative to ``tmp/``.

    Whole-line comments are dropped first, so usage banners and rationale notes
    that spell an artifact name do not register. What the scan then finds is
    literal ``tmp/``-prefixed names, up to the first path segment, with the
    requested ``${VAR}`` substitutions applied to the name. A name reached only
    through a variable holding the directory — ``"${OUTPUT_DIR}/name.md"`` — is
    not found at all, so a caller whose watch set matters has to pin the
    expected derivation rather than only compare against it.

    Args:
        scripts: the shell sources to scan.
        substitutions: shell variable names mapped to the value the caller's
            run gives them, e.g. ``ROUND`` to the round id. A name left out
            stays literal, so its entry keeps the ``${...}`` spelling and
            surfaces as uncovered rather than being silently dropped.

    Returns:
        The distinct names found across all sources, each relative to ``tmp/``
        and carrying every requested substitution already applied — e.g.
        ``codex-exit.json`` or ``codex-review-output-7.md``.

    Raises:
        OSError: if a source cannot be read.
        UnicodeDecodeError: if a source does not decode under the locale's
            preferred encoding, which is what ``Path.read_text`` applies here.
    """
    named: set[str] = set()
    for script in scripts:
        source = _SHELL_COMMENT_LINE.sub("", script.read_text())
        for match in _TMP_PATH.finditer(source):
            named.add(_SHELL_VAR.sub(lambda hit: substitutions.get(hit.group(1), hit.group(0)), match.group(1)))
    return named
