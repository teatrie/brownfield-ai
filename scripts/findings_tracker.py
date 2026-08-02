"""Helper functions for diff-review findings tracking and TODO capture.

Provides findings ledger management, inline-code marker detection,
and marker-to-priority mapping for the diff-review skill.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import defopt

# Mapping of marker keywords to numeric priorities.
# Lower numbers indicate higher priority.
MARKER_PRIORITY_MAP: dict[str, int] = {
    "HACK": 2,
    "XXX": 2,
    "FIXME": 3,
    "TODO": 5,
}

# Regex pattern to match inline code markers (case-insensitive).
MARKER_PATTERN: re.Pattern[str] = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

# Regex pattern to match git diff hunk headers.
HUNK_PATTERN: re.Pattern[str] = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "significant": 3,
    "minor": 2,
    "informational": 1,
    # Aliases for generic 3-tier reviewer scales (high/medium/low).
    # "high" maps to 3 (significant), not 4 (critical), because free-form
    # "high" in a generic scale corresponds to the second-highest canonical
    # level — reviewers who mean critical will say "critical".
    "high": 3,
    "medium": 2,
    "low": 1,
}

# Guard: aliases must never exceed their canonical equivalents.
if SEVERITY_RANK["high"] > SEVERITY_RANK["significant"]:
    raise ValueError("high must not exceed significant")
if SEVERITY_RANK["medium"] > SEVERITY_RANK["minor"]:
    raise ValueError("medium must not exceed minor")
if SEVERITY_RANK["low"] > SEVERITY_RANK["informational"]:
    raise ValueError("low must not exceed informational")


def create(
    finding_id: str,
    reviewer: str,
    severity: str,
    description: str,
    round_num: int,
    *,
    confidence: int = 0,
) -> dict[str, Any]:
    """Create a new finding dict with status set to 'unresolved'.

    Args:
        finding_id: Unique identifier for this finding.
        reviewer: Name or identifier of the reviewer who raised the finding.
        severity: Severity level of the finding (e.g., 'critical', 'significant',
            'minor', 'informational').
        description: Human-readable description of the finding.
        round_num: Review round number in which this finding was raised.
        confidence: Reviewer's confidence score: 0 (unscored/legacy, the default)
            or 1-10 where 10 is highest certainty.

    Returns:
        A finding dict with all fields populated and status 'unresolved'.
    """
    if confidence != 0 and not (1 <= confidence <= 10):
        msg = f"confidence must be 0 (unscored) or 1-10, got {confidence}"
        raise ValueError(msg)
    return {
        "finding_id": finding_id,
        "reviewer": reviewer,
        "severity": severity,
        "description": description,
        "round": round_num,
        "status": "unresolved",
        "confidence": confidence,
    }


def update_status(
    findings: list[dict[str, Any]],
    finding_id: str,
    new_status: str,
    *,
    resolution: str = "",
    validators_count: int = 0,
    total_reviewers: int = 0,
) -> list[dict[str, Any]]:
    """Update the status of a finding identified by finding_id.

    Args:
        findings: List of finding dicts to search through.
        finding_id: The ID of the finding to update.
        new_status: The new status value to set.
        resolution: Optional resolution label (e.g. 'no-action-validated',
            'doc-or-todo-validated', 'code-change'). When non-empty the
            resolution metadata fields are written to the finding dict.
        validators_count: Number of reviewers who accepted the finding.
            Only stored when *resolution* is provided.
        total_reviewers: Total number of reviewers in the gate.
            Only stored when *resolution* is provided.

    Returns:
        The updated list of finding dicts.

    Raises:
        ValueError: If no finding with finding_id exists in the list.
    """
    for finding in findings:
        if finding["finding_id"] == finding_id:
            finding["status"] = new_status
            if resolution:
                finding["resolution"] = resolution
                finding["validators_count"] = validators_count
                finding["total_reviewers"] = total_reviewers
            return findings
    raise ValueError(f"Finding with id '{finding_id}' not found.")


def filter_unresolved(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only findings whose status is 'unresolved'.

    Legacy findings missing a ``status`` field are treated as unresolved
    (default), matching :func:`filter_active`. This provides backward
    compatibility with ledger entries created before the ``status`` field
    became a standard component of :func:`create`.

    Args:
        findings: List of finding dicts to filter.

    Returns:
        A list containing only findings with status 'unresolved'.
    """
    return [f for f in findings if f.get("status", "unresolved") == "unresolved"]


