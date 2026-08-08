"""Lint-routing tests for ``ci/lint_changed.sh`` — the branch-diff gate.

This is the only lint router CI runs: the ``lint`` job is exactly
``task lint:changed``. A check this router omits therefore never fires on a
pull request at all, however faithfully ``lint_staged.sh`` carries it. Harness
details are documented in ``helpers.lint_router_harness``.
"""

from helpers.lint_router_harness import LintRouterContract


class TestChangedLintRouter(LintRouterContract):
    """What ``task lint:changed`` checks on a branch diff."""

    SCRIPT = "lint_changed.sh"
