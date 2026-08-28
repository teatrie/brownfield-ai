"""Registry of known routing-coverage exemptions for the ``scripts`` router target.

Names every ``(router, path)`` pair that the routing-coverage guard in
``tests/ci/test_router_coverage.py`` is permitted to leave uncovered, together
with the reason and the TODO id tracking its closure. The guard compares its
measured hole set against this registry by exact set equality, so an exemption
that stops being needed fails the guard rather than lingering.

This module deliberately lives under ``tests/helpers/`` rather than ``tests/ci/``:
the guard pins that the registry's own announced target set contains
``tests/helpers/`` and ``tests/ci/``, and relocating it would break that
containment pin. Do not move it.

An entry is only ever added for a hole the guard actually reported: an exemption
written in anticipation of one silently excuses a pair that may never have been
a hole, and the set-equality comparison cannot tell the two apart.
"""

from typing import NamedTuple


class RoutingExemption(NamedTuple):
    """One ``(router, path)`` pair the routing-coverage guard may leave uncovered.

    ``router`` and ``path`` together are the identity the guard compares on;
    ``reason`` and ``todo_id`` exist so an exemption cannot be added without
    naming why it holds and what would close it.
    """

    #: Router filename under ``ci/``, as in ``TEST_ROUTERS``.
    router: str
    #: Repository-relative path, spelled exactly as ``git ls-files`` reports it.
    path: str
    #: Why this pair routes to nothing, in terms of the router's own dispatch.
    reason: str
    #: The TODO tracking closure.
    todo_id: str


