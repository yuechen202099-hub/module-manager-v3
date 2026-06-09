from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "module-manager-v2"
    app_env: str = "local"
    database_url: str = "sqlite:///./module_manager_v2.db"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 720
    max_upload_mb: int = 20
    admin_username: str = "admin"
    admin_password: str = "change-me"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

