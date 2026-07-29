FROM python:3.11-slim

ARG OMNI_BUILD_COMMIT=unknown
ARG OMNI_BUILD_SOURCE_FINGERPRINT=unknown
ENV OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT} \
    OMNI_BUILD_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT} \
    OMNI_BAKED_SOURCE_COMMIT=${OMNI_BUILD_COMMIT} \
    OMNI_BAKED_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT}

WORKDIR /app

# System deps for PyMuPDF and the P0 video QA/composition path.  P0 uses
# ffprobe to establish immutable media facts and ffmpeg to burn the approved
# subtitle timeline; keeping both in the KE image makes that path reproducible
# instead of depending on an operator workstation.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libmupdf-dev \
    fonts-noto-cjk \
    poppler-utils \
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
COPY config /app/config
COPY scripts /app/scripts
RUN mkdir -p /app/data

EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
