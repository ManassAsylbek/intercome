"""Persistent override for cloud_bridge_token.

The token comes from docker-compose env interpolation at container start
(``CLOUD_BRIDGE_TOKEN`` from the host's ``.env``). When the cloud rotates
the token via the ``update_bridge_token`` WS command, we cannot rewrite the
host's ``.env`` from inside the container. Instead we drop the new token in
the persistent data volume; on the next process start it overrides the env
value, and at runtime we mutate ``settings.cloud_bridge_token`` in place so
the reconnect loop reads it immediately.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

_TOKEN_FILE = Path(os.environ.get("CLOUD_BRIDGE_TOKEN_FILE", "/app/data/cloud_bridge_token"))


def load_persisted_token() -> str | None:
    """Return the persisted token or None if no override exists."""
    try:
        if _TOKEN_FILE.exists():
            tok = _TOKEN_FILE.read_text(encoding="utf-8").strip()
            return tok or None
    except Exception as exc:
        logger.warning("persisted_token_read_failed", error=str(exc))
    return None


def persist_token(new_token: str) -> None:
    """Write the new token atomically. Raises on failure."""
    if not new_token or not isinstance(new_token, str):
        raise ValueError("new_token must be a non-empty string")
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(new_token, encoding="utf-8")
    os.replace(tmp, _TOKEN_FILE)


def apply_persisted_token_override(settings) -> None:
    """If a persisted token exists, override settings.cloud_bridge_token in place."""
    persisted = load_persisted_token()
    if persisted and persisted != settings.cloud_bridge_token:
        settings.cloud_bridge_token = persisted
        logger.info("cloud_bridge_token_loaded_from_disk")
