from __future__ import annotations

import math
from typing import Iterable

from app.reinfolib.prefecture_bboxes import PREFECTURE_BBOXES
from app.reinfolib.prefectures import PREFECTURES


def lon_lat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n)
    return x, y


def iter_tiles_for_bbox(
    bbox: tuple[float, float, float, float],
    zoom: int,
) -> Iterable[tuple[int, int, int]]:
    lon_min, lat_min, lon_max, lat_max = bbox
    x_min, y_max = lon_lat_to_tile(lon_min, lat_min, zoom)
    x_max, y_min = lon_lat_to_tile(lon_max, lat_max, zoom)
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            yield zoom, x, y


def tile_key(zoom: int, x: int, y: int) -> str:
    return f"{zoom}/{x}/{y}"


def iter_prefecture_tiles(
    prefecture_code: str | None = None,
    *,
    zoom: int = 13,
) -> Iterable[tuple[int, int, int]]:
    seen: set[tuple[int, int, int]] = set()
    codes = [prefecture_code] if prefecture_code else [p["code"] for p in PREFECTURES]
    for code in codes:
        bbox = PREFECTURE_BBOXES.get(code)
        if not bbox:
            continue
        for tile in iter_tiles_for_bbox(bbox, zoom):
            if tile in seen:
                continue
            seen.add(tile)
            yield tile


def count_land_price_requests(
    from_year: int,
    to_year: int,
    prefecture_code: str | None = None,
    *,
    zoom: int = 13,
    skip_empty_tiles: bool = True,
    reference_year: int | None = None,
    data_tile_ratio: float = 0.05,
) -> dict[str, int | float]:
    tiles = list(iter_prefecture_tiles(prefecture_code, zoom=zoom))
    tile_count = len(tiles)
    years = to_year - from_year + 1
    ref_year = reference_year if reference_year is not None else min(to_year, 2024)
    if ref_year < from_year or ref_year > to_year:
        ref_year = to_year

    if skip_empty_tiles:
        data_tiles = max(1, int(tile_count * data_tile_ratio))
        discovery_requests = tile_count
        history_years = max(0, years - 1)
        history_requests = data_tiles * history_years
        requests = discovery_requests + history_requests
    else:
        requests = tile_count * years

    return {
        "tile_count": tile_count,
        "from_year": from_year,
        "to_year": to_year,
        "reference_year": ref_year,
        "skip_empty_tiles": skip_empty_tiles,
        "estimated_data_tiles": max(1, int(tile_count * data_tile_ratio)) if skip_empty_tiles else tile_count,
        "total_requests": requests,
        "estimated_seconds": int(requests * 1.5),
        "estimated_hours": round(requests * 1.5 / 3600, 1),
    }
