from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    reinfolib_api_key: str = ""
    database_url: str = "sqlite:///../data/reinfolib.db"
    reinfolib_base_url: str = "https://www.reinfolib.mlit.go.jp/ex-api/external"
    sync_sleep_seconds: float = 0.5
    # e-Stat 政府統計API（appId・無料登録制）
    estat_app_id: str = ""
    estat_base_url: str = "https://api.e-stat.go.jp/rest/3.0/app/json"
    site_url: str = ""
    site_name: str = "不動産相場ナビ"
    news_cache_ttl_seconds: int = 1800
    # Google Search Console（HTMLタグ方式の content 値）
    google_site_verification: str = ""
    # HTMLファイル方式（例: google1234abcd.html）
    google_site_verification_file: str = ""


settings = Settings()
