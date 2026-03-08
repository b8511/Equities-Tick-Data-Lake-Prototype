/*
    Custom dbt test: no duplicate (symbol, timestamp) rows in stg_trades.
    A double-load caused by re-running scripts/load_data.py without truncating
    the source table would produce duplicate ticks. Any duplicates returned
    here indicate an idempotency failure in the ingestion pipeline.
*/

SELECT
    symbol,
    timestamp,
    count() AS row_count
FROM {{ ref('stg_trades') }}
GROUP BY symbol, timestamp
HAVING count() > 1
