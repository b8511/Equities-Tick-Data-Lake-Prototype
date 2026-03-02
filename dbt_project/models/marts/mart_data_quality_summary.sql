{{
    config(
        materialized='table',
        order_by='(issue_date, symbol, issue_type)',
        engine='MergeTree()'
    )
}}

/*
    Mart: Data Quality Summary
    Aggregated view of data quality issues by day, symbol, and type.
    Powers the Data Quality Monitor dashboard in Grafana.
*/

WITH trade_issues AS (
    SELECT
        trade_date AS issue_date,
        symbol,
        data_quality_flag AS issue_type,
        'trades' AS source_table,
        count() AS issue_count
    FROM {{ ref('stg_trades') }}
    WHERE has_quality_issue
    GROUP BY trade_date, symbol, data_quality_flag
),

quote_issues AS (
    SELECT
        quote_date AS issue_date,
        symbol,
        data_quality_flag AS issue_type,
        'quotes' AS source_table,
        count() AS issue_count
    FROM {{ ref('stg_quotes') }}
    WHERE has_quality_issue
    GROUP BY quote_date, symbol, data_quality_flag
)

SELECT * FROM trade_issues
UNION ALL
SELECT * FROM quote_issues
