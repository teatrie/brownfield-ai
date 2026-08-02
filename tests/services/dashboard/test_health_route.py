import importlib
from unittest.mock import patch

import httpx
import pytest

from services.dashboard.app import app


@pytest.mark.asyncio
async def test_health_returns_200():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_spa_index_served(tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><html><body>Dashboard</body></html>")

    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    test_app = FastAPI()
    test_app.mount("/", StaticFiles(directory=str(tmp_path), html=True), name="static")

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_sqlite_pragmas(tmp_path):
    db_path = str(tmp_path / "test_ledger.db")
    with patch.dict("os.environ", {"LEDGER_DB_PATH": db_path}):
        # Reimport to pick up patched env
        import services.dashboard.deps as deps_mod

        importlib.reload(deps_mod)

        gen = deps_mod.get_sqlite_db()
        conn = next(gen)
        try:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert journal_mode == "wal"

            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert busy_timeout == 5000

            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert foreign_keys == 1
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
