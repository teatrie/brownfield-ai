"""CLI wrappers (thin defopt handlers) for the artifact subsystem.

Each function is a CLI subcommand that wires up infrastructure (DB,
ChromaDB) and delegates to the service-layer functions in ``queries``
and ``mutations``.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from brownfield_ai.ledger.artifacts.constants import (
    COLLECTION_NAME,
    EPICS_COLLECTION_NAME,
    MAX_CONTENT_FILE_BYTES,
    PROJECT_ROOT,
)
from brownfield_ai.ledger.artifacts.mutations import save_artifact
from brownfield_ai.ledger.artifacts.queries import (
    filter_artifacts,
    get_artifact,
    get_timeline,
    query_artifacts,
    search_epics_core,
)
from brownfield_ai.ledger.infra import get_client, get_db


def _parse_save_params(
    required: dict[str, str],
    metadata: str,
) -> dict[str, Any]:
    """Parse and merge save parameters from required fields and JSON metadata.

    Args:
        required: Dictionary with keys ``epic_id``, ``artifact_type``,
            ``agent_model``.
        metadata: JSON string with optional fields.

    Returns:
        dict: Merged parameter dictionary.
    """
    defaults: dict[str, Any] = {
        "wave": "",
        "domain": "",
        "step": "",
        "agent_role": "",
        "verdict": "",
        "version": 1,
        "parent_id": "",
        "epic_status": "pending",
        "title": "",
        "priority": 5,
        "depends_on": "[]",
        "sub_plan": "",
        "sub_plans": "",
        "attempt": "",
        "branches": "",
    }
    try:
        overrides = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        print("Invalid JSON in --metadata")
        sys.exit(1)
    defaults.update(overrides)
    defaults.update(required)
    return defaults


def save(
    *,
    fields: str,
    content: str | None = None,
    content_file: str | None = None,
    metadata: str = "{}",
) -> None:
    """Save an execution artifact to the ledger.

    Exactly one of ``content`` or ``content_file`` must be supplied. A
    ``content_file`` path must resolve inside ``tmp/`` (CLAUDE.md §10).
    Both inputs reject an empty or whitespace-only document body.

    Args:
        fields: JSON with required keys epic_id, artifact_type,
            agent_model (e.g. '{"epic_id":"ACME-2931",
            "artifact_type":"plan_snapshot",
            "agent_model":"claude-opus-4"}').
        content: Inline document body content. Mutually exclusive with
            ``content_file``.
        content_file: Path (relative to the repo root) of a UTF-8 file
            under ``tmp/`` whose contents become the document body.
            Mutually exclusive with ``content``.
        metadata: JSON string with optional fields (wave, domain, step,
            agent_role, verdict, version, parent_id, epic_status, title,
            priority, depends_on).
    """
    # Mutual exclusion + presence checks run FIRST, before fields/metadata
    # parsing, so the exactly-one-of contract is enforced regardless of
    # whether the JSON payloads are well-formed. The if/elif/else dispatch
    # below lets the type-checker narrow ``content`` to ``str`` in the elif
    # branch (a two-guard-then-else structure leaves ``body`` as ``str | None``).
    if content is not None and content_file is not None:
        raise SystemExit("--content and --content-file are mutually exclusive")

    if content_file is not None:
        # Anchor containment to PROJECT_ROOT, not Path.cwd(), so the check is
        # immune to chdir. Read PROJECT_ROOT as a module global at call time so
        # tests can monkeypatch cli.PROJECT_ROOT.
        #
        # tmp_root need not exist strictly — target.resolve(strict=True) below
        # still enforces the target exists, so a missing tmp/ yields a clean
        # "not found or unreadable" instead of a raw FileNotFoundError (tmp/ is
        # gitignored → real fresh-clone/CI case).
        tmp_root = (PROJECT_ROOT / "tmp").resolve()
        # Order: canonicalize -> contain -> is_file -> size -> read ->
        # (universal) strip-check. Reordering would let oversized files OOM the
        # read, surface decode errors before containment, or read a FIFO before
        # the is_file() guard rejects it.
        try:
            # PROJECT_ROOT / content_file returns Path(content_file) when
            # content_file is absolute (pathlib operator semantics: an absolute
            # right operand wins). The subsequent containment check still
            # rejects it because the resolved path won't be under tmp_root — do
            # NOT "fix" this by stripping a leading "/" or switching to
            # .joinpath(); that would mask the rejection path.
            target = (PROJECT_ROOT / content_file).resolve(strict=True)
        except (FileNotFoundError, OSError):
            raise SystemExit(f"--content-file not found or unreadable: {content_file}")
        if not target.is_relative_to(tmp_root):
            raise SystemExit(f"--content-file must resolve inside tmp/ (CLAUDE.md §10): {content_file}")
        # is_file() returns False for directories and FIFOs — this both fixes
        # the IsADirectoryError crash AND prevents the FIFO read_text() hang
        # before any read happens.
        if not target.is_file():
            raise SystemExit(f"--content-file must be a regular file: {content_file}")
        size = target.stat().st_size
        if size > MAX_CONTENT_FILE_BYTES:
            raise SystemExit(f"--content-file exceeds {MAX_CONTENT_FILE_BYTES} bytes (got {size} bytes): {content_file}")
        try:
            body = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise SystemExit(f"--content-file is not valid UTF-8: {content_file}")
        except OSError:
            raise SystemExit(f"--content-file not found or unreadable: {content_file}")
    elif content is not None:
        body = content
    else:
        raise SystemExit("exactly one of --content / --content-file required")

    # Universal whitespace rejection applies to ``body`` regardless of source
    # (both --content and --content-file), so an empty/whitespace-only payload
    # never reaches save_artifact.
    if body.strip() == "":
        raise SystemExit("--content / --content-file is empty or whitespace-only")

    try:
        required = json.loads(fields)
    except json.JSONDecodeError:
        print("Invalid JSON in --fields")
        sys.exit(1)
    for key in ("epic_id", "artifact_type", "agent_model"):
        if key not in required:
            print(f"Missing required key '{key}' in --fields")
            sys.exit(1)
    params = _parse_save_params(required, metadata)
    client = get_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    db = get_db()
    doc_id = save_artifact((collection, db), body, params)
    db.close()
    print(doc_id)


def query(
    query_text: str,
    *,
    filters: str = "{}",
) -> None:
    """Query ledger artifacts by semantic search.

    Args:
        query_text: The search query text.
        filters: JSON string with optional keys epic_id,
            artifact_type, n (max results, default 5).
    """
    try:
        filter_dict = json.loads(filters)
    except json.JSONDecodeError:
        print("Invalid JSON in --filters")
        sys.exit(1)
    client = get_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    results = query_artifacts(collection, query_text, filter_dict)
    if not results:
        print("No results found.")
        return
    for item in results:
        print(f"\nID: {item['id']} (Distance: {item['distance']})")
        print(f"Content: {item['document'][:200]}...")
        print(f"Metadata: {json.dumps(item['metadata'], indent=2)}")


def search_epics_cli(query_text: str, *, n: int = 5) -> None:
    """Search the epics collection by semantic similarity.

    Args:
        query_text: The search query text.
        n: Maximum number of results to return.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=EPICS_COLLECTION_NAME)
    results = search_epics_core(collection, query_text, n=n)
    if not results:
        print("No results found.")
        return
    for item in results:
        print(f"\nID: {item['id']} (Distance: {item['distance']})")
        print(f"Content: {item['document'][:200]}...")
        print(f"Metadata: {json.dumps(item['metadata'], indent=2)}")


