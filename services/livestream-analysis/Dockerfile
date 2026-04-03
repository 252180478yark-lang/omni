FROM python:3.11-slim

ENV HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    fastapi uvicorn[standard] pydantic pydantic-settings python-multipart \
    requests openpyxl python-dotenv psycopg2-binary httpx

COPY app /app/app
RUN mkdir -p /app/data/livestream-analysis

EXPOSE 8007
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
