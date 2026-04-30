"""go2rtc configuration manager.

Generates and writes go2rtc.yaml from the DB whenever RTSP-enabled devices
change. go2rtc watches the config file via fsnotify and reloads automatically.

File path is configured via GO2RTC_CONFIG_PATH (default /go2rtc_config/go2rtc.yaml)
which maps to ./docker/go2rtc/go2rtc.yaml on the host — the same file mounted
into the go2rtc container at /config/go2rtc.yaml.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def stream_name(device_id: int) -> str:
    return f"panel-{device_id}"


def _render_yaml(streams: dict[str, str]) -> str:
    """Render a complete go2rtc.yaml as a string."""
    lines: list[str] = []

    # Streams section
    lines.append("streams:")
    if streams:
        for name, rtsp_url in streams.items():
            lines.append(f"  {name}:")
            lines.append(f"    - {rtsp_url}")
    else:
        lines.append("  {}")
    lines.append("")

    # API section
    lines.append("api:")
    lines.append('  listen: ":1984"')
    lines.append('  origin: "*"')
    lines.append("")

    # WebRTC section
    lines.append("webrtc:")
    lines.append('  listen: ":8555"')

    # Candidates — LAN + WAN + stun so ICE never hangs on timeout
    candidates: list[str] = []
    if settings.server_ip:
        candidates.append(f"{settings.server_ip}:8555")
    host = settings.public_bridge_host
    if host and host != settings.server_ip:
        candidates.append(f"{host}:8555")
    candidates.append("stun:8555")

    lines.append("  candidates:")
    for c in candidates:
        lines.append(f"    - {c}")

    # ICE servers
    lines.append("  ice_servers:")
    lines.append("    - urls:")
    lines.append('        - "stun:stun.l.google.com:19302"')

    if settings.coturn_public_host and settings.coturn_user and settings.coturn_cred:
        h = settings.coturn_public_host
        p = settings.coturn_port
        lines.append("    - urls:")
        lines.append(f'        - "turn:{h}:{p}?transport=udp"')
        lines.append(f'        - "turn:{h}:{p}?transport=tcp"')
        lines.append(f'      username: "{settings.coturn_user}"')
        lines.append(f'      credential: "{settings.coturn_cred}"')

    lines.append("")
    return "\n".join(lines)


def _rtsp_with_hints(rtsp_url: str) -> str:
    """Append go2rtc URL hints for fast connection.

    #timeout=10000 — abort RTSP connect after 10 s.
    No #hardware: may not be available on all servers and silently breaks stream.
    """
    if "#" not in rtsp_url:
        return f"{rtsp_url}#timeout=10000"
    return rtsp_url


async def write_config() -> None:
    """Rebuild go2rtc.yaml from DB and write it to the shared config path.

    go2rtc detects the change via fsnotify and reloads automatically.
    """
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import Device

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Device).where(
                    Device.enabled == True,       # noqa: E712
                    Device.rtsp_enabled == True,  # noqa: E712
                    Device.rtsp_url.isnot(None),
                )
            )
            devices = result.scalars().all()

        streams = {
            stream_name(d.id): _rtsp_with_hints(d.rtsp_url)
            for d in devices
        }

        config_path = Path(settings.go2rtc_config_path)
        yaml_content = _render_yaml(streams)

        await asyncio.get_event_loop().run_in_executor(
            None, config_path.write_text, yaml_content
        )
        logger.info("go2rtc_config_written", path=str(config_path), streams=list(streams.keys()))

        # go2rtc doesn't auto-reload bind-mounted files — restart the container.
        await _restart_go2rtc()
    except Exception as exc:
        logger.warning("go2rtc_config_write_failed", error=str(exc))


async def _restart_go2rtc() -> None:
    """Restart the go2rtc container so it picks up the new config."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "restart", "intercom-go2rtc",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if proc.returncode != 0:
            logger.warning("go2rtc_restart_failed", stderr=stderr.decode().strip())
        else:
            logger.info("go2rtc_restarted")
    except asyncio.TimeoutError:
        logger.warning("go2rtc_restart_timeout")
    except Exception as exc:
        logger.warning("go2rtc_restart_error", error=str(exc))


# Keep these as thin wrappers so device_service call sites stay unchanged.
async def sync_stream(device_id: int, rtsp_url: str) -> None:
    await write_config()


async def remove_stream(device_id: int) -> None:
    await write_config()


async def sync_all_from_db() -> None:
    await write_config()
