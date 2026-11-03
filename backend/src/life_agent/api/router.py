"""Aggregate API router."""

from fastapi import APIRouter

from life_agent.api.routes import (
	auth,
	chat,
	conversations,
	health,
	maps,
	runs,
	shopping_adjustments,
	tasks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(conversations.router, tags=["conversations"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(runs.router, tags=["runs"])
api_router.include_router(shopping_adjustments.router, tags=["shopping-adjustments"])
api_router.include_router(maps.router, tags=["maps"])
