"""Health check endpoint."""

from fastapi import APIRouter

from life_agent.core.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/health")
def health_check() -> dict[str, str]:
    """Report that this API process can respond.

    This does not verify PostgreSQL, model providers, or the Java services.
    """
    return {"status": "ok", "service": settings.app_name}
