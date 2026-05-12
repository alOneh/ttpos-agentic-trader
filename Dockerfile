FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY vendor/ ./vendor/
COPY src/ ./src/
COPY config/ ./config/

# Install the package + its dependencies (incl. the vendored tradingview_api
# wheel referenced from pyproject.toml). setuptools needs src/ on disk
# because pyproject.toml uses `packages.find` against that directory.
RUN pip install .

# data/ holds the SQLite DB; Dokploy mounts a persistent volume here.
RUN mkdir -p /app/data

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD python -m agentic_trader.observability.healthcheck

# Run as PID 1 so SIGTERM from Docker reaches the agent's signal handler
# (set up in live/main.py via loop.add_signal_handler).
CMD ["python", "-m", "agentic_trader.live.main"]
