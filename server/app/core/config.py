"""全局配置：全部从环境变量 / server/.env 读取，不硬编码任何密钥。"""
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "daily-greeting-api"
    APP_ENV: Literal["dev", "prod"] = "dev"
    API_PREFIX: str = "/api/v1"

    # ---- PostgreSQL 连接 ----
    # 字段名统一为 DB_*，同时保留旧的 SUPABASE_DB_* 作为兼容别名。
    # 原因：云托管控制台的环境变量若还配着旧名，改名后不会突然连不上——
    # 这种失败是静默降级成内置兜底语料（接口照样 200），极难发现。
    DB_HOST: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("DB_HOST", "SUPABASE_DB_HOST"),
    )
    DB_PORT: int = Field(
        default=5432,
        validation_alias=AliasChoices("DB_PORT", "SUPABASE_DB_PORT"),
    )
    DB_NAME: str = Field(
        default="greeting",
        validation_alias=AliasChoices("DB_NAME", "SUPABASE_DB_NAME"),
    )
    DB_USER: str = Field(
        default="greeting",
        validation_alias=AliasChoices("DB_USER", "SUPABASE_DB_USER"),
    )
    DB_PASSWORD: str = Field(
        default="",
        validation_alias=AliasChoices("DB_PASSWORD", "SUPABASE_DB_PASSWORD"),
    )
    # disable | require | require-no-verify | verify-full
    DB_SSLMODE: str = Field(
        default="require-no-verify",
        validation_alias=AliasChoices("DB_SSLMODE", "SUPABASE_DB_SSLMODE"),
    )
    # 会话时区：写进连接参数里强制生效，即使数据库服务器本身是 UTC 也按东八区解释
    # timestamptz。不设的话节气、节假日、日期判断会整体偏 8 小时，而且不报错。
    DB_TIMEZONE: str = "Asia/Shanghai"

    # ---- 天气数据源 ----
    # qweather: 和风天气（需 QWEATHER_API_KEY，功能最全）
    # uapis:    uapis.cn（完全免费，无需注册，字段较少，做了兜底估算）
    # auto:     有 Key 用和风，没 Key 用 uapis（推荐）
    WEATHER_PROVIDER: Literal["auto", "qweather", "uapis"] = "auto"
    QWEATHER_API_KEY: str = ""
    QWEATHER_API_HOST: str = "devapi.qweather.com"
    QWEATHER_GEO_HOST: str = "geoapi.qweather.com"
    UAPIS_HOST: str = "https://uapis.cn"

    # ---- 业务 ----
    DEFAULT_CITY: str = "宁波"
    WEATHER_CACHE_TTL: int = 600  # 秒

    # ---- CORS（小程序真机调试、H5 联调用）----
    CORS_ORIGINS: str = "*"

    # 小程序请求需带此 Header，留空表示不校验（仅用于挡掉裸扫）
    APP_TOKEN: str = ""

    @property
    def db_password_set(self) -> bool:
        return bool(self.DB_PASSWORD)

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus

        pwd = quote_plus(self.DB_PASSWORD)
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}"
            f"/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
