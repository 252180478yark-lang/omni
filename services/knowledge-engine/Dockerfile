FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir ".[dev,harvester]" 2>/dev/null || pip install --no-cache-dir ".[harvester]"

# Install Playwright Chromium + all system deps.
# Retry loop with --fix-missing to handle flaky 502 mirrors.
RUN apt-get update && \
    for i in 1 2 3 4 5; do \
      apt-get install -f -y --fix-missing 2>/dev/null; \
      playwright install-deps chromium && break; \
      echo ">>> Attempt $i failed, retrying in 10s..."; \
      sleep 10; \
      apt-get update --fix-missing; \
    done && \
    playwright install chromium && \
    apt-get update && apt-get install -y --no-install-recommends libcups2 && \
    rm -rf /var/lib/apt/lists/*

COPY app /app/app
RUN mkdir -p /app/data

EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
