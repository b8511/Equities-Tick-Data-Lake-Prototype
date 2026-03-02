{{
    config(materialized='view')
}}

/*
    Staging: trades
    Light cleaning layer over raw trades.
    Filters out zero-price rows and adds trade_date for downstream partitioning.
*/

SELECT
    symbol,
    timestamp,
    toDate(timestamp) AS trade_date,
    trade_price,
    trade_size,
    trade_price * trade_size AS trade_notional,
    exchange,
    trade_condition,
    data_quality_flag,
    data_quality_flag != 'OK' AS has_quality_issue
FROM {{ source('raw', 'trades') }}
WHERE trade_price > 0
