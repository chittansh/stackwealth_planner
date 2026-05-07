# Python 3.12 backend — FastAPI + LangGraph
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=4000

# Install uv for fast dep resolution.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy project metadata first for layer caching.
COPY pyproject.toml ./

# Install deps system-wide (no venv inside the container).
RUN uv pip install --system .

# Copy source.
COPY stackwealth/ stackwealth/

EXPOSE 4000

CMD ["uvicorn", "stackwealth.main:app", "--host", "0.0.0.0", "--port", "4000"]
