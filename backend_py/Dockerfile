# Python 3.12 backend — FastAPI + LangGraph + Playwright (for PDF report)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=4000 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install uv for fast dep resolution.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy project metadata first for layer caching.
COPY pyproject.toml ./

# Install Python deps system-wide (no venv inside container).
RUN uv pip install --system .

# Install Chromium + system dependencies for Playwright. `--with-deps` runs
# apt-get under the hood to pull every shared library Chromium needs (nss,
# atk, cups, drm, dbus, gbm, pango, cairo, alsa, etc.) on debian-slim.
RUN playwright install --with-deps chromium

# Copy source.
COPY stackwealth/ stackwealth/

EXPOSE 4000

CMD ["uvicorn", "stackwealth.main:app", "--host", "0.0.0.0", "--port", "4000"]
