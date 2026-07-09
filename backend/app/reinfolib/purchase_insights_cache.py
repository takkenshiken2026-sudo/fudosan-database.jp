from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app.api.schemas import PurchaseInsights

_CACHE_PATH = Path(__file__).resolve().parents[3] / "data" / "purchase_insights_cache.json"
_memory: Optional[dict[str, dict]] = None


def cache_enabled() -> bool:
    return os.environ.get("PURCHASE_INSIGHTS_USE_CACHE", "").strip() in ("1", "true", "yes")


def cache_path() -> Path:
    return _CACHE_PATH


def _load() -> dict[str, dict]:
    global _memory
    if _memory is not None:
        return _memory
    if not _CACHE_PATH.exists():
        _memory = {}
        return _memory
    try:
        _memory = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _memory = {}
    return _memory


def get_cached(municipality_code: str) -> Optional[PurchaseInsights]:
    if not cache_enabled():
        return None
    data = _load().get(municipality_code)
    if not data:
        return None
    return PurchaseInsights.model_validate(data)


def set_cached(municipality_code: str, insights: PurchaseInsights) -> None:
    store = _load()
    store[municipality_code] = insights.model_dump()
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


def save_all(entries: dict[str, PurchaseInsights]) -> None:
    global _memory
    payload = {code: ins.model_dump() for code, ins in entries.items()}
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _memory = payload


def clear_memory() -> None:
    global _memory
    _memory = None
