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
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc