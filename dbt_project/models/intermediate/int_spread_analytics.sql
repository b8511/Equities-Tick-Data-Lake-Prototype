{{
    config(
        materialized='table',
        order_by='(symbol, minute_bucket)',
        engine='MergeTree()'
    )
}}

/*
    Intermediate: Spread Analytics
    Per-symbol, per-minute spread statistics.
    Spread is one of the key market quality indicators that BNP's
    Cash Equities desk monitors continuously.
*/

SELECT
    symbol,
    toStartOfMinute(timestamp) AS minute_bucket,
    quote_date,
    avg(spread_bps) AS avg_spread_bps,
    median(spread_bps) AS median_spread_bps,
    quantile(0.95)(spread_bps) AS p95_spread_bps,
    min(spread_bps) AS min_spread_bps,
    max(spread_bps) AS max_spread_bps,
    avg(bid_size + ask_size) AS avg_depth,
    count() AS quote_count,
    countIf(has_quality_issue) AS quality_issue_count
FROM {{ ref('stg_quotes') }}
GROUP BY symbol, minute_bucket, quote_date
