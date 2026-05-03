# Omni Agent 化升级 W1（闭环周）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 omni 在 Claude Code 里以 MCP server 形式跑起来，5 个查询类 tool 可被 Claude 直接调，每次调用记一行审计，doctor CLI 全绿。

**Architecture:** 在现有 `services/knowledge-engine` 进程内挂载 FastMCP HTTP 子应用（路径 `/mcp`），不新建微服务。`@tool_with_audit` 装饰器统一负责"前置写 pending → 调函数 → 后置写 result"。Human Gate 在 W1 仅留空骨架（5 个 tool 全为只读，不触发）。tool 内部通过 thin wrapper 复用 `services/ingestion`、`services/rag_chain`、`services/briefs` 现有函数，**RAG 主链路 0 改动**。

**Tech Stack:** Python 3.11+, FastAPI, FastMCP 2.13+, asyncpg + pgvector, PostgreSQL 16, pytest-asyncio。Windows 11 + PowerShell 5.1。knowledge-engine 端口 8002。

---

## 文件结构（W1 全量）

### 新增（17 个）

| 路径 | 行数估 | 责任 |
|---|---|---|
| `migrations/016_mcp_audit.sql` | ~50 | mcp schema + tool_calls + human_gates 表 |
| `services/knowledge-engine/config/tool_models.yaml` | ~30 | tool → 模型映射（W1 起步，仅含 `__default__`） |
| `services/knowledge-engine/app/mcp/__init__.py` | ~5 | 包标记，导出 `mcp` 实例 |
| `services/knowledge-engine/app/mcp/types.py` | ~30 | `ToolSuccess` / `ToolError` TypedDict |
| `services/knowledge-engine/app/mcp/model_config.py` | ~50 | yaml 加载 + `get_model_for_tool(tool_name)` 查询 |
| `services/knowledge-engine/app/mcp/prompt_constraints.py` | ~50 | `ANTI_AI_HUMAN_VOICE` 常量（W2 起开始用） |
| `services/knowledge-engine/app/mcp/human_gate.py` | ~60 | W1 stub：require_approval=True 时 raise NotImplementedError |
| `services/knowledge-engine/app/mcp/audit.py` | ~120 | `tool_with_audit` 装饰器：前置/后置写 mcp.tool_calls |
| `services/knowledge-engine/app/mcp/server.py` | ~30 | FastMCP 实例 + 注册所有 W1 tool |
| `services/knowledge-engine/app/mcp/doctor.py` | ~120 | 健康检查 CLI |
| `services/knowledge-engine/app/mcp/tools/__init__.py` | ~5 | 包标记 |
| `services/knowledge-engine/app/mcp/tools/sku.py` | ~80 | `list_skus`, `get_sku` |
| `services/knowledge-engine/app/mcp/tools/kb.py` | ~80 | `search_kb`, `list_kbs` |
| `services/knowledge-engine/app/mcp/tools/briefs.py` | ~50 | `list_briefs` |
| `services/knowledge-engine/app/services/ai_hub_client.py` | ~80 | thin httpx wrapper（W2 起开始用） |
| `services/knowledge-engine/tests/test_mcp_audit.py` | ~80 | audit 装饰器单测（hits dev DB） |
| `services/knowledge-engine/tests/test_mcp_tools.py` | ~120 | 5 个 tool 集成测试（hits dev DB） |
| `services/knowledge-engine/tests/test_mcp_config.py` | ~50 | model_config + types + prompt_constraints 单测 |

### 修改（3 个）

| 路径 | 改动 |
|---|---|
| `services/knowledge-engine/pyproject.toml` | 加 `fastmcp>=2.13.0` 依赖 |
| `services/knowledge-engine/app/main.py` | mount `/mcp` 子应用 + lifespan 合并 + 启动调 doctor |
| `E:\agent\omni\.claude\settings.local.json` | 加 `mcpServers.omni`（http://localhost:8002/mcp） |

---

## 任务

### 任务 1：MCP 审计 schema migration

**Files:**
- Create: `migrations/016_mcp_audit.sql`

- [ ] **Step 1：写 migration**

把 design doc §8 的 016 SQL 一字不差落地（复制下方）：

```sql
-- migrations/016_mcp_audit.sql
-- MCP Server 审计与 Human Gate 表（W1 起用）
CREATE SCHEMA IF NOT EXISTS mcp;

CREATE TABLE IF NOT EXISTS mcp.tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name TEXT NOT NULL,
    args JSONB NOT NULL,
    result JSONB,
    status TEXT NOT NULL,            -- pending|approved|rejected|completed|error
    require_approval BOOLEAN NOT NULL DEFAULT FALSE,
    duration_ms INT,
    error TEXT,
    user_rating TEXT,                -- good|bad|redo|null
    rating_note TEXT,
    model_used TEXT,                 -- 实际用的 provider/model
    tokens_input INT,
    tokens_output INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name_time
    ON mcp.tool_calls (tool_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_calls_pending
    ON mcp.tool_calls (status) WHERE status='pending';
CREATE INDEX IF NOT EXISTS idx_tool_calls_rating
    ON mcp.tool_calls (user_rating) WHERE user_rating IS NOT NULL;

CREATE TABLE IF NOT EXISTS mcp.human_gates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_call_id UUID REFERENCES mcp.tool_calls(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    decision TEXT,                   -- approved|rejected
    decision_note TEXT,
    decided_at TIMESTAMPTZ,
    timeout_seconds INT NOT NULL DEFAULT 3600,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_human_gates_pending
    ON mcp.human_gates (decision) WHERE decision IS NULL;
```

- [ ] **Step 2：dry-run 验证 SQL 合法**

```powershell
$env:DATABASE_URL = "postgresql://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
python E:\agent\omni\scripts\apply_migrations.py --only 016 --dry-run
```

Expected: `(dry-run) would execute 016_mcp_audit.sql (NNN bytes)`，无错误。

- [ ] **Step 3：真跑 migration**

```powershell
python E:\agent\omni\scripts\apply_migrations.py --only 016
```

Expected: `[OK] 016_mcp_audit.sql applied`

- [ ] **Step 4：验证表存在**

```powershell
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "\dt mcp.*"
```

Expected: 输出含 `mcp | tool_calls` 和 `mcp | human_gates` 两行。

```powershell
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "INSERT INTO mcp.tool_calls(tool_name, args, status) VALUES ('_smoke', '{}'::jsonb, 'completed') RETURNING id;"
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "DELETE FROM mcp.tool_calls WHERE tool_name = '_smoke';"
```

Expected: INSERT 返回一行 UUID；DELETE 报 `DELETE 1`。

- [ ] **Step 5：commit**

```powershell
git add migrations/016_mcp_audit.sql
git commit -m "feat(mcp): add mcp schema with tool_calls + human_gates tables (W1)"
```

---

### 任务 2：加 fastmcp 依赖

**Files:**
- Modify: `services/knowledge-engine/pyproject.toml`

- [ ] **Step 1：加依赖**

在 `pyproject.toml` 的 `[project] dependencies` 数组里 `pysrt>=1.1.2` 后插一行：

```toml
  # MCP server (Anthropic Model Context Protocol)
  "fastmcp>=2.13.0",
```

- [ ] **Step 2：装包（在 knowledge-engine 容器内）**

```powershell
docker exec omni-knowledge-engine pip install "fastmcp>=2.13.0"
```

Expected: 看到 `Successfully installed fastmcp-2.x.x mcp-1.x.x ...`

- [ ] **Step 3：导入冒烟测试**

```powershell
docker exec omni-knowledge-engine python -c "from fastmcp import FastMCP; m = FastMCP('smoke'); print('FastMCP OK', m.name)"
```

Expected: `FastMCP OK smoke`

- [ ] **Step 4：commit**

```powershell
git add services/knowledge-engine/pyproject.toml
git commit -m "feat(mcp): add fastmcp 2.13+ dependency (W1)"
```

---

### 任务 3：types.py — 工具返回类型

**Files:**
- Create: `services/knowledge-engine/app/mcp/__init__.py`
- Create: `services/knowledge-engine/app/mcp/types.py`
- Create: `services/knowledge-engine/tests/test_mcp_config.py`（占位文件，本任务先放一条 types 测试）

- [ ] **Step 1：写失败测试**

`tests/test_mcp_config.py`：

