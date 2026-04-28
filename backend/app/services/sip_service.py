"""
SIP / Asterisk integration service.

Поддерживает два режима (ASTERISK_MODE в .env):
  - local  — читает/пишет pjsip.conf прямо на диске, перезагружает через subprocess
  - ssh    — то же самое через Paramiko SSH (для удалённого Asterisk-сервера)

Формат управляемого блока в pjsip.conf:

    ; === managed by intercom-server: 1001 ===
    [1001]
    type=endpoint
    ...

    [1001]
    type=auth
    auth_type=userpass
    username=1001
    password=1001

    [1001]
    type=aor
    max_contacts=1
    ; === end managed 1001 ===

Если аккаунт уже есть — заменяет только password= внутри блока type=auth.
Если аккаунта нет — дописывает три блока в конец файла.
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import subprocess
import tempfile
import time
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import ActionResult

logger = get_logger(__name__)

# ─── Шаблон блока pjsip.conf ──────────────────────────────────────────────────

_BLOCK_START = "; === managed by intercom-server: {acct} ==="
_BLOCK_END   = "; === end managed {acct} ==="

_MANAGED_BLOCK_TMPL = """\
; === managed by intercom-server: {acct} ===
[{acct}]
type=endpoint
context=intercom
disallow=all
allow=alaw
allow=ulaw
auth=auth{acct}
aors={acct}
direct_media=no
rtp_symmetric=yes
force_rport=yes
ice_support=no
rewrite_contact=yes
media_use_received_transport=yes
dtmf_mode=rfc4733
rtcp_mux=no
allow_transfer=no
send_rpid=yes
trust_id_inbound=yes
rtp_timeout=30
rtp_timeout_hold=60
transport=transport-udp

[auth{acct}]
type=auth
auth_type=userpass
username={acct}
password={password}

