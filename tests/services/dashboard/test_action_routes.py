"""Tests for the write action API routes.

Validates all 8 mutation endpoints exposed by the ``actions`` router:
epic status transitions, epic priority updates, PR reference management,
and TODO completion, assignment, priority, and category updates.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.dashboard.app import app
from services.dashboard.routers.actions import _safe_broadcast

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield dashboard_overrides


@pytest.fixture(autouse=True)
def _reset_ws_manager():
    """Ensure app.state.ws_manager is reset after every test."""
    yield
    app.state.ws_manager = None


# ---------------------------------------------------------------------------
# PATCH /api/epics/{epic_id}/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_transition_valid() -> None:
    with patch(
        "services.dashboard.routers.actions.update_status",
        return_value={"success": True},
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/epics/TEST-001/status",
                json={"new_status": "completed"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["new_status"] == "completed"


@pytest.mark.asyncio
async def test_status_transition_invalid() -> None:
    with patch(
        "services.dashboard.routers.actions.update_status",
        side_effect=SystemExit(1),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/epics/TEST-001/status",
                json={"new_status": "invalid_state"},
            )

    assert response.status_code == 400
    assert "Status update failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_status_transition_rejected() -> None:
    with patch(
        "services.dashboard.routers.actions.update_status",
        return_value={"success": False, "error": "Cannot complete epic with open blockers"},
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/epics/TEST-001/status",
                json={"new_status": "completed"},
            )

    assert response.status_code == 400
    assert "Cannot complete epic with open blockers" in response.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH /api/epics/{epic_id}/priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epic_priority_valid() -> None:
    with patch(
        "services.dashboard.routers.actions.update_epic_priority",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/epics/TEST-001/priority",
                json={"priority": 3},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["priority"] == 3


@pytest.mark.asyncio
async def test_epic_priority_out_of_range() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/epics/TEST-001/priority",
            json={"priority": 15},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_epic_priority_not_found() -> None:
    with patch(
        "services.dashboard.routers.actions.update_epic_priority",
        side_effect=SystemExit(1),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/epics/NONEXISTENT/priority",
                json={"priority": 5},
            )

    assert response.status_code == 400
    assert "Priority update failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# PUT /api/epics/{epic_id}/prs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_refs_set() -> None:
    with patch(
        "services.dashboard.routers.actions.set_current_prs",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/epics/TEST-001/prs",
                json={"pr_refs": "acme/analytics#245"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["pr_refs"] == "acme/analytics#245"


@pytest.mark.asyncio
async def test_pr_refs_invalid_format() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/epics/TEST-001/prs",
            json={"pr_refs": "not-a-pr-ref"},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/epics/{epic_id}/prs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_refs_clear() -> None:
    with patch(
        "services.dashboard.routers.actions.clear_current_prs",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/epics/TEST-001/prs")

    assert response.status_code == 200
    assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# PATCH /api/todos/{todo_id}/done
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todo_done_with_resolution() -> None:
    with patch(
        "services.dashboard.routers.actions.done_todo",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/todos/1/done",
                json={"resolution": "Fixed in PR #42"},
            )

    assert response.status_code == 200
    assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_todo_done_without_resolution() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/todos/1/done",
            json={"resolution": ""},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_todo_done_not_found() -> None:
    with patch(
        "services.dashboard.routers.actions.done_todo",
        side_effect=ValueError("not found"),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/todos/999/done",
                json={"resolution": "Attempted resolution"},
            )

    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH /api/todos/{todo_id}/assign
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todo_assign_existing_epic() -> None:
    with patch(
        "services.dashboard.routers.actions.assign_todo",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/todos/1/assign",
                json={"epic_id": "TEST-001"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["epic_id"] == "TEST-001"


@pytest.mark.asyncio
async def test_todo_assign_nonexistent_epic_autocreates() -> None:
    with patch(
        "services.dashboard.routers.actions.assign_todo",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/todos/1/assign",
                json={"epic_id": "NEW-EPIC-999"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["epic_id"] == "NEW-EPIC-999"


# ---------------------------------------------------------------------------
# PATCH /api/todos/{todo_id}/priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todo_priority_valid() -> None:
    with patch(
        "services.dashboard.routers.actions.update_todo",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/todos/1/priority",
                json={"priority": 2},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["priority"] == 2


@pytest.mark.asyncio
async def test_todo_priority_out_of_range() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/todos/1/priority",
            json={"priority": -1},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/todos/{todo_id}/category
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todo_category_valid() -> None:
    with patch(
        "services.dashboard.routers.actions.update_todo",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/todos/1/category",
                json={"category": "infra"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["category"] == "infra"


@pytest.mark.asyncio
async def test_todo_category_empty() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/todos/1/category",
            json={"category": ""},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/epics/{epic_id}/prs — error path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_refs_clear_error() -> None:
    with patch(
        "services.dashboard.routers.actions.clear_current_prs",
        side_effect=SystemExit(1),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/epics/TEST-001/prs")

    assert response.status_code == 400
    assert "Clear PR refs failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# _safe_broadcast unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_broadcast_success() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    message = {"type": "test", "data": {"field": "value"}}

    await _safe_broadcast(ws_manager, message)

    ws_manager.broadcast.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_safe_broadcast_exception_swallowed() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock(side_effect=RuntimeError("connection lost"))
    message = {"type": "test"}

    # Should not raise
    await _safe_broadcast(ws_manager, message)

    ws_manager.broadcast.assert_called_once_with(message)


# ---------------------------------------------------------------------------
# WebSocket broadcast integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_broadcast_after_status_update() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.update_status", return_value={"success": True}):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/epics/TEST-001/status", json={"new_status": "completed"})
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["type"] == "epic_updated"
    assert msg["data"]["field"] == "status"


@pytest.mark.asyncio
async def test_ws_broadcast_after_priority_update() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.update_epic_priority", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/epics/TEST-001/priority", json={"priority": 7})
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["type"] == "epic_updated"
    assert msg["data"]["field"] == "priority"


@pytest.mark.asyncio
async def test_ws_broadcast_after_set_prs() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.set_current_prs", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put("/api/epics/TEST-001/prs", json={"pr_refs": "Org/repo#1"})
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["data"]["field"] == "pr_refs"


@pytest.mark.asyncio
async def test_ws_broadcast_after_clear_prs() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.clear_current_prs", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/epics/TEST-001/prs")
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["data"]["field"] == "pr_refs"
    assert msg["data"]["value"] == ""


@pytest.mark.asyncio
async def test_ws_broadcast_after_todo_done() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.done_todo", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/todos/1/done", json={"resolution": "Done"})
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["type"] == "todo_updated"
    assert msg["data"]["field"] == "status"


@pytest.mark.asyncio
async def test_ws_broadcast_after_todo_assign() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.assign_todo", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/todos/1/assign", json={"epic_id": "TEST-001"})
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["type"] == "todo_updated"
    assert msg["data"]["field"] == "epic_id"


@pytest.mark.asyncio
async def test_ws_broadcast_after_todo_priority() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.update_todo", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/todos/1/priority", json={"priority": 8})
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["data"]["field"] == "priority"


@pytest.mark.asyncio
async def test_ws_broadcast_after_todo_category() -> None:
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    app.state.ws_manager = ws_manager

    with patch("services.dashboard.routers.actions.update_todo", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/todos/1/category", json={"category": "ops"})
        await asyncio.sleep(0)

    assert response.status_code == 200
    ws_manager.broadcast.assert_called_once()
    msg = ws_manager.broadcast.call_args[0][0]
    assert msg["data"]["field"] == "category"


@pytest.mark.asyncio
async def test_ws_no_broadcast_when_manager_absent() -> None:
    app.state.ws_manager = None

    with patch("services.dashboard.routers.actions.update_status", return_value={"success": True}):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/epics/TEST-001/status", json={"new_status": "completed"})

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Malformed JSON body tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("patch", "/api/epics/TEST-001/status"),
        ("patch", "/api/epics/TEST-001/priority"),
        ("put", "/api/epics/TEST-001/prs"),
        ("patch", "/api/todos/1/done"),
        ("patch", "/api/todos/1/assign"),
        ("patch", "/api/todos/1/priority"),
        ("patch", "/api/todos/1/category"),
    ],
    ids=["status", "priority", "set_prs", "todo_done", "todo_assign", "todo_priority", "todo_category"],
)
async def test_malformed_json_body(method: str, path: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await getattr(client, method)(
            path,
            content=b"not json{{",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Boundary value tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epic_priority_boundary_zero() -> None:
    with patch("services.dashboard.routers.actions.update_epic_priority", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/epics/TEST-001/priority", json={"priority": 0})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_epic_priority_boundary_nine() -> None:
    with patch("services.dashboard.routers.actions.update_epic_priority", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/epics/TEST-001/priority", json={"priority": 9})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_epic_priority_boundary_ten() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/api/epics/TEST-001/priority", json={"priority": 10})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_epic_priority_boundary_negative() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/api/epics/TEST-001/priority", json={"priority": -1})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_todo_priority_boundary_zero() -> None:
    with patch("services.dashboard.routers.actions.update_todo", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/todos/1/priority", json={"priority": 0})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_todo_priority_boundary_nine() -> None:
    with patch("services.dashboard.routers.actions.update_todo", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/todos/1/priority", json={"priority": 9})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_todo_priority_boundary_ten() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/api/todos/1/priority", json={"priority": 10})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pr_refs_multiple_valid() -> None:
    with patch("services.dashboard.routers.actions.set_current_prs", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/epics/TEST-001/prs",
                json={"pr_refs": "Org/repo#1, Org/repo#2"},
            )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_pr_refs_empty_string() -> None:
    with patch("services.dashboard.routers.actions.set_current_prs", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/epics/TEST-001/prs",
                json={"pr_refs": ""},
            )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_todo_done_whitespace_only_resolution() -> None:
    # Whitespace-only " " passes Pydantic min_length=1 (counts characters,
    # not stripped length).  This documents the current behavior — the route
    # does not strip-validate the resolution field.
    with patch("services.dashboard.routers.actions.done_todo", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch("/api/todos/1/done", json={"resolution": " "})

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Sequential conflicting request tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sequential_status_transitions() -> None:
    with patch("services.dashboard.routers.actions.update_status", return_value={"success": True}):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.patch("/api/epics/TEST-001/status", json={"new_status": "completed"})
            resp2 = await client.patch("/api/epics/TEST-001/status", json={"new_status": "abandoned"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["new_status"] == "completed"
    assert resp2.json()["new_status"] == "abandoned"


@pytest.mark.asyncio
async def test_sequential_priority_updates() -> None:
    with patch("services.dashboard.routers.actions.update_epic_priority", return_value=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.patch("/api/epics/TEST-001/priority", json={"priority": 1})
            resp2 = await client.patch("/api/epics/TEST-001/priority", json={"priority": 8})

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["priority"] == 1
    assert resp2.json()["priority"] == 8


@pytest.mark.asyncio
async def test_sequential_pr_set_then_clear() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("services.dashboard.routers.actions.set_current_prs", return_value=None):
            resp1 = await client.put("/api/epics/TEST-001/prs", json={"pr_refs": "Org/repo#1"})
        with patch("services.dashboard.routers.actions.clear_current_prs", return_value=None):
            resp2 = await client.delete("/api/epics/TEST-001/prs")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["pr_refs"] == "Org/repo#1"
    assert resp2.json()["success"] is True
