from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import services
from app.news.regional import get_regional_news
from app.news.service import get_news_feed
from app.api.schemas import (
    DistrictSearchResult,
    LandPricePointItem,
    MunicipalityDetail,
    MunicipalitySummary,
    PrefectureSummary,
    SearchResult,
    StationDetail,
    StationSummary,
    TransactionPage,
)
from app.db import get_db

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/prefectures", response_model=list[PrefectureSummary])
def api_prefectures(db: Session = Depends(get_db)) -> list[PrefectureSummary]:
    return services.list_prefectures(db)


@router.get(
    "/prefectures/{prefecture_slug}/municipalities",
    response_model=list[MunicipalitySummary],
)
def api_municipalities(
    prefecture_slug: str, db: Session = Depends(get_db)
) -> list[MunicipalitySummary]:
    prefecture = services.get_prefecture_by_slug(db, prefecture_slug)
    if not prefecture:
        raise HTTPException(status_code=404, detail="都道府県が見つかりません")
    return services.list_municipalities_for_prefecture(db, prefecture)


@router.get(
    "/municipalities/{prefecture_slug}/{municipality_slug}",
    response_model=MunicipalityDetail,
)
def api_municipality_detail(
    prefecture_slug: str,
    municipality_slug: str,
    db: Session = Depends(get_db),
) -> MunicipalityDetail:
    prefecture, municipality = services.resolve_municipality(
        db, prefecture_slug, municipality_slug
    )
    if not prefecture or not municipality:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")
    return services.get_municipality_detail(db, prefecture, municipality)


@router.get("/search", response_model=list[SearchResult])
def api_search(q: str = "", limit: int = 12, db: Session = Depends(get_db)) -> list[SearchResult]:
    return services.search_municipalities(db, q, limit=min(limit, 30))


@router.get("/districts/search", response_model=list[DistrictSearchResult])
def api_district_search(
    q: str = "", limit: int = 20, db: Session = Depends(get_db)
) -> list[DistrictSearchResult]:
    return services.search_districts(db, q, limit=min(limit, 30))


@router.get(
    "/municipalities/{prefecture_slug}/{municipality_slug}/transactions",
    response_model=TransactionPage,
)
def api_transactions(
    prefecture_slug: str,
    municipality_slug: str,
    page: int = 1,
    page_size: int = 20,
    property_type: str = "",
    price_classification: str = "01",
    db: Session = Depends(get_db),
) -> TransactionPage:
    prefecture, municipality = services.resolve_municipality(
        db, prefecture_slug, municipality_slug
    )
    if not prefecture or not municipality:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")
    if price_classification not in ("01", "02"):
        price_classification = "01"
    return services.get_transactions_page(
        db,
        municipality.code,
        page=page,
        page_size=page_size,
        property_type=property_type,
        price_classification=price_classification,
    )


@router.get(
    "/municipalities/{prefecture_slug}/{municipality_slug}/land-prices",
    response_model=list[LandPricePointItem],
)
def api_land_prices(
    prefecture_slug: str,
    municipality_slug: str,
    year: Optional[int] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[LandPricePointItem]:
    prefecture, municipality = services.resolve_municipality(
        db, prefecture_slug, municipality_slug
    )
    if not prefecture or not municipality:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")
    return services.list_land_price_points(
        db, municipality.code, survey_year=year, limit=min(limit, 500)
    )


@router.get("/news")
def api_news(refresh: bool = False) -> dict:
    return get_news_feed(force_refresh=refresh, per_category=12)


@router.get("/news/regional")
def api_regional_news(
    prefecture_slug: str,
    municipality_slug: Optional[str] = None,
    refresh: bool = False,
    limit: int = 10,
    db: Session = Depends(get_db),
) -> dict:
    if municipality_slug:
        prefecture, municipality = services.resolve_municipality(
            db, prefecture_slug, municipality_slug
        )
        if not prefecture or not municipality:
            raise HTTPException(status_code=404, detail="市区町村が見つかりません")
        return get_regional_news(
            prefecture.name_ja,
            prefecture.slug,
            municipality.name_ja,
            municipality.slug,
            force_refresh=refresh,
            limit=min(limit, 20),
        )
    prefecture = services.get_prefecture_by_slug(db, prefecture_slug)
    if not prefecture:
        raise HTTPException(status_code=404, detail="都道府県が見つかりません")
    return get_regional_news(
        prefecture.name_ja,
        prefecture.slug,
        force_refresh=refresh,
        limit=min(limit, 20),
    )


@router.get("/stations/search", response_model=list[StationSummary])
def api_search_stations(
    q: str = "", limit: int = 20, db: Session = Depends(get_db)
) -> list[StationSummary]:
    return services.search_stations(db, q, limit=min(limit, 50))


@router.get("/stations/{station_id}", response_model=StationDetail)
def api_station_detail(
    station_id: int, db: Session = Depends(get_db)
) -> StationDetail:
    station = services.get_station_detail(db, station_id)
    if not station:
        raise HTTPException(status_code=404, detail="駅が見つかりません")
    return station


@router.get(
    "/prefectures/{prefecture_slug}/stations",
    response_model=list[StationSummary],
)
def api_prefecture_stations(
    prefecture_slug: str, limit: int = 30, db: Session = Depends(get_db)
) -> list[StationSummary]:
    prefecture = services.get_prefecture_by_slug(db, prefecture_slug)
    if not prefecture:
        raise HTTPException(status_code=404, detail="都道府県が見つかりません")
    return services.list_stations_for_prefecture(db, prefecture.code, limit=min(limit, 100))
