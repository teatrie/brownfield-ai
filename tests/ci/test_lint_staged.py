"""Lint-routing tests for ``ci/lint_staged.sh`` — the pre-commit gate.

Holds the same contract as ``ci/lint_changed.sh``: both routers carry the
reviewer-template and reviewer-envelope checks, and subclassing one shared
``LintRouterContract`` is what keeps them from drifting apart. Harness details
are documented in ``helpers.lint_router_harness``.
"""

from helpers.lint_router_harness import LintRouterContract


class TestStagedLintRouter(LintRouterContract):
    """What ``task lint:staged`` checks before a commit."""

    SCRIPT = "lint_staged.sh"
