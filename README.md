# Equities Tick Data Lake — ClickHouse

A portfolio project built with ClickHouse, dbt, and Grafana. It models a historical tick data platform of the kind that would sit alongside a KDB+ tickerplant in a cash equities stack — built as prep for a KDB+ Developer role at BNP Paribas Global Markets.

---

## How it works

Synthetic tick data (~50M rows, 25 symbols, 30 trading days) is generated in Python and loaded into ClickHouse. dbt transforms the raw data through staging, intermediate, and mart layers. A quality check script detects anomalies and logs them. Kestra orchestrates the whole thing on a daily schedule. Grafana visualises the results.

```
datagen → ClickHouse → dbt → quality checks → Grafana
                                ↑
                             Kestra
```

## Why ClickHouse instead of KDB?

KDB is the right tool for real-time intraday analytics — sub-millisecond latency, in-memory, first-class temporal joins. But it's expensive (~$50-150K/core/year) and q has a steep learning curve. Most people at a bank (analysts, risk, compliance) just want SQL.

ClickHouse fills that gap: free, SQL-native, excellent compression on tick data (10-20×), and fast enough for historical queries across months of data. The idea is KDB handles the hot path, ClickHouse handles the rest.

## Quick Start

**Requirements:** Docker, Docker Compose, Python 3.10+, [uv](https://docs.astral.sh/uv/)

```bash
make all
```

That's it. It runs the full pipeline: start containers → generate data → load → dbt → quality checks → dbt tests.

To run steps individually:

```bash
uv sync          # install dependencies
make up          # start ClickHouse, Grafana, Kestra
make generate    # generate tick data (~5-10 min)
make load        # load CSVs into ClickHouse
make dbt-run     # build dbt models
make quality     # run quality checks
make dbt-test    # run dbt tests
```

To use Kestra for orchestration, start it with `make up` then run `make kestra-deploy` to push the flows. Trigger from http://localhost:8080.

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin |
| Kestra | http://localhost:8080 | — |
| ClickHouse HTTP | http://localhost:8123 | default / (empty) |
| ClickHouse Native | localhost:9000 | default / (empty) |

## Data Model

### ClickHouse tables

**`trades`** — one row per trade execution

| Column | Type |
|--------|------|
| symbol | LowCardinality(String) |
| timestamp | DateTime64(6, 'UTC') |
| trade_price | Float64 |
| trade_size | UInt32 |
| exchange | LowCardinality(String) |
| trade_condition | LowCardinality(String) |
| data_quality_flag | Enum8 |

**`quotes`** — L1 bid/ask

| Column | Type |
|--------|------|
| symbol | LowCardinality(String) |
| timestamp | DateTime64(6, 'UTC') |
| bid_price / ask_price | Float64 |
| bid_size / ask_size | UInt32 |
| exchange | LowCardinality(String) |
| data_quality_flag | Enum8 |

**`order_book_snapshots`** — L2 book (10 levels each side)

| Column | Type |
|--------|------|
| symbol | LowCardinality(String) |
| timestamp | DateTime64(6, 'UTC') |
| bid_prices / ask_prices | Array(Float64) |
| bid_sizes / ask_sizes | Array(UInt32) |
| mid_price | Float64 |
| weighted_mid | Float64 |
| book_imbalance | Float32 |
| data_quality_flag | Enum8 |

### dbt models

| Layer | Model | What it does |
|-------|-------|-------------|
| Staging | `stg_trades` | cleans trades, adds notional |
| Staging | `stg_quotes` | cleans quotes, adds spread in bps |
| Staging | `stg_order_book` | unpivots L2 snapshots to long format |
| Intermediate | `int_vwap` | per-symbol per-minute VWAP + OHLC |
| Intermediate | `int_spread_analytics` | avg / median / p95 spread |
| Intermediate | `int_volume_profile` | 5-min intraday volume buckets |
| Intermediate | `int_order_book_depth` | per-minute depth, imbalance, spread |
| Mart | `mart_daily_summary` | daily OHLCV + spread + quality % |
| Mart | `mart_data_quality_summary` | rolled-up quality issue counts |

## Data Quality

The synthetic data has intentional anomalies injected:
- crossed spreads (0.1%) — bid > ask
- stale quotes (0.2%) — gaps > 5s
- price outliers (0.05%) — ±5-15% from fair value
- missing fields (0.03%) — zero sizes

`scripts/data_quality_check.py` detects all of these and writes them to the `data_quality_issues` table. The Grafana Data Quality dashboard visualises the results.

dbt tests cover: not_null / accepted_values on key columns, no future timestamps, and VWAP within 5% of close price.

## What I'd add with KDB in the stack

If this were a real hybrid deployment, KDB would sit in front:

1. **KDB tickerplant** — captures the feed in real time
2. **KDB RDB** — in-memory intraday analytics for the trading desk
3. **Kafka bridge** — KDB publishes ticks as a side-channel
4. **ClickHouse** (this project) — consumes from Kafka, stores historical data, serves SQL to analysts and risk
5. **Temporal joins** — `aj`/`wj` in KDB for trade-to-quote alignment; ClickHouse's `ASOF JOIN` doesn't quite get there

## Project Structure

```
bnp_prototype/
├── docker-compose.yml
├── Makefile
├── pyproject.toml
├── clickhouse/init/01_schema.sql     # table DDL
├── datagen/generate_ticks.py         # synthetic data generator
├── scripts/
│   ├── load_data.py                  # CSV → ClickHouse
│   └── data_quality_check.py         # anomaly detection
├── dbt_project/
│   ├── models/staging/
│   ├── models/intermediate/
│   ├── models/marts/
│   └── tests/
├── kestra/flows/
│   ├── equity_tick_pipeline.yml      # manual trigger
│   └── equity_tick_daily_schedule.yml
└── grafana/
    ├── provisioning/
    └── dashboards/
```