```python
"""单测：MCP 基础类型 / 模型配置 / prompt 常量。

不依赖 DB，纯模块测试。
"""
from app.mcp.types import ToolSuccess, ToolError


def test_tool_success_minimal():
    s: ToolSuccess = {"ok": True, "data": [1, 2, 3]}
    assert s["ok"] is True
    assert s["data"] == [1, 2, 3]


def test_tool_error_minimal():
    e: ToolError = {"ok": False, "error": "sku_not_found", "hint": "调 list_skus"}
    assert e["ok"] is False
    assert e["error"] == "sku_not_found"
    assert e["hint"] == "调 list_skus"
```

- [ ] **Step 2：跑测试，看它失败**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_config.py -v
```

Expected: FAIL，`ModuleNotFoundError: No module named 'app.mcp'`

- [ ] **Step 3：写最小实现**

`app/mcp/__init__.py`：

```python
"""MCP server 子模块。

提供 FastMCP 实例、tool 注册、审计装饰器、Human Gate、健康检查。
W1：仅启用 5 个查询类 tool；W2 起接入算账/编排/媒体生成。
"""
```

`app/mcp/types.py`：

```python
"""Tool 返回类型约定（design doc §2.3）。

所有 tool 必须返回 dict，含 `ok: bool`：
- 成功：`ok=True` + 业务字段
- 失败：`ok=False` + `error`（机器码）+ `hint`（给 LLM 的下一步建议）+ 可选 `note`（给人看的）
"""
from __future__ import annotations

from typing import Literal, TypedDict


class ToolSuccess(TypedDict, total=False):
    ok: Literal[True]
    # 业务字段由各 tool 自己加


class ToolError(TypedDict, total=False):
    ok: Literal[False]
    error: str   # 机器可读 code，例如 "sku_not_found"
    hint: str    # 给 LLM 的下一步建议
    note: str    # 给人看的补充（可选）
```

- [ ] **Step 4：跑测试，看它通过**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_config.py -v
```

Expected: 2 passed

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/__init__.py services/knowledge-engine/app/mcp/types.py services/knowledge-engine/tests/test_mcp_config.py
git commit -m "feat(mcp): add ToolSuccess/ToolError type contracts (W1)"
```

---

### 任务 4：tool_models.yaml + model_config 加载器

**Files:**
- Create: `services/knowledge-engine/config/tool_models.yaml`
- Create: `services/knowledge-engine/app/mcp/model_config.py`
- Modify: `services/knowledge-engine/tests/test_mcp_config.py`（追加 model_config 的测试）

- [ ] **Step 1：写 yaml（W1 起步）**

`services/knowledge-engine/config/tool_models.yaml`：

```yaml
# tool → 模型映射（design doc §2.5）
# W1：仅 __default__ 起作用（W1 五个 tool 都不调 LLM）
# W2 起按 tool 名增加覆盖
__default__:
  provider: anthropic
  model: claude-sonnet-4-6
  temperature: 0.3
```

- [ ] **Step 2：写失败测试**

在 `tests/test_mcp_config.py` 末尾追加：

```python
def test_model_config_default_lookup():
    from app.mcp.model_config import get_model_for_tool
    cfg = get_model_for_tool("any_unknown_tool")
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == "claude-sonnet-4-6"
    assert cfg["temperature"] == 0.3


def test_model_config_explicit_override():
    """加一个虚构条目验证按名查询生效。"""
    from app.mcp.model_config import _load_yaml, get_model_for_tool
    raw = _load_yaml()
    raw["_test_tool"] = {"provider": "x", "model": "y", "temperature": 0.0}
    # get_model_for_tool 内部也读同一份缓存，验证 override 命中
    cfg = get_model_for_tool("_test_tool", _override_yaml=raw)
    assert cfg["provider"] == "x"
    assert cfg["model"] == "y"
```

- [ ] **Step 3：跑测试，看失败**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_config.py -v
```

Expected: FAIL，`ModuleNotFoundError: app.mcp.model_config`

- [ ] **Step 4：写实现**

`app/mcp/model_config.py`：

```python
"""tool_models.yaml 加载 + 按 tool 名查模型配置（design doc §2.5）。

调用方式：
    from app.mcp.model_config import get_model_for_tool
    cfg = get_model_for_tool("compute_margin")
    # cfg = {"provider": "anthropic", "model": "claude-opus-4-7", "temperature": 0.0}
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # PyYAML; FastMCP 顺带带进来，未带则需 pip install pyyaml

CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "tool_models.yaml"
)


@lru_cache(maxsize=1)
def _load_yaml() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"__default__": {"provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0.3}}
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_model_for_tool(
    tool_name: str,
    *,
    _override_yaml: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 tool 名取模型配置；查不到 fallback 到 __default__。

    `_override_yaml` 仅供测试注入。
    """
    raw = _override_yaml if _override_yaml is not None else _load_yaml()
    if tool_name in raw:
        return dict(raw[tool_name])
    default = raw.get("__default__") or {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "temperature": 0.3,
    }
    return dict(default)
```

注意：如果 `pyyaml` 不在 fastmcp 依赖链里需自己加。先验证：

```powershell
docker exec omni-knowledge-engine python -c "import yaml; print(yaml.__version__)"
```

如果报 ModuleNotFoundError，则在 pyproject.toml 加 `"pyyaml>=6.0"` 并重装。

- [ ] **Step 5：跑测试，看通过**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_config.py -v
```

Expected: 4 passed

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/config/tool_models.yaml services/knowledge-engine/app/mcp/model_config.py services/knowledge-engine/tests/test_mcp_config.py
# 如果加了 pyyaml 依赖，把 pyproject.toml 也 add 进来
git commit -m "feat(mcp): add tool_models.yaml + get_model_for_tool loader (W1)"
```

---

### 任务 5：prompt_constraints.py — ANTI_AI_HUMAN_VOICE

**Files:**
- Create: `services/knowledge-engine/app/mcp/prompt_constraints.py`
- Modify: `services/knowledge-engine/tests/test_mcp_config.py`（追加常量内容测试）

- [ ] **Step 1：写失败测试**

在 `tests/test_mcp_config.py` 末尾追加：

```python
def test_anti_ai_human_voice_contains_three_pillars():
    """常量必须三块都齐：说人话 / 反幻觉 / 去 AI 化。"""
    from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE
    assert "说人话" in ANTI_AI_HUMAN_VOICE
    assert "反幻觉" in ANTI_AI_HUMAN_VOICE
    assert "去 AI 化" in ANTI_AI_HUMAN_VOICE


def test_anti_ai_human_voice_lists_specific_bans():
    """关键禁词样本必须出现，否则 prompt 失效。"""
    from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE
    for word in ["作为 AI", "希望对您有帮助", "综上", "以下是"]:
        assert word in ANTI_AI_HUMAN_VOICE, f"missing forbidden phrase: {word}"
```

- [ ] **Step 2：跑测试，看失败**

Expected: `ModuleNotFoundError: app.mcp.prompt_constraints`

- [ ] **Step 3：写实现**

`app/mcp/prompt_constraints.py`：

```python
"""全局写作风格强制约束（design doc §2.8 / feedback_writing_style.md）。

W1：仅建好常量，W2 起在所有生成类 tool 的 system prompt 头部拼这一段。
"""

ANTI_AI_HUMAN_VOICE = """\
【写作风格强制约束 — 不遵守视为输出错误】

说人话：
- 日常对话语气，像跟朋友说话
- 短句，1-2 句说清就停
- 关键信息顶到前面，不铺垫
- 用具体数字 / 例子 / 时间，不用抽象描述
- 用"咱""你""我"，不用"用户""贵公司"
- 不写"综上""值得注意""不难发现"等套话
- 不机械堆"首先/其次/最后"（除非用户明确要分点）
- 不用"诉求""赋能""抓手""底层逻辑""链路"等黑话

反幻觉：
- 只用提供的资料里有的信息
- 资料里没有 → 直接说"这块没找到"或"我没数据"
- 数字、价格、人名、时间 → 必须有出处
- 事实和推测分开：推测前加"我猜""可能""估计"
- 不夸大（禁用"惊人""巨大成功""革命性"，除非引用原话）

去 AI 化（这些一律删除）：
- "作为 AI / 作为助手 / 作为大模型"
- "我理解您的需求 / 我可以帮您"
- "以下是.../让我为您..."
- "希望对您有帮助 / 如有疑问随时问我"
- 无意义 emoji（除非用户明确要用）
- 无意义 markdown 标题堆叠
- 客套结尾（"以上就是..."、"祝您..."、"加油！"）
"""
```

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_config.py -v
```

Expected: 6 passed

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/prompt_constraints.py services/knowledge-engine/tests/test_mcp_config.py
git commit -m "feat(mcp): add ANTI_AI_HUMAN_VOICE prompt constraint constant (W1)"
```

