"""Tests for the TODO listing API route.

Validates the ``GET /api/todos`` endpoint including status, category,
and epic_id filtering, sort column and direction validation, pagination
with ``has_more`` flag, limit capping, and response schema structure.
"""

from __future__ import annotations

import httpx
import pytest

from services.dashboard.app import app


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield dashboard_overrides


# ---------------------------------------------------------------------------
# GET /api/todos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_todos_default_returns_open() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos")

    assert response.status_code == 200
    body = response.json()
    assert all(t["status"] == "open" for t in body["todos"])
    assert any(t["id"] == 1 for t in body["todos"])
    assert not any(t["id"] == 2 for t in body["todos"])
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_list_todos_status_all() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    ids = {t["id"] for t in body["todos"]}
    assert ids == {1, 2}


@pytest.mark.asyncio
async def test_list_todos_status_done() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=done")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["todos"][0]["id"] == 2
    assert body["todos"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_list_todos_category_filter() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all&category=infra")

    assert response.status_code == 200
    body = response.json()
    assert len(body["todos"]) == 1
    assert body["todos"][0]["id"] == 1


@pytest.mark.asyncio
async def test_list_todos_epic_id_filter(dashboard_overrides) -> None:
    db = dashboard_overrides["db"]
    db.execute(
        "INSERT INTO todos (title, status, priority, category, epic_id, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Epic TODO", "open", 2, "code", "TEST-001", "2026-01-15", "2026-01-15"),
    )
    db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all&epic_id=TEST-001")

    assert response.status_code == 200
    body = response.json()
    assert len(body["todos"]) == 1
    assert body["todos"][0]["epic_id"] == "TEST-001"


@pytest.mark.asyncio
async def test_list_todos_combined_filters() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_open_infra = await client.get("/api/todos?status=open&category=infra")

    assert resp_open_infra.status_code == 200
    body_open = resp_open_infra.json()
    assert len(body_open["todos"]) == 1
    assert body_open["todos"][0]["id"] == 1

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_done_infra = await client.get("/api/todos?status=done&category=infra")

    assert resp_done_infra.status_code == 200
    body_done = resp_done_infra.json()
    assert body_done["total"] == 0


@pytest.mark.asyncio
async def test_list_todos_invalid_sort_column() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?sort=nonexistent")

    assert response.status_code == 400
    assert "Invalid sort column" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_todos_invalid_order() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?order=sideways")

    assert response.status_code == 400
    assert "Invalid order direction" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_todos_pagination(dashboard_overrides) -> None:
    db = dashboard_overrides["db"]
    for i in range(3):
        db.execute(
            "INSERT INTO todos (title, status, priority, category, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"Extra TODO {i}", "open", 2, "code", "2026-01-10", "2026-01-10"),
        )
    db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_page1 = await client.get("/api/todos?status=all&limit=2&offset=0")

    assert resp_page1.status_code == 200
    body1 = resp_page1.json()
    assert body1["total"] == 5
    assert body1["has_more"] is True
    assert len(body1["todos"]) == 2

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_page3 = await client.get("/api/todos?status=all&limit=2&offset=4")

    assert resp_page3.status_code == 200
    body3 = resp_page3.json()
    assert body3["has_more"] is False
    assert len(body3["todos"]) == 1


@pytest.mark.asyncio
async def test_list_todos_limit_capped_at_200() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all&limit=500")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["todos"]) == 2


@pytest.mark.asyncio
async def test_list_todos_sort_by_created_at(dashboard_overrides) -> None:
    db = dashboard_overrides["db"]
    db.execute(
        "INSERT INTO todos (title, status, priority, category, created_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("Newer TODO", "open", 4, "infra", "2026-02-01", "2026-02-01"),
    )
    db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all&sort=created_at&order=asc")

    assert response.status_code == 200
    body = response.json()
    dates = [t["created_at"] for t in body["todos"]]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_list_todos_sort_desc() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all&sort=priority&order=desc")

    assert response.status_code == 200
    body = response.json()
    priorities = [t["priority"] for t in body["todos"]]
    assert priorities == sorted(priorities, reverse=True)


@pytest.mark.asyncio
async def test_list_todos_empty_result() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all&category=nonexistent")

    assert response.status_code == 200
    body = response.json()
    assert body["todos"] == []
    assert body["total"] == 0
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_todos_response_schema() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos?status=all")

    assert response.status_code == 200
    body = response.json()
    assert "todos" in body
    assert "total" in body
    assert "has_more" in body

    expected_item_keys = {
        "id",
        "title",
        "status",
        "priority",
        "category",
        "epic_id",
        "description",
        "created_at",
        "last_updated_at",
    }
    for todo in body["todos"]:
        assert set(todo.keys()) == expected_item_keys


# ---------------------------------------------------------------------------
# GET /api/todos/{todo_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_todo_by_id_found() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["title"] == "Test TODO"


@pytest.mark.asyncio
async def test_get_todo_by_id_not_found() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos/999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_todo_by_id_invalid_param() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos/abc")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_todo_by_id_response_schema() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos/1")

    assert response.status_code == 200
    body = response.json()
    expected_keys = {
        "id",
        "title",
        "status",
        "priority",
        "category",
        "epic_id",
        "description",
        "created_at",
        "last_updated_at",
    }
    assert set(body.keys()) == expected_keys


@pytest.mark.asyncio
async def test_get_todo_by_id_negative_int() -> None:
    """GET /api/todos/-1 returns 404 (valid int path param, no row)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/todos/-1")
    assert response.status_code == 404
