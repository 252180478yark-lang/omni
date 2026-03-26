FROM python:3.11-slim

ENV HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    fastapi uvicorn[standard] pydantic pydantic-settings python-multipart httpx \
    google-generativeai matplotlib \
    opencv-python-headless librosa faster-whisper

COPY app /app/app
RUN mkdir -p /app/data/video-analysis

EXPOSE 8006
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
