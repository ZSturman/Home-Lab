from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")
    alembic_database_url_override: str | None = Field(default=None, validation_alias="ALEMBIC_DATABASE_URL")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "homeplatform"
    postgres_user: str = "homeplatform"
    postgres_password: str = ""
    postgres_password_file: Path | None = None
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = "control-plane"
    mqtt_password: str = ""
    mqtt_password_file: Path | None = None
    mqtt_client_id: str = "homeplatform-control-plane"
    config_directory: Path = Path("/app/config")
    home_assistant_url: str = "http://host.docker.internal:8123"
    home_assistant_token: str = ""
    home_assistant_token_file: Path | None = None
    service_name: str = "control-plane"
    platform_node_id: str = Field(
        default="pi-control-plane",
        validation_alias="HOMEPLATFORM_NODE_ID",
        pattern=r"^[a-z][a-z0-9-]{0,63}$",
    )
    platform_node_name: str = Field(default="Home Pi", validation_alias="HOMEPLATFORM_NODE_NAME")
    platform_hardware_profile: str = Field(
        default="standard",
        validation_alias="HOMEPLATFORM_HARDWARE_PROFILE",
        pattern=r"^(standard|pi-hardware)$",
    )

    @staticmethod
    def _secret(value: str, path: Path | None, name: str) -> str:
        if value:
            return value
        if path:
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise RuntimeError(f"Unable to read {name} secret from {path}") from exc
        return ""

    @property
    def postgres_password_value(self) -> str:
        return self._secret(self.postgres_password, self.postgres_password_file, "PostgreSQL password")

    @property
    def mqtt_password_value(self) -> str:
        return self._secret(self.mqtt_password, self.mqtt_password_file, "MQTT password")

    @property
    def home_assistant_token_value(self) -> str:
        return self._secret(self.home_assistant_token, self.home_assistant_token_file, "Home Assistant token")

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        password = quote(self.postgres_password_value, safe="")
        return f"postgresql+asyncpg://{self.postgres_user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def alembic_database_url(self) -> str:
        if self.alembic_database_url_override:
            return self.alembic_database_url_override
        if self.database_url_override:
            return self.database_url_override.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1).replace(
                "sqlite+aiosqlite://", "sqlite://", 1
            )
        password = quote(self.postgres_password_value, safe="")
        return f"postgresql+psycopg://{self.postgres_user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