def filter_no_action_validated(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only findings whose resolution is 'no-action-validated'.

    Uses ``.get()`` with a default because ``create()`` does not include
    the ``resolution`` key — findings that were never updated via
    ``update_status()`` will lack it.

    Args:
        findings: List of finding dicts to filter.

    Returns:
        A list containing only findings with resolution 'no-action-validated'.
    """
    return [f for f in findings if f.get("resolution", "") == "no-action-validated"]


def filter_doc_or_todo_validated(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only findings whose resolution is 'doc-or-todo-validated'.

    Uses ``.get()`` with a default because ``create()`` does not include
    the ``resolution`` key — findings that were never updated via
    ``update_status()`` will lack it.

    Args:
        findings: List of finding dicts to filter.

    Returns:
        A list containing only findings with resolution 'doc-or-todo-validated'.
    """
    return [f for f in findings if f.get("resolution", "") == "doc-or-todo-validated"]


def filter_active(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return findings eligible for resolution (excludes resolved and merged).

    Use this instead of ``filter_unresolved()`` after calling
    ``merge_duplicate_findings()`` to make the post-merge iteration
    intent explicit. ``filter_unresolved()`` uses a closed positive
    equality check (``status == "unresolved"``) that is functionally
    equivalent today, but would exclude findings in any hypothetical
    future active status. ``filter_active()`` uses an open-world
    exclusion that only drops explicitly terminal statuses and is
    therefore forward-compatible.

    Args:
        findings: List of finding dicts to filter.

    Returns:
        A list containing only findings with active status.
    """
    return [f for f in findings if f.get("status", "unresolved") not in ("resolved", "merged")]


def load(path: Path) -> list[dict[str, Any]]:
    """Load findings from a JSON file at the given path.

    Args:
        path: Filesystem path to the JSON findings file.

    Returns:
        A list of finding dicts loaded from the file, or an empty list if the
        file does not exist.
    """
    if not path.exists():
        return []
    try:
        data: list[dict[str, Any]] = json.loads(path.read_text())
        return data
    except json.JSONDecodeError:
        return []


def save(findings: list[dict[str, Any]], path: Path) -> None:
    """Persist findings to a JSON file at the given path.

    Writes via a sibling ``<path>.tmp`` + ``os.replace`` so readers
    observe either the old file or the fully-written new file, never a
    torn-read mid-write. On POSIX, ``rename(2)`` is atomic for
    same-directory targets; durability against a hard OS crash is
    weaker because this path does not call ``fsync`` on either the tmp
    file or the parent directory (findings are regenerable, so the
    added syscall cost is not worth the hardening).

    Args:
        findings: List of finding dicts to serialise.
        path: Filesystem path at which to write the JSON file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def parse_diff_markers(diff_text: str) -> list[dict[str, Any]]:
    """Scan git diff output for added lines containing TODO/FIXME/HACK/XXX markers.

    Only lines starting with a single '+' (added lines) are examined. Lines
    starting with '+++' (diff header) are excluded. The function is
    case-insensitive with respect to the marker keyword.

    Args:
        diff_text: Full text of a git diff output.

    Returns:
        A list of dicts, each with keys:
            - 'marker' (str): The matched marker keyword as found in the source.
            - 'line' (str): The full added line (including the leading '+').
            - 'line_number' (int): Line number derived from the nearest diff
              hunk header (@@ -a,b +c,d @@) preceding the matched line.
    """
    results: list[dict[str, Any]] = []
    current_line: int = 0

    for line in diff_text.splitlines():
        hunk_match = HUNK_PATTERN.match(line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if line.startswith("+++") or line.startswith("---"):
            continue

        if line.startswith("+"):
            marker_match = MARKER_PATTERN.search(line)
            if marker_match:
                results.append({
                    "marker": marker_match.group(1),
                    "line": line,
                    "line_number": current_line,
                })
            current_line += 1
        elif line.startswith("-"):
            # Removed lines do not advance the new-file line counter
            pass
        elif line.startswith(" "):
            # Context line: advance counter
            current_line += 1
        # else: diff metadata lines (e.g., "\ No newline at end of file") — ignore

    return results


def marker_to_priority(marker: str) -> int:
    """Map a marker keyword to a numeric priority.

    Priority scale:
        HACK  -> 2
        XXX   -> 2
        FIXME -> 3
        TODO  -> 5

    The lookup is case-insensitive. Unknown markers default to 5.

    Args:
        marker: The marker string to look up (e.g. 'TODO', 'fixme').

    Returns:
        Integer priority value for the given marker.
    """
    return MARKER_PRIORITY_MAP.get(marker.upper(), 5)


def validated_finding_priority(validators_count: int, total_reviewers: int) -> int:
    """Compute TODO priority for a validated finding.

    Applies to both ``no-action-validated`` and ``doc-or-todo-validated``
    resolutions.

    Priority mapping:
        - All reviewers accepted (validators_count == total_reviewers) -> 4
        - Partial acceptance (validators_count < total_reviewers) -> 3
        - Orchestrator only, no reviewer validation (validators_count == 0) -> 2

    Args:
        validators_count: Number of reviewers who accepted the finding.
        total_reviewers: Total number of reviewers in the gate.

    Returns:
        Integer priority value (2, 3, or 4).

    Raises:
        ValueError: If validators_count or total_reviewers is negative,
            if total_reviewers is zero, or if validators_count exceeds
            total_reviewers.
    """
    if validators_count < 0 or total_reviewers < 0:
        msg = f"Counts must be non-negative: validators_count={validators_count}, total_reviewers={total_reviewers}"
        raise ValueError(msg)
    if total_reviewers == 0:
        msg = f"total_reviewers must be positive, got {total_reviewers}"
        raise ValueError(msg)
    if validators_count > total_reviewers:
        msg = f"validators_count ({validators_count}) cannot exceed total_reviewers ({total_reviewers})"
        raise ValueError(msg)
    if validators_count == 0:
        return 2
    if validators_count < total_reviewers:
        return 3
    return 4


def severity_rank(severity: str) -> int:
    """Return the numeric rank for a severity string.

    Higher rank means more severe. Unknown severities default to 0.

    Canonical severities: critical (4), significant (3), minor (2),
    informational (1). Alias mappings: high (3), medium (2), low (1).
    Lookup is case-insensitive. Same-rank ties (e.g., ``"significant"``
    vs ``"high"``) resolve to whichever appears first in the
    ``findings`` list passed to ``merge_duplicate_findings``.

    Args:
        severity: Severity string to look up.

    Returns:
        Integer rank value for the given severity.
    """
    return SEVERITY_RANK.get(severity.lower(), 0)


def find_duplicates_by_anchor(
    findings: list[dict[str, Any]],
    *,
    anchor_keys: tuple[str, ...] = ("file_path", "line_range"),
) -> list[list[str]]:
    """Group finding IDs that share the same anchor tuple.

    Returns a list of duplicate-ID groups (each inner list is suitable
    as the ``duplicate_ids`` argument to
    :func:`merge_duplicate_findings`). Singletons are not returned;
    only anchors with two or more findings appear in the output.
    Outer-list and inner-list ordering both preserve first-seen
    appearance in *findings*.

    Anchor extraction reads the values of *anchor_keys* in order from
    each finding dict. Findings whose anchor tuple contains any
    ``None`` value (i.e. at least one anchor key is missing or
    explicitly null) are skipped so callers cannot accidentally
    collapse anchor-less findings together — the canonical
    :func:`create` shape carries no ``file_path``/``line_range``
    fields, so feeding a vanilla findings ledger to this helper with
    the default *anchor_keys* yields an empty group list, which is the
    correct behavior (those findings have no anchor to dedup on).

    Args:
        findings: List of finding dicts. Each finding MUST carry a
            ``finding_id`` field — the canonical identifier produced by
            :func:`create` and consumed by :func:`merge_duplicate_findings`;
            findings without ``finding_id`` are skipped (not grouped) so
            callers cannot accidentally merge unidentified findings.
        anchor_keys: Tuple of dict keys whose values form the anchor
            tuple. Defaults to ``("file_path", "line_range")``, which
            matches the cross-family per-wave triad dedup contract
            (RVW-001 v6 Req-022). Pass keyword-only — positional callers
            raise ``TypeError`` to surface signature drift.

    Returns:
        List of duplicate-ID groups. Empty list when *findings* contains
        no duplicates under the given *anchor_keys*.
    """
    groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for finding in findings:
        finding_id = finding.get("finding_id")
        if finding_id is None:
            continue
        anchor = tuple(finding.get(key) for key in anchor_keys)
        if any(value is None for value in anchor):
            continue
        groups[anchor].append(finding_id)
    return [ids for ids in groups.values() if len(ids) > 1]


def merge_duplicate_findings(
    findings: list[dict[str, Any]],
    duplicate_ids: list[str],
) -> list[dict[str, Any]]:
    """Merge findings identified as duplicates using the highest-holds rule.

    Mutates *findings* in place and returns the same list for method-chaining
    convenience.

    After calling this function, prefer ``filter_active()`` over
    ``filter_unresolved()`` for post-merge iteration. Both exclude
    merged entries today, but ``filter_active()`` uses an open-world
    exclusion that remains correct if future non-terminal statuses
    are added — see ``filter_active``'s docstring for details.

    The first ID in *duplicate_ids* is treated as the canonical finding.
    Its severity is promoted to the maximum severity among all duplicates
    (highest-holds). Its confidence is also promoted to the maximum
    confidence among all duplicates; findings that omit the ``confidence``
    field are treated as 0 (unscored). Remaining entries are marked as
    ``"merged"`` with a back-reference to the canonical ID.

    Severity comparison is case-insensitive via :func:`severity_rank`.
    The winning finding's severity string is preserved verbatim on the
    canonical entry — including alias forms (e.g., ``"high"`` is kept
    as-is, not normalized to ``"significant"``). Callers MUST use
    :func:`severity_rank` for any severity comparison rather than
    string equality. Unrecognized severities default to rank 0 and
    tie-break on ledger insertion order.

    Args:
        findings: List of finding dicts to search through. Modified in place.
        duplicate_ids: Ordered list of finding IDs to merge. Must contain
            at least 2 entries. The first entry becomes the canonical finding.

    Returns:
        The same *findings* list (mutated in place).

    Raises:
        ValueError: If fewer than 2 IDs are provided, if any ID appears
            more than once, if any ID is not found in *findings*, if
            any finding to be merged is not in 'unresolved' status,
            or if any non-canonical finding already has its own ``merged_from``
            populated (to prevent orphaning multi-hop merge chains).
    """
    if len(duplicate_ids) < 2:
        msg = f"Need at least 2 IDs to merge, got {len(duplicate_ids)}"
        raise ValueError(msg)

    id_set = set(duplicate_ids)

    if len(id_set) != len(duplicate_ids):
        counts = Counter(duplicate_ids)
        repeated = sorted(fid for fid, n in counts.items() if n > 1)
        msg = f"duplicate_ids contains repeated entries: {repeated}"
        raise ValueError(msg)

    duplicates = [f for f in findings if f["finding_id"] in id_set]
    found_ids = {f["finding_id"] for f in duplicates}
    missing = id_set - found_ids
    if missing:
        msg = f"Finding IDs not found: {sorted(missing)}"
        raise ValueError(msg)

    non_unresolved = [f["finding_id"] for f in duplicates if f.get("status", "unresolved") != "unresolved"]
    if non_unresolved:
        msg = f"Cannot merge non-unresolved findings: {non_unresolved}"
        raise ValueError(msg)

    canonical_id = duplicate_ids[0]
    orphan_canonicals = [f["finding_id"] for f in duplicates if f["finding_id"] != canonical_id and f.get("merged_from")]
    if orphan_canonicals:
        msg = f"Cannot merge previously-canonical findings as non-canonical: {orphan_canonicals}"
        raise ValueError(msg)

    max_severity = max(duplicates, key=lambda f: severity_rank(f["severity"]))["severity"]
    max_confidence = max(f.get("confidence", 0) for f in duplicates)

    merged_from = duplicate_ids[1:]

    for finding in findings:
        if finding["finding_id"] == canonical_id:
            finding["severity"] = max_severity
            finding["confidence"] = max_confidence
            finding.setdefault("merged_from", []).extend(merged_from)
        elif finding["finding_id"] in id_set:
            finding["status"] = "merged"
            finding["merged_into"] = canonical_id

    return findings


# ---------------------------------------------------------------------------
# CLI shim layer (TODO-0092 Phase B R_B1)
# ---------------------------------------------------------------------------
#
# These thin wrappers adapt the library surface above into a defopt CLI
# suitable for consumption by the diff-review skill (Phase B R_B3/R_B4).
# Each shim performs JSON I/O at the filesystem boundary and delegates
# the domain logic to the library functions. Mutating CLIs take
# ``--in-path`` / ``--out-path`` and implement durable-per-mutation
# semantics; read-only CLIs emit JSON (or a scalar) to stdout.

_FILTER_KINDS: tuple[str, ...] = (
    "active",
    "no-action-validated",
    "doc-or-todo-validated",
)


def _dump_json(payload: Any) -> None:
    """Serialise *payload* as pretty-printed JSON to stdout.

    Args:
        payload: Any JSON-serialisable object (typically a list of dicts).
    """
    print(json.dumps(payload, indent=2))


def _cli_create(
    *,
    finding_id: str,
    reviewer: str,
    severity: str,
    description: str,
    round_num: int,
    in_path: Path,
    out_path: Path,
    confidence: int = 0,
) -> None:
    """Create a new finding and append it to the ledger at ``out_path``.

    Loads the existing ledger from ``in_path`` (treating a missing file as
    an empty ledger), constructs a new finding via :func:`create`, appends
    it, and writes the resulting ledger to ``out_path``.

    Args:
        finding_id: Unique identifier for the new finding.
        reviewer: Name or identifier of the reviewer raising the finding.
        severity: Severity level string.
        description: Human-readable description of the finding.
        round_num: Review round number.
        in_path: Path to the existing JSON ledger (may not exist).
        out_path: Destination path for the updated ledger.
        confidence: Reviewer confidence score (0=unscored, 1-10).
    """
    findings = load(in_path)
    findings.append(
        create(
            finding_id,
            reviewer,
            severity,
            description,
            round_num,
            confidence=confidence,
        )
    )
    save(findings, out_path)


def _cli_update_status(
    *,
    finding_id: str,
    new_status: str,
    in_path: Path,
    out_path: Path,
    resolution: str = "",
    validators_count: int = 0,
    total_reviewers: int = 0,
) -> None:
    """Update the status of a finding in the ledger.

    Loads the ledger from ``in_path``, applies :func:`update_status`, and
    writes the result to ``out_path``. Propagates :class:`ValueError` if
    the target finding is not found.

    Args:
        finding_id: Finding ID to update.
        new_status: New status value.
        in_path: Source ledger path.
        out_path: Destination ledger path.
        resolution: Optional resolution label.
        validators_count: Number of reviewers who accepted the finding.
        total_reviewers: Total number of reviewers in the gate.
    """
    findings = load(in_path)
    update_status(
        findings,
        finding_id,
        new_status,
        resolution=resolution,
        validators_count=validators_count,
        total_reviewers=total_reviewers,
    )
    save(findings, out_path)


def _cli_filter(*, kind: str, in_path: Path) -> None:
    """Filter the ledger by ``kind`` and emit the result as JSON on stdout.

    Args:
        kind: One of ``active``, ``no-action-validated``, or
            ``doc-or-todo-validated``.
        in_path: Source ledger path (missing file treated as empty ledger).

    Raises:
        ValueError: If ``kind`` is not a recognised filter kind.
    """
    findings = load(in_path)
    if kind == "active":
        result = filter_active(findings)
    elif kind == "no-action-validated":
        result = filter_no_action_validated(findings)
    elif kind == "doc-or-todo-validated":
        result = filter_doc_or_todo_validated(findings)
    else:
        msg = f"Unknown filter kind: {kind!r}. Choose from: {', '.join(_FILTER_KINDS)}"
        raise ValueError(msg)
    _dump_json(result)


def _cli_load(*, in_path: Path) -> None:
    """Load the ledger from ``in_path`` and emit it as JSON on stdout.

    Missing or malformed files yield an empty JSON array.

    Args:
        in_path: Source ledger path.
    """
    _dump_json(load(in_path))


def _cli_parse_diff_markers(*, diff_path: Path) -> None:
    """Parse a git diff file for inline markers and emit results as JSON.

    Args:
        diff_path: Filesystem path to a git diff output file.
    """
    diff_text = diff_path.read_text()
    _dump_json(parse_diff_markers(diff_text))


def _cli_marker_priority(*, marker: str) -> None:
    """Print the numeric priority for the given marker keyword.

    Args:
        marker: Marker string (e.g. ``TODO``, ``HACK``).
    """
    print(marker_to_priority(marker))


def _cli_validated_priority(*, validators_count: int, total_reviewers: int) -> None:
    """Print the numeric priority for a validated finding.

    Args:
        validators_count: Number of reviewers who accepted the finding.
        total_reviewers: Total number of reviewers in the gate.
    """
    print(validated_finding_priority(validators_count, total_reviewers))


def _cli_merge_duplicates(
    *,
    duplicate_ids: list[str],
    in_path: Path,
    out_path: Path,
) -> None:
    """Merge the findings whose IDs appear in ``duplicate_ids``.

    Loads the ledger from ``in_path``, applies
    :func:`merge_duplicate_findings`, and writes the result to ``out_path``.
    The first ID is treated as the canonical entry.

    Args:
        duplicate_ids: Ordered list of finding IDs to merge (>=2 entries).
        in_path: Source ledger path.
        out_path: Destination ledger path.
    """
    findings = load(in_path)
    merge_duplicate_findings(findings, duplicate_ids)
    save(findings, out_path)


def _apply_batch_op(
    op_def: dict[str, Any],
    *,
    diff_text_cache: dict[str, str],
    ledger_cache: dict[str, list[dict[str, Any]]],
    pending_saves: dict[str, tuple[Path, list[dict[str, Any]]]],
) -> Any:
    """Execute one operation from an ``apply-batch`` JSONL line.

    Dispatches to the same library functions as the per-subcommand
    shims. Mutating ops (``create``, ``update-status``,
    ``merge-duplicates``) read each ledger from ``in_path`` once into
    ``ledger_cache`` (keyed by the resolved absolute path) and register
    the result in ``pending_saves`` for a single atomic flush at the
    end of the batch — eliminating the prior per-op load/save N+1
    pattern. When ``in_path`` and ``out_path`` resolve to the same file
    the cached list is mutated in place; when they diverge the source
    list is deep-copied first so the source cache stays clean. Read-
    only ops (``filter``, ``load``) return ``copy.deepcopy`` snapshots
    so a later mutation in the same batch does not retroactively
    alter an earlier read result at end-of-batch JSON serialisation.
    The caller (``_cli_apply_batch``) is responsible for flushing
    ``pending_saves`` only when the batch completes without error,
    giving the batch atomic semantics for the common
    ``in_path == out_path`` case.

    Note: when two divergent-path ops (``in_path`` differs from
    ``out_path``) target the same ``out_path`` from the same
    ``in_path``, the second op's deep-copy starts from the unmutated
    source cache, NOT from the first op's pending state — its
    write replaces the prior ``pending_saves`` entry for that target.
    This matches the per-op CLI semantic (each ``task findings:create``
    invocation is independent and reads from ``in_path`` fresh) and
    is intentional. Callers that want accumulation must use
    ``in_path == out_path``.

    Args:
        op_def: Parsed JSONL line. Required key: ``op``. Optional keys:
            ``args`` (dict, default empty), ``in_path``, ``out_path``,
            ``diff_path`` (op-dependent).
        diff_text_cache: Per-batch cache keyed by the resolved
            ``diff_path`` so repeated ``parse-diff-markers`` ops over
            the same file do not re-read disk.
        ledger_cache: Per-batch cache mapping each resolved ledger path
            (``in_path`` or ``out_path``) to its in-memory findings
            list. Mutating ops with ``in_path == out_path`` modify the
            list in place; divergent-path mutations write their deep
            copy to ``ledger_cache[out_path]`` so a subsequent read
            against ``out_path`` sees the mutated state.
        pending_saves: Output map collecting ledgers that need to be
            flushed when the batch completes. Keyed by resolved
            ``out_path``; the value is a (Path, findings) tuple.

    Returns:
        Operation-specific result. Mutating ops return
        ``{"status": "ok"}``; ``filter``/``load`` return deep-copied
        findings lists; priority ops return an integer; ``parse-diff-
        markers`` returns the marker list.

    Raises:
        ValueError: Unknown op or invalid op-specific args (propagated
            from the underlying library function).
        KeyError: Missing required key in ``op_def`` for the named op.
        TypeError: ``args`` is not a JSON object, or required keyword
            arguments for the underlying library call are absent.
        OSError: Underlying file operations failed (FileNotFoundError
            for missing ``diff_path``, PermissionError for unreadable
            files, IsADirectoryError when a path argument points at a
            directory, etc.). All ``OSError`` subclasses are caught by
            the dispatching ``_cli_apply_batch`` and surfaced as
            structured ``errors[]`` records.
    """
    op = op_def["op"]
    # ``args`` carries untrusted JSON; keep it ``Any`` so the runtime
    # ``isinstance`` guard below is not narrowed away by the type checker.
    args: Any = op_def.get("args", {})
    if not isinstance(args, dict):
        msg = f"args must be a JSON object, got {type(args).__name__}"
        raise TypeError(msg)

    def _load_into_cache(in_path_arg: str) -> tuple[Path, list[dict[str, Any]]]:
        in_path_obj = Path(in_path_arg)
        cache_key = str(in_path_obj.resolve())
        if cache_key not in ledger_cache:
            ledger_cache[cache_key] = load(in_path_obj)
        return in_path_obj, ledger_cache[cache_key]

    def _materialise_target(in_path_arg: str, out_path_arg: str) -> list[dict[str, Any]]:
        """Load the source ledger and return the list to mutate.

        When ``in_path`` and ``out_path`` resolve to the same file, the
        source cache list is mutated in place. When they diverge, a deep
        copy is returned so the source cache stays untouched and a later
        mutation against the same source does not cross-pollute earlier
        divergent outputs (R2 finding, Gemini G1 / Codex C2).
        """
        _, source_findings = _load_into_cache(in_path_arg)
        in_resolved = str(Path(in_path_arg).resolve())
        out_resolved = str(Path(out_path_arg).resolve())
        if in_resolved == out_resolved:
            return source_findings
        return copy.deepcopy(source_findings)

    def _register_save(out_path_arg: str, findings: list[dict[str, Any]]) -> None:
        out_path_obj = Path(out_path_arg)
        save_key = str(out_path_obj.resolve())
        # Mirror the cache so a subsequent read-only op against this path
        # sees the in-memory state, even when in_path != out_path.
        ledger_cache[save_key] = findings
        pending_saves[save_key] = (out_path_obj, findings)

    if op == "create":
        findings = _materialise_target(op_def["in_path"], op_def["out_path"])
        findings.append(create(**args))
        _register_save(op_def["out_path"], findings)
        return {"status": "ok"}
    if op == "update-status":
        findings = _materialise_target(op_def["in_path"], op_def["out_path"])
        update_status(findings, **args)
        _register_save(op_def["out_path"], findings)
        return {"status": "ok"}
    if op == "filter":
        _, findings = _load_into_cache(op_def["in_path"])
        kind = args["kind"]
        # Deep-copy the result so a later mutation in the same batch
        # does not retroactively alter this snapshot when serialised
        # at end-of-batch (R2 finding, Gemini G1 temporal leak).
        if kind == "active":
            return copy.deepcopy(filter_active(findings))
        if kind == "no-action-validated":
            return copy.deepcopy(filter_no_action_validated(findings))
        if kind == "doc-or-todo-validated":
            return copy.deepcopy(filter_doc_or_todo_validated(findings))
        msg = f"Unknown filter kind: {kind!r}. Choose from: {', '.join(_FILTER_KINDS)}"
        raise ValueError(msg)
    if op == "load":
        _, findings = _load_into_cache(op_def["in_path"])
        # Snapshot to prevent temporal read leakage (Gemini G1).
        return copy.deepcopy(findings)
    if op == "parse-diff-markers":
        diff_path_arg = op_def["diff_path"]
        cache_key = str(Path(diff_path_arg).resolve())
        if cache_key not in diff_text_cache:
            diff_text_cache[cache_key] = Path(diff_path_arg).read_text()
        return parse_diff_markers(diff_text_cache[cache_key])
    if op == "marker-priority":
        return marker_to_priority(args["marker"])
    if op == "validated-priority":
        return validated_finding_priority(**args)
    if op == "merge-duplicates":
        findings = _materialise_target(op_def["in_path"], op_def["out_path"])
        merge_duplicate_findings(findings, args["duplicate_ids"])
        _register_save(op_def["out_path"], findings)
        return {"status": "ok"}
    msg = f"Unknown op: {op!r}"
    raise ValueError(msg)


def _cli_apply_batch(*, batch_path: Path) -> None:
    """Execute a JSONL batch of findings operations in one process.

    Reads ``batch_path`` line-by-line; blank lines and lines beginning
    with ``#`` are ignored. Each remaining line must be a JSON object
    whose required key ``op`` names one of the eight subcommands without
    the ``findings:`` prefix (e.g. ``create``, ``filter``). Optional
    keys are ``id`` (caller-chosen identifier echoed in the results map;
    defaults to ``op-<line-number>``), ``args`` (op-specific arguments
    dict), and ``in_path`` / ``out_path`` / ``diff_path`` (filesystem
    paths, op-dependent). See :func:`_apply_batch_op` for the per-op
    argument contract.

    Emits a single JSON object on stdout with keys ``results`` (id ->
    op-result) and ``errors`` (list of error records). Every error
    record carries the same four fields — ``id``, ``op``, ``line``,
    ``error`` — for stable downstream parsing; ``id`` and ``op`` are
    null when the failure happens before per-op dispatch (malformed
    JSON, non-dict op_def).

    Batches are atomic: mutating ops accumulate in an in-memory
    ledger cache and are flushed to disk only when every op succeeds.
    A later failure rolls back all earlier mutations in the same call,
    so a corrected re-run of the same batch is safe — no duplicate
    create-op writes. Read-only ops (``filter``, ``load``) return
    deep-copied snapshots, so a later mutation in the same batch does
    NOT retroactively alter an earlier snapshot when serialised at
    end-of-batch. Mutating ops with divergent ``in_path`` and
    ``out_path`` deep-copy the source ledger before mutating, so the
    source cache stays clean for any subsequent op against the same
    ``in_path``.

    Save failures during the end-of-batch flush are recorded under
    ``errors[]`` with ``op = "save"`` and a null ``line``; this can
    only leave partial on-disk state across multiple ledger targets
    (a true two-phase commit is out of scope). For the common
    ``in_path == out_path`` single-ledger case the flush is a single
    atomic file replace.

    Args:
        batch_path: Filesystem path to the JSONL batch file.
    """
    diff_text_cache: dict[str, str] = {}
    ledger_cache: dict[str, list[dict[str, Any]]] = {}
    pending_saves: dict[str, tuple[Path, list[dict[str, Any]]]] = {}
    results: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []

    for line_num, raw_line in enumerate(batch_path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            op_def = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"id": None, "op": None, "line": line_num, "error": f"malformed JSON: {exc}"})
            break
        if not isinstance(op_def, dict):
            errors.append({
                "id": None,
                "op": None,
                "line": line_num,
                "error": f"op must be a JSON object, got {type(op_def).__name__}",
            })
            break
        # Validate id type and run duplicate-id detection inside the try
        # so non-string ids surface as structured errors instead of
        # bypassing _dump_json (R2 finding Codex C1; R3 finding Codex
        # R3-1, JSON-key collision between e.g. id=1 and id="1" which
        # both serialise to "1" in the results object). OSError covers
        # PermissionError / IsADirectoryError siblings of
        # FileNotFoundError that the underlying file ops can raise (R2
        # finding Gemini G2 / Opus F3).
        #
        # ``op_id`` is initialised to None so the error record can
        # distinguish "validation raised before op_id was synthesised"
        # (echo raw caller input, which is the offending value the
        # caller needs to debug) from "dispatch failed after op_id was
        # synthesised" (echo the resolved id — the synthesised default
        # ``op-<line>`` when the caller omitted ``id``, matching the
        # documented results-map key shape so error records correlate
        # cleanly with the would-have-been results entry; R4 finding
        # Codex R4-1).
        op_id: str | None = None
        try:
            raw_id = op_def.get("id")
            if "id" in op_def and not isinstance(raw_id, str):
                msg = f"id must be a string, got {type(raw_id).__name__}"
                raise TypeError(msg)
            op_id = raw_id if isinstance(raw_id, str) else f"op-{line_num}"
            if op_id in results:
                msg = f"duplicate id {op_id!r}"
                raise ValueError(msg)
            results[op_id] = _apply_batch_op(
                op_def,
                diff_text_cache=diff_text_cache,
                ledger_cache=ledger_cache,
                pending_saves=pending_saves,
            )
        except (KeyError, ValueError, TypeError, OSError) as exc:
            errors.append({
                "id": op_id if op_id is not None else op_def.get("id"),
                "op": op_def.get("op"),
                "line": line_num,
                "error": str(exc),
            })
            break

    if not errors:
        # Atomic flush. If a save fails mid-loop the on-disk state is
        # unavoidably partial (a true 2-phase commit is out of scope),
        # but we surface every failure under errors[] so callers see
        # what landed and what did not (R2 finding, Opus F3).
        for out_path_obj, findings in pending_saves.values():
            try:
                save(findings, out_path_obj)
            except OSError as exc:
                errors.append({
                    "id": None,
                    "op": "save",
                    "line": None,
                    "error": f"flush failed for {out_path_obj}: {exc}",
                })

    _dump_json({"results": results, "errors": errors})


def _collapse_repeated_flag(
    argv: list[str],
    flag: str,
    *,
    subcommand: str | None = None,
) -> list[str]:
    """Collapse repeated ``--flag V`` occurrences into ``--flag V1 V2 ...``.

    Defopt maps ``list[str]`` parameters to argparse ``nargs='*'`` which
    reads multiple values from a *single* flag occurrence but does not
    accumulate across repeated occurrences (each new ``--flag`` overwrites
    the prior value). Phase B R_B1 contract requires the repeated-flag
    form (``--duplicate-ids A --duplicate-ids B``) for CLI ergonomics,
    so we rewrite argv in place before handing it to defopt.

    The closed-form contract (TODO-0127/0128/0129) admits exactly two
    valid token shapes for ``flag`` and rejects every other shape with
    a fail-closed ``sys.exit(2)``:

    1. ``flag VALUE`` — space-form, where ``VALUE`` does not start with
       ``-``. Consumed as a pair; ``VALUE`` is appended to the collected
       list.
    2. ``flag=VALUE`` — equals-form, accepting any ``VALUE`` (including
       empty string and ``-``-prefixed values). Consumed as a single
       token; ``VALUE`` is appended to the collected list.

    Any other shape — bare ``flag`` (anywhere: leading, middle, or
    trailing), ``flag`` followed by a ``-``-prefixed token, or ``flag``
    followed by another long option — prints a stderr error message
    naming the flag and the corrective forms, then exits 2 *before*
    defopt sees the argv. Operators who need ``-``-prefixed values
    MUST use the equals-form (``flag=-A1``); the space-form rejects
    ``-``-prefixed values to avoid silent argparse-layer
    mis-tokenisation downstream.

    Args:
        argv: The command-line argument list (without the script name).
        flag: The long-option flag to collapse (e.g. ``--duplicate-ids``).
        subcommand: The subcommand under which ``flag`` is owned. When
            ``argv[0]`` does not match, the helper returns ``argv``
            unchanged — argv-shape errors outside the configured
            subcommand are not its concern. Callers SHOULD pass a
            configured value; the ``None`` default exists only for
            unit-test ergonomics (it bypasses the gate and runs against
            any ``argv[0]``, which is not a supported production caller
            shape). The sole production call site always passes a
            configured subcommand.

    Returns:
        Trinary outcome:

        - A new argv list with occurrences of ``flag`` collapsed into a
          single ``flag VALUE1 VALUE2 ...`` form when at least one
          collapsible occurrence is found.
        - The original ``argv`` reference unchanged when (a) the
          subcommand gate does not match, or (b) ``flag`` does not
          appear in ``argv`` at all.

    Raises:
        SystemExit: with code ``2`` when ``argv`` contains any
            malformed ``flag`` token (bare flag, or flag followed by a
            ``-``-prefixed token). The message is written to stderr.
    """
    if subcommand is not None and (not argv or argv[0] != subcommand):
        return argv

    collected: list[str] = []
    rest: list[str] = []
    flag_eq_prefix = flag + "="
    i = 0
    first_index: int | None = None
    while i < len(argv):
        token = argv[i]
        if token == flag and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            if first_index is None:
                first_index = len(rest)
                rest.append(flag)
            collected.append(argv[i + 1])
            i += 2
            continue
        if token.startswith(flag_eq_prefix):
            if first_index is None:
                first_index = len(rest)
                rest.append(flag)
            collected.append(token[len(flag_eq_prefix) :])
            i += 1
            continue
        # Fail-closed on any bare ``--flag`` (TODO-0128 symmetric
        # extension of TODO-0127): the rule is position-agnostic, so
        # leading, middle, and trailing bare-flag cases all exit 2 with
        # the same wide stderr message. The post-loop ``first_index is
        # None`` branch is preserved to handle the legitimate
        # ``--flag``-absent case (e.g. argv with no ``--flag`` token at
        # all, or argv that misses the subcommand gate above).
        if token == flag:
            print(
                f"error: {flag} requires a non-option value "
                f"(use {flag} VALUE with VALUE not starting with '-', "
                f"or {flag}=VALUE for any value)",
                file=sys.stderr,
            )
            sys.exit(2)
        rest.append(token)
        i += 1
    if first_index is None:
        return argv
    # Splice the collected values immediately after the first flag marker.
    return rest[: first_index + 1] + collected + rest[first_index + 1 :]


def main() -> None:
    """CLI entry point dispatching to the full findings-tracker command set.

    Exposes nine subcommands under the ``findings:`` namespace: ``create``,
    ``update-status``, ``filter``, ``load``, ``parse-diff-markers``,
    ``marker-priority``, ``validated-priority``, ``merge-duplicates``, and
    ``apply-batch``.

    Lineage note (for archaeology): six were new in Phase B R_B1 and two
    (``load``, ``parse-diff-markers``) are renamed wrappers of pre-existing
    library helpers. ``apply-batch`` was added to amortise container-startup
    cost when the diff-review skill issues many findings ops in close
    succession (Step 3.1 create-loops and Step 5.1 filter+priority+marker
    fan-out). See TODO-0092 Phase B R_B1 for the authoritative subcommand
    table and save-semantic contract.
    """
    dispatch: dict[str, Any] = {
        "findings:create": _cli_create,
        "findings:update-status": _cli_update_status,
        "findings:filter": _cli_filter,
        "findings:load": _cli_load,
        "findings:parse-diff-markers": _cli_parse_diff_markers,
        "findings:marker-priority": _cli_marker_priority,
        "findings:validated-priority": _cli_validated_priority,
        "findings:merge-duplicates": _cli_merge_duplicates,
        "findings:apply-batch": _cli_apply_batch,
    }
    argv = _collapse_repeated_flag(
        sys.argv[1:],
        "--duplicate-ids",
        subcommand="findings:merge-duplicates",
    )
    defopt.run(dispatch, argv=argv)


if __name__ == "__main__":
    main()
