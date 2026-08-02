"""Health check endpoint for the ledger dashboard.

Provides a simple liveness probe for container orchestration
and monitoring tools.
"""

from fastapi import APIRouter

router: APIRouter = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Return service health status.

    Returns:
        dict: A JSON object with status ``ok``.
    """
    return {"status": "ok"}
