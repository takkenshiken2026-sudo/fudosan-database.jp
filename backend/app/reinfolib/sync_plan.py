from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


TRANSACTION_START_YEAR = 2005
CONTRACT_START_YEAR = 2021


@dataclass(frozen=True)
class QuarterWindow:
    year: int
    quarter: int


def iter_quarters(from_year: int, to_year: int) -> Iterable[QuarterWindow]:
    for year in range(from_year, to_year + 1):
        start_quarter = 1
        if year == 2005:
            start_quarter = 3
        for quarter in range(start_quarter, 5):
            yield QuarterWindow(year=year, quarter=quarter)


def estimate_transaction_requests(
    municipality_count: int,
    from_year: int,
    to_year: int,
    *,
    sleep_seconds: float = 1.5,
) -> dict[str, float | int]:
    quarter_count = sum(1 for _ in iter_quarters(from_year, to_year))
    requests = municipality_count * quarter_count
    return {
        "municipality_count": municipality_count,
        "from_year": from_year,
        "to_year": to_year,
        "quarter_count_per_municipality": quarter_count,
        "total_requests": requests,
        "estimated_seconds": int(requests * sleep_seconds),
        "estimated_minutes": round(requests * sleep_seconds / 60, 1),
    }


def iter_transaction_jobs(
    municipality_codes: list[str],
    from_year: int,
    to_year: int,
    *,
    skip_done: bool = False,
    done_keys: Optional[set[tuple[str, int, int]]] = None,
) -> Iterable[tuple[str, int, int]]:
    done = done_keys or set()
    for city_code in municipality_codes:
        for window in iter_quarters(from_year, to_year):
            key = (city_code, window.year, window.quarter)
            if skip_done and key in done:
                continue
            yield city_code, window.year, window.quarter
