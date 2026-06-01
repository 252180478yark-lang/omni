#!/bin/sh
# scout-agent 启动：先拉起虚拟显示（淘宝抓取要 headed 浏览器绕反爬），再 exec uvicorn。
# 不用 xvfb-run —— 它作为容器 PID1 不能可靠 exec 子命令（实测起了 Xvfb 但没起 uvicorn）。
# 这里显式后台跑 Xvfb + exec uvicorn（uvicorn 成 PID1，信号/回收干净）。
set -e

# docker restart 复用容器：上次的 X 锁/套接字会残留在可写层，但进程已死。
# 不清掉的话 Xvfb 起不来、而残留套接字又骗过就绪检测 → headed Chrome 报 "Missing X server"。
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
export DISPLAY=:99

# 等 Xvfb 真就绪：套接字在 + 进程活着（光看套接字会被残留文件骗到）
i=0
while [ "$i" -lt 50 ]; do
  if [ -e /tmp/.X11-unix/X99 ] && kill -0 "$XVFB_PID" 2>/dev/null; then
    break
  fi
  sleep 0.2
  i=$((i + 1))
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8009
