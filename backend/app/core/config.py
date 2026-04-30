from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Абсолютный путь к .env — работает независимо от CWD при запуске
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: str = "development"
    app_secret_key: str = "change-this-secret-key-in-production-min-32-chars"
    app_access_token_expire_minutes: int = 480
    app_algorithm: str = "HS256"
    app_cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Database
    database_url: str = f"sqlite+aiosqlite:///{_ENV_FILE.parent}/data/intercom.db"

    # Admin seed
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_email: str = "admin@local.host"

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    server_ip: str = "192.168.31.132"

    # Asterisk integration
    asterisk_mode: str = "local"            # "local" | "ssh" | "ami"
    asterisk_pjsip_conf: str = "/etc/asterisk/pjsip.conf"
    asterisk_extensions_conf: str = "/etc/asterisk/extensions.conf"
    # Separately managed files — FastAPI writes only these two; never touches the main confs.
    asterisk_pjsip_webrtc_conf: str = "/etc/asterisk/pjsip_webrtc.conf"
    asterisk_extensions_apartments_conf: str = "/etc/asterisk/extensions_apartments.conf"
    asterisk_reload_cmd: str = "sudo systemctl restart asterisk"
    asterisk_ssh_host: str = ""
    asterisk_ssh_port: int = 22
    asterisk_ssh_user: str = ""
    asterisk_ssh_key_file: str = ""
    # AMI (Asterisk Manager Interface)
    asterisk_ami_host: str = "127.0.0.1"
    asterisk_ami_port: int = 5038
    asterisk_ami_user: str = "intercom"
    asterisk_ami_secret: str = "intercom-ami-secret"

    # Cloud SIP trunk (relay calls to cloud → mobile app)
    # Set to the PJSIP endpoint name configured in pjsip.conf for the cloud trunk
    # e.g. "cloud-trunk"  →  Dial(...&PJSIP/{call_code}@cloud-trunk)
    cloud_sip_trunk_endpoint: str = ""

    # Cloud WebSocket bridge
    cloud_ws_url: str = ""          # e.g. wss://cloud.example.com/ws/bridge
    cloud_bridge_token: str = ""    # bearer token issued by cloud to this server

    # WebRTC: STUN URL returned to mobile clients in provision_webrtc_endpoint ack
    intercom_stun_url: str = ""     # e.g. stun:192.168.50.132:3478

    # Public base URL of this server (used to build go2rtc video links sent to
    # the cloud in call_started). Defaults to https://{server_ip} if empty.
    intercom_public_base_url: str = ""  # e.g. https://intercom.example.com

    # Public host/IP of this bridge as reachable by mobile clients.
    # Used to build SIP WSS URL and TURN URLs in media_config.
    public_bridge_host: str = ""    # e.g. bridge.example.com or 192.168.31.51

    # Path where backend writes go2rtc.yaml (shared volume with go2rtc container).
    # go2rtc watches this file and auto-reloads when it changes.
    go2rtc_config_path: str = "/go2rtc_config/go2rtc.yaml"

    # Internal go2rtc REST API URL (kept for health checks).
    go2rtc_api_url: str = ""   # e.g. http://192.168.50.132:1984

    # WHEP basic-auth (go2rtc) — sent to mobile in media_config.
    go2rtc_user: str = ""
    go2rtc_pass: str = ""

    # TURN (coturn) — sent to mobile in media_config.ice_servers.
    coturn_public_host: str = ""
    coturn_port: int = 3478
    # Short-lived HMAC-SHA1 credentials (coturn use-auth-secret).
    # Set COTURN_SECRET to the same value as `static-auth-secret` in turnserver.conf.
    # When set, COTURN_USER / COTURN_CRED are ignored.
    coturn_secret: str = ""
    # Fallback static credentials (used only when coturn_secret is not set).
    coturn_user: str = ""
    coturn_cred: str = ""

    # SIP-over-WSS endpoint exposed by the bridge (Asterisk via nginx).
    # Empty → derived from public_bridge_host as wss://{host}/asterisk/ws.
    sip_ws_url: str = ""
    sip_domain: str = ""    # SIP realm/domain used by the SIP.js client

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",")]

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url


settings = Settings()
