"""全局配置：全部从环境变量 / server/.env 读取，不硬编码任何密钥。"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "daily-greeting-api"
    APP_ENV: Literal["dev", "prod"] = "dev"
    API_PREFIX: str = "/api/v1"

    # ---- Supabase Postgres（直连 5432）----
    SUPABASE_DB_HOST: str = "db.acqnkgbovfhocoqdgtps.supabase.co"
    SUPABASE_DB_PORT: int = 5432
    SUPABASE_DB_NAME: str = "postgres"
    SUPABASE_DB_USER: str = "postgres"
    SUPABASE_DB_PASSWORD: str = ""
    SUPABASE_DB_SSLMODE: str = "require"  # require | require-no-verify | disable

    # ---- 和风天气 ----
    QWEATHER_API_KEY: str = ""
    QWEATHER_API_HOST: str = "devapi.qweather.com"
    QWEATHER_GEO_HOST: str = "geoapi.qweather.com"

    # ---- 业务 ----
    DEFAULT_CITY: str = "宁波"
    WEATHER_CACHE_TTL: int = 600  # 秒

    # ---- CORS（小程序真机调试、H5 联调用）----
    CORS_ORIGINS: str = "*"

    # 小程序请求需带此 Header，留空表示不校验（仅用于挡掉裸扫）
    APP_TOKEN: str = ""

    @property
    def db_password_set(self) -> bool:
        return bool(self.SUPABASE_DB_PASSWORD)

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus

        pwd = quote_plus(self.SUPABASE_DB_PASSWORD)
        return (
            f"postgresql+asyncpg://{self.SUPABASE_DB_USER}:{pwd}"
            f"@{self.SUPABASE_DB_HOST}:{self.SUPABASE_DB_PORT}"
            f"/{self.SUPABASE_DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
