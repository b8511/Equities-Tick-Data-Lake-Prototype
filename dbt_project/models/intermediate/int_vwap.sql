{{
    config(
        materialized='table',
        order_by='(symbol, minute_bucket)',
        engine='MergeTree()'
    )
}}

/*
    Intermediate: VWAP (Volume-Weighted Average Price)
    Per-symbol, per-minute VWAP — the single most common intraday metric
    used by trading desks to benchmark execution quality.
*/

SELECT
    symbol,
    toStartOfMinute(timestamp) AS minute_bucket,
    trade_date,
    sum(trade_notional) / sum(trade_size) AS vwap,
    sum(trade_size) AS total_volume,
    sum(trade_notional) AS total_notional,
    count() AS trade_count,
    min(trade_price) AS low,
    max(trade_price) AS high,
    argMin(trade_price, timestamp) AS open,
    argMax(trade_price, timestamp) AS close
FROM {{ ref('stg_trades') }}
WHERE NOT has_quality_issue
GROUP BY symbol, minute_bucket, trade_date
