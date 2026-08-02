"""Ledger CLI wrapper for ralph headless epic runner.

Wraps ``task ledger:*`` CLI commands via subprocess. Ralph runs on the host;
the ledger runs in a container via python-cli. They communicate via CLI
invocations and JSON over stdout --- not direct imports.

Subprocess is acceptable here because ``task`` is a non-Python CLI with
no SDK equivalent.
"""

import json
import subprocess
from typing import Any

# ---------------------------------------------------------------------------
# Core CLI wrapper
# ---------------------------------------------------------------------------


def _run_task(
    task_name: str,
    positional_args: list[str],
    *,
    flag_args: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a ``task ledger:<task_name>`` command and return the result.

    Raises ``RuntimeError`` on non-zero exit code with stderr details.

    Args:
        task_name: The ledger sub-command (e.g. ``resume``, ``touch``).
        positional_args: Positional arguments forwarded after ``--``.
        flag_args: Optional flag arguments appended as ``--key value``.

    Returns:
        The completed subprocess result.
    """
    cmd: list[str] = ["task", f"ledger:{task_name}", "--"]
    cmd.extend(positional_args)
    if flag_args:
        for key, value in flag_args.items():
            if value:
                cmd.extend([f"--{key}", value])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"task ledger:{task_name} failed (exit {result.returncode}): {result.stderr.strip()}")
    return result


def parse_json_output(output: str) -> Any:
    """Extract and parse the first JSON object or array from CLI output.

    The ``task`` runner emits preamble lines (container output, security
    gate messages) before the actual JSON payload. This function scans for
    the first line starting with ``{`` or ``[`` and parses from that point.

    Args:
        output: Raw stdout from a ``task ledger:*`` invocation.

    Returns:
        Parsed JSON value (dict or list).

    Raises:
        ValueError: If no valid JSON is found in the output.
    """
    lines = output.strip().splitlines()
    json_start = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("{", "[")):
            json_start = i
            break
    if json_start == -1:
        raise ValueError(f"No JSON found in task output: {output[:500]}")
    json_text = "\n".join(lines[json_start:])
    return json.loads(json_text)


# ---------------------------------------------------------------------------
# Ledger operations
# ---------------------------------------------------------------------------


def ledger_resume(epic_id: str) -> dict[str, Any]:
    """Call ``task ledger:resume -- <epic_id>`` and parse JSON output.

    Args:
        epic_id: The epic identifier.

    Returns:
        Parsed resume context dictionary.

    Raises:
        RuntimeError: On non-zero exit from the task command.
        ValueError: If the output cannot be parsed as JSON.
    """
    result = _run_task("resume", [epic_id])
    data: dict[str, Any] = parse_json_output(result.stdout)
    return data


def ledger_touch(epic_id: str) -> None:
    """Call ``task ledger:touch -- <epic_id>`` to refresh claim heartbeat.

    Args:
        epic_id: The epic identifier.

    Raises:
        RuntimeError: On non-zero exit from the task command.
    """
    _run_task("touch", [epic_id])


def ledger_status(epic_id: str, new_status: str) -> None:
    """Call ``task ledger:status -- <epic_id> --new-status <new_status>``.

    Args:
        epic_id: The epic identifier.
        new_status: The target lifecycle status.

    Raises:
        RuntimeError: On non-zero exit from the task command.
    """
    _run_task("status", [epic_id], flag_args={"new-status": new_status})


def ledger_set_prs(epic_id: str, pr_refs_csv: str) -> None:
    """Call ``task ledger:set-prs -- <epic_id> --pr-refs <refs>``.

    Args:
        epic_id: The epic identifier.
        pr_refs_csv: Comma-separated PR refs (e.g. ``acme/brownfield-ai#42,acme/service-b#15``).

    Raises:
        RuntimeError: On non-zero exit from the task command.
    """
    _run_task("set-prs", [epic_id], flag_args={"pr-refs": pr_refs_csv})


def ledger_save(
    epic_id: str,
    artifact_type: str,
    document: str,
    *,
    metadata: str = "",
) -> None:
    """Call ``task ledger:save`` to persist an artifact.

    The document body is passed inline via the ``--content`` flag. The
    migrated CLI requires exactly one of ``--content`` / ``--content-file``
    and has no positional content slot, so ``document`` must be a non-empty
    string. ``--content-file`` mode is intentionally not used here (deferred
    to TODO-0162); ralph passes inline ``--content`` only.

    Args:
        epic_id: The epic identifier.
        artifact_type: Type of artifact (e.g. ``session_exit``).
        document: The document body content. Must be non-empty and not
            whitespace-only.
        metadata: Optional JSON string of additional metadata fields.

    Raises:
        ValueError: If ``document`` is empty or whitespace-only.
        RuntimeError: On non-zero exit from the task command.
    """
    if not document.strip():
        raise ValueError("ledger_save: document must be a non-empty string")
    fields_dict = {
        "epic_id": epic_id,
        "artifact_type": artifact_type,
        "agent_model": "ralph-runner",
    }
    _run_task(
        "save",
        [],  # no positional args after migration
        flag_args={
            "content": document,
            "fields": json.dumps(fields_dict),
            "metadata": metadata if metadata else "",
        },
    )


def ledger_query(
    epic_id: str,
    *,
    artifact_type: str = "",
    sub_plan: str = "",
    attempt: str = "",
) -> list[dict[str, Any]]:
    """Call ``task ledger:query`` with filter args and parse JSON output.

    Performs a semantic search filtered by epic and optional artifact type.
    Results are returned as a list of artifact dicts.

    Args:
        epic_id: The epic identifier.
        artifact_type: Optional artifact type filter.
        sub_plan: Optional sub-plan label filter.
        attempt: Optional attempt number filter.

    Returns:
        List of matching artifact dictionaries.

    Raises:
        RuntimeError: On non-zero exit from the task command.
    """
    filters: dict[str, str] = {"epic_id": epic_id}
    if artifact_type:
        filters["artifact_type"] = artifact_type
    if sub_plan:
        filters["sub_plan"] = sub_plan
    if attempt:
        filters["attempt"] = attempt
    result = _run_task(
        "query",
        [f"epic {epic_id} artifacts"],
        flag_args={"filters": json.dumps(filters)},
    )
    try:
        items: list[dict[str, Any]] = parse_json_output(result.stdout)
        return items
    except (ValueError, json.JSONDecodeError):
        return []


def ledger_filter(
    epic_id: str,
    *,
    artifact_type: str = "",
    sub_plan: str = "",
    attempt: str = "",
    verdict: str = "",
    artifact_status: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Call ``task ledger:filter`` with metadata filters and parse JSON output.

    Performs a deterministic metadata lookup (not semantic search).
    Results are returned as a list of artifact dicts sorted newest-first.

    Args:
        epic_id: The epic identifier.
        artifact_type: Optional artifact type filter.
        sub_plan: Optional sub-plan label filter.
        attempt: Optional attempt number filter.
        verdict: Optional verdict filter.
        artifact_status: Optional artifact status filter.
        limit: Maximum number of results.

    Returns:
        List of matching artifact dictionaries.

    Raises:
        RuntimeError: On non-zero exit from the task command.
    """
    flag_args: dict[str, str] = {}
    if artifact_type:
        flag_args["artifact-type"] = artifact_type
    if sub_plan:
        flag_args["sub-plan"] = sub_plan
    if attempt:
        flag_args["attempt"] = attempt
    if verdict:
        flag_args["verdict"] = verdict
    if artifact_status:
        flag_args["artifact-status"] = artifact_status
    if limit != 50:
        flag_args["limit"] = str(limit)
    result = _run_task("filter", [epic_id], flag_args=flag_args if flag_args else None)
    try:
        items: list[dict[str, Any]] = parse_json_output(result.stdout)
        return items
    except (ValueError, json.JSONDecodeError):
        return []


def get_latest_session_exit(
    epic_id: str,
    sub_plan_label: str,
    attempt: int,
) -> dict[str, Any] | None:
    """Query for the most recent ``session_exit`` artifact for a sub-plan attempt.

    Filters by BOTH ``sub_plan`` AND ``attempt`` to avoid reading a prior
    attempt's exit artifact.

    Args:
        epic_id: The epic identifier.
        sub_plan_label: The sub-plan label (e.g. ``"A"``).
        attempt: The attempt number (1-based).

    Returns:
        The latest matching session_exit artifact dict, or ``None`` if
        no matching artifact is found.
    """
    artifacts = ledger_filter(
        epic_id,
        artifact_type="session_exit",
        sub_plan=sub_plan_label,
        attempt=str(attempt),
    )
    if not artifacts:
        return None
    return artifacts[0]


# ---------------------------------------------------------------------------
# Parsing utilities
# ---------------------------------------------------------------------------


def parse_sub_plans(plan_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse pipe-delimited ``sub_plans`` from plan_snapshot metadata.

    Format: ``"A:0,1|B:2,3|C:4,5,6,QA"``

    Split on ``|``, then ``:`` --- left is the label, right is a
    comma-separated list of wave IDs.

    Wave IDs are **opaque strings** --- they are never cast to ``int``
    (e.g. ``"3a"``, ``"3b"`` are valid).

    Args:
        plan_snapshot: The plan_snapshot dict containing ``metadata``
            with a ``sub_plans`` key.

    Returns:
        List of dicts with ``"label"`` and ``"waves"`` keys.
    """
    metadata = plan_snapshot.get("metadata", {})
    raw = metadata.get("sub_plans", "")
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for segment in raw.split("|"):
        label, _, waves_csv = segment.partition(":")
        waves = [w.strip() for w in waves_csv.split(",") if w.strip()]
        result.append({"label": label.strip(), "waves": waves})
    return result


def serialize_sub_plans(sub_plans: list[dict[str, Any]]) -> str:
    """Round-trip serialize sub_plans back to pipe-delimited format.

    Inverse of :func:`parse_sub_plans`. Satisfies the invariant::

        serialize_sub_plans(parse_sub_plans(s)) == s

    Args:
        sub_plans: List of dicts with ``"label"`` and ``"waves"`` keys.

    Returns:
        Pipe-delimited string representation.
    """
    segments: list[str] = []
    for sp in sub_plans:
        waves_csv = ",".join(sp["waves"])
        segments.append(f"{sp['label']}:{waves_csv}")
    return "|".join(segments)


def parse_branches(branches_str: str) -> dict[str, str]:
    """Parse pipe-delimited branches from plan_snapshot metadata.

    Format: ``"brownfield-ai:feat/ACME-1234|service-b:feat/ACME-1234-sub"``

    Split on ``|``, then ``:`` --- left is the repo key, right is the
    branch name.

    **Empty input contract**: ``parse_branches("")`` returns ``{}``.

    Args:
        branches_str: The pipe-delimited branches string.

    Returns:
        Dict mapping repo key to branch name.
    """
    if not branches_str or not branches_str.strip():
        return {}
    result: dict[str, str] = {}
    for segment in branches_str.split("|"):
        repo, _, branch = segment.partition(":")
        if repo.strip() and branch.strip():
            result[repo.strip()] = branch.strip()
    return result


def serialize_branches(branches: dict[str, str]) -> str:
    """Round-trip serialize branches back to pipe-delimited format.

    Inverse of :func:`parse_branches`.

    Args:
        branches: Dict mapping repo key to branch name.

    Returns:
        Pipe-delimited string representation.
    """
    return "|".join(f"{repo}:{branch}" for repo, branch in branches.items())
