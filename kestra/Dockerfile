# ---------------------------------------------------------------------------
# Kestra image extended with Python, uv, and project dependencies.
#
# Why a custom image?
#   Kestra's shell/process task runner executes commands directly in the
#   container.  The project pipeline requires Python 3, uv, dbt-clickhouse,
#   clickhouse-connect, and numpy — none of which ship in the base Kestra
#   image.  Rather than installing them at runtime on every flow run, we
#   bake them in here so task startup is instant.
# ---------------------------------------------------------------------------
FROM kestra/kestra:latest-full

USER root

# ---- System dependencies --------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- uv (fast Python package manager) ------------------------------------
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# ---- Isolated virtual environment ----------------------------------------
# Using a fixed path so the venv is predictable for all flow task commands.
RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ---- Project Python dependencies -----------------------------------------
# Mirrors pyproject.toml [dependencies] so the installed set is consistent.
RUN uv pip install \
        "numpy>=1.24" \
        "clickhouse-connect>=0.7" \
        "dbt-core>=1.7" \
        "dbt-clickhouse>=1.7"

# Return to the default kestra user for runtime
# (keep root only for the package installation above)
USER kestra
