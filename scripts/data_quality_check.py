"""
Data Quality Checker
====================
Standalone script that scans trades and quotes tables for anomalies
and logs results into equity_market.data_quality_issues.

Checks:
  1. Crossed spreads (bid > ask)
  2. Stale quotes (gap > 5s during market hours for same symbol)
  3. Price outliers (|price - rolling_mean| > 3σ)
  4. Null / zero fields in required columns
  5. Summary statistics

Usage:
    python scripts/data_quality_check.py
"""

import sys
from datetime import datetime, timezone

try:
    import clickhouse_connect
except ImportError:
    print("Install clickhouse-connect: pip install clickhouse-connect")
    sys.exit(1)


CH_HOST = "localhost"
CH_PORT = 8123
CH_DB = "equity_market"
CH_PASSWORD = "clickhouse"


def get_client():
    return clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, database=CH_DB, password=CH_PASSWORD)


def check_crossed_spreads(client):
    """Find quotes where bid > ask (already flagged during generation, but verify independently)."""
    print("\n[1/5] Checking crossed spreads ...")
    query = """
        INSERT INTO data_quality_issues
            (source_table, symbol, event_time, issue_type, severity, details)
        SELECT
            'quotes',
            symbol,
            timestamp,
            'CROSSED_SPREAD',
            'CRITICAL',
            concat('bid=', toString(bid_price), ' ask=', toString(ask_price),
                   ' spread=', toString(round(bid_price - ask_price, 4)))
        FROM quotes
        WHERE bid_price > ask_price
          AND (symbol, timestamp) NOT IN (
              SELECT symbol, event_time FROM data_quality_issues
              WHERE issue_type = 'CROSSED_SPREAD'
          )
    """
    client.command(query)
    count = client.command(
        "SELECT count() FROM data_quality_issues WHERE issue_type = 'CROSSED_SPREAD'"
    )
    print(f"    Found {count:,} crossed spread events")


def check_stale_quotes(client):
    """Find gaps > 5 seconds between consecutive quotes for the same symbol during market hours."""
    print("\n[2/5] Checking stale quotes (gap > 5s) ...")
    query = """
        INSERT INTO data_quality_issues
            (source_table, symbol, event_time, issue_type, severity, details)
        SELECT
            'quotes',
            symbol,
            timestamp,
            'STALE_QUOTE',
            'WARNING',
            concat('gap_seconds=', toString(round(gap_s, 2)))
        FROM (
            SELECT
                symbol,
                timestamp,
                dateDiff('millisecond',
                    lagInFrame(timestamp) OVER (PARTITION BY symbol ORDER BY timestamp),
                    timestamp
                ) / 1000.0 AS gap_s
            FROM quotes
            WHERE toHour(timestamp) >= 14 AND toHour(timestamp) < 21
        )
        WHERE gap_s > 5
          AND (symbol, timestamp) NOT IN (
              SELECT symbol, event_time FROM data_quality_issues
              WHERE issue_type = 'STALE_QUOTE'
          )
    """
    client.command(query)
    count = client.command(
        "SELECT count() FROM data_quality_issues WHERE issue_type = 'STALE_QUOTE'"
    )
    print(f"    Found {count:,} stale quote events")


