"""Unconditional routing-coverage guard for the ``scripts`` router target.

Asserts that every git-tracked source path under a router prefix both routes to
at least one test target and that each announced target actually collects at
least one test — unless the ``(router, path)`` pair is registered as a known
exemption in ``helpers.router_coverage_registry``.

Placeholder module: the predicate lands in Step 2 of TODO-0309. Until then this
module intentionally declares no tests, so ``task test:routing`` reports pytest
exit 5 (no tests collected). That is expected, not a defect, and MUST NOT be
tolerated by adding an exit-5 fallback to the task target (Req-N12).
"""
