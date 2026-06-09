from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="module-manager-v2", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    app_secret: str = Field(default="change-me", alias="APP_SECRET")
    database_url: str = Field(
        default="postgresql+psycopg://module_manager:module_manager_password@localhost:5432/module_manager_v2",
        alias="DATABASE_URL",
    )
    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=720, alias="JWT_EXPIRE_MINUTES")
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="change-me", alias="ADMIN_PASSWORD")
    ezcodes_access_token: str = Field(default="", alias="EZCODES_ACCESS_TOKEN")
    ezcodes_team_id: str = Field(default="", alias="EZCODES_TEAM_ID")
    ezcodes_env_id: str = Field(default="cloud1-8g4k4khc04701207", alias="EZCODES_ENV_ID")
    ezcodes_endpoint: str = Field(
        default="https://cloud1-8g4k4khc04701207.ap-shanghai.tcb-api.tencentcloudapi.com/web",
        alias="EZCODES_ENDPOINT",
    )
    ezcodes_sync_enabled: bool = Field(default=False, alias="EZCODES_SYNC_ENABLED")
    ezcodes_sync_interval_seconds: int = Field(default=1800, alias="EZCODES_SYNC_INTERVAL_SECONDS")
    ezcodes_sync_max_files: int = Field(default=50, alias="EZCODES_SYNC_MAX_FILES")
    ezcodes_sync_max_records_per_file: int = Field(default=500, alias="EZCODES_SYNC_MAX_RECORDS_PER_FILE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
