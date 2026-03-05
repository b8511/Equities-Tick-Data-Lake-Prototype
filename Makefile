.PHONY: up down sync generate load quality dbt-run dbt-test dbt-docs kestra-deploy kestra-ui all clean

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
# Kestra orchestration
# ---------------------------------------------------------------------------
# Deploy (or re-deploy) flows to Kestra via its REST API.
# Kestra must be running: make up
kestra-deploy:
	@echo "Deploying flows to Kestra ..."
	@for f in kestra/flows/*.yml; do \
		echo "  deploying $$f"; \
		curl -s -o /dev/null -w "  $$f → HTTP %{http_code}\n" \
		  -X POST http://localhost:8080/api/v1/flows/import \
		  -H "Content-Type: multipart/form-data" \
		  -F "fileUpload=@$$f"; \
	done
	@echo "Done. Open http://localhost:8080 to view flows."

kestra-ui:
	@echo "Kestra UI → http://localhost:8080"
	@open http://localhost:8080 2>/dev/null || xdg-open http://localhost:8080 2>/dev/null || true

# ---------------------------------------------------------------------------
# Full pipeline (manual / CI mode — bypasses Kestra)
# ---------------------------------------------------------------------------
all: up sync generate load dbt-run quality dbt-test
	@echo ""
	@echo "=== Pipeline complete ==="
	@echo "  Grafana:  http://localhost:3000  (admin/admin)"
	@echo "  Kestra:   http://localhost:8080"
	@echo "  ClickHouse: http://localhost:8123"
	@echo "  Run 'make kestra-deploy' to load flows into Kestra."
	@echo ""

clean:
	rm -rf data/*.csv
	docker compose down -v
