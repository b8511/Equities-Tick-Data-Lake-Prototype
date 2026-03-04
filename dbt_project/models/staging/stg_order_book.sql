{{
    config(materialized='view')
}}

/*
    Staging: L2 order book snapshots
    Unpivots the wide array columns into a long (tidy) format:
    one row per (symbol, timestamp, side, level).  Downstream models
    can therefore use standard aggregations without fighting with arrays.

    Also carries pre-computed convenience fields (mid_price, weighted_mid,
    book_imbalance) through from the raw snapshot for models that only
    need top-level book stats without the full depth curve.
*/

WITH snapshot AS (
    SELECT
        symbol,
        timestamp,
        toDate(timestamp)   AS snap_date,
        bid_prices,
        bid_sizes,
        ask_prices,
        ask_sizes,
        mid_price,
        weighted_mid,
        book_imbalance,
        data_quality_flag,
        data_quality_flag != 'OK' AS has_quality_issue
    FROM {{ source('raw', 'order_book_snapshots') }}
),

bid_levels AS (
    SELECT
        symbol,
        timestamp,
        snap_date,
        'bid'                        AS side,
        arrayJoin(
            arrayEnumerate(bid_prices)
        )                            AS level,        -- 1 = best bid
        bid_prices[level]            AS price,
        bid_sizes[level]             AS size,
        mid_price,
        weighted_mid,
        book_imbalance,
        has_quality_issue
    FROM snapshot
),

ask_levels AS (
    SELECT
        symbol,
        timestamp,
        snap_date,
        'ask'                        AS side,
        arrayJoin(
            arrayEnumerate(ask_prices)
        )                            AS level,        -- 1 = best ask
        ask_prices[level]            AS price,
        ask_sizes[level]             AS size,
        mid_price,
        weighted_mid,
        book_imbalance,
        has_quality_issue
    FROM snapshot
)

SELECT * FROM bid_levels
UNION ALL
SELECT * FROM ask_levels
