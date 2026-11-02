"""Aggregate API router."""

from fastapi import APIRouter

from life_agent.api.routes import auth, conversations, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(conversations.router, tags=["conversations"])
