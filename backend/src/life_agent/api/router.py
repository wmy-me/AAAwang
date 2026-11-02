"""Aggregate API router."""

from fastapi import APIRouter

from life_agent.api.routes import health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
