/*
    Custom dbt test: assert no quote timestamps are in the future.
*/

SELECT
    symbol,
    timestamp,
    bid_price,
    ask_price
FROM {{ ref('stg_quotes') }}
WHERE timestamp > now()