def filter_cli(
    epic_id: str,
    *,
    artifact_type: str = "",
    sub_plan: str = "",
    attempt: str = "",
    verdict: str = "",
    artifact_status: str = "",
    limit: int = 50,
) -> None:
    """Filter ledger artifacts by deterministic metadata match.

    Unlike ``query`` (semantic search), this uses exact metadata filters
    via ``collection.get()``. Output is always JSON for programmatic
    consumption by the ralph client's ``parse_json_output()``.

    Args:
        epic_id: The epic identifier.
        artifact_type: Optional artifact type filter.
        sub_plan: Optional sub-plan label filter.
        attempt: Optional attempt number filter.
        verdict: Optional verdict filter.
        artifact_status: Optional artifact status filter.
        limit: Maximum number of results.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    items = filter_artifacts(
        collection,
        epic_id,
        artifact_type=artifact_type,
        sub_plan=sub_plan,
        attempt=attempt,
        verdict=verdict,
        artifact_status=artifact_status,
        limit=limit,
    )
    print(json.dumps(items, indent=2))


def timeline(
    epic_id: str,
    *,
    artifact_type: str = "",
    limit: int = 50,
) -> None:
    """List all artifacts for an epic in chronological order.

    Args:
        epic_id: The epic identifier.
        artifact_type: Optional artifact type filter.
        limit: Maximum number of results.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    items = get_timeline(
        collection,
        {
            "epic_id": epic_id,
            "artifact_type": artifact_type,
            "limit": limit,
        },
    )
    if not items:
        print("No artifacts found.")
        return
    for item in items:
        meta = item["metadata"]
        print(f"{item['id']}  [{meta.get('artifact_type', '')}]  v{meta.get('version', '')}  {meta.get('verdict', '')}")


def get(doc_id: str) -> None:
    """Retrieve a single artifact by exact ID.

    Args:
        doc_id: The exact document ID.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    result = get_artifact(collection, doc_id)
    if result is None:
        print("Document not found.")
        sys.exit(1)
    print(f"ID: {result['id']}")
    print(f"Content:\n{result['document']}")
    print(f"Metadata: {json.dumps(result['metadata'], indent=2)}")
