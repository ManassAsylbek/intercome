"""API router aggregator."""

from fastapi import APIRouter

from app.api.routes import auth, dashboard, devices, routing_rules

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(devices.router)
api_router.include_router(routing_rules.router)
api_router.include_router(dashboard.router)
