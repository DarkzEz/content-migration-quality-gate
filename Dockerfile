FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

USER app:app
EXPOSE 8000
CMD ["uvicorn", "content_migration_gate.admin:app", "--host", "0.0.0.0", "--port", "8000"]
