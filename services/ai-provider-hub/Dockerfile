FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir ".[dev]" 2>/dev/null || pip install --no-cache-dir .

COPY app /app/app
RUN mkdir -p /app/data

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
