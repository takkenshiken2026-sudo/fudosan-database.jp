from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class Prefecture(Base):
    __tablename__ = "prefectures"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name_ja: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(40))
    slug: Mapped[str] = mapped_column(String(20), unique=True, index=True)

    municipalities: Mapped[list["Municipality"]] = relationship(back_populates="prefecture")


class Municipality(Base):
    __tablename__ = "municipalities"

    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    prefecture_code: Mapped[str] = mapped_column(
        ForeignKey("prefectures.code"), index=True
    )
    name_ja: Mapped[str] = mapped_column(String(40))
    name_en: Mapped[Optional[str]] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(40), index=True)

    prefecture: Mapped["Prefecture"] = relationship(back_populates="municipalities")
    districts: Mapped[list["District"]] = relationship(back_populates="municipality")
    transactions: Mapped[list["TradeTransaction"]] = relationship(
        back_populates="municipality"
    )
    trade_stats: Mapped[list["MunicipalityTradeStat"]] = relationship(
        back_populates="municipality"
    )
    page_meta: Mapped[Optional["MunicipalityPageMeta"]] = relationship(
        back_populates="municipality", uselist=False
    )


class District(Base):
    __tablename__ = "districts"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))

    municipality: Mapped["Municipality"] = relationship(back_populates="districts")


class TradeTransaction(Base):
    __tablename__ = "trade_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    price_category: Mapped[str] = mapped_column(String(40))
    price_classification: Mapped[str] = mapped_column(String(2), index=True)
    trade_year: Mapped[int] = mapped_column(Integer, index=True)
    trade_quarter: Mapped[int] = mapped_column(Integer, index=True)
    property_type: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    region: Mapped[Optional[str]] = mapped_column(String(40))
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code"), index=True
    )
    prefecture_name: Mapped[Optional[str]] = mapped_column(String(20))
    municipality_name: Mapped[Optional[str]] = mapped_column(String(40))
    district_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    district_name: Mapped[Optional[str]] = mapped_column(String(80))
    trade_price: Mapped[Optional[int]] = mapped_column(Integer)
    price_per_unit: Mapped[Optional[int]] = mapped_column(Integer)
    unit_price: Mapped[Optional[int]] = mapped_column(Integer)
    area: Mapped[Optional[float]] = mapped_column(Float)
    total_floor_area: Mapped[Optional[float]] = mapped_column(Float)
    floor_plan: Mapped[Optional[str]] = mapped_column(String(20))
    building_year: Mapped[Optional[str]] = mapped_column(String(20))
    structure: Mapped[Optional[str]] = mapped_column(String(20))
    city_planning: Mapped[Optional[str]] = mapped_column(String(40))
    coverage_ratio: Mapped[Optional[float]] = mapped_column(Float)
    floor_area_ratio: Mapped[Optional[float]] = mapped_column(Float)
    period_label: Mapped[Optional[str]] = mapped_column(String(30))
    remarks: Mapped[Optional[str]] = mapped_column(Text)
    raw_json: Mapped[Optional[str]] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    municipality: Mapped["Municipality"] = relationship(back_populates="transactions")


class MunicipalityTradeStat(Base):
    __tablename__ = "municipality_trade_stats"
    __table_args__ = (
        UniqueConstraint(
            "municipality_code",
            "trade_year",
            "trade_quarter",
            "price_classification",
            "property_type",
            name="uq_municipality_trade_stats_bucket",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code"), index=True
    )
    trade_year: Mapped[int] = mapped_column(Integer, index=True)
    trade_quarter: Mapped[int] = mapped_column(Integer, index=True)
    price_classification: Mapped[str] = mapped_column(String(2), default="", index=True)
    property_type: Mapped[str] = mapped_column(String(40), default="", index=True)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    trade_price_sum: Mapped[Optional[int]] = mapped_column(Integer)
    trade_price_avg: Mapped[Optional[float]] = mapped_column(Float)
    trade_price_min: Mapped[Optional[int]] = mapped_column(Integer)
    trade_price_max: Mapped[Optional[int]] = mapped_column(Integer)
    unit_price_avg: Mapped[Optional[float]] = mapped_column(Float)
    area_avg: Mapped[Optional[float]] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    municipality: Mapped["Municipality"] = relationship(back_populates="trade_stats")


class LandPricePoint(Base):
    __tablename__ = "land_price_points"
    __table_args__ = (UniqueConstraint("point_id", "survey_year", name="uq_land_price_point_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_id: Mapped[int] = mapped_column(Integer, index=True)
    survey_year: Mapped[int] = mapped_column(Integer, index=True)
    land_price_type: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    prefecture_code: Mapped[str] = mapped_column(String(2), index=True)
    municipality_code: Mapped[str] = mapped_column(String(5), index=True)
    use_category_name: Mapped[Optional[str]] = mapped_column(String(40))
    standard_lot_number: Mapped[Optional[str]] = mapped_column(String(80))
    location: Mapped[Optional[str]] = mapped_column(String(200))
    ward_name: Mapped[Optional[str]] = mapped_column(String(40))
    place_name: Mapped[Optional[str]] = mapped_column(String(80))
    unit_price: Mapped[Optional[int]] = mapped_column(Integer)
    last_years_price: Mapped[Optional[int]] = mapped_column(Integer)
    year_on_year_change_rate: Mapped[Optional[float]] = mapped_column(Float)
    area_sqm: Mapped[Optional[float]] = mapped_column(Float)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    target_year_label: Mapped[Optional[str]] = mapped_column(String(40))
    regulations_use_category: Mapped[Optional[str]] = mapped_column(String(40))
    nearest_station: Mapped[Optional[str]] = mapped_column(String(80))
    raw_json: Mapped[Optional[str]] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StationPassenger(Base):
    __tablename__ = "station_passengers"
    __table_args__ = (
        UniqueConstraint("group_code", "line_name", name="uq_station_group_line"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_code: Mapped[str] = mapped_column(String(10), index=True)
    group_code: Mapped[str] = mapped_column(String(10), index=True)
    station_name: Mapped[str] = mapped_column(String(80), index=True)
    operator_name: Mapped[Optional[str]] = mapped_column(String(80))
    line_name: Mapped[str] = mapped_column(String(80), default="")
    railway_type: Mapped[Optional[str]] = mapped_column(String(10))
    prefecture_code: Mapped[Optional[str]] = mapped_column(String(2), index=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    passengers_json: Mapped[str] = mapped_column(Text, default="{}")
    latest_year: Mapped[Optional[int]] = mapped_column(Integer)
    latest_passengers: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    raw_json: Mapped[Optional[str]] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MunicipalityPageMeta(Base):
    __tablename__ = "municipality_page_meta"

    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code"), primary_key=True
    )
    latest_year: Mapped[Optional[int]] = mapped_column(Integer)
    latest_quarter: Mapped[Optional[int]] = mapped_column(Integer)
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)
    recent_avg_price: Mapped[Optional[float]] = mapped_column(Float)
    stats_updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    municipality: Mapped["Municipality"] = relationship(back_populates="page_meta")


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "sync_type",
            "municipality_code",
            "trade_year",
            "trade_quarter",
            name="uq_sync_checkpoint_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sync_type: Mapped[str] = mapped_column(String(20), index=True)
    prefecture_code: Mapped[Optional[str]] = mapped_column(String(2), index=True)
    municipality_code: Mapped[Optional[str]] = mapped_column(String(5), index=True)
    trade_year: Mapped[Optional[int]] = mapped_column(Integer)
    trade_quarter: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), index=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 60}
    if settings.database_url.startswith("sqlite")
    else {},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
