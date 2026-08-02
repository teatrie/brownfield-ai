"""Background synchronization loop for the ledger dashboard.

Polls SQLite and ChromaDB for changes and emits WebSocket events
when new artifacts or epic state changes are detected.  Also keeps
the ``epics`` ChromaDB collection in sync for semantic search.
"""

import asyncio
import logging
import os
import sqlite3
from typing import Any

import chromadb

from services.dashboard.ws import ConnectionManager

logger: logging.Logger = logging.getLogger(__name__)

SYNC_INTERVAL: int = int(os.environ.get("SYNC_INTERVAL_SECONDS", "5"))
BACKOFF_BASE: float = 2.0
BACKOFF_CEILING: float = 60.0

LEDGER_DB_PATH: str = os.environ.get("LEDGER_DB_PATH", "/brownfield-ai/ledger_index.db")
CHROMADB_HOST: str = os.environ.get("CHROMADB_HOST", "host.docker.internal")
CHROMADB_PORT: int = int(os.environ.get("CHROMADB_PORT", "8000"))


async def sync_loop(manager: ConnectionManager) -> None:
    """Poll for ledger changes and emit WebSocket update events.

    Tracks last-known epic timestamps and artifact counts per epic.
    On each cycle:

    1. Opens a fresh SQLite connection (short-lived, WAL mode).
    2. Queries all epics for ``last_updated_at`` changes.
    3. Queries ChromaDB ``execution_ledger`` for artifact count changes per epic.
    4. Syncs epic data to the ``epics`` ChromaDB collection for search.
    5. Emits WebSocket events for detected changes.
    6. Updates tracking state.

    Per Risk-006: artifact detection is NOT solely reliant on ``touch_epic()``.
    The loop also polls ChromaDB directly for new artifact counts.

    Implements exponential backoff on failure: starts at ``BACKOFF_BASE``
    seconds and doubles up to ``BACKOFF_CEILING`` seconds, resetting to
    zero on a successful cycle.

    Args:
        manager: The WebSocket connection manager for broadcasting events.
    """
    logger.info("sync loop started (interval=%ds)", SYNC_INTERVAL)

    epic_timestamps: dict[str, str] = {}
    epic_artifact_counts: dict[str, int] = {}
    epic_chromadb_timestamps: dict[str, str] = {}
    backoff: float = 0.0

    while True:
        if backoff > 0:
            logger.warning("sync loop backing off %.1fs", backoff)
            await asyncio.sleep(backoff)

        try:
            changes = await asyncio.to_thread(
                _detect_changes,
                epic_timestamps,
                epic_artifact_counts,
                epic_chromadb_timestamps,
            )
            backoff = 0.0

            for event in changes:
                if event.get("epic_id"):
                    await manager.send_to_epic(event["epic_id"], event)
                await manager.broadcast(event)

        except Exception:
            logger.exception("sync loop error")
            backoff = min((backoff * 2) or BACKOFF_BASE, BACKOFF_CEILING)

        await asyncio.sleep(SYNC_INTERVAL)


def _detect_changes(
    epic_timestamps: dict[str, str],
    epic_artifact_counts: dict[str, int],
    epic_chromadb_timestamps: dict[str, str],
) -> list[dict[str, Any]]:
    """Detect epic and artifact changes since the last poll.

    Opens short-lived SQLite and ChromaDB connections.
    Mutates the tracking dicts in-place to record the latest state.
    On the first poll cycle (when tracking dicts are empty), seeds them
    without emitting events.

    Args:
        epic_timestamps: Mutable mapping of epic_id to last_updated_at.
        epic_artifact_counts: Mutable mapping of epic_id to artifact count.
        epic_chromadb_timestamps: Mutable mapping of epic_id to the
            last_updated_at value most recently synced to the epics
            ChromaDB collection.

    Returns:
        List of WebSocket event dicts for detected changes.
    """
    events: list[dict[str, Any]] = []
    epic_rows: list[sqlite3.Row] = []

    # 1. Check SQLite for epic timestamp changes
    try:
        conn = sqlite3.connect(LEDGER_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        epic_rows = conn.execute("SELECT epic_id, last_updated_at, status, title, depends_on FROM epics").fetchall()
        conn.close()

        for row in epic_rows:
            eid: str = row["epic_id"]
            ts: str = row["last_updated_at"] or ""
            prev = epic_timestamps.get(eid)
            if prev is not None and prev != ts:
                events.append({
                    "type": "epic_change",
                    "epic_id": eid,
                    "data": {
                        "status": row["status"],
                        "last_updated_at": ts,
                    },
                })
            epic_timestamps[eid] = ts

    except sqlite3.Error:
        logger.exception("sync loop SQLite error")

    # 2. Check ChromaDB for new artifacts per epic
    try:
        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        collection = client.get_or_create_collection("execution_ledger")

        for eid in list(epic_timestamps.keys()):
            results = collection.get(where={"epic_id": eid})
            count = len(results.get("ids", []))
            prev_count = epic_artifact_counts.get(eid, 0)

            if prev_count > 0 and count > prev_count:
                all_ids = sorted(results["ids"])
                new_ids = all_ids[prev_count:]
                docs = results["documents"] or []
                metas = results["metadatas"] or []
                for doc_id in new_ids:
                    idx = results["ids"].index(doc_id)
                    events.append({
                        "type": "artifact_new",
                        "epic_id": eid,
                        "data": {
                            "id": doc_id,
                            "document": docs[idx] if idx < len(docs) else "",
                            "metadata": metas[idx] if idx < len(metas) else {},
                        },
                    })

            epic_artifact_counts[eid] = count

    except (ConnectionError, ValueError):
        logger.exception("sync loop ChromaDB error")

    # 3. Sync epic data to ChromaDB epics collection for semantic search
    try:
        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        epics_collection = client.get_or_create_collection("epics")
        is_first_sync = len(epic_chromadb_timestamps) == 0

        for row in epic_rows:
            eid = row["epic_id"]
            ts = row["last_updated_at"] or ""
            prev_chromadb_ts = epic_chromadb_timestamps.get(eid)

            if is_first_sync or prev_chromadb_ts != ts:
                title = row["title"] or ""
                status = row["status"] or ""
                depends_on = row["depends_on"] or ""
                document = f"{eid} {title} {status} {depends_on}"
                epics_collection.upsert(
                    ids=[eid],
                    documents=[document],
                    metadatas=[{"last_updated_at": ts, "status": status, "title": title}],
                )
                epic_chromadb_timestamps[eid] = ts

    except (ConnectionError, ValueError):
        logger.exception("sync loop epics collection sync error")

    return events
