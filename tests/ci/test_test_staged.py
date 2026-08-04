"""Routing tests for ``ci/test_staged.sh`` — the pre-commit gate.

Covers the shared contract plus the branch unique to this router. Harness
details and its deliberate limits are documented in ``helpers.router_harness``.
"""

from helpers.router_harness import RouteFn, RouterContract, assert_routed_nothing


class TestStagedRouter(RouterContract):
    """What ``task test:staged`` selects before a commit."""

    SCRIPT = "test_staged.sh"

    def test_agent_cli_paths_are_not_routed(self, route: RouteFn) -> None:
        """docker/agent-cli/ is absent from this router's grep, unlike test_changed.sh.

        Pins the asymmetry between the two files so a future reader sees it as
        recorded rather than as fresh drift.
        """
        assert_routed_nothing(route(self.SCRIPT, ["docker/agent-cli/entrypoint.sh"]))
