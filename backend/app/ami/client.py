"""Asterisk AMI async client using panoramisk, with auto-reconnect."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

import panoramisk

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class AMIClient:
    """Persistent AMI connection with exponential-backoff reconnect loop."""

    def __init__(self) -> None:
        self._manager: Optional[panoramisk.Manager] = None
        self._connected = False
        self._event_handlers: list[tuple[str, Callable]] = []
        self._task: Optional[asyncio.Task] = None

    def register_event(self, pattern: str, callback: Callable) -> None:
        """Register an event handler before start()."""
        self._event_handlers.append((pattern, callback))

    async def start(self) -> None:
        """Launch the reconnect loop as a background task."""
        self._task = asyncio.create_task(self._reconnect_loop(), name="ami-reconnect")

    async def _reconnect_loop(self) -> None:
        backoff = 2
        while True:
            try:
                await self._run_session()
                backoff = 2  # reset on clean exit
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("ami_session_error", error=str(exc), retry_in=backoff)
            finally:
                self._connected = False
                self._manager = None

            logger.info("ami_reconnecting", in_seconds=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _run_session(self) -> None:
        manager = panoramisk.Manager(
            host=settings.asterisk_ami_host,
            port=settings.asterisk_ami_port,
            username=settings.asterisk_ami_user,
            secret=settings.asterisk_ami_secret,
        )
        for pattern, cb in self._event_handlers:
            manager.register_event(pattern, cb)

        try:
            await manager.connect()
            self._manager = manager
            self._connected = True
            logger.info("ami_connected", host=settings.asterisk_ami_host, port=settings.asterisk_ami_port)

            # Keep session alive via periodic Ping; exit on failure → triggers reconnect.
            while True:
                await asyncio.sleep(25)
                try:
                    await asyncio.wait_for(
                        manager.send_action({"Action": "Ping"}),
                        timeout=10.0,
                    )
                except Exception as exc:
                    logger.warning("ami_ping_failed", error=str(exc))
                    break
        finally:
            # Always close the manager so its TCP connection doesn't linger and
            # fire duplicate events when a new session is created on reconnect.
            self._connected = False
            self._manager = None
            try:
                manager.close()
            except Exception:
                pass

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._manager:
            try:
                self._manager.close()
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_action(self, action: dict) -> Optional[Any]:
        if not self._manager or not self._connected:
            return None
        try:
            return await asyncio.wait_for(
                self._manager.send_action(action),
                timeout=10.0,
            )
        except Exception as exc:
            logger.error("ami_send_action_failed", action=action.get("Action"), error=str(exc))
            return None


# Module-level singleton — used in consumer, routers and main.py.
ami_client = AMIClient()
