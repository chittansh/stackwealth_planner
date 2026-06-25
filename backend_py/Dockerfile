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

# LibreOffice (Calc only) + Python-UNO bridge — the CFP Excel engine drives a
# headless LibreOffice via UNO to recalculate the firm's formulas. NOTE: plain
# `soffice --convert-to xlsx` does NOT recalc on Linux LibreOffice 25.2 (it
# trusts cached values), so we MUST use UNO (officehelper.bootstrap +
# calculateAll). python3-uno provides uno.py/unohelper.py; officehelper.py ships
# under /usr/lib/libreoffice/program. Both dirs are added to PYTHONPATH by the
# recalc module at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc python3-uno \
    && rm -rf /var/lib/apt/lists/*

# Copy source (includes stackwealth/excel_engine/master/cfp_master.xlsx).
COPY stackwealth/ stackwealth/

EXPOSE 4000

CMD ["uvicorn", "stackwealth.main:app", "--host", "0.0.0.0", "--port", "4000"]
