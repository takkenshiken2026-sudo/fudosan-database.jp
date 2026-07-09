from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app.config import settings


class EstatClient:
    """e-Stat 政府統計API（getStatsList / getStatsData）の薄いクライアント。

    reinfolib の ReinfolibClient と同じスロットリング構造を踏襲。認証はヘッダではなく
    クエリパラメータ appId を全リクエストに付与する。
    """

    def __init__(
        self,
        app_id: str,
        *,
        base_url: str = settings.estat_base_url,
        sleep_seconds: float = settings.sync_sleep_seconds,
    ) -> None:
        self.app_id = app_id
        self.base_url = base_url.rstrip("/")
        self.sleep_seconds = sleep_seconds
        self._last_request_at = 0.0
        self._client = httpx.Client(timeout=120.0)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.sleep_seconds:
            time.sleep(self.sleep_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _get_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        self._throttle()
        url = f"{self.base_url}/{endpoint}"
        merged = {"appId": self.app_id, **params}
        response = self._client.get(url, params=merged)
        response.raise_for_status()
        return response.json()

    def get_stats_list(
        self,
        *,
        search_word: Optional[str] = None,
        stats_code: Optional[str] = None,
        limit: int = 20,
        **extra: Any,
    ) -> dict[str, Any]:
        """統計表を検索。目的の statsDataId を探すために使う。"""
        params: dict[str, Any] = {"limit": limit}
        if search_word:
            params["searchWord"] = search_word
        if stats_code:
            params["statsCode"] = stats_code
        params.update(extra)
        return self._get_json("getStatsList", params)

    def get_stats_data(
        self,
        *,
        stats_data_id: str,
        start_position: Optional[int] = None,
        limit: Optional[int] = None,
        **filters: Any,
    ) -> dict[str, Any]:
        """統計表の実データを1ページ取得（cdArea/cdCat01/cdTime 等の絞り込みは filters で）。"""
        params: dict[str, Any] = {"statsDataId": stats_data_id}
        if start_position is not None:
            params["startPosition"] = start_position
        if limit is not None:
            params["limit"] = limit
        # None のフィルタは送らない
        params.update({k: v for k, v in filters.items() if v is not None})
        return self._get_json("getStatsData", params)
