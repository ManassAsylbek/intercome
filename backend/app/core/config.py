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
