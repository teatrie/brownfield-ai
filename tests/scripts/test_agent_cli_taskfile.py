"""Tests for taskfiles/agent-cli.yml — CLI_ARGS shim architecture.

The previous architecture threaded caller-supplied values through each
review task's ``env:`` map using ``'{{.VAR}}'`` Go templates. That path
was replaced by a dedicated shim, ``scripts/agent-cli/cli-args-to-env.sh``,
which now owns the entire validation surface:

- Callers pass values as ``task <target> -- KEY=value KEY=value`` and
  Task exposes the trailing tokens as ``{{.CLI_ARGS}}``.
- The shim validates each token against a key allowlist regex and a
  value-character allowlist regex, then ``exec env`` into the target
  command. This closes the ``$(...)``/backtick injection surface that
  the previous ``env:`` map relied on ``os.Setenv`` to avoid.
- Review recipes therefore no longer declare ``vars:`` blocks: the shim
  carries all caller-supplied values forward. The ``env:`` map is now
  reserved for static execution-context markers
  (``GEMINI_EXECUTION_CONTEXT=host`` and ``CODEX_EXECUTION_CONTEXT=host``).

Invariants preserved from the previous architecture:
- The three secrets (``OPENAI_API_KEY``, ``GEMINI_API_KEY``,
  ``COPILOT_GITHUB_TOKEN``) MUST NOT appear in any task's ``env:`` map
  and MUST remain bare ``-e VAR`` tokens so they are inherited from the
  caller's shell only. This is the plan-mandated secret boundary.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml

WORKSPACE = Path(__file__).resolve().parents[2]
TASKFILE = WORKSPACE / "taskfiles" / "agent-cli.yml"

SECRETS = {"OPENAI_API_KEY", "GEMINI_API_KEY", "COPILOT_GITHUB_TOKEN"}

# Pattern splits a ``-e NAME`` or ``-e NAME=...`` token. Interpolated form
# is ``-e NAME={{.NAME}}``; bare form is ``-e NAME`` with no ``=``.
_E_FLAG_RE = re.compile(r"-e\s+([A-Z_][A-Z0-9_]*)(=\S+)?")


def _load_taskfile() -> dict:
    """Load taskfiles/agent-cli.yml as a parsed YAML document."""
    with TASKFILE.open() as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"Taskfile root must be a mapping, got {type(data).__name__}"
    return data


def _extract_e_flags() -> list[tuple[str, str, str]]:
    """Return a list of ``(task_name, var_name, value_or_empty)`` tuples.

    Iterates every task's cmds (strings only), parses ``-e VAR`` tokens.
    ``value_or_empty`` is the full ``=...`` suffix (e.g., ``={{.VAR}}``) or
    the empty string for bare ``-e VAR`` tokens.
    """
    data = _load_taskfile()
    result: list[tuple[str, str, str]] = []
    for task_name, task_body in data.get("tasks", {}).items():
        cmds = task_body.get("cmds", []) if isinstance(task_body, dict) else []
        for cmd in cmds:
            if not isinstance(cmd, str):
                continue
            for match in _E_FLAG_RE.finditer(cmd):
                var_name = match.group(1)
                suffix = match.group(2) or ""
                result.append((task_name, var_name, suffix))
    return result


# ---------------------------------------------------------------------------
# YAML validity + structural assertions
# ---------------------------------------------------------------------------


def test_taskfile_parses_as_yaml() -> None:
    """Taskfile must be valid YAML."""
    data = _load_taskfile()
    assert "tasks" in data
    assert isinstance(data["tasks"], dict)


def test_secrets_remain_bare_and_not_in_env_map() -> None:
    """The three secrets MUST continue using bare ``-e VAR`` and MUST NOT
    appear in any task's ``env:`` map.

    This is the plan-mandated security boundary: embedding a secret in
    the Taskfile YAML (even via template) exposes its value in dry-run
    output, logs, or CI inspection. Secrets are inherited from the
    caller's shell environment only.
    """
    # Part 1: every secret reference in cmds must be bare (no = suffix).
    e_flags = _extract_e_flags()
    for task_name, var_name, suffix in e_flags:
        if var_name in SECRETS:
            assert suffix == "", f"Secret {var_name} in task {task_name} must be bare (``-e {var_name}``), got ``-e {var_name}{suffix}``"

    # Part 2: no secret may appear in any task's env: map.
    data = _load_taskfile()
    for task_name, task_body in data.get("tasks", {}).items():
        if not isinstance(task_body, dict):
            continue
        env_map = task_body.get("env", {}) or {}
        if not isinstance(env_map, dict):
            continue
        for key in env_map:
            assert key not in SECRETS, (
                f"Secret {key} must not appear in task {task_name}'s env: map (plan-mandated boundary — secrets use bare -e VAR only)"
            )


# ---------------------------------------------------------------------------
# CLI_ARGS shim architecture assertions
# ---------------------------------------------------------------------------


# TODO-0092 Phase A renamed every review recipe to the axis-first form
# (``review:<family>[:local]``) and the preflight recipes to
# ``preflight:<family>``. The wrapper contract also migrated from
# caller-supplied ``PROMPT_FILE``/``REVIEW_PROMPT_FILE``/``REVIEW_DIFF_FILE``
# to the ``REVIEW_TYPE=<enum>`` + ``DIFF_FILE=<path>`` pair that the shared
# ``_review-common.sh`` helpers enforce. The allowlisted-key sets below
# reflect that migration.
REVIEW_TASKS: tuple[str, ...] = (
    "review:copilot",
    "review:gemini",
    "review:codex",
    "review:gemini:local",
    "review:codex:local",
)

# Canonical allowlisted key set advertised in each review task's desc.
REVIEW_TASK_DESC_KEYS: dict[str, tuple[str, ...]] = {
    "review:copilot": ("ROUND", "REVIEW_TYPE", "DIFF_FILE"),
    "review:gemini": (
        "ROUND",
        "EFFORT",
        "REVIEW_SESSION_ID",
        "WORKSPACE",
        "REVIEW_TYPE",
        "DIFF_FILE",
        "GEMINI_MODEL",
        "GEMINI_TIMEOUT",
    ),
    "review:codex": (
        "ROUND",
        "EFFORT",
        "REVIEW_SESSION_ID",
        "WORKSPACE",
        "MODEL",
        "REVIEW_TYPE",
        "DIFF_FILE",
    ),
    "review:gemini:local": (
        "ROUND",
        "EFFORT",
        "REVIEW_SESSION_ID",
        "WORKSPACE",
        "REVIEW_TYPE",
        "DIFF_FILE",
        "GEMINI_MODEL",
        "GEMINI_TIMEOUT",
    ),
    "review:codex:local": (
        "ROUND",
        "EFFORT",
        "REVIEW_SESSION_ID",
        "WORKSPACE",
        "MODEL",
        "REVIEW_TYPE",
        "DIFF_FILE",
    ),
}

# Under the target-first shim signature each review task routes through
# the shim with a per-task target script path. The shim token is
# therefore the prefix up to and including the target path; the
# ``{{.CLI_ARGS}}`` expansion trails the target.
SHIM_PREFIX = "scripts/agent-cli/cli-args-to-env.sh"

REVIEW_TASK_TARGETS: dict[str, str] = {
    "review:copilot": "scripts/agent-cli/copilot-review-container.sh",
    "review:gemini": "scripts/agent-cli/gemini-review-container.sh",
    "review:codex": "scripts/agent-cli/codex-review-container.sh",
    "review:gemini:local": "scripts/agent-cli/gemini-review.sh",
    "review:codex:local": "scripts/agent-cli/codex-review.sh",
}


def _joined_cmds(task_name: str) -> str:
    """Join all string ``cmds`` entries for a task into a single whitespace-
    collapsed buffer suitable for substring checks.
    """
    data = _load_taskfile()
    task_body = data["tasks"].get(task_name, {})
    cmds = task_body.get("cmds", []) if isinstance(task_body, dict) else []
    joined = " ".join(cmd for cmd in cmds if isinstance(cmd, str))
    # Collapse runs of whitespace so YAML line-folded ``>-`` blocks compare
    # as a single logical command.
    return re.sub(r"\s+", " ", joined).strip()


def test_review_tasks_route_cli_args_through_shim() -> None:
    """Every review task's ``cmds:`` must invoke the CLI_ARGS shim.

    The exact token sequence
    ``scripts/agent-cli/cli-args-to-env.sh <target> {{.CLI_ARGS}}``
    MUST appear in the task's commands. This is the single choke point
    that validates caller-supplied ``KEY=value`` tokens before they reach
    any downstream script or ``docker compose run`` invocation.
    """
    missing: list[str] = []
    for task_name, target in REVIEW_TASK_TARGETS.items():
        joined = _joined_cmds(task_name)
        expected = f"{SHIM_PREFIX} {target} " + "{{.CLI_ARGS}}"
        if expected not in joined:
            missing.append(f"{task_name}: expected shim invocation {expected!r} not found in cmds; got {joined!r}")
    assert not missing, "Review tasks missing the CLI_ARGS shim invocation: " + "; ".join(missing)


def test_review_tasks_advertise_allowlisted_keys_in_desc() -> None:
    """Each review task's ``desc:`` must document its allowlisted keys.

    The canonical key set for each task is duplicated in the shim's
    ``ALLOWED_KEYS_REGEX``. Documenting the subset in the task ``desc:``
    keeps callers discoverable without having to read the shim source.
    """
    data = _load_taskfile()
    missing: list[str] = []
    for task_name, required_keys in REVIEW_TASK_DESC_KEYS.items():
        task_body = data["tasks"].get(task_name)
        assert task_body is not None, f"task {task_name} missing from Taskfile"
        desc = task_body.get("desc", "")
        assert isinstance(desc, str), f"task {task_name} desc must be a string"
        for key in required_keys:
            if key not in desc:
                missing.append(f"{task_name}:desc missing key {key}")
    assert not missing, "Review tasks missing allowlisted-key mentions in desc: " + "; ".join(missing)


def test_copilot_review_uses_container_wrapper() -> None:
    """``review:copilot`` delegates to the container wrapper script.

    The recipe must invoke ``scripts/agent-cli/copilot-review-container.sh``
    rather than inlining a ``docker compose run`` command. Keeping the
    docker invocation inside a wrapper lets the shim validate its
    ``CLI_ARGS`` token list without leaking docker flags through
    ``cli-args-to-env.sh``'s value regex.
    """
    joined = _joined_cmds("review:copilot")
    assert "scripts/agent-cli/copilot-review-container.sh" in joined, (
        f"review:copilot must delegate to scripts/agent-cli/copilot-review-container.sh; cmds resolved to: {joined!r}"
    )
    # Inline docker compose invocation must NOT appear at the top level of the recipe.
    assert "docker compose run" not in joined, (
        "review:copilot must not inline `docker compose run` — delegate to the container wrapper script instead"
    )


def test_gemini_review_uses_container_wrapper() -> None:
    """``review:gemini`` delegates to the container wrapper script.

    Under the target-first shim signature, any recipe that needs a
    multi-word invocation (``docker compose run ...``) MUST route it
    through a wrapper script — the shim executes a single target path.
    """
    joined = _joined_cmds("review:gemini")
    assert "scripts/agent-cli/gemini-review-container.sh" in joined, (
        f"review:gemini must delegate to scripts/agent-cli/gemini-review-container.sh; cmds resolved to: {joined!r}"
    )
    assert "docker compose run" not in joined, (
        "review:gemini must not inline `docker compose run` — delegate to the container wrapper script instead"
    )


def test_codex_review_uses_container_wrapper() -> None:
    """``review:codex`` delegates to the container wrapper script.

    Same target-first constraint as review:gemini and review:copilot:
    multi-word commands live in wrappers so the shim target is always
    a single-word script path.
    """
    joined = _joined_cmds("review:codex")
    assert "scripts/agent-cli/codex-review-container.sh" in joined, (
        f"review:codex must delegate to scripts/agent-cli/codex-review-container.sh; cmds resolved to: {joined!r}"
    )
    assert "docker compose run" not in joined, (
        "review:codex must not inline `docker compose run` — delegate to the container wrapper script instead"
    )


CODEX_REVIEW_ALIAS_COMMANDS: dict[str, str] = {
    task_name: f"{SHIM_PREFIX} {REVIEW_TASK_TARGETS[task_name]} " + "{{.CLI_ARGS}}" for task_name in ("review:codex", "review:codex:local")
}

CODEX_REVIEW_ALIAS_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "review:codex": frozenset({"desc", "cmds"}),
    "review:codex:local": frozenset({"desc", "env", "cmds"}),
}


def _exit_status_masking_offenders(tasks: dict[str, object]) -> list[str]:
    """Return how each codex review alias in ``tasks`` departs from its bare shim invocation.

    Each alias must run exactly one plain-string cmd equal, after whitespace
    normalisation, to its shim invocation. A mapping cmd is rejected
    outright: that is the form that carries a cmd-level ``ignore_error``.
    Task-level keys outside the allowlist are rejected: a satisfied
    ``status:`` skips the cmd and go-task exits 0.
    """
    offenders: list[str] = []
    for task_name, expected in CODEX_REVIEW_ALIAS_COMMANDS.items():
        task_body = tasks.get(task_name)
        if not isinstance(task_body, dict):
            offenders.append(f"{task_name} is not defined")
            continue
        unexpected_keys = sorted(set(task_body) - CODEX_REVIEW_ALIAS_ALLOWED_KEYS[task_name])
        if unexpected_keys:
            offenders.append(f"{task_name} sets keys outside its allowlist: {unexpected_keys}")
        cmds = task_body.get("cmds")
        if not isinstance(cmds, list) or len(cmds) != 1:
            offenders.append(f"{task_name} must have exactly one cmd, got {cmds!r}")
            continue
        cmd = cmds[0]
        if not isinstance(cmd, str):
            offenders.append(f"{task_name} cmd must be a plain string, got {cmd!r}")
            continue
        normalised = re.sub(r"\s+", " ", cmd).strip()
        if normalised != expected:
            offenders.append(f"{task_name} cmd must be exactly {expected!r}, got {normalised!r}")
    return offenders


def test_codex_review_tasks_do_not_mask_the_wrapper_exit_status() -> None:
    """The codex review aliases must fail whenever the wrapper fails.

    The wrapper exits non-zero on every CODEX_ERROR, and callers gate on
    the alias's status. go-task exits non-zero (observed: 201, not
    the cmd's own status) when a cmd fails, including one followed by
    ``; true``, and runs no later cmd. A cmd-level ``ignore_error`` or a
    trailing ``|| true`` (both observed: exit 0) turns a failed review into
    a pass, so the recipe must be the bare shim invocation.

    Baseline: this reads the recipe text only, so it passes whatever the
    wrapper exits; pairs with ``test_exit_status_guard_rejects_masking_recipes``
    and ``test_codex_review.py::test_failed_review_fails_the_shim_pair``.
    """
    offenders = _exit_status_masking_offenders(_load_taskfile()["tasks"])
    assert not offenders, "Codex review aliases must not mask a failed wrapper run: " + "; ".join(offenders)


@pytest.mark.parametrize(
    ("task_name", "mutation"),
    [
        ("review:codex", {"cmds": [CODEX_REVIEW_ALIAS_COMMANDS["review:codex"] + "; true"]}),
        ("review:codex:local", {"cmds": [CODEX_REVIEW_ALIAS_COMMANDS["review:codex:local"] + " || true"]}),
        ("review:codex:local", {"cmds": [CODEX_REVIEW_ALIAS_COMMANDS["review:codex:local"], "true"]}),
        ("review:codex", {"cmds": [{"cmd": CODEX_REVIEW_ALIAS_COMMANDS["review:codex"], "ignore_error": True}]}),
        ("review:codex", {"cmds": [CODEX_REVIEW_ALIAS_COMMANDS["review:codex"]], "ignore_error": True}),
        ("review:codex:local", {"status": ["true"]}),
        ("review:codex", {"platforms": ["windows"]}),
    ],
    ids=["semicolon_true", "or_true", "second_cmd", "cmd_ignore_error", "task_ignore_error", "task_status", "task_platforms"],
)
def test_exit_status_guard_rejects_masking_recipes(task_name: str, mutation: dict[str, object]) -> None:
    """The guard above must reject each recipe shape that departs from the bare shim invocation."""
    tasks = copy.deepcopy(_load_taskfile()["tasks"])
    tasks[task_name].update(mutation)
    assert _exit_status_masking_offenders(tasks), f"guard accepted a masking recipe for {task_name}: {mutation!r}"


def test_local_tasks_preserve_execution_context_env() -> None:
    """Host-mode review tasks set the execution-context marker env var.

    These static markers are the one legitimate use of the task ``env:``
    map under the new architecture. They are not caller-supplied values,
    they are fixed constants that downstream scripts read to distinguish
    container vs host execution (e.g., to skip the OpenAI token guard
    when running with local Codex OAuth).
    """
    data = _load_taskfile()

    gemini_local = data["tasks"].get("review:gemini:local")
    assert isinstance(gemini_local, dict), "review:gemini:local must be defined"
    gemini_env = gemini_local.get("env")
    assert isinstance(gemini_env, dict), "review:gemini:local must declare an env: map"
    assert gemini_env.get("GEMINI_EXECUTION_CONTEXT") == "host", (
        f"review:gemini:local must set GEMINI_EXECUTION_CONTEXT=host in env:, got {gemini_env!r}"
    )

    codex_local = data["tasks"].get("review:codex:local")
    assert isinstance(codex_local, dict), "review:codex:local must be defined"
    codex_env = codex_local.get("env")
    assert isinstance(codex_env, dict), "review:codex:local must declare an env: map"
    assert codex_env.get("CODEX_EXECUTION_CONTEXT") == "host", (
        f"review:codex:local must set CODEX_EXECUTION_CONTEXT=host in env:, got {codex_env!r}"
    )


def test_review_tasks_have_no_vars_block() -> None:
    """Review tasks must NOT declare a ``vars:`` block.

    Under the CLI_ARGS shim architecture the shim carries every
    caller-supplied value forward via ``env``. A lingering ``vars:``
    block would indicate a stale Go-template-driven recipe that the
    migration missed.
    """
    data = _load_taskfile()
    offenders: list[str] = []
    for task_name in REVIEW_TASKS:
        task_body = data["tasks"].get(task_name, {})
        if not isinstance(task_body, dict):
            continue
        if "vars" in task_body:
            offenders.append(f"{task_name} still declares vars: {task_body['vars']!r}")
    assert not offenders, "Review tasks must not declare vars: blocks under the CLI_ARGS shim architecture. Offenders: " + "; ".join(
        offenders
    )
