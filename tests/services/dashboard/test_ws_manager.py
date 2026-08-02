from unittest.mock import AsyncMock

import pytest

from services.dashboard.ws import ConnectionManager


@pytest.fixture
def manager():
    return ConnectionManager()


def _make_ws():
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_connect_adds_websocket(manager):
    ws = _make_ws()
    await manager.connect(ws)
    ws.accept.assert_called_once()
    assert ws in manager._connections


@pytest.mark.asyncio
async def test_disconnect_removes_websocket(manager):
    ws = _make_ws()
    await manager.connect(ws)
    await manager.disconnect(ws)
    assert ws not in manager._connections


@pytest.mark.asyncio
async def test_broadcast_sends_to_all(manager):
    ws1 = _make_ws()
    ws2 = _make_ws()
    await manager.connect(ws1)
    await manager.connect(ws2)
    await manager.broadcast({"type": "test"})
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_broadcast_removes_disconnected(manager):
    ws_good = _make_ws()
    ws_bad = _make_ws()
    ws_bad.send_text.side_effect = RuntimeError("disconnected")
    await manager.connect(ws_good)
    await manager.connect(ws_bad)
    await manager.broadcast({"type": "test"})
    assert ws_bad not in manager._connections
    assert ws_good in manager._connections


@pytest.mark.asyncio
async def test_subscribe_and_send_to_epic(manager):
    ws = _make_ws()
    await manager.connect(ws)
    await manager.subscribe(ws, "EPIC-001")
    await manager.send_to_epic("EPIC-001", {"type": "update"})
    ws.send_text.assert_called()
