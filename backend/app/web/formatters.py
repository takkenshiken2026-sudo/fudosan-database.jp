from __future__ import annotations

from typing import Optional


def format_man_yen(value: Optional[float | int]) -> str:
    if value is None:
        return "—"
    man = float(value) / 10_000
    if man >= 10_000:
        return f"{man / 10_000:.1f}億円"
    if man >= 1:
        return f"{man:,.0f}万円"
    return f"{value:,.0f}円"


def format_yen_per_sqm(value: Optional[float | int]) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}円/㎡"


def format_count(value: Optional[int]) -> str:
    if value is None:
        return "0"
    return f"{value:,}"


def format_passengers_daily(value: Optional[int]) -> str:
    if value is None:
        return "—"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万人/日"
    return f"{value:,}人/日"


def format_percent(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def quarter_label(year: int, quarter: int) -> str:
    return f"{year}年 第{quarter}四半期"


def format_news_datetime(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%Y/%m/%d %H:%M")
    except (TypeError, ValueError):
        return str(value)[:16]
