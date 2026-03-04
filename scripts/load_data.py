"""
Load generated CSV data into ClickHouse.
Streams data in chunks via clickhouse-connect to avoid OOM issues
with large files (60M+ rows).

Handles L2 order book snapshots: array columns (bid_prices, bid_sizes,
ask_prices, ask_sizes) are stored as JSON strings in CSV and parsed back
to Python lists before insert.

Usage:
    python scripts/load_data.py
"""

import csv
import json
import sys
from pathlib import Path

try:
    import clickhouse_connect
except ImportError:
    print("Install clickhouse-connect: pip install clickhouse-connect")
    sys.exit(1)

DATA_DIR = Path(__file__).parent.parent / "data"
CH_HOST = "localhost"
CH_PORT = 8123
CH_DB = "equity_market"
CH_PASSWORD = "clickhouse"
CHUNK_SIZE = 500_000  # rows per insert batch


# Columns in order_book_snapshots that contain JSON arrays in CSV
OB_ARRAY_COLUMNS = {"bid_prices", "bid_sizes", "ask_prices", "ask_sizes"}


def get_client():
    return clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, database=CH_DB, password=CH_PASSWORD
    )


def load_csv(client, table: str, csv_path: Path):
    """Stream a CSV into ClickHouse in chunks."""
    print(f"Loading {csv_path.name} into {CH_DB}.{table} ...")

    total_rows = sum(1 for _ in open(csv_path)) - 1  # exclude header
    print(f"  Rows to load: {total_rows:,}")

    is_ob = table == "order_book_snapshots"

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames

        chunk = []
        loaded = 0
        for row in reader:
            if is_ob:
                # Parse JSON array strings back to Python lists for array columns
                parsed = []
                for col in columns:
                    val = row[col]
                    if col in OB_ARRAY_COLUMNS:
                        parsed.append(json.loads(val))
                    else:
                        parsed.append(val)
                chunk.append(parsed)
            else:
                chunk.append(list(row.values()))

            if len(chunk) >= CHUNK_SIZE:
                client.insert(table, chunk, column_names=columns)
                loaded += len(chunk)
                print(f"  ... {loaded:,} / {total_rows:,} rows", end="\r")
                chunk = []

        # Final partial chunk
        if chunk:
            client.insert(table, chunk, column_names=columns)
            loaded += len(chunk)

    print(f"  Done ({loaded:,} rows loaded).          ")


def verify(client, table: str):
    """Print row count and compression stats."""
    count = client.command(f"SELECT count() FROM {CH_DB}.{table}")
    stats = client.query(
        f"SELECT "
        f"formatReadableSize(sum(data_compressed_bytes)) AS compressed, "
        f"formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed, "
        f"round(sum(data_uncompressed_bytes) / sum(data_compressed_bytes), 1) AS ratio "
        f"FROM system.columns WHERE database='{CH_DB}' AND table='{table}'"
    )
    row = stats.result_rows[0]
    print(f"  {table}: {count:,} rows | {row[0]} compressed / {row[1]} uncompressed (ratio {row[2]}x)")


def main():
    trades_csv = DATA_DIR / "trades.csv"
    quotes_csv = DATA_DIR / "quotes.csv"
    ob_csv     = DATA_DIR / "order_book_snapshots.csv"

    for p in [trades_csv, quotes_csv, ob_csv]:
        if not p.exists():
            print(f"ERROR: {p} not found. Run datagen/generate_ticks.py first.")
            sys.exit(1)

    client = get_client()

    load_csv(client, "trades", trades_csv)
    load_csv(client, "quotes", quotes_csv)
    load_csv(client, "order_book_snapshots", ob_csv)

    print("\nVerification:")
    verify(client, "trades")
    verify(client, "quotes")
    verify(client, "order_book_snapshots")
    print("\nAll data loaded successfully.")


if __name__ == "__main__":
    main()
