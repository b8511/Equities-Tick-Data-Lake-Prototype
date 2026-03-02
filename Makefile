.PHONY: up down sync generate load quality dbt-run dbt-test all clean

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
up:
	docker compose up -d
	@echo "ClickHouse: http://localhost:8123  |  Grafana: http://localhost:3000 (admin/admin)"

down:
	docker compose down

# ---------------------------------------------------------------------------
# Dependencies (uv)
# ---------------------------------------------------------------------------
sync:
	uv sync

# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------
generate:
	@echo "Generating synthetic tick data (~50M rows) ..."
	uv run python datagen/generate_ticks.py

load:
	@echo "Loading data into ClickHouse ..."
	uv run python scripts/load_data.py

quality:
	@echo "Running data quality checks ..."
	uv run python scripts/data_quality_check.py

# ---------------------------------------------------------------------------
# dbt
# ---------------------------------------------------------------------------
dbt-run:
	cd dbt_project && uv run dbt run --profiles-dir .

dbt-test:
	cd dbt_project && uv run dbt test --profiles-dir .

dbt-docs:
	cd dbt_project && uv run dbt docs generate --profiles-dir . && uv run dbt docs serve --profiles-dir .

# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
all: up sync generate load dbt-run quality dbt-test
	@echo ""
	@echo "=== Pipeline complete ==="
	@echo "  Grafana:  http://localhost:3000  (admin/admin)"
	@echo "  ClickHouse: http://localhost:8123"
	@echo ""

clean:
	rm -rf data/*.csv
	docker compose down -v