---

### 任务 6：ai_hub_client.py — thin httpx wrapper

**Files:**
- Create: `services/knowledge-engine/app/services/ai_hub_client.py`
- Modify: `services/knowledge-engine/tests/test_mcp_config.py`（追加 import 冒烟）

> W1 不真调；W2 起 `compute_margin` 第一个用。本任务只验证模块能 import 且类签名稳定。

- [ ] **Step 1：写失败测试**

末尾追加：

```python
def test_ai_hub_client_importable():
    from app.services.ai_hub_client import AIHubClient
    c = AIHubClient(base_url="http://example.invalid")
    # 三个核心方法都存在
    assert callable(c.chat)
    assert callable(c.generate_image)
    assert callable(c.generate_video)
    assert c.base_url == "http://example.invalid"
```

- [ ] **Step 2：跑测试看失败**

Expected: `ModuleNotFoundError: app.services.ai_hub_client`

- [ ] **Step 3：写实现**

`app/services/ai_hub_client.py`：

```python
"""ai-hub HTTP 客户端 thin wrapper（design doc §2.6）。

调用 `services/ai-provider-hub`（http://ai-provider-hub:8001）的统一端点：
- POST /api/v1/ai/chat                  → chat()
- POST /api/v1/ai/images/generate       → generate_image()
- POST /api/v1/ai/videos/generate       → generate_video()
- GET  /api/v1/ai/videos/status/{id}    → wait_for_video()

W1 仅留接口；W2 起在 generate_brief / generate_image / generate_video tool 中
作为唯一入口使用，避免各 tool 重复写 httpx 调用模式。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class AIHubClient:
    def __init__(self, base_url: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = (base_url or settings.ai_provider_hub_url).rstrip("/")
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict],
        *,
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-6",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        enforce_human_voice: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        """统一 chat 入口。enforce_human_voice=True 时在 system 头拼 ANTI_AI_HUMAN_VOICE。"""
        if enforce_human_voice:
            from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE
            sys_idx = next((i for i, m in enumerate(messages) if m.get("role") == "system"), None)
            if sys_idx is None:
                messages = [{"role": "system", "content": ANTI_AI_HUMAN_VOICE}, *messages]
            else:
                messages = list(messages)
                messages[sys_idx] = {
                    **messages[sys_idx],
                    "content": ANTI_AI_HUMAN_VOICE + "\n\n" + (messages[sys_idx].get("content") or ""),
                }
        body = {
            "provider": provider,
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **(extra or {}),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/chat", json=body)
            r.raise_for_status()
            return r.json()

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "gpt-image-2",
        refs: list[str] | None = None,
        aspect: str | None = None,
        n: int = 1,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"prompt": prompt, "model": model, "n": n}
        if refs:
            body["reference_images"] = refs
        if aspect:
            body["aspect_ratio"] = aspect
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/images/generate", json=body)
            r.raise_for_status()
            return r.json()

    async def generate_video(
        self,
        prompt: str,
        *,
        model: str | None = None,
        refs: list[str] | None = None,
        duration_sec: int = 5,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"prompt": prompt, "duration": duration_sec}
        if model:
            body["model"] = model
        if refs:
            body["reference_images"] = refs
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/videos/generate", json=body)
            r.raise_for_status()
            return r.json()

    async def wait_for_video(self, task_id: str, *, max_seconds: int = 600, poll: float = 5.0) -> dict:
        import asyncio
        deadline = max_seconds
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            while deadline > 0:
                r = await cli.get(f"{self.base_url}/api/v1/ai/videos/status/{task_id}")
                r.raise_for_status()
                data = r.json()
                status = (data.get("data") or {}).get("status") or data.get("status")
                if status in {"succeeded", "failed", "completed", "error"}:
                    return data
                await asyncio.sleep(poll)
                deadline -= poll
            return {"status": "timeout", "task_id": task_id}
```

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_config.py -v
```

Expected: 7 passed

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/services/ai_hub_client.py services/knowledge-engine/tests/test_mcp_config.py
git commit -m "feat(mcp): add AIHubClient thin wrapper (W1 placeholder, W2 callers)"
```

---

### 任务 7：human_gate.py — W1 stub

**Files:**
- Create: `services/knowledge-engine/app/mcp/human_gate.py`
- Modify: `services/knowledge-engine/tests/test_mcp_config.py`

> W1 五个 tool 全是只读，require_approval=False，永远不触发 gate。
> 但 audit 装饰器要调它的接口；W1 给 stub，调到时 raise NotImplementedError 并附 TODO 提示。

- [ ] **Step 1：写失败测试**

末尾追加：

```python
import pytest


@pytest.mark.asyncio
async def test_human_gate_stub_raises_not_implemented():
    from app.mcp.human_gate import request_approval
    with pytest.raises(NotImplementedError) as exc_info:
        await request_approval(
            tool_call_id="00000000-0000-0000-0000-000000000000",
            summary="dry-run",
            timeout_seconds=3600,
        )
    # 错误信息必须提示 W2 才实现
    assert "W2" in str(exc_info.value) or "Human Gate" in str(exc_info.value)
```

- [ ] **Step 2：跑测试看失败**

Expected: `ModuleNotFoundError: app.mcp.human_gate`

- [ ] **Step 3：写 stub**

`app/mcp/human_gate.py`：

```python
"""Human Gate（design doc §5）。

W1：5 个 tool 全是只读，require_approval=False，本模块仅留接口骨架。
W2 起在算账/编排/媒体生成 tool 上启用：写入 mcp.human_gates 表 → 推 /inbox →
等批/驳/超时（默认 3600s）。

接口签名稳定（W2 改实现，不改签名）。
"""
from __future__ import annotations

from typing import TypedDict


class GateDecision(TypedDict):
    decision: str          # approved | rejected | timeout
    decision_note: str | None


async def request_approval(
    *,
    tool_call_id: str,
    summary: str,
    timeout_seconds: int = 3600,
) -> GateDecision:
    """W1 stub：调到时报错。W2 起真实现：写表 → 等待 → 返回决策。"""
    raise NotImplementedError(
        "Human Gate 在 W1 未实现。当前 5 个 tool 应全部 require_approval=False。"
        " W2 起在 compute_margin / run_sku_orch / generate_brief 等 tool 落地。"
    )
```

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_config.py -v
```

Expected: 8 passed（含新加的 async 一条）

> 如果 pytest-asyncio mode 不是 auto，需在 pyproject.toml 加 `[tool.pytest.ini_options] asyncio_mode = "auto"`。先 grep 确认：

```powershell
docker exec omni-knowledge-engine grep -E "asyncio_mode|pytest" pyproject.toml
```

如果没有这一段，加上后再跑测试。

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/human_gate.py services/knowledge-engine/tests/test_mcp_config.py
# 如改了 pyproject.toml asyncio_mode 也加进来
git commit -m "feat(mcp): add Human Gate stub (W1 raises, W2 implements)"
```

---

### 任务 8：audit.py — `tool_with_audit` 装饰器

**Files:**
- Create: `services/knowledge-engine/app/mcp/audit.py`
- Create: `services/knowledge-engine/tests/test_mcp_audit.py`

> 这是 MCP 底座最关键的一块。每次 tool 调用：开始时插 pending 行 → 跑函数 →
> 结束时 update result/duration/status。出错也要记。require_approval=True 时
> 在跑函数前调 human_gate（W1 不会触发）。

- [ ] **Step 1：写失败测试**

`tests/test_mcp_audit.py`：

