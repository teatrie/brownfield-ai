"""Routing tests for ``ci/test_changed.sh`` — the pre-push gate.

This is the router ``auto-pr`` and ``ship`` run before pushing, so a routing
hole here reaches the PR path. Covers the shared contract plus the branch
unique to this router. Harness details and its deliberate limits are
documented in ``helpers.router_harness``.
"""

from helpers.router_harness import RouteFn, RouterContract, diagnose, routed_targets


class TestChangedRouter(RouterContract):
    """What ``task test:changed`` selects before a push."""

    SCRIPT = "test_changed.sh"

    def test_agent_cli_path_routes_to_prefixed_test(self, route: RouteFn) -> None:
        """docker/agent-cli/ routes via the agent-cli-prefixed naming convention.

        Present only in this router; ``test_staged.sh`` omits the prefix from
        its grep entirely.
        """
        result = route(self.SCRIPT, ["docker/agent-cli/entrypoint.sh"])
        assert routed_targets(result) == ["tests/scripts/test_agent_cli_entrypoint.py"], diagnose(result)
