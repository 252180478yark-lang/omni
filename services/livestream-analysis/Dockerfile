FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] pydantic pydantic-settings python-multipart \
    requests openpyxl python-dotenv

COPY app /app/app
RUN mkdir -p /app/data/livestream-analysis

EXPOSE 8007
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