```python
"""tool_with_audit 装饰器单测（hits dev DB）。

每条用例自插自删，避免互相干扰。
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastmcp import FastMCP

from app.database import init_pool, close_pool, get_pool
from app.mcp.audit import tool_with_audit


@pytest.fixture(scope="module", autouse=True)
async def _db():
    await init_pool()
    yield
    # 清理本测试新增的所有 _smoke_ 行
    pool = get_pool()
    await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name LIKE '_smoke_%'")
    await close_pool()


@pytest.fixture
def mcp():
    return FastMCP("test-omni")


async def test_audit_writes_completed_row_on_success(mcp):
    @tool_with_audit(mcp, require_approval=False)
    async def _smoke_ok(x: int) -> dict:
        """smoke tool"""
        return {"ok": True, "doubled": x * 2}

    result = await _smoke_ok(7)
    assert result == {"ok": True, "doubled": 14}

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT tool_name, status, args, result, error, duration_ms"
        " FROM mcp.tool_calls WHERE tool_name=$1 ORDER BY created_at DESC LIMIT 1",
        "_smoke_ok",
    )
    assert row is not None
    assert row["status"] == "completed"
    assert row["error"] is None
    assert row["duration_ms"] is not None and row["duration_ms"] >= 0
    assert json.loads(row["args"])["x"] == 7
    assert json.loads(row["result"])["doubled"] == 14


async def test_audit_writes_error_row_on_exception(mcp):
    @tool_with_audit(mcp, require_approval=False)
    async def _smoke_boom() -> dict:
        """raises"""
        raise RuntimeError("synthetic failure for test")

    # 装饰器把异常吞掉，转成 ToolError dict
    result = await _smoke_boom()
    assert result["ok"] is False
    assert "synthetic failure" in result["error"]

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT status, error FROM mcp.tool_calls"
        " WHERE tool_name='_smoke_boom' ORDER BY created_at DESC LIMIT 1",
    )
    assert row["status"] == "error"
    assert "synthetic failure" in row["error"]


async def test_audit_returns_tool_error_when_approval_required_in_w1(mcp):
    """W1 暂未实现 human_gate；require_approval=True 应 graceful 返回 ToolError，
    而不是 hard crash。"""

    @tool_with_audit(
        mcp,
        require_approval=True,
        summary_fn=lambda args: f"smoke gated {args}",
    )
    async def _smoke_gated() -> dict:
        return {"ok": True}

    result = await _smoke_gated()
    assert result["ok"] is False
    assert result["error"] in {"human_gate_unavailable", "not_implemented"}
```

- [ ] **Step 2：跑测试看失败**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_audit.py -v
```

Expected: `ModuleNotFoundError: app.mcp.audit`

- [ ] **Step 3：写实现**

`app/mcp/audit.py`：

```python
"""@tool_with_audit 装饰器（design doc §2.2）。

职责：
1. 审计：每次调用前插 mcp.tool_calls(status='pending')，结束后 update
   result/status/duration/error。
2. Human Gate（W2 起）：require_approval=True 时调 human_gate.request_approval；
   W1 当前为 stub，stub 抛出时 graceful 返回 `ToolError`，避免 LLM 拿到 500。

调用方式：
    from fastmcp import FastMCP
    from app.mcp.audit import tool_with_audit

    mcp = FastMCP("omni")

    @tool_with_audit(mcp, require_approval=False)
    async def list_skus(status: str | None = None) -> dict:
        ...

`tool_with_audit` 内部会调 `mcp.tool(...)` 把函数注册到 FastMCP。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from functools import wraps
from typing import Any, Awaitable, Callable

from fastmcp import FastMCP

from app.database import get_pool
from app.mcp import human_gate

logger = logging.getLogger(__name__)


def tool_with_audit(
    mcp: FastMCP,
    *,
    require_approval: bool = False,
    summary_fn: Callable[[dict], str] | None = None,
    timeout_seconds: int | None = None,
    **mcp_kwargs: Any,
) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[dict]]]:
    """把一个 async tool 函数包成"前置审计 → (gate) → 调用 → 后置审计"。

    Args:
        mcp: FastMCP 实例
        require_approval: 设 True 时在调函数前进 Human Gate（W1 stub 抛 NotImplementedError）
        summary_fn: 给人看的摘要生成函数（用于 /inbox 卡片）；W1 暂存表里
        timeout_seconds: Gate 等批超时（None = 默认 3600）
        **mcp_kwargs: 透传给 `mcp.tool(...)`（如 description override 等）
    """

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        tool_name = fn.__name__

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict:
            pool = get_pool()
            args_dict = _bind_args(fn, args, kwargs)
            tool_call_id = str(uuid.uuid4())
            start = time.perf_counter()

            await pool.execute(
                """
                INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval)
                VALUES ($1, $2, $3::jsonb, 'pending', $4)
                """,
                uuid.UUID(tool_call_id),
                tool_name,
                json.dumps(args_dict, ensure_ascii=False, default=str),
                require_approval,
            )

            if require_approval:
                try:
                    summary = summary_fn(args_dict) if summary_fn else f"{tool_name}({args_dict})"
                    decision = await human_gate.request_approval(
                        tool_call_id=tool_call_id,
                        summary=summary,
                        timeout_seconds=timeout_seconds or 3600,
                    )
                    if decision["decision"] != "approved":
                        await _finalize_error(pool, tool_call_id, "rejected_by_user", start)
                        return {
                            "ok": False,
                            "error": "rejected_by_user",
                            "note": decision.get("decision_note"),
                        }
                except NotImplementedError as exc:
                    logger.warning("Human Gate stub hit (W1): %s", exc)
                    await _finalize_error(pool, tool_call_id, "human_gate_unavailable", start)
                    return {
                        "ok": False,
                        "error": "human_gate_unavailable",
                        "hint": "Human Gate 在 W1 未启用，所有 W1 tool 必须 require_approval=False",
                    }

            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                logger.exception("tool %s raised", tool_name)
                err_msg = f"{type(exc).__name__}: {exc}"
                await _finalize_error(pool, tool_call_id, err_msg, start)
                return {"ok": False, "error": err_msg, "hint": "tool 内部异常，看 server 日志定位"}

            duration_ms = int((time.perf_counter() - start) * 1000)
            await pool.execute(
                """
                UPDATE mcp.tool_calls
                SET status='completed', result=$1::jsonb, duration_ms=$2, completed_at=NOW()
                WHERE id=$3
                """,
                json.dumps(result, ensure_ascii=False, default=str),
                duration_ms,
                uuid.UUID(tool_call_id),
            )
            return result

        # 关键：让 FastMCP 能反射出 fn 原签名生成 JSON schema
        # @functools.wraps 仅设 __wrapped__，不复制 __signature__；
        # 部分 FastMCP 版本直接读 __signature__，显式拷贝防止 schema 退化为 (*args, **kwargs)
        import inspect as _inspect
        wrapper.__signature__ = _inspect.signature(fn)  # type: ignore[attr-defined]
        wrapper.__annotations__ = dict(fn.__annotations__)

        # 注册到 FastMCP
        mcp.tool(**mcp_kwargs)(wrapper)
        return wrapper

    return decorator


async def _finalize_error(pool, tool_call_id: str, error: str, start: float) -> None:
    duration_ms = int((time.perf_counter() - start) * 1000)
    await pool.execute(
        """
        UPDATE mcp.tool_calls
        SET status='error', error=$1, duration_ms=$2, completed_at=NOW()
        WHERE id=$3
        """,
        error,
        duration_ms,
        uuid.UUID(tool_call_id),
    )


def _bind_args(fn: Callable[..., Any], args: tuple, kwargs: dict) -> dict:
    """把 (args, kwargs) 转成 {param_name: value} 用于审计。"""
    import inspect
    try:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return {"_args": list(args), "_kwargs": kwargs}
```

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_audit.py -v
```

Expected: 3 passed

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/audit.py services/knowledge-engine/tests/test_mcp_audit.py
git commit -m "feat(mcp): add tool_with_audit decorator (audit + Human Gate hook) (W1)"
```

---

### 任务 9：server.py + main.py mount

**Files:**
- Create: `services/knowledge-engine/app/mcp/server.py`
- Create: `services/knowledge-engine/app/mcp/tools/__init__.py`
- Modify: `services/knowledge-engine/app/main.py`

> 把 FastMCP 实例挂到 FastAPI 的 `/mcp` 路径下。FastMCP 2.x 的 streamable_http_app
> 有自己的 lifespan，必须和 FastAPI lifespan 合并，否则 session manager 不启动。

- [ ] **Step 1：先验证 FastMCP 2.x 的挂载 API**

```powershell
docker exec omni-knowledge-engine python -c "from fastmcp import FastMCP; m = FastMCP('x'); print([n for n in dir(m) if 'app' in n.lower() or 'http' in n.lower()])"
```

记录输出（应含 `http_app` 或 `streamable_http_app`，以及可能的 `session_manager`）。

- [ ] **Step 2：写 tools 包标记**

`app/mcp/tools/__init__.py`：

```python
"""W1 tools：list_skus, get_sku, search_kb, list_kbs, list_briefs。

注册顺序：在 `app.mcp.server` import 时通过 `import app.mcp.tools.sku` 等触发副作用。
"""
```

- [ ] **Step 3：写 server.py（FastMCP 实例 + tool 注册聚合）**

`app/mcp/server.py`：

```python
"""omni MCP server 实例 + tool 注册（design doc §2.1 / §2.7）。

