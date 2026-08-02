"""Write operations (mutations) for the artifact subsystem.

Provides ``supersede_previous`` for version management and
``save_artifact`` for dual-store (ChromaDB + SQLite) persistence.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from brownfield_ai.ledger.artifacts.builders import (
    build_metadata,
    generate_id,
    validate_artifact_type,
)
from brownfield_ai.ledger.artifacts.queries import build_and_filter
from brownfield_ai.ledger.artifacts.sanitize import sanitize_content
from brownfield_ai.ledger.epics.lifecycle import upsert_epic_index


def supersede_previous(
    collection: Any,
    epic_id: str,
    artifact_type: str,
) -> None:
    """Mark all previous artifacts of the same type as ``superseded``.

    Uses ``$and`` filter with graceful fallback, matching Req-023/Req-025.

    Args:
        collection: The ChromaDB collection.
        epic_id: Epic identifier.
        artifact_type: Artifact type to supersede.
    """
    results = build_and_filter(collection, epic_id, artifact_type)
    for i, doc_id in enumerate(results.get("ids", [])):
        meta = results["metadatas"][i]
        if meta.get("artifact_status") == "active":
            updated = {**meta, "artifact_status": "superseded"}
            collection.update(ids=[doc_id], metadatas=[updated])


def save_artifact(
    stores: tuple[Any, sqlite3.Connection],
    content: str,
    params: dict[str, Any],
) -> str:
    """Save an execution artifact to ChromaDB (and SQLite for plan_snapshot).

    Validates artifact type, sanitizes content, supersedes previous versions,
    then upserts the epic index in SQLite (``plan_snapshot`` only) and writes
    the document to ChromaDB (idempotent upsert, all artifact types).

    Args:
        stores: Tuple of ``(chromadb_collection, sqlite3_connection)``.
        content: The document body content.
        params: Dictionary with all artifact fields including ``epic_id``,
            ``artifact_type``, ``agent_model``, ``wave``, ``domain``,
            ``step``, ``agent_role``, ``verdict``, ``version`` (int),
            ``parent_id``, ``epic_status``, ``title``, ``priority`` (int),
            ``depends_on`` (JSON string).

    Returns:
        str: The generated document ID.
    """
    collection, db = stores
    epic_id = params["epic_id"]
    artifact_type = params["artifact_type"]
    validate_artifact_type(artifact_type)

    now = datetime.now().isoformat()
    sanitized = sanitize_content(content, artifact_type)

    # Only plan_snapshot and requirement_map get superseded on update.
    # All other types (design_decision, gate_verdict, step_result,
    # wave_summary) accumulate — preserving the full audit trail.
    if artifact_type in ("plan_snapshot", "requirement_map"):
        supersede_previous(collection, epic_id, artifact_type)

    doc_id: str = generate_id({
        "epic_id": epic_id,
        "timestamp": now,
        "artifact_type": artifact_type,
        "agent_model": params.get("agent_model", ""),
        "wave": params.get("wave", ""),
        "step": params.get("step", ""),
    })
    metadata = build_metadata({
        "epic_id": epic_id,
        "artifact_type": artifact_type,
        "wave": params.get("wave", ""),
        "domain": params.get("domain", ""),
        "step": params.get("step", ""),
        "agent_role": params.get("agent_role", ""),
        "agent_model": params.get("agent_model", ""),
        "verdict": params.get("verdict", ""),
        "timestamp": now,
        "version": params.get("version", 1),
        "parent_id": params.get("parent_id", ""),
        "epic_status": params.get("epic_status", "pending"),
        "artifact_status": "active",
        "sub_plan": params.get("sub_plan", ""),
        "sub_plans": params.get("sub_plans", ""),
        "attempt": params.get("attempt", ""),
        "branches": params.get("branches", ""),
    })

    # Dual-write: SQLite first, then ChromaDB
    if artifact_type == "plan_snapshot":
        upsert_epic_index(db, params, now)

    collection.upsert(
        ids=[doc_id],
        documents=[sanitized],
        metadatas=[metadata],
    )

    return doc_id
