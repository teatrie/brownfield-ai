"""Lint-routing tests for ``ci/lint_staged.sh`` — the pre-commit gate.

Holds the same contract as ``ci/lint_changed.sh``: this router carries the
reviewer-template and reviewer-envelope checks today, and pinning it keeps the
two from drifting apart again once the branch-diff router gains them. Harness
details are documented in ``helpers.lint_router_harness``.
"""

from helpers.lint_router_harness import LintRouterContract


class TestStagedLintRouter(LintRouterContract):
    """What ``task lint:staged`` checks before a commit."""

    SCRIPT = "lint_staged.sh"