FastAPI 挂载在 main.py：`app.mount("/mcp", get_mcp_http_app())`。
Claude Code 端配置：`{"omni": {"type": "http", "url": "http://localhost:8002/mcp"}}`
"""
from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("omni")

# 触发 tool 注册副作用（每个模块用 @tool_with_audit(mcp, ...) 自注册）
from app.mcp.tools import sku as _sku  # noqa: E402, F401
from app.mcp.tools import kb as _kb    # noqa: E402, F401
from app.mcp.tools import briefs as _briefs  # noqa: E402, F401


def get_mcp_http_app():
    """返回 ASGI app 用于 `app.mount("/mcp", ...)`。

    FastMCP 2.x：优先 `streamable_http_app()`；老接口 fallback `http_app()`。
    """
    if hasattr(mcp, "streamable_http_app"):
        return mcp.streamable_http_app()
    return mcp.http_app()  # type: ignore[attr-defined]


def get_mcp_lifespan():
    """FastMCP session manager 的 lifespan，需要并入 FastAPI lifespan。

    返回 async context manager；若 FastMCP 版本不带 session_manager，返回 None。
    """
    sm = getattr(mcp, "session_manager", None)
    if sm is None:
        return None
    return sm.run  # 是 async context manager
```

- [ ] **Step 4：把 main.py 改为合并 lifespan + mount**

把 `app/main.py` 的 lifespan 和 app 装配段改成（**只改差异部分，不改其它代码**）：

```python
# 头部 import 段加：
from contextlib import AsyncExitStack
from app.mcp.server import get_mcp_http_app, get_mcp_lifespan

# 替换 lifespan 函数（保留原有 init_pool / migrate / recover_stuck_tasks 逻辑，
# 在 yield 前后分别加 MCP session manager 的 enter/exit）：
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s — connecting to PostgreSQL...", settings.service_name)
    await init_pool()
    logger.info("PostgreSQL connection pool ready")

    from app.database import get_pool
    try:
        await _migrate_tsv_column(get_pool())
    except Exception:
        logger.warning("tsv column migration skipped", exc_info=True)

    from app.services.ingestion import recover_stuck_tasks
    try:
        result = await recover_stuck_tasks()
        if result["recovered"] > 0:
            logger.info("Recovered %d stuck tasks from previous run", result["recovered"])
    except Exception:
        logger.warning("Task recovery failed, continuing startup", exc_info=True)

    # 启动 MCP session manager（如有）
    async with AsyncExitStack() as stack:
        mcp_lifespan = get_mcp_lifespan()
        if mcp_lifespan is not None:
            await stack.enter_async_context(mcp_lifespan())
            logger.info("MCP session manager started")

        # W1 启动自检（doctor）—— 任务 12 落地后取消注释
        # from app.mcp.doctor import run_at_startup
        # await run_at_startup()

        yield

    logger.info("Shutting down — closing database pool...")
    await close_pool()


app = FastAPI(title=settings.service_name, lifespan=lifespan)
app.include_router(knowledge_router)
# ... 其它现有 router 全部保留 ...
app.include_router(accounting_router)

# 挂载 MCP HTTP 子应用（在所有 router 之后）
app.mount("/mcp", get_mcp_http_app())
```

- [ ] **Step 5：先建 3 个 tool 模块的 stub（让 server.py 能 import 通）**

`app/mcp/tools/sku.py`：

```python
"""W1: list_skus, get_sku — 任务 10 实现。"""
```

`app/mcp/tools/kb.py`：

```python
"""W1: search_kb, list_kbs — 任务 11 实现。"""
```

`app/mcp/tools/briefs.py`：

```python
"""W1: list_briefs — 任务 12 实现。"""
```

> 这一步是为了 server.py 的 `from app.mcp.tools import sku` 不爆 ImportError；
> 任务 10/11/12 才填实际 @tool_with_audit 装饰的函数。

- [ ] **Step 6：重启 knowledge-engine 验证不崩**

```powershell
docker compose -f E:\agent\omni\docker-compose.yml restart knowledge-engine
docker logs omni-knowledge-engine --tail 50
```

Expected: 启动日志含 `Application startup complete`，无 ImportError / lifespan 异常。

- [ ] **Step 7：HTTP 冒烟测试 /mcp 路径**

```powershell
curl.exe -i http://localhost:8002/health
curl.exe -i -X POST http://localhost:8002/mcp/ -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0.0"}}}'
```

Expected:
- /health → 200 + `{"status":"healthy"}`
- /mcp 初始化 → 返回 JSON-RPC 响应，含 `serverInfo.name = "omni"` 或 SSE 流（视 FastMCP 版本）；不应是 404 或 500。

> 如 FastMCP 端点是 `/mcp` 而非 `/mcp/`，按实际调整 curl 路径。如果命中 SSE 流而 curl 显示挂起，按 Ctrl+C，能看到 SSE 头返回即可。

- [ ] **Step 8：commit**

```powershell
git add services/knowledge-engine/app/mcp/server.py services/knowledge-engine/app/mcp/tools/__init__.py services/knowledge-engine/app/mcp/tools/sku.py services/knowledge-engine/app/mcp/tools/kb.py services/knowledge-engine/app/mcp/tools/briefs.py services/knowledge-engine/app/main.py
git commit -m "feat(mcp): mount FastMCP server at /mcp + tool stubs (W1)"
```

---

### 任务 10：tools/sku.py — list_skus + get_sku

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/sku.py`
- Create: `services/knowledge-engine/tests/test_mcp_tools.py`

- [ ] **Step 1：写失败测试**

`tests/test_mcp_tools.py`：

```python
"""5 个 W1 tool 的端到端测试（hits dev DB）。

前提：docker-compose up，dev DB 已 apply 全部 migration。
"""
from __future__ import annotations

import pytest

from app.database import init_pool, close_pool, get_pool


@pytest.fixture(scope="module", autouse=True)
async def _db():
    await init_pool()
    yield
    await close_pool()


@pytest.fixture(scope="module")
async def seed_sku():
    """插一条已知 SKU；测试结束清理。"""
    pool = get_pool()
    sku_id = "_smoke_sku_001"
    await pool.execute(
        """
        INSERT INTO mvp_sku (id, name, category, douyin_product_id, status)
        VALUES ($1, '冒烟测试 SKU', '测试', '_smoke_dy_001', 'active')
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """,
        sku_id,
    )
    yield sku_id
    await pool.execute("DELETE FROM mvp_sku WHERE id=$1", sku_id)


async def test_list_skus_returns_smoke_sku(seed_sku):
    from app.mcp.tools.sku import list_skus
    out = await list_skus(status="active")
    assert out["ok"] is True
    ids = [s["id"] for s in out["skus"]]
    assert seed_sku in ids


async def test_get_sku_returns_detail(seed_sku):
    from app.mcp.tools.sku import get_sku
    out = await get_sku(sku_id=seed_sku)
    assert out["ok"] is True
    assert out["sku"]["id"] == seed_sku
    assert out["sku"]["name"] == "冒烟测试 SKU"
    # 关联字段（无数据时是空的，但 key 必须在）
    assert "recent_briefs" in out
    assert isinstance(out["recent_briefs"], list)


async def test_get_sku_not_found_returns_tool_error():
    from app.mcp.tools.sku import get_sku
    out = await get_sku(sku_id="_definitely_not_exists_xyz")
    assert out["ok"] is False
    assert out["error"] == "sku_not_found"
    assert "list_skus" in out["hint"]
```

- [ ] **Step 2：跑测试看失败**

Expected: `ImportError` / `AttributeError: list_skus`

- [ ] **Step 3：写实现**

`app/mcp/tools/sku.py`：

```python
"""W1: list_skus, get_sku（design doc §3.2 W1 行 1-2）。

