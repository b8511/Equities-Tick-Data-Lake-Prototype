/*
    Custom dbt test: assert no trade timestamps are in the future.
    A common data quality invariant for market data.
*/

SELECT
    symbol,
    timestamp,
    trade_price
FROM {{ ref('stg_trades') }}
WHERE timestamp > now()
