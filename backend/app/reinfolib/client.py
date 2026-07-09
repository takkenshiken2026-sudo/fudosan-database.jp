from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Optional

import httpx

from app.config import settings


class ReinfolibClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = settings.reinfolib_base_url,
        sleep_seconds: float = settings.sync_sleep_seconds,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.sleep_seconds = sleep_seconds
        self._last_request_at = 0.0
        self._client = httpx.Client(timeout=60.0, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        return {"Ocp-Apim-Subscription-Key": self.api_key}

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.sleep_seconds:
            time.sleep(self.sleep_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _get_json(self, endpoint: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        self._throttle()
        url = f"{self.base_url}/{endpoint}"
        response = self._client.get(url, params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def fetch_municipalities(self, prefecture_code: str) -> list[dict[str, Any]]:
        payload = self._get_json("XIT002", {"area": prefecture_code, "language": "ja"})
        if not payload:
            return []
        data = payload.get("data", payload)
        if isinstance(data, dict):
            return [data]
        return list(data)

    def fetch_transactions(
        self,
        *,
        city_code: str,
        year: int,
        quarter: int,
        price_classification: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "year": str(year),
            "quarter": str(quarter),
            "city": city_code,
            "language": "ja",
        }
        if price_classification:
            params["priceClassification"] = price_classification
        payload = self._get_json("XIT001", params)
        if not payload:
            return []
        data = payload.get("data", payload)
        if isinstance(data, dict):
            return [data]
        return list(data)

    def fetch_land_prices(
        self,
        *,
        zoom: int,
        x: int,
        y: int,
        year: int,
        price_classification: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "response_format": "geojson",
            "z": str(zoom),
            "x": str(x),
            "y": str(y),
            "year": str(year),
        }
        if price_classification is not None:
            params["priceClassification"] = price_classification
        payload = self._get_json("XPT002", params)
        if not payload:
            return []
        return list(payload.get("features", []))

    def fetch_station_passengers(
        self,
        *,
        zoom: int,
        x: int,
        y: int,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "response_format": "geojson",
            "z": str(zoom),
            "x": str(x),
            "y": str(y),
        }
        payload = self._get_json("XKT015", params)
        if not payload:
            return []
        return list(payload.get("features", []))


def parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def classify_price_category(price_category: str) -> str:
    if "成約" in price_category:
        return "02"
    return "01"


def compute_record_hash(
    record: dict[str, Any],
    *,
    trade_year: int,
    trade_quarter: int,
) -> str:
    key_fields = {
        "trade_year": trade_year,
        "trade_quarter": trade_quarter,
        "PriceCategory": record.get("PriceCategory", ""),
        "Type": record.get("Type", ""),
        "MunicipalityCode": record.get("MunicipalityCode", ""),
        "DistrictCode": record.get("DistrictCode", ""),
        "DistrictName": record.get("DistrictName", ""),
        "TradePrice": record.get("TradePrice", ""),
        "Area": record.get("Area", ""),
        "TotalFloorArea": record.get("TotalFloorArea", ""),
        "FloorPlan": record.get("FloorPlan", ""),
        "BuildingYear": record.get("BuildingYear", ""),
        "Period": record.get("Period", ""),
        "Remarks": record.get("Remarks", ""),
    }
    payload = json.dumps(key_fields, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_PERIOD_RE = re.compile(r"(\d{4})年第(\d)四半期")


def parse_period_label(period_label: str) -> tuple[Optional[int], Optional[int]]:
    match = _PERIOD_RE.search(period_label or "")
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))
