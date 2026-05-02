"""Dev entry point: sets Windows ProactorEventLoop and runs uvicorn without
--reload so Playwright / asyncio.subprocess work everywhere.

scout-agent uses Playwright to drive Chromium for douyin/yuntu relogin,
which requires `asyncio.create_subprocess_exec` — only supported by
ProactorEventLoop on Windows. Default Selector loop raises NotImplementedError.

Usage: python _dev_server.py <port>
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8009
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, loop="asyncio")
