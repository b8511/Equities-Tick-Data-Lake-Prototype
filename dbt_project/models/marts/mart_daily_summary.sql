{{
    config(
        materialized='table',
        order_by='(symbol, trade_date)',
        engine='MergeTree()'
    )
}}

/*
    Mart: Daily Summary
    OHLCV + spread + quality metrics per symbol per day.
    This is the table analysts query most frequently — the "go-to"
    overview for any given symbol on any given day.
*/

WITH trade_stats AS (
    SELECT
        symbol,
        trade_date,
        argMin(trade_price, timestamp) AS open_price,
        argMax(trade_price, timestamp) AS close_price,
        max(trade_price) AS high_price,
        min(trade_price) AS low_price,
        sum(trade_size) AS total_volume,
        sum(trade_notional) AS total_notional,
        sum(trade_notional) / sum(trade_size) AS day_vwap,
        count() AS trade_count,
        countIf(has_quality_issue) AS trade_quality_issues
    FROM {{ ref('stg_trades') }}
    GROUP BY symbol, trade_date
),

quote_stats AS (
    SELECT
        symbol,
        quote_date AS trade_date,
        avg(spread_bps) AS avg_spread_bps,
        median(spread_bps) AS median_spread_bps,
        quantile(0.95)(spread_bps) AS p95_spread_bps,
        count() AS quote_count,
        countIf(has_quality_issue) AS quote_quality_issues
    FROM {{ ref('stg_quotes') }}
    GROUP BY symbol, quote_date
)

SELECT
    t.symbol,
    t.trade_date,
    t.open_price,
    t.high_price,
    t.low_price,
    t.close_price,
    t.total_volume,
    t.total_notional,
    t.day_vwap,
    t.trade_count,
    q.avg_spread_bps,
    q.median_spread_bps,
    q.p95_spread_bps,
    q.quote_count,
    t.trade_quality_issues + q.quote_quality_issues AS total_quality_issues,
    (t.close_price - t.open_price) / t.open_price * 100 AS daily_return_pct
FROM trade_stats t
LEFT JOIN quote_stats q ON t.symbol = q.symbol AND t.trade_date = q.trade_date
