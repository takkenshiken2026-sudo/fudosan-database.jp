from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from time import time as time_time
from typing import Optional

from app.config import settings
from app.news.categories import CATEGORY_BY_ID
from app.news.fetcher import fetch_google_news

_REGIONAL_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "regional_news_cache.json"
_REGIONAL_MEMORY: dict[str, tuple[float, dict]] = {}

# タイトルからカテゴリを推定
_TITLE_RULES: list[tuple[str, list[str]]] = [
    ("land_price", ["地価", "公示", "調査", "坪単価"]),
    ("housing", ["マンション", "住宅", "分譲", "中古", "新築", "賃貸"]),
    ("policy", ["税制", "規制", "政策", "融資", "ローン", "法改正"]),
    ("development", ["再開発", "開発", "駅前", "都市計画", "区画"]),
    ("market", ["取引", "相場", "価格", "売買", "成約"]),
]


def _cache_ttl() -> int:
    return getattr(settings, "news_cache_ttl_seconds", 1800)


def _cache_key(prefecture_slug: str, municipality_slug: Optional[str] = None) -> str:
    if municipality_slug:
        return f"{prefecture_slug}/{municipality_slug}"
    return prefecture_slug


def _load_regional_disk() -> dict:
    if not _REGIONAL_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_REGIONAL_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_regional_disk(data: dict) -> None:
    _REGIONAL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGIONAL_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")


def _classify_title(title: str) -> str:
    for cat_id, keywords in _TITLE_RULES:
        if any(kw in title for kw in keywords):
            return cat_id
    return "market"


def _build_query(
    prefecture_name: str,
    municipality_name: Optional[str] = None,
) -> str:
    if municipality_name:
        area = f"{prefecture_name}{municipality_name}"
        return f'"{area}" (不動産 OR 地価 OR マンション)'
    return f'"{prefecture_name}" (不動産 OR 地価 OR マンション)'


def _serialize_regional(raw: dict, area_label: str) -> dict:
    pub = raw.get("published_at")
    if isinstance(pub, datetime):
        pub_str = pub.isoformat()
    else:
        pub_str = pub
    cat_id = _classify_title(raw["title"])
    cat = CATEGORY_BY_ID[cat_id]
    return {
        "title": raw["title"],
        "link": raw["link"],
        "source": raw.get("source") or "",
        "published_at": pub_str,
        "category_id": cat_id,
        "category_label": cat.label,
        "category_color": cat.color,
        "area_label": area_label,
    }


def _fetch_regional(
    prefecture_name: str,
    prefecture_slug: str,
    municipality_name: Optional[str] = None,
    municipality_slug: Optional[str] = None,
    limit: int = 10,
) -> dict:
    query = _build_query(prefecture_name, municipality_name)
    if municipality_name:
        area_label = f"{prefecture_name}{municipality_name}"
    else:
        area_label = prefecture_name

    try:
        raw_items = fetch_google_news(query, limit=limit + 5)
    except Exception:
        raw_items = []

    items = [
        _serialize_regional(raw, area_label)
        for raw in raw_items[:limit]
    ]

    by_category: dict[str, list[dict]] = {}
    for item in items:
        cid = item["category_id"]
        by_category.setdefault(cid, []).append(item)

    categories = [
        {
            "id": cid,
            "label": CATEGORY_BY_ID[cid].label,
            "color": CATEGORY_BY_ID[cid].color,
            "items": cat_items,
        }
        for cid, cat_items in by_category.items()
    ]
    categories.sort(key=lambda c: len(c["items"]), reverse=True)

    return {
        "fetched_at": datetime.utcnow().isoformat(),
        "query": query,
        "area_label": area_label,
        "prefecture_slug": prefecture_slug,
        "municipality_slug": municipality_slug,
        "items": items,
        "categories": categories,
    }


def get_regional_news(
    prefecture_name: str,
    prefecture_slug: str,
    municipality_name: Optional[str] = None,
    municipality_slug: Optional[str] = None,
    *,
    force_refresh: bool = False,
    limit: int = 10,
) -> dict:
    key = _cache_key(prefecture_slug, municipality_slug)
    now = time_time()
    ttl = _cache_ttl()

    if not force_refresh and key in _REGIONAL_MEMORY:
        ts, payload = _REGIONAL_MEMORY[key]
        if now - ts < ttl:
            return payload

    if not force_refresh:
        disk = _load_regional_disk()
        entry = disk.get(key)
        if entry and entry.get("fetched_at"):
            try:
                fetched = datetime.fromisoformat(entry["fetched_at"])
                if (datetime.utcnow() - fetched).total_seconds() < ttl:
                    _REGIONAL_MEMORY[key] = (now, entry)
                    return entry
            except ValueError:
                pass

    try:
        payload = _fetch_regional(
            prefecture_name,
            prefecture_slug,
            municipality_name,
            municipality_slug,
            limit=limit,
        )
        disk = _load_regional_disk()
        disk[key] = payload
        _save_regional_disk(disk)
        _REGIONAL_MEMORY[key] = (now, payload)
        return payload
    except Exception:
        disk = _load_regional_disk()
        if key in disk:
            return disk[key]
        area = f"{prefecture_name}{municipality_name or ''}"
        return {
            "fetched_at": None,
            "query": _build_query(prefecture_name, municipality_name),
            "area_label": area,
            "prefecture_slug": prefecture_slug,
            "municipality_slug": municipality_slug,
            "items": [],
            "categories": [],
            "error": f"{area}のニュースを取得できませんでした。",
        }
