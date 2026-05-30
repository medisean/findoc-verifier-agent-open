FROM python:3.11-slim AS runtime

ARG INSTALL_MINERU=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    UVICORN_WORKERS=1 \
    ARTIFACT_ROOT=/data/runs \
    TASK_STORE_PATH=/data/runs/tasks.sqlite3 \
    MINERU_CLI=mineru \
    MINERU_MAX_CONCURRENCY=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md uv.lock ./
COPY app ./app

RUN python -m pip install --upgrade pip \
    && if [ "$INSTALL_MINERU" = "true" ]; then \
        python -m pip install ".[mineru]"; \
    else \
        python -m pip install .; \
    fi

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/runs \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${UVICORN_WORKERS:-1}"]
