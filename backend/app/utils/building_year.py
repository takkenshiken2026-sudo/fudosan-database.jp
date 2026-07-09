from __future__ import annotations

import re
from typing import Optional

_RE_WESTERN = re.compile(r"(\d{4})\s*年")
_RE_HEISEI = re.compile(r"平成\s*(\d{1,2})\s*年")
_RE_SHOWA = re.compile(r"昭和\s*(\d{1,2})\s*年")
_RE_REIWA = re.compile(r"令和\s*(\d{1,2})\s*年")


def parse_building_year(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    s = str(text).strip()
    m = _RE_WESTERN.search(s)
    if m:
        year = int(m.group(1))
        return year if 1900 <= year <= 2100 else None
    m = _RE_REIWA.search(s)
    if m:
        return 2018 + int(m.group(1))
    m = _RE_HEISEI.search(s)
    if m:
        return 1988 + int(m.group(1))
    m = _RE_SHOWA.search(s)
    if m:
        return 1925 + int(m.group(1))
    return None


def building_age_bucket(age_years: int) -> str:
    if age_years <= 5:
        return "築5年以内"
    if age_years <= 10:
        return "築6〜10年"
    if age_years <= 20:
        return "築11〜20年"
    if age_years <= 30:
        return "築21〜30年"
    return "築31年以上"


AGE_BUCKET_ORDER = [
    "築5年以内",
    "築6〜10年",
    "築11〜20年",
    "築21〜30年",
    "築31年以上",
]
