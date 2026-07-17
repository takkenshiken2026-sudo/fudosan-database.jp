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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class EstatBase(DeclarativeBase):
    pass


class EstatSurvey(EstatBase):
    __tablename__ = "estat_surveys"

    stats_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    survey_name: Mapped[str] = mapped_column(String(80))
    update_cycle: Mapped[str] = mapped_column(String(20), default="")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class EstatStatsTable(EstatBase):
    __tablename__ = "estat_stats_tables"

    stats_data_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    stats_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("estat_surveys.stats_code"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    survey_year: Mapped[Optional[str]] = mapped_column(String(20))
    collect_area: Mapped[Optional[int]] = mapped_column(Integer)
    statistics_name: Mapped[Optional[str]] = mapped_column(Text)
    updated_date: Mapped[Optional[str]] = mapped_column(String(20))
    is_sync_target: Mapped[int] = mapped_column(Integer, default=0, index=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class EstatClassObject(EstatBase):
    __tablename__ = "estat_class_objects"
    __table_args__ = (
        UniqueConstraint("stats_data_id", "object_id", name="uq_estat_class_object"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stats_data_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("estat_stats_tables.stats_data_id"), index=True
    )
    object_id: Mapped[str] = mapped_column(String(10))
    object_name: Mapped[Optional[str]] = mapped_column(String(80))


class EstatClassCode(EstatBase):
    __tablename__ = "estat_class_codes"
    __table_args__ = (
        UniqueConstraint(
            "stats_data_id", "object_id", "code", name="uq_estat_class_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stats_data_id: Mapped[str] = mapped_column(String(20), index=True)
    object_id: Mapped[str] = mapped_column(String(10))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[Optional[int]] = mapped_column(Integer)
    parent_code: Mapped[Optional[str]] = mapped_column(String(20))
    unit: Mapped[Optional[str]] = mapped_column(String(20))


class EstatAreaCodeMap(EstatBase):
    __tablename__ = "estat_area_code_map"

    estat_area_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    area_level: Mapped[str] = mapped_column(String(20))
    prefecture_code: Mapped[Optional[str]] = mapped_column(String(2), index=True)
    municipality_code: Mapped[Optional[str]] = mapped_column(String(5), index=True)
    area_name: Mapped[Optional[str]] = mapped_column(String(80))


class EstatStatValue(EstatBase):
    __tablename__ = "estat_stat_values"
    __table_args__ = (
        UniqueConstraint(
            "stats_data_id",
            "tab_code",
            "area_code",
            "time_code",
            "cat01",
            "cat02",
            "cat03",
            "cat04",
            "cat05",
            name="uq_estat_stat_value",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stats_data_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("estat_stats_tables.stats_data_id"), index=True
    )
    tab_code: Mapped[str] = mapped_column(String(20), default="")
    area_code: Mapped[str] = mapped_column(String(10), index=True)
    time_code: Mapped[str] = mapped_column(String(20), index=True)
    cat01: Mapped[str] = mapped_column(String(20), default="")
    cat02: Mapped[str] = mapped_column(String(20), default="")
    cat03: Mapped[str] = mapped_column(String(20), default="")
    cat04: Mapped[str] = mapped_column(String(20), default="")
    cat05: Mapped[str] = mapped_column(String(20), default="")
    value: Mapped[Optional[float]] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    annotation: Mapped[Optional[str]] = mapped_column(String(10))
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EstatSyncCheckpoint(EstatBase):
    __tablename__ = "estat_sync_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "sync_type",
            "stats_data_id",
            "area_code",
            name="uq_estat_sync_checkpoint",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sync_type: Mapped[str] = mapped_column(String(20), index=True)
    stats_data_id: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    area_code: Mapped[Optional[str]] = mapped_column(String(10))
    start_position: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), index=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


estat_engine = create_engine(
    settings.estat_database_url,
    connect_args={"check_same_thread": False, "timeout": 60}
    if settings.estat_database_url.startswith("sqlite")
    else {},
)


@event.listens_for(estat_engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    if settings.estat_database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.close()


EstatSessionLocal = sessionmaker(bind=estat_engine, autoflush=False, autocommit=False)


def init_estat_db() -> None:
    if settings.estat_database_url.startswith("sqlite:///"):
        db_path = settings.estat_database_url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    EstatBase.metadata.create_all(bind=estat_engine)