直接读 mvp_sku；get_sku 额外关联 content_studio.briefs 拉最近 3 条 brief 摘要。
"""
from __future__ import annotations

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp


@tool_with_audit(mcp, require_approval=False)
async def list_skus(status: str | None = None) -> dict:
    """列出 SKU 主数据。

    Args:
        status: 过滤状态（active / archived / draft 等），None=全部

    Returns:
        {"ok": True, "count": N, "skus": [{id, name, category, status,
            growth_class, in_focus_pool, total_stock, available_stock}, ...]}
    """
    pool = get_pool()
    if status:
        rows = await pool.fetch(
            "SELECT id, name, category, status, growth_class, in_focus_pool,"
            "       total_stock, available_stock"
            "  FROM mvp_sku WHERE status=$1 ORDER BY created_at DESC",
            status,
        )
    else:
        rows = await pool.fetch(
            "SELECT id, name, category, status, growth_class, in_focus_pool,"
            "       total_stock, available_stock"
            "  FROM mvp_sku ORDER BY created_at DESC"
        )
    skus = [dict(r) for r in rows]
    return {"ok": True, "count": len(skus), "skus": skus}


@tool_with_audit(mcp, require_approval=False)
async def get_sku(sku_id: str) -> dict:
    """单 SKU 详情 + 最近 3 条 brief。

    Args:
        sku_id: mvp_sku.id (VARCHAR(64))

    Returns:
        成功 {"ok": True, "sku": {...全字段}, "recent_briefs": [...]}
        失败 {"ok": False, "error": "sku_not_found", "hint": "..."}
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM mvp_sku WHERE id=$1",
        sku_id,
    )
    if row is None:
        return {
            "ok": False,
            "error": "sku_not_found",
            "hint": f"SKU id '{sku_id}' 不存在；调 list_skus 看可用 ID 列表",
        }

    briefs = await pool.fetch(
        """
        SELECT id, title, status, target_purpose, created_at
          FROM content_studio.briefs
         WHERE sku_id=$1
         ORDER BY created_at DESC LIMIT 3
        """,
        sku_id,
    )
    return {
        "ok": True,
        "sku": dict(row),
        "recent_briefs": [dict(b) for b in briefs],
    }
```

- [ ] **Step 4：重启 + 跑测试**

```powershell
docker compose -f E:\agent\omni\docker-compose.yml restart knowledge-engine
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_tools.py -v -k "sku"
```

Expected: 3 passed

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/sku.py services/knowledge-engine/tests/test_mcp_tools.py
git commit -m "feat(mcp): add list_skus + get_sku tools (W1)"
```

---

### 任务 11：tools/kb.py — search_kb + list_kbs

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/kb.py`
- Modify: `services/knowledge-engine/tests/test_mcp_tools.py`

- [ ] **Step 1：在测试文件末尾追加**

```python
async def test_list_kbs_basic():
    from app.mcp.tools.kb import list_kbs
    out = await list_kbs()
    assert out["ok"] is True
    assert "count" in out
    assert isinstance(out["kbs"], list)
    # 每条至少含 id / name / kb_role
    if out["kbs"]:
        kb0 = out["kbs"][0]
        for k in ("id", "name", "kb_role"):
            assert k in kb0


async def test_list_kbs_filter_by_role():
    from app.mcp.tools.kb import list_kbs
    out = await list_kbs(role="general")
    assert out["ok"] is True
    for kb in out["kbs"]:
        assert kb["kb_role"] == "general"


async def test_search_kb_no_kb_ids_returns_empty():
    """无任何 KB 时（或显式 kb_ids=[]）返回 ok=True + 空 hits，不抛错。"""
    from app.mcp.tools.kb import search_kb
    out = await search_kb(query="测试", kb_ids=[])
    assert out["ok"] is True
    assert out["hits"] == []
    assert out["count"] == 0


async def test_search_kb_role_filter_resolves_kb_ids():
    """传 kb_roles 时应自动解析为 kb_ids；无匹配 KB 时返回空。"""
    from app.mcp.tools.kb import search_kb
    out = await search_kb(query="测试", kb_roles=["_no_such_role_"])
    # _no_such_role_ 不在 CHECK 约束允许列表，list_kbs 也查不到 → 空 hits
    assert out["ok"] is True
    assert out["hits"] == []
```

- [ ] **Step 2：跑测试看失败**

Expected: `ImportError` / `AttributeError: list_kbs / search_kb`

- [ ] **Step 3：写实现**

`app/mcp/tools/kb.py`：

```python
"""W1: search_kb, list_kbs（design doc §3.2 W1 行 3-4）。

list_kbs：thin wrapper over services.ingestion.list_kbs，可选按 kb_role 过滤。
search_kb：thin wrapper over services.rag_chain.retrieve_multi_kb；支持
  - kb_ids: 直接指定
  - kb_roles: 按 role 自动解析为 kb_ids
  - 都没传 → 用全量 KB（可能很慢，hint 提醒）
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import ingestion, rag_chain


@tool_with_audit(mcp, require_approval=False)
async def list_kbs(role: str | None = None) -> dict:
    """列出所有知识库。

    Args:
        role: 可选 kb_role 过滤（authoritative / methodology / personal_log /
              template / private_doc / general）

    Returns:
        {"ok": True, "count": N, "kbs": [{id, name, description, kb_role,
            embedding_provider, embedding_model, dimension, created_at}, ...]}
    """
    kbs = await ingestion.list_kbs()
    if role:
        kbs = [k for k in kbs if k.get("kb_role") == role]
    return {"ok": True, "count": len(kbs), "kbs": kbs}


@tool_with_audit(mcp, require_approval=False)
async def search_kb(
    query: str,
    kb_ids: list[str] | None = None,
    kb_roles: list[str] | None = None,
    top_k: int = 8,
) -> dict:
    """KB 检索；返回排序后的 chunks。

    Args:
        query: 自然语言查询
        kb_ids: 显式指定 KB id 列表
        kb_roles: 按角色筛 KB（自动解析为 kb_ids）；与 kb_ids 同时给则取并集
        top_k: 总返回上限（默认 8）

    Returns:
        {"ok": True, "count": N, "hits": [{source, kb_id, id, score, content,
            title}, ...]}
    """
    resolved_ids: set[str] = set(kb_ids or [])
    if kb_roles:
        all_kbs = await ingestion.list_kbs()
        wanted = set(kb_roles)
        resolved_ids.update(
            k["id"] for k in all_kbs if k.get("kb_role") in wanted
        )
    if not resolved_ids and not kb_ids and not kb_roles:
        # 都没给 → 全量 KB（小数据量场景下 OK；大库时 hint 用户限定）
        all_kbs = await ingestion.list_kbs()
        resolved_ids = {k["id"] for k in all_kbs}

    if not resolved_ids:
        return {"ok": True, "count": 0, "hits": []}

    name_map = {k["id"]: k["name"] for k in (await ingestion.list_kbs())}
    hits = await rag_chain.retrieve_multi_kb(
        query,
        list(resolved_ids),
        top_k_per_kb=max(3, top_k // max(1, len(resolved_ids))),
        min_per_kb=0,
        score_threshold=0.0,
        total_limit=top_k,
        kb_name_map=name_map,
    )
    return {"ok": True, "count": len(hits), "hits": hits}
```

- [ ] **Step 4：重启 + 跑测试**

```powershell
docker compose -f E:\agent\omni\docker-compose.yml restart knowledge-engine
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_tools.py -v -k "kb"
```

Expected: 4 passed

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/kb.py services/knowledge-engine/tests/test_mcp_tools.py
git commit -m "feat(mcp): add list_kbs + search_kb tools with kb_role resolver (W1)"
```

---

### 任务 12：tools/briefs.py — list_briefs

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/briefs.py`
- Modify: `services/knowledge-engine/tests/test_mcp_tools.py`

- [ ] **Step 1：在测试末尾追加**

```python
async def test_list_briefs_smoke(seed_sku):
    """seed_sku 存在但通常没 brief，验证返回 ok=True + 空数组也是合法。"""
    from app.mcp.tools.briefs import list_briefs
    out = await list_briefs(sku_id=seed_sku)
    assert out["ok"] is True
    assert isinstance(out["briefs"], list)
    assert out["count"] == len(out["briefs"])


async def test_list_briefs_status_filter():
    from app.mcp.tools.briefs import list_briefs
    out = await list_briefs(status="active")
    assert out["ok"] is True
    for b in out["briefs"]:
        assert b["status"] == "active"
```

- [ ] **Step 2：跑测试看失败**

Expected: `AttributeError: list_briefs`

- [ ] **Step 3：写实现**

`app/mcp/tools/briefs.py`：

```python
"""W1: list_briefs（design doc §3.2 W1 行 5）。

thin wrapper over services.briefs.list_briefs（已存在）。
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import briefs as briefs_service


