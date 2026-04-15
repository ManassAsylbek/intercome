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

import re
import socket
import subprocess
import time

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import ActionResult

logger = get_logger(__name__)

# ─── Шаблон блока ─────────────────────────────────────────────────────────────

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

[auth{acct}]
type=auth
auth_type=userpass
username={acct}
password={password}

[{acct}]
type=aor
max_contacts=2
remove_existing=yes
; === end managed {acct} ===
"""

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

    ok, msg = _reload_local(reload_cmd)
    if ok:
        return ActionResult(
            success=True,
            message=f"pjsip.conf обновлён, Asterisk перезагружен (аккаунт {acct})",
        )
    return ActionResult(
        success=False,
        message="pjsip.conf обновлён, но перезагрузка Asterisk не удалась",
        detail=msg,
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
    return ActionResult(
        success=False,
        message="pjsip.conf обновлён, но перезагрузка через AMI не удалась",
        detail=msg,
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
            return _apply_via_ssh(acct, password)
        if settings.asterisk_mode == "ami":
            return _apply_local_ami(acct, password)
        return _apply_local(acct, password)

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
        rules_by_code: dict[str, list[str]],
        backend_url: str = "http://127.0.0.1:8000",
    ) -> ActionResult:
        """
        Генерирует extensions.conf из словаря:
            { "1001": ["1099", "1001", "1003"], "1002": ["1099", "1002"] }
        Каждый call_code становится extension'ом, все target_sip_accounts
        набираются одновременно через Dial(PJSIP/a&PJSIP/b&...).

        Браузер (1099) добавляется автоматически если его нет в списке.
        """
        conf_path = settings.asterisk_extensions_conf
        lines: list[str] = []

        lines.append("; ─── Intercom dialplan — generated by intercom-server ─────────────────────────")
        lines.append("; DO NOT EDIT MANUALLY — изменения перезапишутся автоматически.")
        lines.append("; Управляйте правилами через веб-интерфейс → Routing Rules.")
        lines.append("")
        lines.append("[general]")
        lines.append("static=yes")
        lines.append("writeprotect=no")
        lines.append("")
        lines.append("[intercom]")

        for call_code, accounts in sorted(rules_by_code.items()):
            # Браузер всегда в списке
            dial_accounts = list(dict.fromkeys(["1099"] + accounts))  # уникальные, браузер первый
            dial_str = "&".join(f"PJSIP/{a}" for a in dial_accounts)

            lines.append(f"")
            lines.append(f"; === call_code {call_code}: ring {', '.join(dial_accounts)} ===")
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

        # Reload dialplan via AMI or local
        if settings.asterisk_mode == "ami":
            ok, msg = _reload_via_ami()
        else:
            ok, msg = _reload_local("asterisk -rx 'dialplan reload'")

        if ok:
            return ActionResult(
                success=True,
                message=f"extensions.conf сгенерирован ({len(rules_by_code)} extension(s)), dialplan перезагружен",
            )
        return ActionResult(
            success=False,
            message="extensions.conf записан, но dialplan reload не удался — перезапустите Asterisk вручную",
            detail=msg,
        )


# Module-level singleton
sip_service = SIPService()
