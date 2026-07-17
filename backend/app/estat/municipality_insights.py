from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.estat.db import EstatSessionLocal

# 同期済みの統計表（targets.py と整合）
CENSUS_POPULATION_TABLES = ("0004050397", "0003433219")
SOCIAL_POPULATION_TABLE = "0000020301"
SOCIAL_HOUSING_TABLE = "0000020308"
HOUSING_COUNT_TABLE = "0004021610"
HOUSING_OWNERSHIP_TABLE = "0004021628"
HOUSING_HOUSEHOLD_TABLE = "0004021644"
HOUSING_VACANT_TABLE = "0004021631"
HOUSING_RENT_TABLE = "0004021480"
HOUSING_BUILDING_AGE_TABLE = "0004021676"

SOCIAL_METRIC_CODES = {
    "elderly_pct": "#A03506",
    "population_growth_pct": "#A05101",
    "population_density": "#A01202",
    "single_elderly_household_pct": "#A06304",
}

HOUSING_AGE_LABELS = {
    "01": "1970年以前",
    "02": "1971〜1980年",
    "04": "1981〜1990年",
    "05": "1991〜2000年",
    "06": "2001〜2010年",
    "07": "2011〜2020年",
    "08": "2021年以降",
}


@dataclass(frozen=True)
class _ValueRow:
    value: Optional[float]
    unit: str
    time_code: str


def _estat_db_available() -> bool:
    url = settings.estat_database_url
    if not url.startswith("sqlite:///"):
        return True
    path = Path(url.replace("sqlite:///", "", 1))
    return path.exists()


def _parse_survey_year(time_code: str) -> Optional[int]:
    if not time_code or len(time_code) < 4:
        return None
    year = int(time_code[:4])
    return year if 1900 <= year <= 2100 else None


def _fetch_latest_value(
    db: Session,
    *,
    area_code: str,
    stats_data_id: str,
    cat01: str,
    cat02: str = "",
    cat03: str = "",
    cat04: str = "",
) -> Optional[_ValueRow]:
    row = db.execute(
        text(
            """
            SELECT value, unit, time_code
            FROM estat_stat_values
            WHERE area_code = :area_code
              AND stats_data_id = :stats_data_id
              AND cat01 = :cat01
              AND cat02 = :cat02
              AND cat03 = :cat03
              AND cat04 = :cat04
              AND value IS NOT NULL
            ORDER BY time_code DESC
            LIMIT 1
            """
        ),
        {
            "area_code": area_code,
            "stats_data_id": stats_data_id,
            "cat01": cat01,
            "cat02": cat02,
            "cat03": cat03,
            "cat04": cat04,
        },
    ).first()
    if not row:
        return None
    return _ValueRow(value=float(row[0]), unit=row[1] or "", time_code=row[2] or "")


def _fetch_latest_from_tables(
    db: Session,
    *,
    area_code: str,
    stats_data_ids: tuple[str, ...],
    cat01: str,
    cat02: str = "",
) -> Optional[_ValueRow]:
    for stats_data_id in stats_data_ids:
        row = _fetch_latest_value(
            db,
            area_code=area_code,
            stats_data_id=stats_data_id,
            cat01=cat01,
            cat02=cat02,
        )
        if row:
            return row
    return None


def _fetch_social_metric(
    db: Session, *, area_code: str, cat01: str
) -> Optional[_ValueRow]:
    return _fetch_latest_value(
        db,
        area_code=area_code,
        stats_data_id=SOCIAL_POPULATION_TABLE,
        cat01=cat01,
    )


