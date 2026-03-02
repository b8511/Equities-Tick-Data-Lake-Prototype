-- ============================================================
-- Equities Tick Data Lake — ClickHouse Schema
-- BNP Prototype: Cash Equities Market Data
-- ============================================================

CREATE DATABASE IF NOT EXISTS equity_market;

-- --------------------------------------------------------
-- Raw trades table
-- Partitioned by day, ordered for fast symbol+time lookups
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS equity_market.trades
(
    symbol        LowCardinality(String),
    timestamp     DateTime64(6, 'UTC'),     -- microsecond precision
    trade_price   Float64,
    trade_size    UInt32,
    exchange      LowCardinality(String),
    trade_condition LowCardinality(String),  -- e.g. '@' regular, 'T' extended hours
    data_quality_flag Enum8(
        'OK' = 0,
        'PRICE_OUTLIER' = 1,
        'SIZE_OUTLIER' = 2,
        'STALE' = 3,
        'MISSING_FIELD' = 4
    ) DEFAULT 'OK'
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (symbol, timestamp)
SETTINGS index_granularity = 8192;

-- --------------------------------------------------------
-- Raw quotes table (NBBO / L1)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS equity_market.quotes
(
    symbol        LowCardinality(String),
    timestamp     DateTime64(6, 'UTC'),
    bid_price     Float64,
    ask_price     Float64,
    bid_size      UInt32,
    ask_size      UInt32,
    exchange      LowCardinality(String),
    data_quality_flag Enum8(
        'OK' = 0,
        'CROSSED_SPREAD' = 1,
        'WIDE_SPREAD' = 2,
        'STALE' = 3,
        'MISSING_FIELD' = 4
    ) DEFAULT 'OK'
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (symbol, timestamp)
SETTINGS index_granularity = 8192;

-- --------------------------------------------------------
-- Data quality issues log
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS equity_market.data_quality_issues
(
    detected_at   DateTime64(6, 'UTC') DEFAULT now64(6),
    source_table  LowCardinality(String),   -- 'trades' or 'quotes'
    symbol        LowCardinality(String),
    event_time    DateTime64(6, 'UTC'),
    issue_type    LowCardinality(String),
    severity      Enum8('INFO' = 0, 'WARNING' = 1, 'CRITICAL' = 2),
    details       String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(detected_at)
ORDER BY (source_table, symbol, detected_at)
SETTINGS index_granularity = 8192;
