from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PrefectureSummary(BaseModel):
    code: str
    name_ja: str
    slug: str
    municipality_count: int = 0
    total_transactions: int = 0
    avg_price: Optional[float] = None


class MunicipalitySummary(BaseModel):
    code: str
    name_ja: str
    slug: str
    total_transactions: int = 0
    recent_avg_price: Optional[float] = None
    latest_year: Optional[int] = None
    latest_quarter: Optional[int] = None


class StatBucket(BaseModel):
    trade_year: int
    trade_quarter: int
    property_type: str
    transaction_count: int
    trade_price_avg: Optional[float] = None
    unit_price_avg: Optional[float] = None


class YearlyStat(BaseModel):
    trade_year: int
    transaction_count: int
    trade_price_avg: Optional[float] = None
    unit_price_avg: Optional[float] = None
    yoy_transaction_pct: Optional[float] = None


class PrefectureChartData(BaseModel):
    yearly_stats: list[YearlyStat] = []
    land_price_yearly: list[LandPriceYearlyStat] = []
    top_municipalities: list[MunicipalitySummary] = []
    top_stations: list[StationSummary] = []


class SearchResult(BaseModel):
    code: str
    name_ja: str
    slug: str
    prefecture_name: str
    prefecture_slug: str
    total_transactions: int = 0
    recent_avg_price: Optional[float] = None


class RankingItem(BaseModel):
    rank: int
    code: str
    name_ja: str
    slug: str
    prefecture_name: str
    prefecture_slug: str
    total_transactions: int = 0
    recent_avg_price: Optional[float] = None


class LandPriceSummary(BaseModel):
    point_count: int = 0
    latest_year: Optional[int] = None
    avg_unit_price: Optional[float] = None
    max_unit_price: Optional[int] = None
    min_unit_price: Optional[int] = None
    yoy_change_avg: Optional[float] = None


class LandPriceChangeItem(BaseModel):
    rank: int
    code: str
    name_ja: str
    slug: str
    prefecture_name: str
    prefecture_slug: str
    survey_year: Optional[int] = None
    point_count: int = 0
    avg_unit_price: Optional[float] = None
    yoy_change_avg: Optional[float] = None


class HomeHighlights(BaseModel):
    top_by_volume: list[RankingItem] = []
    top_by_price: list[RankingItem] = []
    land_price_gainers: list[LandPriceChangeItem] = []
    land_price_losers: list[LandPriceChangeItem] = []
    land_price_year: Optional[int] = None
    total_transactions: int = 0
    municipality_count: int = 0


class HomeChartData(BaseModel):
    yearly_stats: list[YearlyStat] = []
    land_price_yearly: list[LandPriceYearlyStat] = []
    top_prefectures_volume: list[PrefectureSummary] = []
    top_prefectures_price: list[PrefectureSummary] = []


class TransactionItem(BaseModel):
    id: int
    trade_year: int
    trade_quarter: int
    property_type: Optional[str] = None
    district_name: Optional[str] = None
    trade_price: Optional[int] = None
    unit_price: Optional[int] = None
    area: Optional[float] = None
    period_label: Optional[str] = None
    building_year: Optional[str] = None
    structure: Optional[str] = None
    city_planning: Optional[str] = None
    floor_plan: Optional[str] = None
    renovation: Optional[str] = None


class InsightBucket(BaseModel):
    label: str
    transaction_count: int
    trade_price_avg: Optional[float] = None
    unit_price_avg: Optional[float] = None


class PriceClassComparison(BaseModel):
    trade_count: int
    trade_price_avg: Optional[float] = None
    contract_count: int
    contract_price_avg: Optional[float] = None
    discount_pct: Optional[float] = None


class LandTradeGap(BaseModel):
    trade_unit_price_avg: Optional[float] = None
    land_price_avg: Optional[float] = None
    gap_pct: Optional[float] = None
    sample_count: int = 0


class MarketSummary(BaseModel):
    property_label: str = "中古マンション"
    sample_count: int = 0
    median_price: Optional[float] = None
    p25_price: Optional[float] = None
    p75_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None


