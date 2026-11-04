"""Private map place lookup endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from life_agent.api.dependencies import CurrentUser
from life_agent.core.config import Settings, get_settings
from life_agent.tools.maps import MapPlaceSearchError, search_places

router = APIRouter(prefix="/maps")


class PlaceSearchResponse(BaseModel):
    places: list[dict[str, object]]
    source: dict[str, object]
    observed_at: str


@router.get("/places", response_model=PlaceSearchResponse)
async def get_places(
    _user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    query: Annotated[str, Query(min_length=1, max_length=120)],
    city: Annotated[str, Query(min_length=1, max_length=120)],
) -> PlaceSearchResponse:
    """Search POIs for a stated city; results are request-scoped and not persisted."""
    if "map" not in settings.mcp_services or not settings.mcp_services["map"].enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="地图服务未配置。",
        )
    try:
        return PlaceSearchResponse(
            **await search_places(settings, query, city=city)
        )
    except MapPlaceSearchError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
                if exc.code == "invalid_request"
                else status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.code == "not_configured"
                else status.HTTP_401_UNAUTHORIZED
                if exc.code == "authentication_failed"
                else status.HTTP_429_TOO_MANY_REQUESTS
                if exc.code == "rate_limited"
                else status.HTTP_504_GATEWAY_TIMEOUT
                if exc.code == "timeout"
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail={"code": exc.code, "message": exc.message},
        ) from exc
