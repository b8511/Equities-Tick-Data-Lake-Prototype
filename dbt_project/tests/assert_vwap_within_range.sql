/*
    Custom dbt test: daily VWAP should be within a reasonable range
    of the close price (within 5%). If not, something is wrong
    with the aggregation or the underlying data.
*/

SELECT
    symbol,
    trade_date,
    day_vwap,
    close_price,
    abs(day_vwap - close_price) / close_price * 100 AS deviation_pct
FROM {{ ref('mart_daily_summary') }}
WHERE abs(day_vwap - close_price) / close_price > 0.05
