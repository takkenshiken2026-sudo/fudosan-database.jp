from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Optional

from app.reinfolib.client import parse_int
from app.reinfolib.prefecture_bboxes import PREFECTURE_BBOXES

PASSENGER_YEAR_START = 2011
PASSENGER_YEAR_END = 2023


def passenger_field_for_year(year: int) -> str:
    return f"S12_{(year - PASSENGER_YEAR_START) * 4 + 9:03d}"


def availability_field_for_year(year: int) -> str:
    return f"S12_{(year - PASSENGER_YEAR_START) * 4 + 7:03d}"


def parse_passengers_by_year(props: dict[str, Any]) -> dict[int, int]:
    result: dict[int, int] = {}
    for year in range(PASSENGER_YEAR_START, PASSENGER_YEAR_END + 1):
        avail = props.get(availability_field_for_year(year))
        if avail not in (None, "", "0"):
            count = parse_int(props.get(passenger_field_for_year(year)))
            if count is not None:
                result[year] = count
    return result


def latest_passenger_year(counts: dict[int, int]) -> tuple[Optional[int], Optional[int]]:
    if not counts:
        return None, None
    year = max(counts)
    return year, counts[year]


def geometry_centroid(geometry: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Point" and len(coords) >= 2:
        return parse_float(coords[1]), parse_float(coords[0])
    if gtype == "LineString" and coords:
        lon = sum(c[0] for c in coords) / len(coords)
        lat = sum(c[1] for c in coords) / len(coords)
        return lat, lon
    if gtype == "MultiLineString" and coords and coords[0]:
        line = coords[0]
        lon = sum(c[0] for c in line) / len(line)
        lat = sum(c[1] for c in line) / len(line)
        return lat, lon
    return None, None


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def prefecture_code_for_point(
    latitude: Optional[float], longitude: Optional[float]
) -> Optional[str]:
    if latitude is None or longitude is None:
        return None
    for code, bbox in PREFECTURE_BBOXES.items():
        lon_min, lat_min, lon_max, lat_max = bbox
        if lon_min <= longitude <= lon_max and lat_min <= latitude <= lat_max:
            return code
    return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def passengers_json_dumps(counts: dict[int, int]) -> str:
    return json.dumps({str(k): v for k, v in counts.items()}, ensure_ascii=False)


def passengers_json_loads(raw: Optional[str]) -> dict[int, int]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {int(k): int(v) for k, v in data.items()}


def normalize_station_name(name: str) -> str:
    return name.replace("駅", "").strip()
