"""omni MCP server 实例 + tool 注册（design doc §2.1 / §2.7）。

FastMCP 3.x 适配：
- 没有 `streamable_http_app` / `session_manager`，用 `http_app()` 返回的
  StarletteWithLifespan，其 `.lifespan` 属性即 ASGI lifespan callable。
- `http_app()` 每次新建实例，故必须单例缓存：mount 与 lifespan 使用同一实例。

main.py 集成：
    from app.mcp.server import mcp_http_app
    # FastAPI lifespan 内：
    async with mcp_http_app.lifespan(app):
        ... existing init ...
        yield
    # FastAPI 装配末尾：
    app.mount("/mcp", mcp_http_app)

Claude Code 端配置：
    {"omni": {"type": "http", "url": "http://localhost:8002/mcp"}}
"""
from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("omni")

# 触发 tool 注册副作用（每个模块用 @tool_with_audit(mcp, ...) 自注册）
# W1 stubs 不含 @tool 调用，T10-T12 实施时填实际函数
from app.mcp.tools import sku as _sku  # noqa: E402, F401
from app.mcp.tools import kb as _kb    # noqa: E402, F401
from app.mcp.tools import briefs as _briefs  # noqa: E402, F401
from app.mcp.tools import accounting as _accounting  # noqa: E402, F401
from app.mcp.tools import media as _media_tools  # noqa: E402, F401
from app.mcp.tools import cost_admin as _cost_admin  # noqa: E402, F401  # W3a T8

# 单例：mount 与 lifespan 必须共用同一 ASGI 实例
# path="/" 使子应用内路由为 "/"，挂载到 /mcp 后完整路径即 /mcp
mcp_http_app = mcp.http_app(path="/")
