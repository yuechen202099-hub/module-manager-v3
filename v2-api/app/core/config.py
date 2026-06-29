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
    state_backend: str = Field(default="postgres", alias="STATE_BACKEND")
    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=720, alias="JWT_EXPIRE_MINUTES")
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="change-me", alias="ADMIN_PASSWORD")
    admin_team_id: str = Field(default="default-team", alias="ADMIN_TEAM_ID")
    auth_users_path: str = Field(default="", alias="AUTH_USERS_PATH")
    demo_auth_enabled: bool | None = Field(default=None, alias="DEMO_AUTH_ENABLED")
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
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    oss_endpoint: str = Field(default="", alias="OSS_ENDPOINT")
    oss_internal_endpoint: str = Field(default="", alias="OSS_INTERNAL_ENDPOINT")
    oss_bucket: str = Field(default="", alias="OSS_BUCKET")
    oss_access_key_id: str = Field(default="", alias="OSS_ACCESS_KEY_ID")
    oss_access_key_secret: str = Field(default="", alias="OSS_ACCESS_KEY_SECRET")
    oss_region: str = Field(default="", alias="OSS_REGION")
    oss_prefix: str = Field(default="module-manager-v2", alias="OSS_PREFIX")
    oss_public_base_url: str = Field(default="", alias="OSS_PUBLIC_BASE_URL")
    oss_signed_url_expire_seconds: int = Field(default=3600, alias="OSS_SIGNED_URL_EXPIRE_SECONDS")
    oss_thumbnail_process: str = Field(
        default="image/resize,m_lfit,w_360,h_360/quality,q_75",
        alias="OSS_THUMBNAIL_PROCESS",
    )
    oss_preview_process: str = Field(
        default="image/resize,m_lfit,w_1280,h_1280/quality,q_85",
        alias="OSS_PREVIEW_PROCESS",
    )
    delivery_cache_path: str = Field(default="", alias="DELIVERY_CACHE_PATH")
    project_board_summary_cache_enabled: bool = Field(default=True, alias="PROJECT_BOARD_SUMMARY_CACHE_ENABLED")
    project_board_summary_cache_seconds: int = Field(default=300, alias="PROJECT_BOARD_SUMMARY_CACHE_SECONDS")
    project_board_summary_cache_path: str = Field(default="", alias="PROJECT_BOARD_SUMMARY_CACHE_PATH")
    wechat_miniprogram_appid: str = Field(default="", alias="WECHAT_MINIPROGRAM_APPID")
    wechat_miniprogram_secret: str = Field(default="", alias="WECHAT_MINIPROGRAM_SECRET")
    wechat_binding_store_path: str = Field(default="", alias="WECHAT_BINDING_STORE_PATH")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
