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
from app.mcp.tools import sop as _sop  # noqa: E402, F401  # W3a T10
from app.mcp.tools import scout as _scout  # noqa: E402, F401  # W3b T1+
from app.mcp.tools import general as _general  # noqa: E402, F401  # W3c T1+
from app.mcp.tools import feedback as _feedback  # noqa: E402, F401  # W4-A T2
from app.mcp.tools import agent_meta as _agent_meta  # noqa: E402, F401  # W4-A T3+
from app.mcp.tools import agent_extras as _agent_extras  # noqa: E402, F401  # W4-B 切片 5
from app.mcp.tools import pipeline as _pipeline  # noqa: E402, F401  # W4-B 切片 14.3 phase A
from app.mcp.tools import realman as _realman  # noqa: E402, F401  # realman 真实人物视频
from app.mcp.tools import bug_memory as _bug_memory  # noqa: E402, F401  # 2026-05-28 Phase A+/A++ bug 记忆库 + 客户端日志
from app.mcp.tools import competitor as _competitor  # noqa: E402, F401  # 2026-06-01 竞品调研（淘宝抓取 + 视觉拆解）
from app.mcp.tools import spend as _spend  # noqa: E402, F401  # 2026-06-02 阶段0 L0-2 月度成本总账查询
from app.mcp.tools import diagnose as _diagnose  # noqa: E402, F401  # 2026-06-02 §6.2 诊断官（可调用 + 提议生命周期）
from app.mcp.tools import platform_fetch as _platform_fetch  # noqa: E402, F401  # 2026-06-03 三平台实时取数底座（Mac→集成）
from app.mcp.tools import analytics as _analytics  # noqa: E402, F401  # 2026-06-03 综合经营分析 + 临时问数（§6 分析半）

# 单例：mount 与 lifespan 必须共用同一 ASGI 实例
# path="/" 使子应用内路由为 "/"，挂载到 /mcp 后完整路径即 /mcp
mcp_http_app = mcp.http_app(path="/")
