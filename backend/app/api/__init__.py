"""API router aggregator."""

from fastapi import APIRouter

from app.api.routes import apartments, auth, calls, dashboard, devices, events, routing_rules, sip

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(events.router)   # GET /api/events/stream
api_router.include_router(calls.router)
api_router.include_router(sip.router)      # POST /api/sip/webrtc-endpoint
api_router.include_router(devices.router)
api_router.include_router(routing_rules.router)
api_router.include_router(apartments.router)
api_router.include_router(dashboard.router)
