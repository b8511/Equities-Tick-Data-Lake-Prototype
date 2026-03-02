{{
    config(
        materialized='table',
        order_by='(symbol, trade_date, bucket_start)',
        engine='MergeTree()'
    )
}}

/*
    Intermediate: Volume Profile
    5-minute intraday volume distribution — shows where liquidity
    concentrates throughout the trading day (U-shaped pattern expected).
*/

SELECT
    symbol,
    trade_date,
    toStartOfFiveMinutes(timestamp) AS bucket_start,
    sum(trade_size) AS bucket_volume,
    sum(trade_notional) AS bucket_notional,
    count() AS bucket_trade_count,
    sum(trade_notional) / sum(trade_size) AS bucket_vwap,
    min(trade_price) AS bucket_low,
    max(trade_price) AS bucket_high
FROM {{ ref('stg_trades') }}
WHERE NOT has_quality_issue
GROUP BY symbol, trade_date, bucket_start