class PurchaseInsights(BaseModel):
    period_label: str = ""
    sample_years: int = 5
    market_summary: Optional[MarketSummary] = None
    price_bracket_stats: list[InsightBucket] = []
    floor_plan_stats: list[InsightBucket] = []
    age_bucket_stats: list[InsightBucket] = []
    structure_stats: list[InsightBucket] = []
    renovation_stats: list[InsightBucket] = []
    region_stats: list[InsightBucket] = []
    city_planning_stats: list[InsightBucket] = []
    district_hotspots: list[InsightBucket] = []
    price_comparison: Optional[PriceClassComparison] = None
    land_trade_gap: Optional[LandTradeGap] = None


class TransactionPage(BaseModel):
    items: list[TransactionItem] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_more: bool = False


class LandPricePointItem(BaseModel):
    id: int
    point_id: int
    survey_year: int
    location: Optional[str] = None
    standard_lot_number: Optional[str] = None
    unit_price: Optional[int] = None
    year_on_year_change_rate: Optional[float] = None
    area_sqm: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    nearest_station: Optional[str] = None
    use_category_name: Optional[str] = None


class LandPriceYearlyStat(BaseModel):
    survey_year: int
    point_count: int
    avg_unit_price: Optional[float] = None
    yoy_avg_price_pct: Optional[float] = None


class StationYearlyPassenger(BaseModel):
    year: int
    passengers: int
    yoy_pct: Optional[float] = None


class StationSummary(BaseModel):
    id: int
    station_name: str
    line_name: str
    operator_name: Optional[str] = None
    prefecture_code: Optional[str] = None
    prefecture_slug: Optional[str] = None
    prefecture_name: Optional[str] = None
    latest_year: Optional[int] = None
    latest_passengers: Optional[int] = None


class StationDetail(StationSummary):
    railway_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    yearly_passengers: list[StationYearlyPassenger] = []


class DistrictSearchResult(BaseModel):
    code: str
    name: str
    municipality_name: str
    municipality_slug: str
    prefecture_slug: str
    transaction_count: int = 0


class MunicipalityDetail(BaseModel):
    code: str
    name_ja: str
    slug: str
    prefecture_code: str
    prefecture_name: str
    prefecture_slug: str
    total_transactions: int = 0
    recent_avg_price: Optional[float] = None
    latest_year: Optional[int] = None
    latest_quarter: Optional[int] = None
    quarterly_stats: list[StatBucket] = []
    quarterly_chart: list[StatBucket] = []
    yearly_stats: list[YearlyStat] = []
    property_stats: list[StatBucket] = []
    recent_transactions: list[TransactionItem] = []
    land_prices: Optional[LandPriceSummary] = None
    land_price_yearly: list[LandPriceYearlyStat] = []
    related_municipalities: list[MunicipalitySummary] = []
    yoy_price_change_pct: Optional[float] = None
    stats_updated_at: Optional[datetime] = None
    purchase_insights: Optional[PurchaseInsights] = None


class CompareSide(BaseModel):
    code: str
    name_ja: str
    slug: str
    prefecture_name: str
    prefecture_slug: str
    total_transactions: int = 0
    recent_avg_price: Optional[float] = None
    yearly_stats: list[YearlyStat] = []
    property_stats: list[StatBucket] = []
    yoy_price_change_pct: Optional[float] = None
    land_prices: Optional[LandPriceSummary] = None
    land_price_yearly: list[LandPriceYearlyStat] = []


class ReportContext(BaseModel):
    report_type: str = "seller"
    period_years: int = 2
    report_type_label: str = "売主向け（周辺取引事例）"
    period_label: str = "直近2年 + 年次推移"


class CompareView(BaseModel):
    left: CompareSide
    right: CompareSide


class AppraisalArea(BaseModel):
    slug: str
    name: str
    mansion_unit_price: Optional[int] = None
    mansion_samples: int = 0
    land_unit_price: Optional[int] = None
    land_samples: int = 0


class AppraisalPrefecture(BaseModel):
    slug: str
    name: str
    areas: list[AppraisalArea] = []


class AppraisalDataset(BaseModel):
    prefectures: list[AppraisalPrefecture] = []
    base_year: Optional[int] = None
    area_count: int = 0
