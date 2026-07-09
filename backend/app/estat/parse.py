from __future__ import annotations

import re
from typing import Any, Iterator, Optional

# e-Stat の VALUE セルで欠損/秘匿を表す記号
_MISSING = {"", "-", "***", "X", "x", "…", "‐", "－", "*", "NA", "N/A"}

# 表章項目・分類の次元（area/time 以外）。stat_label / cat_key の材料。
_DIM_PREFIX = "@"


def _as_list(value: Any) -> list[Any]:
    """e-Stat は要素が1件だと list ではなく dict を返すので正規化する。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def result_status(payload: dict[str, Any]) -> tuple[Optional[int], Optional[str]]:
    """RESULT.STATUS（0=正常）と ERROR_MSG を返す。"""
    root = payload.get("GET_STATS_DATA") or payload.get("GET_STATS_LIST") or {}
    result = root.get("RESULT", {})
    status = result.get("STATUS")
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        pass
    return status, result.get("ERROR_MSG")


def _statistical_data(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {}) or {}


def next_key(payload: dict[str, Any]) -> Optional[int]:
    """ページングの次開始位置（NEXT_KEY）。無ければ None。"""
    info = _statistical_data(payload).get("RESULT_INF", {})
    nk = info.get("NEXT_KEY")
    if nk is None:
        return None
    try:
        return int(nk)
    except (TypeError, ValueError):
        return None


def build_class_lookup(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    """CLASS_INF から {class_id: {code: name}} を構築する。"""
    lookup: dict[str, dict[str, str]] = {}
    class_inf = _statistical_data(payload).get("CLASS_INF", {})
    for obj in _as_list(class_inf.get("CLASS_OBJ")):
        cid = obj.get("@id")
        if not cid:
            continue
        codes: dict[str, str] = {}
        for cls in _as_list(obj.get("CLASS")):
            code = cls.get("@code")
            if code is None:
                continue
            codes[str(code)] = cls.get("@name", "")
        lookup[cid] = codes
    return lookup


def parse_year(time_code: Optional[str]) -> Optional[int]:
    """e-Stat の時間軸コード（例 '2020000000', '2023100000'）先頭4桁を年として取り出す。"""
    if not time_code:
        return None
    match = re.match(r"(\d{4})", str(time_code))
    if not match:
        return None
    year = int(match.group(1))
    if 1900 <= year <= 2100:
        return year
    return None


def parse_value(raw: Any) -> Optional[float]:
    """セル値を float に。欠損/秘匿記号やカンマ・単位付きは None もしくは数値へ。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if text in _MISSING:
        return None
    text = text.replace(",", "").replace("　", "").strip()
    if text in _MISSING:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def iter_values(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """DATA_INF.VALUE を1セルずつ、area/time/分類・値・単位・系列ラベルに正規化して返す。

    yield する dict:
      area_code, area_name, cats(dict: class_id->code), cat_key, stat_label,
      time_code, period_year, value, unit, raw
    """
    lookup = build_class_lookup(payload)
    values = _statistical_data(payload).get("DATA_INF", {}).get("VALUE")
    for cell in _as_list(values):
        area_code: Optional[str] = None
        area_name: Optional[str] = None
        time_code: Optional[str] = None
        unit: Optional[str] = None
        cats: dict[str, str] = {}
        label_parts: list[str] = []

        for key, val in cell.items():
            if not key.startswith(_DIM_PREFIX):
                continue
            dim = key[1:]  # '@area' -> 'area'
            code = str(val)
            if dim == "area":
                area_code = code
                area_name = lookup.get("area", {}).get(code)
            elif dim == "time":
                time_code = code
            elif dim == "unit":
                unit = code
            else:
                # tab / cat01 / cat02 ... = 系列を決める分類
                cats[dim] = code
                name = lookup.get(dim, {}).get(code)
                if name:
                    label_parts.append(name)

        if area_code is None:
            continue

        cat_key = ";".join(f"{k}={cats[k]}" for k in sorted(cats))
        stat_label = " / ".join(label_parts) if label_parts else None
        yield {
            "area_code": area_code,
            "area_name": area_name,
            "cats": cats,
            "cat_key": cat_key,
            "stat_label": stat_label,
            "time_code": time_code,
            "period_year": parse_year(time_code),
            "value": parse_value(cell.get("$")),
            "unit": unit,
            "raw": cell,
        }
