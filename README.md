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

### Prerequisites
- Docker & Docker Compose
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (package manager)

### One-command pipeline

```bash
make all
```

This runs the full pipeline:
1. `make up` — starts ClickHouse + Grafana + Kestra containers
2. `make sync` — installs Python dependencies via `uv sync`
3. `make generate` — creates ~50M rows of synthetic tick data
4. `make load` — bulk-loads CSVs into ClickHouse
5. `make dbt-run` — builds all dbt models (staging → intermediate → marts)
6. `make quality` — runs data quality checks, logs issues
7. `make dbt-test` — validates schema + custom tests

To also orchestrate via Kestra:
```bash
make kestra-deploy   # push flows to Kestra's API (Kestra must be running)
```
Then trigger the pipeline from the Kestra UI at http://localhost:8080.

### Step by step

```bash
# 1. Install dependencies
uv sync

# 2. Start infrastructure
make up

# 3. Generate data (takes ~5-10 min)
make generate

# 4. Load into ClickHouse
make load

# 5. Build dbt models
make dbt-run

# 6. Run quality checks
make quality

# 7. Run dbt tests
make dbt-test
```

### Access points
| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin |
| Kestra UI | http://localhost:8080 | none (auth disabled) |
| ClickHouse HTTP | http://localhost:8123 | default / (empty) |
| ClickHouse Native | localhost:9000 | default / (empty) |

## Data Model

### Raw tables (ClickHouse)

**`trades`** — individual trade executions
| Column | Type | Description |
|--------|------|-------------|
| symbol | LowCardinality(String) | Ticker symbol |
| timestamp | DateTime64(6, 'UTC') | Microsecond precision |
| trade_price | Float64 | Execution price |
| trade_size | UInt32 | Shares traded |
| exchange | LowCardinality(String) | NYSE, NASDAQ, etc. |
| trade_condition | LowCardinality(String) | Regular, extended hours, etc. |
| data_quality_flag | Enum8 | OK, PRICE_OUTLIER, STALE, etc. |

**`quotes`** — L1 bid/ask quotes
| Column | Type | Description |
|--------|------|-------------|
| symbol | LowCardinality(String) | Ticker symbol |
| timestamp | DateTime64(6, 'UTC') | Microsecond precision |
| bid_price / ask_price | Float64 | Best bid and ask |
| bid_size / ask_size | UInt32 | Depth at top of book |
| exchange | LowCardinality(String) | Reporting exchange |
| data_quality_flag | Enum8 | OK, CROSSED_SPREAD, STALE, etc. |

**`order_book_snapshots`** — L2 order book (10 bid + 10 ask price levels)
| Column | Type | Description |
|--------|------|-------------|
| symbol | LowCardinality(String) | Ticker symbol |
| timestamp | DateTime64(6, 'UTC') | Microsecond precision |
| bid_prices / ask_prices | Array(Float64) | 10 price levels; index 1 = best |
| bid_sizes / ask_sizes | Array(UInt32) | Volume at each level |
| mid_price | Float64 | (BBO bid + BBO ask) / 2 |
| weighted_mid | Float64 | Size-weighted mid across all levels |
| book_imbalance | Float32 | (sum_bid_vol − sum_ask_vol) / total_vol; range [−1, 1] |
| data_quality_flag | Enum8 | OK, CROSSED_BOOK, MISSING_LEVELS, STALE |

### dbt models

| Layer | Model | Description |
|-------|-------|-------------|
| Staging | `stg_trades` | Cleaned trades + computed notional |
| Staging | `stg_quotes` | Cleaned quotes + spread in bps |
| Staging | `stg_order_book` | L2 snapshots unpivoted to long format (one row per side+level) |
| Intermediate | `int_vwap` | Per-symbol per-minute VWAP + OHLC |
| Intermediate | `int_spread_analytics` | Spread stats (avg, median, p95) |
| Intermediate | `int_volume_profile` | 5-min intraday volume distribution |
| Intermediate | `int_order_book_depth` | Per-minute depth, imbalance, spread from L2 book |
| Mart | `mart_daily_summary` | Daily OHLCV + spread + quality metrics |
| Mart | `mart_data_quality_summary` | Aggregated quality issues |

## Data Quality

### Injected anomalies (synthetic data)
- **Crossed spreads** (0.1%): bid > ask — simulates exchange errors
- **Stale quotes** (0.2%): gaps > 5s — simulates feed disconnects
- **Price outliers** (0.05%): ±5-15% from fair value — simulates bad prints
- **Missing fields** (0.03%): zero sizes — simulates parsing failures

### Detection pipeline
The quality checker (`scripts/data_quality_check.py`) independently detects all
injected anomalies and logs them to `data_quality_issues` with severity levels.
Results are visualized in the **Data Quality Monitor** dashboard.

### dbt tests
- Schema tests: not_null, accepted_values on all critical columns
- Custom: no future timestamps, VWAP within 5% of close price

## What I'd Add With KDB

In a production hybrid deployment:
1. **KDB Tickerplant** → real-time feed capture (sub-μs latency)
2. **KDB RDB** → intraday in-memory analytics for trading desk
3. **Kafka bridge** → KDB publishes ticks to Kafka as side-channel
4. **ClickHouse** (this project) → consumes from Kafka, stores historical,
   serves SQL analytics to the broader organization
5. **Temporal joins** → KDB's `aj`/`wj` for execution quality analysis
   (trade-to-quote alignment) — cannot be replicated efficiently in ClickHouse

## Project Structure

```
bnp_prototype/
├── docker-compose.yml          # ClickHouse + Grafana + Kestra
├── Makefile                    # Pipeline commands
├── pyproject.toml              # Python dependencies (uv)
├── clickhouse/
│   └── init/
│       └── 01_schema.sql       # DDL: trades, quotes, order_book_snapshots, quality tables
├── datagen/
│   └── generate_ticks.py       # Synthetic data generator (~50M rows, L1 + L2)
├── scripts/
│   ├── load_data.py            # Bulk CSV → ClickHouse loader
│   └── data_quality_check.py   # Anomaly detection + logging
├── dbt_project/
│   ├── dbt_project.yml
│   ├── profiles.yml            # dev (localhost) + docker (container hostname) targets
│   ├── models/
│   │   ├── staging/            # stg_trades, stg_quotes, stg_order_book
│   │   ├── intermediate/       # int_vwap, int_spread, int_volume, int_order_book_depth
│   │   └── marts/              # mart_daily_summary, mart_quality
│   └── tests/                  # Custom SQL tests
├── kestra/
│   ├── Dockerfile              # Kestra + Python/uv/dbt baked in
│   └── flows/
│       ├── equity_tick_pipeline.yml         # Main DAG (manual trigger)
│       └── equity_tick_daily_schedule.yml   # Weekday 22:00 UTC schedule
├── grafana/
│   ├── provisioning/           # Auto-configured datasource + dashboards
│   └── dashboards/             # 3 JSON dashboard definitions
└── docs/
```

## License

MIT — built as a portfolio / interview demonstration project.
