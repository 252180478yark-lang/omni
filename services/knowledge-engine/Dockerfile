FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF and python-docx
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir ".[dev]" 2>/dev/null || pip install --no-cache-dir .

COPY app /app/app
RUN mkdir -p /app/data

EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
