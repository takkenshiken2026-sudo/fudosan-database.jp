from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from time import time as time_time
from typing import Optional

from app.config import settings
from app.news.categories import CATEGORY_BY_ID, NEWS_CATEGORIES, NewsCategory
from app.news.fetcher import fetch_google_news

_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "news_cache.json"
_MEMORY_CACHE: Optional[tuple[float, dict]] = None


def _cache_ttl() -> int:
    return getattr(settings, "news_cache_ttl_seconds", 1800)


def _load_disk_cache() -> Optional[dict]:
    if not _CACHE_PATH.exists():
        return None
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_disk_cache(payload: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


def _serialize_item(category_id: str, raw: dict) -> dict:
    pub = raw.get("published_at")
    if isinstance(pub, datetime):
        pub_str = pub.isoformat()
    else:
        pub_str = pub
    return {
        "title": raw["title"],
        "link": raw["link"],
        "source": raw.get("source") or "",
        "published_at": pub_str,
        "category_id": category_id,
        "category_label": CATEGORY_BY_ID[category_id].label,
        "category_color": CATEGORY_BY_ID[category_id].color,
    }


def _fetch_all_categories(per_category: int = 10) -> dict:
    seen_links: set[str] = set()
    categories: list[dict] = []
    all_items: list[dict] = []

    for cat in NEWS_CATEGORIES:
        cat_items: list[dict] = []
        try:
            raw_items = fetch_google_news(cat.query, limit=per_category + 5)
        except Exception:
            raw_items = []
        for raw in raw_items:
            link = raw["link"]
            if link in seen_links:
                continue
            seen_links.add(link)
            item = _serialize_item(cat.id, raw)
            cat_items.append(item)
            all_items.append(item)
            if len(cat_items) >= per_category:
                break
        categories.append(
            {
                "id": cat.id,
                "label": cat.label,
                "description": cat.description,
                "color": cat.color,
                "items": cat_items,
            }
        )

    all_items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return {
        "fetched_at": datetime.utcnow().isoformat(),
        "categories": categories,
        "latest": all_items[:15],
    }


def get_news_feed(*, force_refresh: bool = False, per_category: int = 10) -> dict:
    global _MEMORY_CACHE
    now = time_time()
    ttl = _cache_ttl()

    if not force_refresh and _MEMORY_CACHE and now - _MEMORY_CACHE[0] < ttl:
        return _MEMORY_CACHE[1]

    if not force_refresh:
        disk = _load_disk_cache()
        if disk and disk.get("fetched_at"):
            try:
                fetched = datetime.fromisoformat(disk["fetched_at"])
                if (datetime.utcnow() - fetched).total_seconds() < ttl:
                    _MEMORY_CACHE = (now, disk)
                    return disk
            except ValueError:
                pass

    try:
        payload = _fetch_all_categories(per_category=per_category)
        _save_disk_cache(payload)
        _MEMORY_CACHE = (now, payload)
        return payload
    except Exception:
        disk = _load_disk_cache()
        if disk:
            return disk
        return {
            "fetched_at": None,
            "categories": [
                {
                    "id": c.id,
                    "label": c.label,
                    "description": c.description,
                    "color": c.color,
                    "items": [],
                }
                for c in NEWS_CATEGORIES
            ],
            "latest": [],
            "error": "ニュースの取得に失敗しました。しばらくしてから再度お試しください。",
        }


def get_category(category_id: str) -> Optional[NewsCategory]:
    return CATEGORY_BY_ID.get(category_id)
