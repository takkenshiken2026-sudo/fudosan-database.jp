-- 参考用 DDL（SQLite）。実体は SQLAlchemy が init-db で作成します。

CREATE TABLE prefectures (
    code TEXT PRIMARY KEY,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE
);

CREATE TABLE municipalities (
    code TEXT PRIMARY KEY,
    prefecture_code TEXT NOT NULL REFERENCES prefectures(code),
    name_ja TEXT NOT NULL,
    name_en TEXT,
    slug TEXT NOT NULL
);

CREATE TABLE districts (
    code TEXT PRIMARY KEY,
    municipality_code TEXT NOT NULL REFERENCES municipalities(code),
    name TEXT NOT NULL
);

CREATE TABLE trade_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_hash TEXT NOT NULL UNIQUE,
    price_category TEXT NOT NULL,
    price_classification TEXT NOT NULL,
    trade_year INTEGER NOT NULL,
    trade_quarter INTEGER NOT NULL,
    property_type TEXT,
    region TEXT,
    municipality_code TEXT NOT NULL REFERENCES municipalities(code),
    prefecture_name TEXT,
    municipality_name TEXT,
    district_code TEXT,
    district_name TEXT,
    trade_price INTEGER,
    price_per_unit INTEGER,
    unit_price INTEGER,
    area REAL,
    total_floor_area REAL,
    floor_plan TEXT,
    building_year TEXT,
    structure TEXT,
    city_planning TEXT,
    coverage_ratio REAL,
    floor_area_ratio REAL,
    period_label TEXT,
    remarks TEXT,
    raw_json TEXT,
    synced_at DATETIME NOT NULL
);

CREATE TABLE municipality_trade_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_code TEXT NOT NULL REFERENCES municipalities(code),
    trade_year INTEGER NOT NULL,
    trade_quarter INTEGER NOT NULL,
    price_classification TEXT NOT NULL DEFAULT '',
    property_type TEXT NOT NULL DEFAULT '',
    transaction_count INTEGER NOT NULL DEFAULT 0,
    trade_price_sum INTEGER,
    trade_price_avg REAL,
    trade_price_min INTEGER,
    trade_price_max INTEGER,
    unit_price_avg REAL,
    area_avg REAL,
    updated_at DATETIME NOT NULL,
    UNIQUE (
        municipality_code,
        trade_year,
        trade_quarter,
        price_classification,
        property_type
    )
);

CREATE TABLE municipality_page_meta (
    municipality_code TEXT PRIMARY KEY REFERENCES municipalities(code),
    latest_year INTEGER,
    latest_quarter INTEGER,
    total_transactions INTEGER NOT NULL DEFAULT 0,
    recent_avg_price REAL,
    stats_updated_at DATETIME NOT NULL
);

CREATE TABLE sync_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type TEXT NOT NULL,
    prefecture_code TEXT,
    municipality_code TEXT,
    trade_year INTEGER,
    trade_quarter INTEGER,
    status TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at DATETIME,
    finished_at DATETIME,
    UNIQUE (sync_type, municipality_code, trade_year, trade_quarter)
);

CREATE INDEX idx_municipalities_prefecture ON municipalities(prefecture_code);
CREATE INDEX idx_transactions_municipality_period ON trade_transactions(
    municipality_code, trade_year, trade_quarter
);
CREATE INDEX idx_trade_stats_lookup ON municipality_trade_stats(
    municipality_code, trade_year, trade_quarter
);
