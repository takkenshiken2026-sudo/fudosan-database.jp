from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app.config import require_estat_app_id, settings

ESTAT_API_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"


def estat_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("$") or value.get("@name") or "").strip()
    return str(value).strip()


def estat_code(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("@code") or "").strip()
    return estat_text(value)


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class EstatClient:
    def __init__(
        self,
        *,
        app_id: Optional[str] = None,
        sleep_seconds: float = settings.sync_sleep_seconds,
    ) -> None:
        self.app_id = app_id or require_estat_app_id()
        self.sleep_seconds = sleep_seconds
        self._last_request_at = 0.0
        self._client = httpx.Client(timeout=120.0)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.sleep_seconds:
            time.sleep(self.sleep_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        self._throttle()
        query = {"appId": self.app_id, "lang": "J", **params}
        response = self._client.get(f"{ESTAT_API_BASE}/{endpoint}", params=query)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _api_status(payload: dict[str, Any], root_key: str) -> tuple[int, str]:
        result = payload.get(root_key, {}).get("RESULT", {})
        status = int(result.get("STATUS", -1))
        message = estat_text(result.get("ERROR_MSG"))
        return status, message

    def get_stats_list(self, **params: Any) -> dict[str, Any]:
        payload = self._get("getStatsList", params)
        status, message = self._api_status(payload, "GET_STATS_LIST")
        if status not in (0, 1):
            raise RuntimeError(f"getStatsList failed ({status}): {message}")
        return payload["GET_STATS_LIST"]

    def get_meta_info(self, stats_data_id: str) -> dict[str, Any]:
        payload = self._get(
            "getMetaInfo",
            {"statsDataId": stats_data_id, "explanationGetFlg": "N"},
        )
        status, message = self._api_status(payload, "GET_META_INFO")
        if status != 0:
            raise RuntimeError(f"getMetaInfo failed ({status}): {message}")
        return payload["GET_META_INFO"]

    def get_stats_data(self, **params: Any) -> dict[str, Any]:
        payload = self._get(
            "getStatsData",
            {
                "metaGetFlg": "N",
                "explanationGetFlg": "N",
                "annotationGetFlg": "Y",
                **params,
            },
        )
        status, message = self._api_status(payload, "GET_STATS_DATA")
        if status not in (0, 1):
            raise RuntimeError(f"getStatsData failed ({status}): {message}")
        return payload["GET_STATS_DATA"]

    def iter_stats_data(self, **params: Any):
        start_position = int(params.pop("startPosition", 1) or 1)
        limit = int(params.get("limit", 100000) or 100000)
        while True:
            page = self.get_stats_data(startPosition=start_position, **params)
            statistical = page.get("STATISTICAL_DATA", {})
            values = ensure_list(statistical.get("DATA_INF", {}).get("VALUE"))
            result_inf = statistical.get("RESULT_INF") or {}
            yield values, result_inf
            next_key = result_inf.get("NEXT_KEY")
            if not next_key:
                break
            start_position = int(next_key)
            if not values:
                break
