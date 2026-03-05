# Equities Tick Data Lake — ClickHouse

> A portfolio project demonstrating a production-style analytical data platform for
> cash equities market data, built with ClickHouse, dbt, and Grafana.
> Designed to showcase the skills required for a **KDB+ Developer** role at a Tier-1
> investment bank (specifically the BNP Paribas Global Markets Cash Equities team).

---

## Architecture

```
┌─────────────────────┐
│  Synthetic Data Gen │   Python / NumPy
│  (datagen/)         │   ~50M rows: 25 symbols × 30 trading days
└────────┬────────────┘   Realistic GBM prices, U-shaped volume, injected anomalies
         │
         ▼
┌─────────────────────┐
│     ClickHouse      │   MergeTree tables, partitioned by day
│  (equity_market DB) │   10-20× compression on tick data
│                     │   Schema: trades, quotes, order_book_snapshots,
│                     │           data_quality_issues
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│       dbt           │   7 models: staging → intermediate → marts
│  (dbt_project/)     │   VWAP, spread analytics, volume profile,
│                     │   L2 order book depth, daily summary
│                     │   Schema tests + 3 custom data quality tests
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Data Quality       │   Standalone Python checker
│  (scripts/)         │   Crossed spreads, stale quotes, price outliers, null fields
│                     │   Results → data_quality_issues table
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│      Kestra         │   Workflow orchestration (http://localhost:8080)
│  (kestra/)          │   YAML-defined DAG: generate → load → dbt_run →
│                     │     ┌─ quality_checks (parallel)
│                     │     └─ dbt_test       (parallel)
│                     │   Weekday schedule trigger (22:00 UTC)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│      Grafana        │   3 provisioned dashboards:
│  (grafana/)         │   • Market Overview (VWAP, volume, spread heatmap)
│                     │   • Data Quality Monitor (issues, severity, quality %)
│                     │   • Symbol Deep Dive (tick chart, OHLC, distribution)
└─────────────────────┘
```

## Why ClickHouse (not KDB)?

| Dimension | KDB+/q | ClickHouse |
|-----------|--------|------------|
| **Best at** | Real-time intraday (sub-ms in-memory) | Historical analytics (months/years) |
| **Query language** | q (niche, ~5K global practitioners) | SQL (universal) |
| **License** | $50-150K/core/year | Apache 2.0 (free) |
| **Scaling** | Vertical (manual sharding) | Horizontal (native distributed) |
| **Compression** | 2-5× | 10-20× on tick data |
| **Temporal joins** | First-class (`aj`, `wj`) | Limited `ASOF JOIN` |

**The hybrid thesis:** KDB owns the real-time hot path. ClickHouse extends reach to
the 90% of users (analysts, risk, compliance) who need SQL access to historical tick
data without learning q — at 1/10th the storage cost.

This project demonstrates the **ClickHouse side** of that architecture: the
analytical data lake that would sit alongside KDB's tickerplant in production.

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
