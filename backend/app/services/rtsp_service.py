"""
RTSP Integration Service — Placeholder for future RTSP stream integration.

This service will eventually:
- Proxy RTSP streams via a media server (e.g., MediaMTX / rtsp-simple-server)
- Provide WebRTC or HLS transcoded streams for the web frontend
- Take snapshots from RTSP streams using ffmpeg
- Monitor stream health

For now it provides stubs that log intent and return "not_implemented" results.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.models import Device
from app.schemas import ActionResult

logger = get_logger(__name__)


class RTSPService:
    """Placeholder RTSP stream integration service."""

    def __init__(self):
        logger.info("rtsp_service_init", status="placeholder – no media server connected")

    async def get_stream_url(self, device: Device) -> dict:
        """Return playable stream info for a device."""
        if not device.rtsp_enabled or not device.rtsp_url:
            return {"available": False, "reason": "RTSP not configured for this device"}

        return {
            "available": True,
            "rtsp_url": device.rtsp_url,
            "hls_url": None,  # Future: proxy via MediaMTX
            "webrtc_url": None,  # Future: proxy via MediaMTX
            "note": "Direct RTSP URL – HLS/WebRTC transcoding not yet configured",
        }

    async def take_snapshot(self, device: Device) -> ActionResult:
        """Capture a snapshot from the device RTSP stream. Not implemented."""
        return ActionResult(
            success=False,
            message="RTSP snapshot not yet implemented",
            detail="Requires ffmpeg and MediaMTX integration",
        )

    async def check_stream_health(self, device: Device) -> ActionResult:
        """Check if the RTSP stream is accessible. Not implemented."""
        return ActionResult(
            success=False,
            message="RTSP health check not yet implemented",
            detail="Future integration – will use ffprobe",
        )

    async def health_check(self) -> dict:
        return {
            "status": "not_configured",
            "media_server": "not_connected",
            "message": "Future integration point – configure MediaMTX or similar",
        }


# Module-level singleton
rtsp_service = RTSPService()
