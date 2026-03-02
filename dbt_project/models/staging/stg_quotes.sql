{{
    config(materialized='view')
}}

/*
    Staging: quotes
    Light cleaning layer over raw quotes.
    Computes spread and mid price.
*/

SELECT
    symbol,
    timestamp,
    toDate(timestamp) AS quote_date,
    bid_price,
    ask_price,
    bid_size,
    ask_size,
    ask_price - bid_price AS spread,
    CASE
        WHEN bid_price > 0 THEN (ask_price - bid_price) / ((bid_price + ask_price) / 2) * 10000
        ELSE NULL
    END AS spread_bps,
    (bid_price + ask_price) / 2 AS mid_price,
    exchange,
    data_quality_flag,
    data_quality_flag != 'OK' AS has_quality_issue
FROM {{ source('raw', 'quotes') }}
WHERE bid_price > 0 AND ask_price > 0