def check_price_outliers(client):
    """Find trades where price deviates > 3σ from a rolling 1000-tick mean."""
    print("\n[3/5] Checking price outliers (>3σ from rolling mean) ...")
    query = """
        INSERT INTO data_quality_issues
            (source_table, symbol, event_time, issue_type, severity, details)
        SELECT
            'trades',
            symbol,
            timestamp,
            'PRICE_OUTLIER',
            'CRITICAL',
            concat('price=', toString(trade_price),
                   ' rolling_mean=', toString(round(rm, 2)),
                   ' rolling_std=', toString(round(rs, 4)),
                   ' z_score=', toString(round(z, 2)))
        FROM (
            SELECT
                symbol,
                timestamp,
                trade_price,
                avg(trade_price) OVER w AS rm,
                stddevPop(trade_price) OVER w AS rs,
                CASE WHEN stddevPop(trade_price) OVER w > 0
                     THEN abs(trade_price - avg(trade_price) OVER w)
                          / stddevPop(trade_price) OVER w
                     ELSE 0
                END AS z
            FROM trades
            WINDOW w AS (PARTITION BY symbol ORDER BY timestamp
                         ROWS BETWEEN 999 PRECEDING AND CURRENT ROW)
        )
        WHERE z > 3 AND rs > 0
          AND (symbol, timestamp) NOT IN (
              SELECT symbol, event_time FROM data_quality_issues
              WHERE issue_type = 'PRICE_OUTLIER'
          )
    """
    client.command(query)
    count = client.command(
        "SELECT count() FROM data_quality_issues WHERE issue_type = 'PRICE_OUTLIER'"
    )
    print(f"    Found {count:,} price outlier events")


def check_null_fields(client):
    """Check for zero-size trades/quotes (proxy for missing fields)."""
    print("\n[4/5] Checking null/zero required fields ...")

    # Zero-size trades
    client.command("""
        INSERT INTO data_quality_issues
            (source_table, symbol, event_time, issue_type, severity, details)
        SELECT
            'trades', symbol, timestamp, 'MISSING_FIELD', 'WARNING',
            'trade_size is 0'
        FROM trades WHERE trade_size = 0
          AND (symbol, timestamp) NOT IN (
              SELECT symbol, event_time FROM data_quality_issues
              WHERE issue_type = 'MISSING_FIELD' AND source_table = 'trades'
          )
    """)

    # Zero-size quotes
    client.command("""
        INSERT INTO data_quality_issues
            (source_table, symbol, event_time, issue_type, severity, details)
        SELECT
            'quotes', symbol, timestamp, 'MISSING_FIELD', 'WARNING',
            concat('bid_size=', toString(bid_size), ' ask_size=', toString(ask_size))
        FROM quotes WHERE bid_size = 0 OR ask_size = 0
          AND (symbol, timestamp) NOT IN (
              SELECT symbol, event_time FROM data_quality_issues
              WHERE issue_type = 'MISSING_FIELD' AND source_table = 'quotes'
          )
    """)

    count = client.command(
        "SELECT count() FROM data_quality_issues WHERE issue_type = 'MISSING_FIELD'"
    )
    print(f"    Found {count:,} missing field events")


def print_summary(client):
    """Print overall quality summary."""
    print("\n[5/5] Quality Summary")
    print("=" * 60)

    summary = client.query("""
        SELECT
            issue_type,
            severity,
            count() AS cnt,
            count(DISTINCT symbol) AS symbols_affected,
            min(event_time) AS first_seen,
            max(event_time) AS last_seen
        FROM data_quality_issues
        GROUP BY issue_type, severity
        ORDER BY cnt DESC
    """)

    for row in summary.result_rows:
        issue_type, severity, cnt, syms, first, last = row
        print(f"  {severity:<10} {issue_type:<20} count={cnt:>8,}  "
              f"symbols={syms:>3}  range=[{first} .. {last}]")

    total = client.command("SELECT count() FROM data_quality_issues")
    trades_total = client.command("SELECT count() FROM trades")
    quotes_total = client.command("SELECT count() FROM quotes")
    all_rows = trades_total + quotes_total
    if all_rows > 0:
        print(f"\n  Total issues: {total:,} / {all_rows:,} "
              f"rows ({total / all_rows * 100:.3f}%)")
    else:
        print(f"\n  Total issues: {total:,} (no data rows in tables)")


def main():
    client = get_client()

    # Clear previous run (idempotent re-runs)
    client.command("TRUNCATE TABLE IF EXISTS data_quality_issues")

    check_crossed_spreads(client)
    check_stale_quotes(client)
    check_price_outliers(client)
    check_null_fields(client)
    print_summary(client)

    print("\nData quality check complete.")


if __name__ == "__main__":
    main()
