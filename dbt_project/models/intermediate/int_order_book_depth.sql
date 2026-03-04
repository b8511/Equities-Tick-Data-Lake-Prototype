{{
    config(
        materialized='table',
        order_by='(symbol, minute_bucket)',
        engine='MergeTree()'
    )
}}

/*
    Intermediate: Order Book Depth Analytics
    =========================================
    Per-symbol, per-minute aggregates of L2 order book microstructure.

    Key metrics produced:
      • bbo_spread_bps        — average BBO spread across all snapshots in the minute
      • depth_bid_5bps        — avg cumulative bid volume within 5 bps of mid
      • depth_ask_5bps        — avg cumulative ask volume within 5 bps of mid
      • depth_bid_10bps       — avg cumulative bid volume within 10 bps of mid
      • depth_ask_10bps       — avg cumulative ask volume within 10 bps of mid
      • avg_book_imbalance    — avg (bid_vol - ask_vol) / (bid_vol + ask_vol) over minute
      • avg_weighted_mid      — avg size-weighted mid price
      • tob_bid_size_avg      — avg top-of-book (L1) bid size
      • tob_ask_size_avg      — avg top-of-book (L1) ask size
      • snapshot_count        — number of book snapshots that fed the minute bar

    Use cases:
      • Liquidity heatmaps (how deep is the book at different times/symbols?)
      • Imbalance signals (persistent positive imbalance → buy pressure)
      • Execution quality context (was there enough depth to absorb the order?)
*/

WITH per_snapshot_stats AS (
    -- Collapse long (side, level) rows back to one row per snapshot,
    -- computing depth at fixed bps thresholds.
    SELECT
        symbol,
        toStartOfMinute(timestamp)  AS minute_bucket,
        snap_date,
        timestamp,
        mid_price,
        weighted_mid,
        book_imbalance,

        -- BBO spread in bps: uses level-1 bid/ask prices from the long table
        -- Both sides contribute level=1; use conditional aggregation
        round(
            (minIf(price, side = 'ask' AND level = 1)
             - maxIf(price, side = 'bid' AND level = 1))
            / nullIf(mid_price, 0) * 10000, 2
        ) AS bbo_spread_bps,

        -- Top-of-book sizes (level 1 only)
        maxIf(size, side = 'bid' AND level = 1) AS tob_bid_size,
        maxIf(size, side = 'ask' AND level = 1) AS tob_ask_size,

        -- Cumulative depth within 5 bps of mid
        sumIf(size,
              side = 'bid'
              AND price >= mid_price * (1 - 5.0 / 10000)
              AND NOT has_quality_issue)         AS depth_bid_5bps,
        sumIf(size,
              side = 'ask'
              AND price <= mid_price * (1 + 5.0 / 10000)
              AND NOT has_quality_issue)         AS depth_ask_5bps,

        -- Cumulative depth within 10 bps of mid
        sumIf(size,
              side = 'bid'
              AND price >= mid_price * (1 - 10.0 / 10000)
              AND NOT has_quality_issue)         AS depth_bid_10bps,
        sumIf(size,
              side = 'ask'
              AND price <= mid_price * (1 + 10.0 / 10000)
              AND NOT has_quality_issue)         AS depth_ask_10bps

    FROM {{ ref('stg_order_book') }}
    GROUP BY symbol, minute_bucket, snap_date, timestamp, mid_price, weighted_mid, book_imbalance
)

SELECT
    symbol,
    minute_bucket,
    snap_date,

    -- Pricing
    avg(mid_price)          AS avg_mid_price,
    avg(weighted_mid)       AS avg_weighted_mid,
    avg(bbo_spread_bps)     AS avg_bbo_spread_bps,
    median(bbo_spread_bps)  AS median_bbo_spread_bps,
    quantile(0.95)(bbo_spread_bps) AS p95_bbo_spread_bps,

    -- Top-of-book
    avg(tob_bid_size)        AS avg_tob_bid_size,
    avg(tob_ask_size)        AS avg_tob_ask_size,

    -- Depth at 5 bps
    avg(depth_bid_5bps)      AS avg_depth_bid_5bps,
    avg(depth_ask_5bps)      AS avg_depth_ask_5bps,
    round(
        avg(depth_bid_5bps) / nullIf(avg(depth_bid_5bps) + avg(depth_ask_5bps), 0), 4
    )                        AS depth_imbalance_5bps,  -- >0.5 = more bid-side depth

    -- Depth at 10 bps
    avg(depth_bid_10bps)     AS avg_depth_bid_10bps,
    avg(depth_ask_10bps)     AS avg_depth_ask_10bps,
    round(
        avg(depth_bid_10bps) / nullIf(avg(depth_bid_10bps) + avg(depth_ask_10bps), 0), 4
    )                        AS depth_imbalance_10bps,

    -- Book imbalance signal (from pre-computed field)
    avg(book_imbalance)      AS avg_book_imbalance,
    quantile(0.25)(book_imbalance) AS p25_book_imbalance,
    quantile(0.75)(book_imbalance) AS p75_book_imbalance,

    count()                  AS snapshot_count

FROM per_snapshot_stats
GROUP BY symbol, minute_bucket, snap_date
