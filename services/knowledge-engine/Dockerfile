FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir ".[dev,harvester]" 2>/dev/null || pip install --no-cache-dir ".[harvester]"

# Install Playwright Chromium + system deps (with retry for flaky mirrors)
RUN for i in 1 2 3; do \
      apt-get update \
      && playwright install-deps chromium \
      && break || sleep 5; \
    done \
    && rm -rf /var/lib/apt/lists/*
RUN playwright install chromium

COPY app /app/app
RUN mkdir -p /app/data

EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
