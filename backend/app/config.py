from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    reinfolib_api_key: str = ""
    estat_app_id: SecretStr = SecretStr("")
    estat_database_url: str = "sqlite:///../data/estat.db"
    database_url: str = "sqlite:///../data/reinfolib.db"
    reinfolib_base_url: str = "https://www.reinfolib.mlit.go.jp/ex-api/external"
    sync_sleep_seconds: float = 0.5
    site_url: str = ""
    site_name: str = "不動産相場ナビ"
    news_cache_ttl_seconds: int = 1800
    # Google Search Console（HTMLタグ方式の content 値）
    google_site_verification: str = ""
    # HTMLファイル方式（例: google1234abcd.html）
    google_site_verification_file: str = ""


settings = Settings()


def require_estat_app_id() -> str:
    """e-Stat API 用 appId。未設定時は例外（値はログに出さない）。"""
    value = settings.estat_app_id.get_secret_value().strip()
    if not value:
        raise RuntimeError("ESTAT_APP_ID を .env に設定してください")
    return value
