from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/robot_factor.db"
    public_base_url: str = "http://localhost:8000"
    webhook_path_secret: str = "development-webhook-secret"
    admin_api_key: str = "development-admin-key"
    admin_identities_raw: str = Field(default="", alias="ADMIN_IDENTITIES")

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = "development-telegram-secret"
    rubika_bot_token: str = ""

    pdf_browser_executable_path: str = ""
    pdf_headless: bool = True
    session_ttl_minutes: int = 60
    invoice_storage_dir: Path = Path("./data/invoices")

    @field_validator("public_base_url")
    @classmethod
    def strip_public_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("session_ttl_minutes")
    @classmethod
    def validate_session_ttl(cls, value: int) -> int:
        if not 5 <= value <= 24 * 60:
            raise ValueError("SESSION_TTL_MINUTES must be between 5 and 1440")
        return value

    @property
    def admin_identities(self) -> list[tuple[str, str]]:
        identities: list[tuple[str, str]] = []
        for raw_item in self.admin_identities_raw.split(","):
            item = raw_item.strip()
            if not item:
                continue
            platform, separator, external_id = item.partition(":")
            if not separator or platform not in {"telegram", "rubika"} or not external_id:
                raise ValueError(
                    "ADMIN_IDENTITIES entries must look like telegram:123 or rubika:u0..."
                )
            identities.append((platform, external_id.strip()))
        return identities

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def validate_runtime_secrets(self) -> None:
        if not self.is_production:
            return
        weak_values = {
            "development-webhook-secret",
            "development-admin-key",
            "development-telegram-secret",
            "replace-with-a-long-random-path",
            "replace-with-a-long-random-key",
            "replace-with-telegram-secret",
        }
        current = {
            self.webhook_path_secret,
            self.admin_api_key,
            self.telegram_webhook_secret,
        }
        if current & weak_values:
            raise RuntimeError("Production secrets must be replaced before startup")
        if not self.admin_identities:
            raise RuntimeError("At least one ADMIN_IDENTITIES entry is required in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