[{acct}]
type=aor
max_contacts=2
remove_existing=yes
qualify_frequency=0
; === end managed {acct} ===
"""

# ─── Шаблон блока extensions.conf ────────────────────────────────────────────

_EXT_BLOCK_START = "; === managed extension: {acct} ==="
_EXT_BLOCK_END   = "; === end extension: {acct} ==="

_EXT_BLOCK_TMPL = """\
; === managed extension: {acct} ===
exten => {acct},1,NoOp(Incoming call to {acct} from ${{CALLERID(num)}})
exten => {acct},n,Set(CALL_UID=${{UNIQUEID}})
exten => {acct},n,Set(UNUSED=${{CURL(http://127.0.0.1:8000/api/webhooks/asterisk?event=call_start&caller=${{CALLERID(num)}}&callee={acct}&call_id=${{CALL_UID}})}})
exten => {acct},n,Set(JITTERBUFFER(adaptive)=default)
exten => {acct},n,Dial(PJSIP/1099&PJSIP/{acct},60,g)
exten => {acct},n,Set(UNUSED=${{CURL(http://127.0.0.1:8000/api/webhooks/asterisk?event=call_end&caller=${{CALLERID(num)}}&call_id=${{CALL_UID}})}})
exten => {acct},n,Hangup()
; === end extension: {acct} ===
"""


def _ext_apply_to_text(text: str, acct: str) -> str:
    """Добавляет управляемый блок расширения если его ещё нет в extensions.conf."""
    start_marker = _EXT_BLOCK_START.format(acct=acct)
    if start_marker in text:
        return text  # уже есть — не трогаем
    block = _EXT_BLOCK_TMPL.format(acct=acct)
    return text.rstrip("\n") + "\n\n" + block + "\n"


def _apply_extension_to_conf(acct: str) -> ActionResult:
    """Добавляет экстеншн для аккаунта в extensions.conf если его нет."""
    conf = settings.asterisk_extensions_conf
    try:
        with open(conf, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as exc:
        return ActionResult(success=False, message=f"Не могу прочитать {conf}", detail=str(exc))

    if _EXT_BLOCK_START.format(acct=acct) in text:
        return ActionResult(success=True, message=f"Экстеншн {acct} уже есть в extensions.conf")

    new_text = _ext_apply_to_text(text, acct)
    try:
        with open(conf, "w", encoding="utf-8") as f:
            f.write(new_text)
    except Exception as exc:
        return ActionResult(success=False, message=f"Не могу записать {conf}", detail=str(exc))

    # Reload dialplan via docker exec
    try:
        result = subprocess.run(
            ["docker", "exec", "intercom-asterisk", "asterisk", "-rx", "dialplan reload"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return ActionResult(success=True, message=f"Экстеншн {acct} добавлен в extensions.conf, dialplan перезагружен")
        return ActionResult(success=True, message=f"Экстеншн {acct} добавлен в extensions.conf (dialplan reload не удался)")
    except Exception:
        return ActionResult(success=True, message=f"Экстеншн {acct} добавлен в extensions.conf")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _update_password_in_block(text: str, acct: str, password: str) -> str:
    """Заменяет password= внутри управляемого блока аккаунта."""
    start_marker = _BLOCK_START.format(acct=acct)
    end_marker   = _BLOCK_END.format(acct=acct)

    start_idx = text.find(start_marker)
    end_idx   = text.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return text

    block = text[start_idx : end_idx + len(end_marker)]
    new_block = re.sub(
        r"(type=auth.*?password=)[^\n]*",
        rf"\g<1>{re.escape(password)}",
        block,
        flags=re.DOTALL,
    )
    return text[:start_idx] + new_block + text[end_idx + len(end_marker):]


def _inject_block(text: str, acct: str, password: str) -> str:
    """Дописывает новый управляемый блок в конец файла."""
    block = _MANAGED_BLOCK_TMPL.format(acct=acct, password=password)
    return text.rstrip("\n") + "\n\n" + block + "\n"


def _apply_to_text(text: str, acct: str, password: str) -> str:
    """Обновить или добавить блок аккаунта."""
    if _BLOCK_START.format(acct=acct) in text:
        return _update_password_in_block(text, acct, password)
    return _inject_block(text, acct, password)


def _reload_local(cmd: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True, result.stdout.strip() or "OK"
        return False, result.stderr.strip() or f"exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timeout waiting for asterisk reload"
    except Exception as exc:
        return False, str(exc)


def _reload_via_ami(command: str = "pjsip reload") -> tuple[bool, str]:
    """Перезагружает Asterisk через AMI, отправляя произвольную команду."""
    host   = settings.asterisk_ami_host
    port   = settings.asterisk_ami_port
    user   = settings.asterisk_ami_user
    secret = settings.asterisk_ami_secret

    try:
        sock = socket.create_connection((host, port), timeout=10)
        sock.settimeout(10)

        def recv_block() -> str:
            """Читает до двойного CRLF (конец AMI-блока)."""
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            return buf.decode(errors="replace")

        def send_action(msg: str) -> None:
            sock.sendall((msg + "\r\n\r\n").encode())

        # Читаем баннер (одна строка типа "Asterisk Call Manager/11.0.0\r\n")
        banner_buf = b""
        while b"\n" not in banner_buf:
            banner_buf += sock.recv(256)

        # Login
        send_action(f"Action: Login\r\nUsername: {user}\r\nSecret: {secret}")
        login_resp = recv_block()
        if "Success" not in login_resp:
            sock.close()
            return False, f"AMI login failed: {login_resp.strip()}"

        # Send command
        send_action(f"Action: Command\r\nCommand: {command}")
        cmd_resp = recv_block()

        # Logoff
        try:
            send_action("Action: Logoff")
        except Exception:
            pass
        sock.close()

        return True, cmd_resp.strip() or "OK"
    except Exception as exc:
        return False, f"AMI error: {exc}"



def reload_asterisk_ami(commands: list[str] | None = None) -> ActionResult:
    """Перезагружает нужные модули Asterisk через AMI. Публичная функция."""
    if commands is None:
        commands = ["module reload res_pjsip.so", "dialplan reload"]
    errors = []
    for cmd in commands:
        ok, msg = _reload_via_ami(cmd)
        if not ok:
            errors.append(f"{cmd}: {msg}")
    if errors:
        return ActionResult(
            success=False,
            message="Asterisk reload не удался",
            detail="; ".join(errors),
        )
    return ActionResult(success=True, message="Asterisk перезагружен через AMI")


def _reload_via_docker_exec() -> tuple[bool, str]:
    """Reload Asterisk via 'docker exec' — works in Docker Compose setup."""
    try:
        result = subprocess.run(
            ["docker", "exec", "intercom-asterisk", "asterisk", "-rx", "module reload res_pjsip.so"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or "OK"
        return False, result.stderr.strip() or f"exit code {result.returncode}"
    except FileNotFoundError:
        return False, "docker CLI not found"
    except Exception as exc:
        return False, str(exc)


def _reload_via_docker_exec_dialplan() -> tuple[bool, str]:
    """Reload dialplan via 'docker exec'."""
    try:
        result = subprocess.run(
            ["docker", "exec", "intercom-asterisk", "asterisk", "-rx", "dialplan reload"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or "OK"
        return False, result.stderr.strip() or f"exit code {result.returncode}"
    except FileNotFoundError:
        return False, "docker CLI not found"
    except Exception as exc:
        return False, str(exc)


# ─── Transport ────────────────────────────────────────────────────────────────


def _apply_local(acct: str, password: str) -> ActionResult:
    conf       = settings.asterisk_pjsip_conf
    reload_cmd = settings.asterisk_reload_cmd

    try:
        with open(conf, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return ActionResult(
            success=False,
            message=f"pjsip.conf не найден: {conf}",
            detail="Проверьте ASTERISK_PJSIP_CONF в .env",
        )
    except PermissionError:
        return ActionResult(
            success=False,
            message=f"Нет доступа на чтение {conf}",
            detail="Запустите бэкенд от root или добавьте sudo-права",
        )

    new_text = _apply_to_text(text, acct, password)

    try:
        with open(conf, "w", encoding="utf-8") as f:
            f.write(new_text)
    except PermissionError:
        return ActionResult(
            success=False,
            message=f"Нет доступа на запись {conf}",
            detail="sudo chmod a+rw /etc/asterisk/pjsip.conf  — или запустите от root",
        )

    # Try configured reload command first (if set)
    if reload_cmd:
        ok, msg = _reload_local(reload_cmd)
        if ok:
            return ActionResult(
                success=True,
                message=f"pjsip.conf обновлён, Asterisk перезагружен (аккаунт {acct})",
            )
        logger.warning("local_reload_cmd_failed_trying_docker_exec", cmd=reload_cmd, error=msg)

    # Fallback: docker exec (backend has /var/run/docker.sock mounted)
    ok2, msg2 = _reload_via_docker_exec()
    if ok2:
        return ActionResult(
            success=True,
            message=f"pjsip.conf обновлён, Asterisk перезагружен через docker exec (аккаунт {acct})",
        )
    return ActionResult(
        success=False,
        message="pjsip.conf обновлён, но перезагрузка Asterisk не удалась",
        detail=f"reload_cmd: {msg if reload_cmd else 'not set'} | docker exec: {msg2}",
    )


def _apply_local_ami(acct: str, password: str) -> ActionResult:
    """Пишет pjsip.conf локально, перезагружает через AMI."""
    conf = settings.asterisk_pjsip_conf
    try:
        with open(conf, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as exc:
        return ActionResult(success=False, message=f"Не могу прочитать {conf}", detail=str(exc))

    new_text = _apply_to_text(text, acct, password)

    try:
        with open(conf, "w", encoding="utf-8") as f:
            f.write(new_text)
    except Exception as exc:
        return ActionResult(success=False, message=f"Не могу записать {conf}", detail=str(exc))

    ok, msg = _reload_via_ami("module reload res_pjsip.so")
    if ok:
        return ActionResult(
            success=True,
            message=f"pjsip.conf обновлён, Asterisk перезагружен через AMI (аккаунт {acct})",
        )
    logger.warning("ami_reload_failed_trying_docker_exec", ami_error=msg)
    # Fallback: docker exec (backend has /var/run/docker.sock mounted)
    ok2, msg2 = _reload_via_docker_exec()
    if ok2:
        return ActionResult(
            success=True,
            message=f"pjsip.conf обновлён, Asterisk перезагружен через docker exec (аккаунт {acct})",
        )
    return ActionResult(
        success=False,
        message="pjsip.conf обновлён, но перезагрузка Asterisk не удалась",
        detail=f"AMI: {msg} | docker exec: {msg2}",
    )


def _apply_via_ssh(acct: str, password: str) -> ActionResult:
    try:
        import paramiko  # noqa: PLC0415
    except ImportError:
        return ActionResult(
            success=False,
            message="Paramiko не установлен",
            detail="pip install paramiko",
        )

    host       = settings.asterisk_ssh_host
    port       = settings.asterisk_ssh_port
    user       = settings.asterisk_ssh_user
    key_file   = settings.asterisk_ssh_key_file or None
    conf       = settings.asterisk_pjsip_conf
    reload_cmd = settings.asterisk_reload_cmd

    if not host or not user:
        return ActionResult(
            success=False,
            message="SSH не настроен",
            detail="Задайте ASTERISK_SSH_HOST и ASTERISK_SSH_USER в .env",
        )

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw: dict = {"hostname": host, "port": port, "username": user, "timeout": 15}
        if key_file:
            kw["key_filename"] = key_file
        ssh.connect(**kw)

        sftp = ssh.open_sftp()
        with sftp.open(conf, "r") as fh:
            text = fh.read().decode("utf-8")

        new_text = _apply_to_text(text, acct, password)

        with sftp.open(conf, "w") as fh:
            fh.write(new_text.encode("utf-8"))
        sftp.close()

        _, stdout, stderr = ssh.exec_command(reload_cmd)
        exit_status = stdout.channel.recv_exit_status()
        ssh.close()

        if exit_status == 0:
            return ActionResult(
                success=True,
                message=f"[SSH] pjsip.conf обновлён и Asterisk перезагружен (аккаунт {acct})",
            )
        return ActionResult(
            success=False,
            message=f"[SSH] pjsip.conf обновлён, но reload не удался (exit {exit_status})",
            detail=stderr.read().decode().strip(),
        )
    except Exception as exc:
        logger.error("sip_ssh_error", acct=acct, error=str(exc))
        return ActionResult(success=False, message="SSH ошибка", detail=str(exc))


# ─── SIPService ───────────────────────────────────────────────────────────────


class SIPService:
    """Управление SIP-аккаунтами в Asterisk через pjsip.conf."""

    def apply_credentials(self, acct: str, password: str) -> ActionResult:
        """
        Обновляет (или создаёт) SIP-аккаунт в pjsip.conf и перезагружает Asterisk.
        Режим определяется ASTERISK_MODE в .env: 'local', 'ssh' или 'ami'.
        """
        logger.info("sip_apply_credentials", acct=acct, mode=settings.asterisk_mode)
        if settings.asterisk_mode == "ssh":
            result = _apply_via_ssh(acct, password)
        elif settings.asterisk_mode == "ami":
            result = _apply_local_ami(acct, password)
        else:
            result = _apply_local(acct, password)
        if result.success:
            _apply_extension_to_conf(acct)
        return result

    async def get_peer_status(self, sip_account: str) -> dict:
        return {
            "sip_account": sip_account,
            "status": "not_configured",
            "message": "Asterisk AMI polling not yet implemented",
        }

    async def health_check(self) -> dict:
        mode = settings.asterisk_mode
        conf = settings.asterisk_pjsip_conf
        readable = False
        detail = ""

        if mode in ("local", "ami"):
            try:
                with open(conf, "r"):
                    readable = True
                detail = "OK"
            except Exception as exc:
                detail = str(exc)
        else:
            detail = "SSH mode"
            readable = True  # Assume configured if SSH is set up

        return {
            "status": "configured" if readable else "not_configured",
            "mode": mode,
            "pjsip_conf": conf,
            "pjsip_readable": readable,
            "detail": detail or "OK",
        }

    def generate_extensions_conf(
        self,
        apartments: list[dict],
        backend_url: str = "http://127.0.0.1:8000",
    ) -> ActionResult:
        """
        Генерирует extensions.conf из списка квартир:
            apartments = [
                {
                    "call_code": "1042",
                    "monitors": ["1001", "1003"],      # SIP-аккаунты мониторов
                    "cloud_relay_enabled": True,
                    "cloud_sip_account": "1042",       # аккаунт на облачном транке
                },
                ...
            ]
        Каждая квартира → один extension.
        Dial: PJSIP/1099 (браузер) + все мониторы + облако (если включено).
        """
        conf_path = settings.asterisk_extensions_conf
        cloud_trunk = settings.cloud_sip_trunk_endpoint
        lines: list[str] = []

        lines.append("; ─── Intercom dialplan — generated by intercom-server ─────────────────────────")
        lines.append("; DO NOT EDIT MANUALLY — изменения перезапишутся автоматически.")
        lines.append("; Управляйте квартирами через веб-интерфейс → Квартиры.")
        lines.append("")
        lines.append("[general]")
        lines.append("static=yes")
        lines.append("writeprotect=no")
        lines.append("")
        lines.append("[intercom]")

        for apt in sorted(apartments, key=lambda a: a["call_code"]):
            call_code = apt["call_code"]
            monitors = apt.get("monitors", [])
            cloud_enabled = apt.get("cloud_relay_enabled", False)
            cloud_acct = apt.get("cloud_sip_account") or call_code

            # Build dial targets: browser + monitors + cloud
            dial_parts = list(dict.fromkeys(["1099"] + monitors))
            if cloud_enabled and cloud_trunk:
                dial_parts.append(f"{cloud_acct}@{cloud_trunk}")

            dial_str = "&".join(
                f"PJSIP/{p}" if "@" not in p else f"PJSIP/{p}"
                for p in dial_parts
            )

            lines.append("")
            lines.append(f"; === Квартира {call_code}: {', '.join(dial_parts)} ===")
            lines.append(f"exten => {call_code},1,NoOp(Incoming call to {call_code} from ${{CALLERID(num)}})")
            lines.append(f"exten => {call_code},n,Set(CALL_UID=${{UNIQUEID}})")
            lines.append(f"exten => {call_code},n,Set(UNUSED=${{CURL({backend_url}/api/webhooks/asterisk?event=call_start&caller=${{CALLERID(num)}}&callee={call_code}&call_id=${{CALL_UID}})}})")
            lines.append(f"exten => {call_code},n,Set(JITTERBUFFER(adaptive)=default)")
            lines.append(f"exten => {call_code},n,Dial({dial_str},60,g)")
            lines.append(f"exten => {call_code},n,Set(UNUSED=${{CURL({backend_url}/api/webhooks/asterisk?event=call_end&caller=${{CALLERID(num)}}&call_id=${{CALL_UID}})}})")
            lines.append(f"exten => {call_code},n,Hangup()")

        lines.append("")
        lines.append("; Hangup handler — финальный webhook если вызывающий сбросил сам")
        lines.append("exten => h,1,NoOp(Hangup: ${CALLERID(num)})")
        lines.append("")

        content = "\n".join(lines) + "\n"

        try:
            with open(conf_path, "w", encoding="utf-8") as f:
                f.write(content)
        except PermissionError:
            return ActionResult(
                success=False,
                message=f"Нет доступа на запись {conf_path}",
                detail="Проверьте права доступа к файлу extensions.conf",
            )
        except Exception as exc:
            return ActionResult(success=False, message="Ошибка записи extensions.conf", detail=str(exc))

        # Reload dialplan
        ok, msg = _reload_via_docker_exec_dialplan()
        if ok:
            return ActionResult(
                success=True,
                message=f"extensions.conf сгенерирован ({len(apartments)} квартир), dialplan перезагружен",
            )
        return ActionResult(
            success=False,
            message="extensions.conf записан, но dialplan reload не удался",
            detail=msg,
        )


# Module-level singleton
sip_service = SIPService()


# ─── pjsip_webrtc.conf management ────────────────────────────────────────────

_WEBRTC_BLOCK_TMPL = """\
; === webrtc: {ext} ===
[{ext}]
type=endpoint
transport=transport-wss
aors={ext}
auth={ext}
context=from-internal
disallow=all
allow=opus,ulaw,alaw
webrtc=yes
use_avpf=yes
media_encryption=dtls
dtls_verify=fingerprint
dtls_setup=actpass
ice_support=yes
media_use_received_transport=yes
rtcp_mux=yes

[{ext}]
type=auth
auth_type=userpass
username={ext}
password={password}

[{ext}]
type=aor
max_contacts=5
remove_existing=yes
; === end webrtc: {ext} ===
"""


def _write_pjsip_webrtc_from_records(records: list[tuple[str, str]]) -> None:
    """Atomically rewrite pjsip_webrtc.conf from (extension, password) pairs."""
    conf_path = settings.asterisk_pjsip_webrtc_conf
    lines = [
        "; === pjsip_webrtc.conf — generated by intercom-server ===",
        "; DO NOT EDIT MANUALLY",
        "",
    ]
    for ext, password in sorted(records):
        lines.append(_WEBRTC_BLOCK_TMPL.format(ext=ext, password=password))

    content = "\n".join(lines)
    _atomic_write(conf_path, content)


def _atomic_write(path: str, content: str) -> None:
    """Write *content* to *path* atomically (temp-file + os.replace)."""
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Debounce state for PJSIP reload — avoids 50 reloads on mass migration.
_pjsip_reload_task: Optional[asyncio.Task] = None
_PJSIP_RELOAD_DEBOUNCE = 1.5  # seconds


async def _debounced_pjsip_reload() -> None:
    global _pjsip_reload_task
    await asyncio.sleep(_PJSIP_RELOAD_DEBOUNCE)
    _pjsip_reload_task = None
    _do_pjsip_reload()


def _do_pjsip_reload() -> tuple[bool, str]:
    """Reload res_pjsip.so — try AMI first, then docker exec."""
    ok, msg = _reload_via_ami("module reload res_pjsip.so")
    if ok:
        logger.info("pjsip_reloaded", method="ami")
        return True, msg
    ok2, msg2 = _reload_via_docker_exec()
    if ok2:
        logger.info("pjsip_reloaded", method="docker_exec")
        return True, msg2
    logger.warning("pjsip_reload_failed", ami=msg, docker=msg2)
    return False, f"AMI: {msg} | docker: {msg2}"


def schedule_pjsip_reload() -> None:
    """Schedule a debounced PJSIP reload (safe to call many times in a row)."""
    global _pjsip_reload_task
    if _pjsip_reload_task and not _pjsip_reload_task.done():
        _pjsip_reload_task.cancel()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            _pjsip_reload_task = loop.create_task(_debounced_pjsip_reload())
    except RuntimeError:
        pass


async def upsert_webrtc_conf(extension: str, password: str) -> tuple[bool, str]:
    """Add/replace one endpoint in pjsip_webrtc.conf (atomic + debounced reload).

    Reads the existing file, replaces the block for *extension* (or appends it),
    writes atomically, then schedules a debounced reload.
    """
    conf_path = settings.asterisk_pjsip_webrtc_conf

    try:
        with open(conf_path, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = "; === pjsip_webrtc.conf — generated by intercom-server ===\n; DO NOT EDIT MANUALLY\n\n"
    except Exception as exc:
        return False, f"Cannot read {conf_path}: {exc}"

    start_marker = f"; === webrtc: {extension} ==="
    end_marker = f"; === end webrtc: {extension} ==="
    new_block = _WEBRTC_BLOCK_TMPL.format(ext=extension, password=password)

    if start_marker in text:
        s = text.find(start_marker)
        e = text.find(end_marker)
        if e != -1:
            text = text[:s] + new_block.rstrip() + "\n" + text[e + len(end_marker) :]
        else:
            text = text[:s] + new_block + text[s + len(start_marker) :]
    else:
        text = text.rstrip("\n") + "\n\n" + new_block

    try:
        _atomic_write(conf_path, text)
    except Exception as exc:
        return False, f"Cannot write {conf_path}: {exc}"

    schedule_pjsip_reload()
    return True, "OK"


async def regenerate_webrtc_conf_from_db() -> None:
    """Re-create pjsip_webrtc.conf from the webrtc_endpoints table (self-healing at startup)."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import WebrtcEndpoint

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(WebrtcEndpoint))
        rows = result.scalars().all()

    records = [(r.extension, r.password) for r in rows]
    if not records:
        return
    conf_path = settings.asterisk_pjsip_webrtc_conf
    try:
        _write_pjsip_webrtc_from_records(records)
        logger.info("pjsip_webrtc_conf_regenerated", endpoints=len(records), path=conf_path)
        _do_pjsip_reload()
    except Exception as exc:
        logger.error("pjsip_webrtc_conf_regen_failed", error=str(exc))


# ─── extensions_apartments.conf management ───────────────────────────────────

_DIALPLAN_BLOCK_TMPL = """\
; === apt: {call_code} ===
exten => {call_code},1,NoOp(Call to apartment {call_code})
 same => n,Dial({dial_str},30,tT)
 same => n,Hangup()
; === end apt: {call_code} ===
"""

_DIALPLAN_EMPTY_TMPL = """\
; === apt: {call_code} ===
exten => {call_code},1,NoOp(Call to apartment {call_code} — no monitors)
 same => n,Hangup()
; === end apt: {call_code} ===
"""


def write_apartments_dialplan(
    apartments: list[dict],
) -> ActionResult:
    """Write /etc/asterisk/extensions_apartments.conf from apartment dicts.

    Each dict: {"call_code": "1042", "monitors": ["ext1", "ext2"]}
    Atomic write; reloads dialplan via docker exec.
    """
    conf_path = settings.asterisk_extensions_apartments_conf

    header = (
        "; === extensions_apartments.conf — generated by intercom-server ===\n"
        "; DO NOT EDIT MANUALLY\n\n"
        "[intercom-apartments]\n"
    )
    blocks: list[str] = [header]

    for apt in sorted(apartments, key=lambda a: a["call_code"]):
        call_code = apt["call_code"]
        monitors: list[str] = apt.get("monitors", [])
        if monitors:
            dial_str = "&".join(f"PJSIP/{m}" for m in monitors)
            block = _DIALPLAN_BLOCK_TMPL.format(call_code=call_code, dial_str=dial_str)
        else:
            block = _DIALPLAN_EMPTY_TMPL.format(call_code=call_code)
        blocks.append(block)

    content = "\n".join(blocks) + "\n"

    try:
        _atomic_write(conf_path, content)
    except Exception as exc:
        return ActionResult(
            success=False, message=f"Cannot write {conf_path}", detail=str(exc)
        )

    ok, msg = _reload_via_docker_exec_dialplan()
    if ok:
        return ActionResult(
            success=True,
            message=f"extensions_apartments.conf updated ({len(apartments)} apt), dialplan reloaded",
        )
    return ActionResult(
        success=False,
        message="extensions_apartments.conf written, dialplan reload failed",
        detail=msg,
    )

