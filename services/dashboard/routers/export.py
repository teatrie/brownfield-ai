"""Epic export API route for the ledger dashboard.

Provides a single endpoint that packages an epic's metadata and all
associated artifacts into a downloadable zip archive.
"""

from __future__ import annotations

import asyncio
import io
import re
import sqlite3
import zipfile
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from brownfield_ai.ledger.artifacts.queries import get_timeline
from brownfield_ai.ledger.epics.constants import EPIC_BY_ID_SQL
from services.dashboard.deps import get_chromadb_collection, get_sqlite_db

if TYPE_CHECKING:
    import chromadb

router: APIRouter = APIRouter(prefix="/api", tags=["export"])


@router.get("/epics/{epic_id}/export")
async def export_epic(
    epic_id: str,
    db: sqlite3.Connection = Depends(get_sqlite_db),
    collection: chromadb.Collection = Depends(get_chromadb_collection),
) -> StreamingResponse:
    """Export an epic and its artifacts as a zip archive.

    Packages the epic metadata as ``epic.yaml`` and each artifact as
    a Markdown file with YAML frontmatter into a zip archive streamed
    to the client.

    Args:
        epic_id: Path parameter identifying the epic to export.
        db: Injected SQLite connection.
        collection: Injected ChromaDB collection.

    Returns:
        A streaming zip archive response.

    Raises:
        HTTPException: 404 if the epic does not exist.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", epic_id):
        raise HTTPException(status_code=400, detail="Invalid epic_id format")

    row: sqlite3.Row | None = await asyncio.to_thread(lambda: db.execute(EPIC_BY_ID_SQL, (epic_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail=f"Epic '{epic_id}' not found")
    epic = dict(row)

    artifacts: list[dict[str, Any]] = await asyncio.to_thread(get_timeline, collection, {"epic_id": epic_id, "limit": 0})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest: list[dict[str, str]] = []
        for idx, artifact in enumerate(artifacts, start=1):
            meta = artifact.get("metadata", {})
            safe_ts = meta.get("timestamp", "unknown").replace(":", "-")
            a_type = meta.get("artifact_type", "artifact")
            filename = f"{idx:03d}_{a_type}_{safe_ts}.md"
            manifest.append({
                "filename": filename,
                "type": a_type,
                "timestamp": meta.get("timestamp", ""),
                "verdict": meta.get("verdict", ""),
            })

            frontmatter = yaml.dump(
                meta,
                default_flow_style=False,
                allow_unicode=True,
            )
            body = artifact.get("document", "")
            content = f"---\n{frontmatter}---\n\n{body}"
            zf.writestr(f"{epic_id}/artifacts/{filename}", content)

        epic_data = {**epic, "artifact_manifest": manifest}
        epic_yaml = yaml.dump(
            epic_data,
            default_flow_style=False,
            allow_unicode=True,
        )
        zf.writestr(f"{epic_id}/epic.yaml", epic_yaml)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{epic_id}.zip"',
        },
    )
