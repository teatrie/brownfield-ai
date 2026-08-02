"""FastAPI application entry point for the ledger dashboard.

Configures the ASGI application with CORS, WebSocket support,
static file serving, and background sync loop lifecycle management.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from services.dashboard.routers import actions, artifacts, epics, export, health, kb, search, stats, todos
from services.dashboard.sync import sync_loop
from services.dashboard.ws import ConnectionManager

logger: logging.Logger = logging.getLogger(__name__)

manager: ConnectionManager = ConnectionManager()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: start and stop the background sync loop.

    Args:
        app: The FastAPI application instance.

    Yields:
        None after the sync loop background task is started.
    """
    task = asyncio.create_task(sync_loop(manager))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app: FastAPI = FastAPI(title="Ledger Dashboard", lifespan=lifespan)
app.state.ws_manager = manager

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8484", "http://127.0.0.1:8484"],
    allow_methods=["GET", "PATCH", "PUT", "DELETE"],  # Scoped to active verbs; update if new HTTP methods are added
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(epics.router)
app.include_router(artifacts.router)
app.include_router(search.router)
app.include_router(actions.router)
app.include_router(export.router)
app.include_router(todos.router)
app.include_router(kb.router)
app.include_router(stats.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle WebSocket connections for real-time dashboard updates.

    Accepts the connection, listens for messages (including epic
    subscription requests), and cleans up on disconnect.

    Args:
        websocket: The incoming WebSocket connection.
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "subscribe" and "epic_id" in msg:
                    await manager.subscribe(websocket, msg["epic_id"])
            except (ValueError, KeyError):
                pass
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


class SPAStaticFiles(StaticFiles):
    """Serve index.html for unknown paths to support SPA client-side routing."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


static_dir: Path = Path(__file__).resolve().parent / "static"
if static_dir.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8484)
