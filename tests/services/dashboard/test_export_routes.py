"""Tests for the epic export API route.

Validates the ``GET /api/epics/{epic_id}/export`` endpoint including
input validation, zip archive structure, artifact metadata encoding,
and edge cases for epic ID formats.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import yaml

from services.dashboard.app import app


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield dashboard_overrides


# ---------------------------------------------------------------------------
# GET /api/epics/{epic_id}/export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_invalid_epic_id_format() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/epics/bad%20epic%21id/export")

    assert response.status_code == 400
    assert "Invalid epic_id format" in response.json()["detail"]


@pytest.mark.asyncio
async def test_export_epic_not_found() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/epics/NONEXISTENT-999/export")

    assert response.status_code == 404
    assert "NONEXISTENT-999" in response.json()["detail"]


@pytest.mark.asyncio
async def test_export_success_with_artifacts() -> None:
    mock_artifacts: list[dict[str, Any]] = [
        {
            "id": "art-1",
            "document": "Step result content",
            "metadata": {
                "epic_id": "TEST-001",
                "artifact_type": "step_result",
                "timestamp": "2026-04-01T10:00:00",
                "verdict": "GREEN",
            },
        },
        {
            "id": "art-2",
            "document": "Gate verdict content",
            "metadata": {
                "epic_id": "TEST-001",
                "artifact_type": "gate_verdict",
                "timestamp": "2026-04-02T12:30:00",
                "verdict": "FAIL",
            },
        },
    ]

    with patch(
        "services.dashboard.routers.export.get_timeline",
        return_value=mock_artifacts,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics/TEST-001/export")

    assert response.status_code == 200
    assert "application/zip" in response.headers["content-type"]
    assert "TEST-001" in response.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = zf.namelist()

    assert "TEST-001/epic.yaml" in names
    assert "TEST-001/artifacts/001_step_result_2026-04-01T10-00-00.md" in names
    assert "TEST-001/artifacts/002_gate_verdict_2026-04-02T12-30-00.md" in names

    epic_yaml = yaml.safe_load(zf.read("TEST-001/epic.yaml"))
    assert "epic_id" in epic_yaml
    assert "artifact_manifest" in epic_yaml
    assert len(epic_yaml["artifact_manifest"]) == 2

    artifact_md = zf.read("TEST-001/artifacts/001_step_result_2026-04-01T10-00-00.md").decode()
    assert artifact_md.startswith("---\n")


@pytest.mark.asyncio
async def test_export_success_no_artifacts() -> None:
    with patch(
        "services.dashboard.routers.export.get_timeline",
        return_value=[],
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics/TEST-001/export")

    assert response.status_code == 200

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = zf.namelist()

    assert "TEST-001/epic.yaml" in names

    epic_yaml = yaml.safe_load(zf.read("TEST-001/epic.yaml"))
    assert epic_yaml["artifact_manifest"] == []

    artifact_files = [n for n in names if n.startswith("TEST-001/artifacts/")]
    assert artifact_files == []


@pytest.mark.asyncio
async def test_export_artifact_metadata_encoding() -> None:
    mock_artifacts: list[dict[str, Any]] = [
        {
            "id": "art-enc",
            "document": "Encoding test",
            "metadata": {
                "epic_id": "TEST-001",
                "artifact_type": "step_result",
                "timestamp": "2026-04-01T10:15:30",
                "verdict": "GREEN",
            },
        },
    ]

    with patch(
        "services.dashboard.routers.export.get_timeline",
        return_value=mock_artifacts,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics/TEST-001/export")

    assert response.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = zf.namelist()
    assert "TEST-001/artifacts/001_step_result_2026-04-01T10-15-30.md" in names


@pytest.mark.asyncio
async def test_export_epic_id_with_hyphens_and_underscores(
    dashboard_overrides,
) -> None:
    db = dashboard_overrides["db"]
    db.execute(
        """INSERT INTO epics VALUES (
            'TEST_EPIC-001', 'backlog', 5, '[]', '', '',
            'Hybrid ID Epic', '2026-01-01', '2026-01-02', NULL
        )"""
    )
    db.commit()

    with patch(
        "services.dashboard.routers.export.get_timeline",
        return_value=[],
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics/TEST_EPIC-001/export")

    assert response.status_code == 200
    assert "TEST_EPIC-001" in response.headers["content-disposition"]