@tool_with_audit(mcp, require_approval=False)
async def list_briefs(
    sku_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict:
    """列已生成的 Brief。

    Args:
        sku_id: 按 SKU 过滤
        status: 按状态过滤（active / archived 等）
        limit: 上限（默认 50，最大 200）

    Returns:
        {"ok": True, "count": N, "briefs": [{id, sku_id, title, usp, status,
            target_purpose, created_at}, ...]}
    """
    rows = await briefs_service.list_briefs(
        limit=min(limit, 200),
        offset=0,
        sku_id=sku_id,
        status=status,
    )
    # 只回 LLM 关心的薄字段；避免返 audience_profile 这种 JSON 太大撑爆 context
    slim = [
        {
            "id": str(b["id"]),
            "sku_id": b.get("sku_id"),
            "title": b.get("title"),
            "usp": b.get("usp"),
            "status": b.get("status"),
            "target_purpose": b.get("target_purpose"),
            "created_at": b.get("created_at"),
        }
        for b in rows
    ]
    return {"ok": True, "count": len(slim), "briefs": slim}
```

- [ ] **Step 4：重启 + 跑测试**

```powershell
docker compose -f E:\agent\omni\docker-compose.yml restart knowledge-engine
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_tools.py -v -k "briefs"
```

Expected: 2 passed

- [ ] **Step 5：跑全套 mcp 测试做总检**

```powershell
docker exec omni-knowledge-engine python -m pytest tests/test_mcp_audit.py tests/test_mcp_config.py tests/test_mcp_tools.py -v
```

Expected: 全部 passed（约 17 用例）

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/briefs.py services/knowledge-engine/tests/test_mcp_tools.py
git commit -m "feat(mcp): add list_briefs tool (W1) — completes 5/5 W1 tools"
```

---

### 任务 13：doctor.py — 健康检查 CLI

**Files:**
- Create: `services/knowledge-engine/app/mcp/doctor.py`
- Modify: `services/knowledge-engine/app/main.py`（取消注释 `await run_at_startup()`）

> 检查项：DB pool / mcp schema 表 / yaml 解析 / /mcp 端点可达 / 5 tool 注册
> 模式：(a) CLI `python -m app.mcp.doctor`，退出码 0/1；(b) lifespan 启动时调
> `run_at_startup()`，仅 logger.warning 不阻断启动。

- [ ] **Step 1：写 doctor.py**

`app/mcp/doctor.py`：

```python
"""omni MCP 健康检查（design doc §6.3 调试三件套之一）。

用法：
    # CLI（容器内）
    docker exec omni-knowledge-engine python -m app.mcp.doctor
    # 退出码 0 = 全绿；1 = 有红

    # 启动期（main.py lifespan 内）
    from app.mcp.doctor import run_at_startup
    await run_at_startup()  # 仅日志，不抛
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.database import init_pool, close_pool, get_pool

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_green(self) -> bool:
        return all(c.ok for c in self.checks)

    def render(self) -> str:
        lines = ["omni MCP doctor 报告"]
        for c in self.checks:
            mark = "OK  " if c.ok else "FAIL"
            lines.append(f"  [{mark}] {c.name}{(': ' + c.detail) if c.detail else ''}")
        lines.append("")
        lines.append("结论：全绿 ✓" if self.all_green else "结论：存在 FAIL ✗")
        return "\n".join(lines)


async def _check_db_pool(report: DoctorReport) -> None:
    try:
        pool = get_pool()
        v = await pool.fetchval("SELECT 1")
        report.checks.append(CheckResult("DB pool", v == 1))
    except Exception as exc:
        report.checks.append(CheckResult("DB pool", False, str(exc)))


async def _check_mcp_schema(report: DoctorReport) -> None:
    try:
        pool = get_pool()
        n = await pool.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables"
            " WHERE table_schema='mcp' AND table_name IN ('tool_calls','human_gates')"
        )
        ok = n == 2
        report.checks.append(CheckResult("mcp schema tables", ok, f"found {n}/2"))
    except Exception as exc:
        report.checks.append(CheckResult("mcp schema tables", False, str(exc)))


def _check_yaml(report: DoctorReport) -> None:
    try:
        from app.mcp.model_config import _load_yaml
        raw = _load_yaml()
        ok = "__default__" in raw
        report.checks.append(CheckResult("tool_models.yaml", ok, f"keys={list(raw.keys())[:5]}"))
    except Exception as exc:
        report.checks.append(CheckResult("tool_models.yaml", False, str(exc)))


def _check_tools_registered(report: DoctorReport) -> None:
    try:
        from app.mcp.server import mcp
        # FastMCP 2.x：用 mcp._tool_manager._tools 或公共 list_tools
        tools = []
        if hasattr(mcp, "list_tools"):
            tools = list(mcp.list_tools())  # 同步或 awaitable，看版本
            if asyncio.iscoroutine(tools):
                tools = []  # 异步分支由 _check_via_http 处理
        elif hasattr(mcp, "_tool_manager"):
            tools = list(mcp._tool_manager._tools.keys())
        wanted = {"list_skus", "get_sku", "search_kb", "list_kbs", "list_briefs"}
        names = set()
        for t in tools:
            names.add(getattr(t, "name", t) if hasattr(t, "name") else t)
        missing = wanted - names
        report.checks.append(CheckResult(
            "5 tools registered", not missing,
            f"missing={sorted(missing)}" if missing else f"all 5 ok",
        ))
    except Exception as exc:
        report.checks.append(CheckResult("5 tools registered", False, str(exc)))


async def _check_mcp_http(report: DoctorReport) -> None:
    url = f"http://localhost:{settings.service_port}/mcp/"
    try:
        async with httpx.AsyncClient(timeout=5.0) as cli:
            # 用 initialize JSON-RPC 探活；MCP 协议要求 Accept SSE
            r = await cli.post(
                url,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "doctor", "version": "0.0"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            ok = r.status_code in (200, 202)
            report.checks.append(CheckResult("/mcp HTTP", ok, f"status={r.status_code}"))
    except Exception as exc:
        report.checks.append(CheckResult("/mcp HTTP", False, str(exc)))


async def run() -> DoctorReport:
    report = DoctorReport()
    await _check_db_pool(report)
    await _check_mcp_schema(report)
    _check_yaml(report)
    _check_tools_registered(report)
    await _check_mcp_http(report)
    return report


async def run_at_startup() -> None:
    """启动期非阻塞自检：只 logger.warning 不抛。"""
    try:
        report = await run()
        for c in report.checks:
            if c.ok:
                logger.info("[doctor] %s OK %s", c.name, c.detail)
            else:
                logger.warning("[doctor] %s FAIL %s", c.name, c.detail)
    except Exception:
        logger.warning("doctor self-check failed", exc_info=True)


async def _cli() -> int:
    await init_pool()
    try:
        report = await run()
    finally:
        await close_pool()
    print(report.render())
    return 0 if report.all_green else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli()))
```

- [ ] **Step 2：在 main.py lifespan 内启用 startup self-check**

把任务 9 中预留的注释行打开：

```python
# 在 enter_async_context(mcp_lifespan()) 之后，yield 之前：
from app.mcp.doctor import run_at_startup
await run_at_startup()
```

- [ ] **Step 3：重启 + 看日志**

```powershell
docker compose -f E:\agent\omni\docker-compose.yml restart knowledge-engine
docker logs omni-knowledge-engine --tail 60 | findstr "doctor"
```

Expected: 5 行 `[doctor] ... OK` （DB pool / mcp schema / yaml / 5 tools / /mcp HTTP）。

- [ ] **Step 4：CLI 模式跑一遍**

```powershell
docker exec omni-knowledge-engine python -m app.mcp.doctor
echo $LASTEXITCODE
```

Expected:
```
omni MCP doctor 报告
  [OK  ] DB pool
  [OK  ] mcp schema tables: found 2/2
  [OK  ] tool_models.yaml: keys=['__default__']
  [OK  ] 5 tools registered: all 5 ok
  [OK  ] /mcp HTTP: status=200
结论：全绿 ✓
```
退出码 0。

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/app/main.py
git commit -m "feat(mcp): add omni-mcp-doctor CLI + startup self-check (W1)"
```

---

### 任务 14：Claude Code 端注册 + e2e 验收

**Files:**
- Modify: `E:\agent\omni\.claude\settings.local.json`

- [ ] **Step 1：把 `mcpServers` 加到现有 settings**

读现有 `.claude/settings.local.json` 顶层 keys（不要破坏 `permissions`），加入：

```json
{
  "permissions": { "...保持原样不动..." },
  "mcpServers": {
    "omni": {
      "type": "http",
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

> 用 Edit 工具加，避免误改 permissions 数组中的 110+ 条 entries。

- [ ] **Step 2：重启 Claude Code（或在当前会话执行 `/mcp` 命令）**

如果当前 Claude Code 会话不能热加载 MCP，则关掉 → 在 omni 项目目录重开。

```
（在 Claude Code 里输入）
/mcp
```

Expected: 列表里看到 `omni` 状态 `connected`，5 个 tool 可见：
- mcp__omni__list_skus
- mcp__omni__get_sku
- mcp__omni__search_kb
- mcp__omni__list_kbs
- mcp__omni__list_briefs

- [ ] **Step 3：对话冒烟（验收点 1）**

在 Claude Code 输入：

```
我有几个 SKU？
```

Expected: Claude 调 `mcp__omni__list_skus`，返回数量。检查 mcp.tool_calls 表新增一行：

```powershell
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT tool_name, status, duration_ms, created_at FROM mcp.tool_calls ORDER BY created_at DESC LIMIT 3"
```

应看到 `list_skus | completed | <small_ms> | <最近时间>`。

- [ ] **Step 4：对话冒烟（验收点 2）**

```
查一下 KB 里有没有提过『净利率』
```

Expected: Claude 调 `mcp__omni__search_kb`（kb_ids 留空，自动用全量），返回若干 hits 或空数组（取决于真实 KB 内容）。`mcp.tool_calls` 多一行 `search_kb | completed`。

- [ ] **Step 5：对话冒烟（验收点 3）**

```
我有哪些知识库？
```

Expected: Claude 调 `mcp__omni__list_kbs`，按角色分组展示。

- [ ] **Step 6：错误路径冒烟**

```
查一下 SKU 叫 _definitely_not_exists 的详情
```

Expected: Claude 调 `mcp__omni__get_sku(sku_id="_definitely_not_exists")` → 返回 `{ok:false, error:"sku_not_found", hint:"..."}` → Claude 用人话解释并建议先 list_skus。

- [ ] **Step 7：commit**

```powershell
git add .claude/settings.local.json
git commit -m "feat(mcp): register omni MCP server in Claude Code settings (W1)"
```

- [ ] **Step 8：更新进度文档**

把 `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md` 的 W1 行打勾：

```diff
- [ ] **writing-plans skill 出 W1 详细实施计划**
+ [x] writing-plans skill 出 W1 详细实施计划（2026-05-03）
- [ ] W1 落地：MCP 底座 + 5 个 tool（约 5 天）
+ [x] W1 落地：MCP 底座 + 5 个 tool（YYYY-MM-DD 完成；commit `xxx..xxx`）
```

并把"九、最后更新"日期改成 W1 落地日。

> 注意：这是 memory 文件，**不**进 git。直接用 Edit 工具改即可。

---

## 风险点 + 验证策略

| 风险 | 验证策略 | 应急方案 |
|---|---|---|
| **FastMCP 2.x 与 FastAPI lifespan 冲突** | 任务 9 步骤 6 先重启看日志，任何 lifespan 异常立即停下来查 FastMCP 文档 | 改用 `app.mount` 但不合并 lifespan，依赖 FastMCP 自启 session manager（部分版本可行） |
| **FastMCP 反射不到 fn 签名（schema 退化为 *args / **kwargs）** | 任务 8 已显式拷 `__signature__` + `__annotations__`；任务 9 step 7 看 `/mcp initialize` 返回的 tool schema 是否含 `status`/`sku_id` 等真实参数 | 改用 `@mcp.tool` 直接装饰原 fn + 在函数体里手动调审计写表 |
| **/mcp 路径是 `/mcp` 还是 `/mcp/`** | 任务 9 步骤 7 两种都试 curl | 调整 `app.mount` 路径或 Claude Code url 末尾斜杠 |
| **fastmcp 包带 pyyaml 但 langgraph 锁定旧 yaml** | 任务 4 步骤 4 先 `import yaml` 验证版本 | 显式 pin `pyyaml>=6.0` 到 pyproject |
| **pytest-asyncio mode 不是 auto** | 任务 7 步骤 4 先 grep 配置 | pyproject.toml 加 `[tool.pytest.ini_options] asyncio_mode = "auto"` |
| **rag_chain.retrieve_multi_kb 在 KB 都为空时报错** | 任务 11 测试 `kb_ids=[]` 直接早返回 | tools/kb.py 已加早 return |
| **Claude Code Windows 端 HTTP MCP 不通** | 任务 14 步骤 2 `/mcp` 命令查看状态 | 备选改用 stdio：knowledge-engine 暴露 `python -m app.mcp.stdio_main`，Claude Code config 改 `"command": "docker exec ...","args": [...]` |
| **mvp_sku 表为空导致 e2e 通不过** | 任务 14 前先确认 `SELECT COUNT(*) FROM mvp_sku` > 0 | 没数据就跑 scout-agent runbook A 灌一次，或人工 INSERT 一条 |
| **content_studio.briefs 字段名漂移** | 任务 12 测试覆盖 status / sku_id 字段 | 已对齐 services/briefs.py 现有 list_briefs 参数 |
| **Docker 容器内 localhost ≠ 宿主 localhost** | doctor.py `_check_mcp_http` 用 `localhost:8002`，容器内调容器自己 → 行 | 若 doctor 在容器内调失败，改用 `127.0.0.1` 或服务名 |
| **审计装饰器在异常路径中泄漏 args（含敏感数据）** | W1 5 个 tool 全是只读，args 不含 token | W4 审计 tool 时引入字段脱敏 |

### 关键验证 checklist（任务 14 之后必须全过）

- [ ] `docker exec omni-knowledge-engine python -m pytest tests/test_mcp_*.py -v` → 全 passed
- [ ] `docker exec omni-knowledge-engine python -m app.mcp.doctor` → 退出码 0，5 项全 OK
- [ ] Claude Code `/mcp` 命令显示 omni 状态 connected
- [ ] mcp.tool_calls 在 e2e 4 个对话后至少有 4 行 status=completed
- [ ] `git log --oneline | head -14` 看到 14 个 W1 提交（每任务一个）

---

## Self-Review

**1. Spec 覆盖**

| Spec 要求（W1） | 对应任务 |
|---|---|
| §2.1 mcp/ 目录结构（7 顶层 .py + tools/）| T3, T4, T5, T7, T8, T9, T13 |
| §2.2 tool_with_audit 装饰器接口 | T8 |
| §2.3 ToolSuccess / ToolError 类型 | T3 |
| §2.5 tool_models.yaml + 加载器 | T4 |
| §2.6 ai_hub_client.py thin wrapper | T6 |
| §2.7 Claude Code 注册 | T14 |
| §2.8 ANTI_AI_HUMAN_VOICE 常量 | T5 |
| §3.2 W1 五 tool（list_skus / get_sku / search_kb / list_kbs / list_briefs）| T10, T11, T12 |
| §6.3 doctor 健康检查 | T13 |
| §8 016_mcp_audit.sql migration | T1 |
| §9 W1 验收标准 4 条 | T14 步骤 3-6 |

**2. Placeholder 扫描**

- 无 "TODO/TBD/implement later" 字样在 step 内
- 每段代码都是完整可粘贴
- 异常处理是显式的（捕获 NotImplementedError → ToolError；捕获 Exception → ToolError）
- 测试代码、错误码、命令行全部具名

**3. 类型一致性**

- `ToolError.error` 在所有 tool 一致：`sku_not_found` / `human_gate_unavailable` / `rejected_by_user` / 异常类名
- `tool_with_audit` 签名和 design doc §2.2 一致（`mcp` + 4 个 keyword 参数）
- `get_model_for_tool(tool_name, _override_yaml=None)` 单一签名贯穿测试和实现
- `list_kbs` 返回字段（id / name / kb_role）和 `services.ingestion.list_kbs` 实际返回字段对齐（任务前已 grep 验证 line 89-91）

**修复项**：无（自审通过）

---

## Execution Handoff

Plan 已存到 `docs/superpowers/plans/2026-05-03-omni-agent-uplift-W1-plan.md`。两种执行方式：

**1. Subagent-Driven（推荐）** — 每任务派一个 fresh subagent，任务间老板/Claude 二段 review；适合任务多、希望并行/隔离的场景。
**2. Inline Execution** — 当前会话连续跑，每 3-4 个任务停下来 checkpoint review；适合任务相对简单、想盯着进度的场景。

W1 14 个任务里：
- T1, T2 是基础设施（migration + 依赖），适合先一起跑掉
- T3-T7 是无状态小模块（types / config / 常量 / wrapper / stub），可批量
- T8-T9 是底座关键件（audit 装饰器 + server 挂载），需重点 review
- T10-T12 是三个 tool 实现，互相独立，subagent 并行最快
- T13-T14 是 doctor + e2e，必须串行收尾

**老板选哪种？**
