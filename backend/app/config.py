from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    reinfolib_api_key: str = ""
    database_url: str = "sqlite:///../data/reinfolib.db"
    reinfolib_base_url: str = "https://www.reinfolib.mlit.go.jp/ex-api/external"
    sync_sleep_seconds: float = 0.5
    site_url: str = ""
    site_name: str = "不動産相場ナビ"
    news_cache_ttl_seconds: int = 1800


settings = Settings()