def _fetch_population_series(db: Session, *, area_code: str) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT time_code, value, stats_data_id
            FROM estat_stat_values
            WHERE area_code = :area_code
              AND stats_data_id IN ('0004050397', '0003433219')
              AND cat01 = '0'
              AND value IS NOT NULL
            ORDER BY time_code ASC
            """
        ),
        {"area_code": area_code},
    ).all()
    series: list[dict] = []
    seen_years: set[int] = set()
    for time_code, value, _stats_data_id in rows:
        year = _parse_survey_year(time_code)
        if year is None or year in seen_years:
            continue
        seen_years.add(year)
        series.append({"year": year, "population": int(value)})
    return series


def _fetch_building_age_chart(db: Session, *, area_code: str) -> list[dict]:
    time_code = db.scalar(
        text(
            """
            SELECT MAX(time_code)
            FROM estat_stat_values
            WHERE area_code = :area_code
              AND stats_data_id = :stats_data_id
            """
        ),
        {"area_code": area_code, "stats_data_id": HOUSING_BUILDING_AGE_TABLE},
    )
    if not time_code:
        return []

    rows = db.execute(
        text(
            """
            SELECT v.cat01, c.name, v.value
            FROM estat_stat_values v
            LEFT JOIN estat_class_codes c
              ON c.stats_data_id = v.stats_data_id
             AND c.object_id = 'cat01'
             AND c.code = v.cat01
            WHERE v.area_code = :area_code
              AND v.stats_data_id = :stats_data_id
              AND v.time_code = :time_code
              AND v.cat01 NOT IN ('', '0', '00')
              AND v.cat02 = '0'
              AND v.cat03 = ''
              AND v.cat04 = ''
              AND v.cat05 = ''
              AND v.value IS NOT NULL
            ORDER BY v.cat01
            """
        ),
        {
            "area_code": area_code,
            "stats_data_id": HOUSING_BUILDING_AGE_TABLE,
            "time_code": time_code,
        },
    ).all()

    chart: list[dict] = []
    for cat01, name, value in rows:
        label = HOUSING_AGE_LABELS.get(cat01) or (name or cat01)
        chart.append({"label": label, "count": int(value)})
    return chart


def get_municipality_estat_insights(municipality_code: str) -> Optional[dict]:
    if not _estat_db_available():
        return None

    db = EstatSessionLocal()
    try:
        population = _fetch_latest_from_tables(
            db,
            area_code=municipality_code,
            stats_data_ids=CENSUS_POPULATION_TABLES,
            cat01="0",
        )
        if not population:
            return None

        population_series = _fetch_population_series(db, area_code=municipality_code)
        population_change_pct: Optional[float] = None
        if len(population_series) >= 2:
            prev = population_series[-2]["population"]
            latest = population_series[-1]["population"]
            if prev:
                population_change_pct = (latest - prev) / prev * 100

        housing_count = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=HOUSING_COUNT_TABLE,
            cat01="0",
        )
        owned_homes = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=HOUSING_OWNERSHIP_TABLE,
            cat01="1",
        )
        rented_homes = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=HOUSING_OWNERSHIP_TABLE,
            cat01="2",
        )
        owner_occupied_pct: Optional[float] = None
        if (
            owned_homes
            and owned_homes.value is not None
            and housing_count
            and housing_count.value
        ):
            owner_occupied_pct = owned_homes.value / housing_count.value * 100

        vacant_row = db.execute(
            text(
                """
                SELECT value, unit, time_code
                FROM estat_stat_values
                WHERE area_code = :area_code
                  AND stats_data_id = :stats_data_id
                  AND cat01 = '0'
                  AND cat02 = '0'
                  AND cat03 = '0'
                  AND cat04 = '0'
                  AND value IS NOT NULL
                ORDER BY time_code DESC, value DESC
                LIMIT 1
                """
            ),
            {
                "area_code": municipality_code,
                "stats_data_id": HOUSING_VACANT_TABLE,
            },
        ).first()
        vacant_count = (
            _ValueRow(value=float(vacant_row[0]), unit=vacant_row[1] or "", time_code=vacant_row[2] or "")
            if vacant_row
            else None
        )
        vacancy_pct: Optional[float] = None
        if (
            vacant_count
            and vacant_count.value is not None
            and housing_count
            and housing_count.value
        ):
            vacancy_pct = vacant_count.value / housing_count.value * 100

        rent = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=HOUSING_RENT_TABLE,
            cat01="1",
            cat02="1",
        )

        main_households = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=HOUSING_HOUSEHOLD_TABLE,
            cat01="0",
            cat02="1",
        )
        single_households = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=HOUSING_HOUSEHOLD_TABLE,
            cat01="0",
            cat02="11",
        )
        single_household_pct: Optional[float] = None
        if (
            single_households
            and single_households.value is not None
            and main_households
            and main_households.value
        ):
            single_household_pct = single_households.value / main_households.value * 100

        social_owner_pct = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=SOCIAL_HOUSING_TABLE,
            cat01="#H01301",
        )
        social_vacancy_pct = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=SOCIAL_HOUSING_TABLE,
            cat01="#H01405",
        )
        avg_floor_area = _fetch_latest_value(
            db,
            area_code=municipality_code,
            stats_data_id=SOCIAL_HOUSING_TABLE,
            cat01="#H02103",
        )

        elderly_pct = _fetch_social_metric(
            db, area_code=municipality_code, cat01=SOCIAL_METRIC_CODES["elderly_pct"]
        )
        population_growth = _fetch_social_metric(
            db,
            area_code=municipality_code,
            cat01=SOCIAL_METRIC_CODES["population_growth_pct"],
        )
        population_density = _fetch_social_metric(
            db,
            area_code=municipality_code,
            cat01=SOCIAL_METRIC_CODES["population_density"],
        )
        single_elderly_household_pct = _fetch_social_metric(
            db,
            area_code=municipality_code,
            cat01=SOCIAL_METRIC_CODES["single_elderly_household_pct"],
        )

        building_age_chart = _fetch_building_age_chart(db, area_code=municipality_code)

        def metric(
            label: str,
            row: Optional[_ValueRow],
            *,
            source: str,
            computed: Optional[float] = None,
            unit: str = "",
        ) -> Optional[dict]:
            if computed is not None:
                return {
                    "label": label,
                    "value": round(computed, 1),
                    "unit": unit,
                    "year": None,
                    "source": source,
                }
            if not row or row.value is None:
                return None
            return {
                "label": label,
                "value": round(row.value, 1) if row.unit == "％" else round(row.value),
                "unit": row.unit or unit,
                "year": _parse_survey_year(row.time_code),
                "source": source,
            }

        highlights = [
            m
            for m in [
                metric("人口", population, source="国勢調査"),
                metric(
                    "65歳以上人口",
                    elderly_pct,
                    source="社会・人口統計体系",
                ),
                metric(
                    "持ち家比率",
                    social_owner_pct,
                    source="社会・人口統計体系",
                )
                or metric(
                    "持ち家比率",
                    None,
                    source="住宅・土地統計調査",
                    computed=owner_occupied_pct,
                    unit="％",
                ),
                metric(
                    "空き家比率",
                    social_vacancy_pct,
                    source="社会・人口統計体系",
                )
                or metric(
                    "空き家比率",
                    None,
                    source="住宅・土地統計調査",
                    computed=vacancy_pct,
                    unit="％",
                ),
                metric("平均家賃（専用住宅）", rent, source="住宅・土地統計調査"),
                metric("住宅数", housing_count, source="住宅・土地統計調査"),
            ]
            if m
        ]

        details = [
            m
            for m in [
                metric("人口密度", population_density, source="社会・人口統計体系"),
                metric("人口増減率", population_growth, source="社会・人口統計体系"),
                metric(
                    "単独世帯（65歳以上）",
                    single_elderly_household_pct,
                    source="社会・人口統計体系",
                ),
                metric(
                    "1人世帯比率",
                    None,
                    source="住宅・土地統計調査",
                    computed=single_household_pct,
                    unit="％",
                ),
                metric("持ち家数", owned_homes, source="住宅・土地統計調査"),
                metric("借家数", rented_homes, source="住宅・土地統計調査"),
                metric("空き家数", vacant_count, source="住宅・土地統計調査"),
                metric("延べ面積（1住宅）", avg_floor_area, source="社会・人口統計体系"),
            ]
            if m
        ]

        latest_years = sorted(
            {
                year
                for year in (
                    _parse_survey_year(population.time_code),
                    _parse_survey_year(housing_count.time_code) if housing_count else None,
                    _parse_survey_year(social_owner_pct.time_code) if social_owner_pct else None,
                )
                if year
            },
            reverse=True,
        )

        return {
            "available": True,
            "population": int(population.value) if population.value is not None else None,
            "population_year": _parse_survey_year(population.time_code),
            "population_change_pct": round(population_change_pct, 2)
            if population_change_pct is not None
            else None,
            "population_series": population_series,
            "building_age_chart": building_age_chart,
            "highlights": highlights,
            "details": details,
            "latest_year": latest_years[0] if latest_years else None,
            "sources": [
                "総務省統計局 e-Stat（国勢調査）",
                "総務省統計局 e-Stat（社会・人口統計体系）",
                "国土交通省 e-Stat（住宅・土地統計調査）",
            ],
            "average_monthly_rent": float(rent.value) if rent and rent.value is not None else None,
            "elderly_pct": float(elderly_pct.value)
            if elderly_pct and elderly_pct.value is not None
            else None,
            "owner_occupied_pct": (
                float(social_owner_pct.value)
                if social_owner_pct and social_owner_pct.value is not None
                else (round(owner_occupied_pct, 1) if owner_occupied_pct is not None else None)
            ),
            "vacancy_pct": (
                float(social_vacancy_pct.value)
                if social_vacancy_pct and social_vacancy_pct.value is not None
                else (round(vacancy_pct, 1) if vacancy_pct is not None else None)
            ),
            "population_density": float(population_density.value)
            if population_density and population_density.value is not None
            else None,
            "single_household_pct": round(single_household_pct, 1)
            if single_household_pct is not None
            else None,
            "housing_count": int(housing_count.value)
            if housing_count and housing_count.value is not None
            else None,
        }
    finally:
        db.close()
