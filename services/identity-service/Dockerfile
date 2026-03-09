FROM python:3.11-slim AS builder

WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
COPY celery_app /app/celery_app
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -e .

FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN useradd -m -u 10001 appuser
COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
