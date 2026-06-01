FROM python:3.11-slim

ENV HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    xvfb xauth libgtk-3-0 libxshmfence1 libxtst6 fonts-liberation fonts-noto-cjk \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    -r requirements.txt
# headed Chromium 跑淘宝绕反爬；所需系统库已在上面 apt 装齐（gtk/xvfb/cjk 字体）
RUN playwright install chromium

COPY app /app/app
COPY runbooks /app/runbooks
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

RUN mkdir -p /app/sessions /app/downloads /app/snapshots

EXPOSE 8009
# entrypoint.sh 后台起 Xvfb 虚拟显示 + exec uvicorn，让 headed Chromium 在无显示器容器里跑
# （淘宝抓取要 headed 绕反爬）。headless 跑的 runbook 在虚拟显示下照常 headless，无影响。
CMD ["/app/entrypoint.sh"]
