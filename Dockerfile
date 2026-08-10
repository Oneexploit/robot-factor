FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

RUN pip install --upgrade pip && \
    pip install . && \
    playwright install --with-deps chromium && \
    chmod -R a+rX /ms-playwright

RUN useradd --create-home --uid 10001 appuser && \
    mkdir -p /app/data/invoices && \
    chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn robot_factor.main:app --host 0.0.0.0 --port 8000"]
