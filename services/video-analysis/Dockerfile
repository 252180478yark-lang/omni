FROM python:3.11-slim

ARG OMNI_BUILD_COMMIT=unknown
ARG OMNI_BUILD_SOURCE_FINGERPRINT=unknown
ENV OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT} \
    OMNI_BUILD_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT}

ENV HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir --retries 5 --timeout 60 -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    fastapi uvicorn[standard] pydantic pydantic-settings python-multipart httpx \
    google-generativeai matplotlib psycopg2-binary PySocks \
    opencv-python-headless scenedetect[opencv] scipy librosa faster-whisper

COPY app /app/app
RUN mkdir -p /app/data/video-analysis

EXPOSE 8006
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
