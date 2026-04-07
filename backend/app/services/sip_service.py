"""
SIP Integration Service — Placeholder for future Asterisk AMI/ARI integration.

This service will eventually:
- Register/unregister SIP peers in Asterisk
- Initiate calls via Asterisk Manager Interface (AMI)
- Handle DTMF-based unlock via SIP calls
- Retrieve peer status from Asterisk

For now it provides stubs that return "not_implemented" results,
allowing the rest of the system to compile and run cleanly.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.models import Device
from app.schemas import ActionResult

logger = get_logger(__name__)


class SIPService:
    """Placeholder SIP/Asterisk integration service."""

    def __init__(self):
        self._connected = False
        logger.info("sip_service_init", status="placeholder – Asterisk not connected")

    async def get_peer_status(self, sip_account: str) -> dict:
        """Return peer status from Asterisk. Not implemented."""
        return {
            "sip_account": sip_account,
            "status": "not_configured",
            "message": "Asterisk integration not yet configured",
        }

    async def originate_call(self, from_account: str, to_account: str) -> ActionResult:
        """Initiate a call via Asterisk AMI. Not implemented."""
        logger.info(
            "sip_originate_stub",
            from_account=from_account,
            to_account=to_account,
        )
        return ActionResult(
            success=False,
            message="SIP call origination not yet implemented",
            detail="Configure Asterisk AMI connection first",
        )

    async def send_dtmf_unlock(self, device: Device, dtmf_code: str = "#") -> ActionResult:
        """Send DTMF via active SIP call to trigger unlock. Not implemented."""
        return ActionResult(
            success=False,
            message="SIP DTMF unlock not yet implemented",
            detail="Requires active Asterisk AMI session",
        )

    async def health_check(self) -> dict:
        return {
            "status": "not_configured",
            "asterisk_ami": "disconnected",
            "message": "Future integration point – configure Asterisk AMI credentials in .env",
        }


# Module-level singleton
sip_service = SIPService()