#: Every exemption the guard honours, compared against the measured hole set by
#: exact set equality — so a pair that stops being a hole fails the guard rather
#: than lingering here.
EXEMPTIONS: tuple[RoutingExemption, ...] = (
    RoutingExemption(
        router="test_staged.sh",
        path="ci/check_reviews.sh",
        reason="the scripts/-or-ci/ branch derives tests/ci/test_check_reviews.py, which does not exist, so [ -f ] drops it",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="ci/repo_routing.sh",
        reason="the scripts/-or-ci/ branch derives tests/ci/test_repo_routing.py, which does not exist, so [ -f ] drops it",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="docker/shared/jsonlint-batch.sh",
        reason="the docker/shared/ branch derives tests/scripts/test_jsonlint_batch.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/__init__.py",
        reason="the scripts/-or-ci/ branch derives tests/scripts/test___init__.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/_review-common.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test__review_common.py; "
        "neither agent-cli candidate name exists either",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/cli-args-to-env.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_cli_args_to_env.py, "
        "while ci/test_changed.sh resolves tests/scripts/test_cli_args_to_env.py",
        todo_id="TODO-0332",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/codex-preflight-tiered.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_codex_preflight_tiered.py; "
        "neither agent-cli candidate name exists either",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/codex-review-container.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_codex_review_container.py; "
        "neither agent-cli candidate name exists either",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/codex-review.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_codex_review.py, "
        "while ci/test_changed.sh resolves tests/scripts/test_codex_review.py",
        todo_id="TODO-0332",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/copilot-review-container.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_copilot_review_container.py; "
        "neither agent-cli candidate name exists either",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/copilot-review.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_copilot_review.py; "
        "neither agent-cli candidate name exists either",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/gemini-preflight-tiered.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_gemini_preflight_tiered.py; "
        "neither agent-cli candidate name exists either",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/gemini-review-container.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_gemini_review_container.py; "
        "neither agent-cli candidate name exists either",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/gemini-review.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_gemini_review.py, "
        "while ci/test_changed.sh resolves tests/scripts/test_gemini_review.py",
        todo_id="TODO-0332",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/agent-cli/preflight.sh",
        reason="no agent-cli branch here, so the scripts/ branch derives tests/scripts/agent-cli/test_preflight.py, "
        "while ci/test_changed.sh resolves tests/scripts/test_agent_cli_preflight.py",
        todo_id="TODO-0332",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/aws_vault_auth.sh",
        reason="the scripts/-or-ci/ branch derives tests/scripts/test_aws_vault_auth.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/ledger/__init__.py",
        reason="the scripts/-or-ci/ branch derives tests/scripts/ledger/test___init__.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/orchestrator/__init__.py",
        reason="the scripts/-or-ci/ branch derives tests/scripts/orchestrator/test___init__.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/setup_env.sh",
        reason="the scripts/-or-ci/ branch derives tests/scripts/test_setup_env.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="scripts/templates/dms_task.tf.j2",
        reason="the scripts/-or-ci/ branch strips only the last suffix, deriving tests/scripts/templates/test_dms_task.tf.py",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="tests/ci/conftest.py",
        reason="the tests/ci/ branch admits any existing *.py and routes it to itself, and a conftest collects no tests",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="tests/lint/__init__.py",
        reason="the tests/lint/ branch admits any existing *.py and routes it to itself, and this module holds no tests",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="tests/scripts/ledger/__init__.py",
        reason="the tests/scripts/ branch admits any existing *.py and routes it to itself, and this module holds no tests",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_staged.sh",
        path="tests/scripts/orchestrator/__init__.py",
        reason="the tests/scripts/ branch admits any existing *.py and routes it to itself, and this module holds no tests",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="ci/check_reviews.sh",
        reason="the scripts/-or-ci/ branch derives tests/ci/test_check_reviews.py, which does not exist, so [ -f ] drops it",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="ci/repo_routing.sh",
        reason="the scripts/-or-ci/ branch derives tests/ci/test_repo_routing.py, which does not exist, so [ -f ] drops it",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="docker/agent-cli/Dockerfile",
        reason="the agent-cli branch checks tests/scripts/test_Dockerfile.py and tests/scripts/test_agent_cli_Dockerfile.py, "
        "neither of which exists; the path is still tested, via the post-loop AGENT_CLI_RELEVANT match that delegates to "
        "task test:container-integration — a channel this guard cannot observe, since it equates coverage with announced "
        "pytest targets",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="docker/agent-cli/codex-config.toml",
        reason="the agent-cli branch precedes the reviewer-template branch and checks tests/scripts/test_codex_config.py and "
        "tests/scripts/test_agent_cli_codex_config.py, neither of which exists; the path is still tested, via the post-loop "
        "AGENT_CLI_RELEVANT match that delegates to task test:container-integration — a channel this guard cannot observe, "
        "since it equates coverage with announced pytest targets",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="docker/shared/jsonlint-batch.sh",
        reason="the docker/shared/ branch derives tests/scripts/test_jsonlint_batch.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/__init__.py",
        reason="the scripts/-or-ci/ branch derives tests/scripts/test___init__.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/agent-cli/_review-common.sh",
        reason="the agent-cli branch checks tests/scripts/test__review_common.py and "
        "tests/scripts/test_agent_cli__review_common.py, neither of which exists; the path is still tested, via the "
        "post-loop AGENT_CLI_RELEVANT match that delegates to task test:container-integration — a channel this guard "
        "cannot observe, since it equates coverage with announced pytest targets",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/agent-cli/codex-preflight-tiered.sh",
        reason="the agent-cli branch checks tests/scripts/test_codex_preflight_tiered.py and "
        "tests/scripts/test_agent_cli_codex_preflight_tiered.py, neither of which exists",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/agent-cli/codex-review-container.sh",
        reason="the agent-cli branch checks tests/scripts/test_codex_review_container.py and "
        "tests/scripts/test_agent_cli_codex_review_container.py, neither of which exists",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/agent-cli/copilot-review-container.sh",
        reason="the agent-cli branch checks tests/scripts/test_copilot_review_container.py and "
        "tests/scripts/test_agent_cli_copilot_review_container.py, neither of which exists",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/agent-cli/copilot-review.sh",
        reason="the agent-cli branch checks tests/scripts/test_copilot_review.py and "
        "tests/scripts/test_agent_cli_copilot_review.py, neither of which exists; the path is still tested, via the "
        "post-loop AGENT_CLI_RELEVANT match that delegates to task test:container-integration — a channel this guard "
        "cannot observe, since it equates coverage with announced pytest targets",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/agent-cli/gemini-preflight-tiered.sh",
        reason="the agent-cli branch checks tests/scripts/test_gemini_preflight_tiered.py and "
        "tests/scripts/test_agent_cli_gemini_preflight_tiered.py, neither of which exists",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/agent-cli/gemini-review-container.sh",
        reason="the agent-cli branch checks tests/scripts/test_gemini_review_container.py and "
        "tests/scripts/test_agent_cli_gemini_review_container.py, neither of which exists",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/aws_vault_auth.sh",
        reason="the scripts/-or-ci/ branch derives tests/scripts/test_aws_vault_auth.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/ledger/__init__.py",
        reason="the scripts/-or-ci/ branch derives tests/scripts/ledger/test___init__.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/orchestrator/__init__.py",
        reason="the scripts/-or-ci/ branch derives tests/scripts/orchestrator/test___init__.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/setup_env.sh",
        reason="the scripts/-or-ci/ branch derives tests/scripts/test_setup_env.py, which does not exist",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="scripts/templates/dms_task.tf.j2",
        reason="the scripts/-or-ci/ branch strips only the last suffix, deriving tests/scripts/templates/test_dms_task.tf.py",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="tests/ci/conftest.py",
        reason="the tests/ci/ branch admits only a test_*.py basename, so a conftest matches the branch but adds no target",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="tests/lint/__init__.py",
        reason="the tests/lint/ branch admits only a test_*.py basename, so this module matches the branch but adds no target",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="tests/scripts/ledger/__init__.py",
        reason="the tests/scripts/ branch admits only a test_*.py basename, so this module matches the branch but adds no target",
        todo_id="TODO-0333",
    ),
    RoutingExemption(
        router="test_changed.sh",
        path="tests/scripts/orchestrator/__init__.py",
        reason="the tests/scripts/ branch admits only a test_*.py basename, so this module matches the branch but adds no target",
        todo_id="TODO-0333",
    ),
)
