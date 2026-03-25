"""Dev-only entry point: sets Windows ProactorEventLoop before uvicorn starts."""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8002
    reload = "--reload" in sys.argv
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, loop="asyncio", reload=reload)
