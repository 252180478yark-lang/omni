FROM python:3.11-slim

ARG OMNI_BUILD_COMMIT=unknown
ARG OMNI_BUILD_SOURCE_FINGERPRINT=unknown
ENV OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT} \
    OMNI_BUILD_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT}

ENV HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

COPY app /app/app
RUN mkdir -p /app/data

EXPOSE 8008
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
