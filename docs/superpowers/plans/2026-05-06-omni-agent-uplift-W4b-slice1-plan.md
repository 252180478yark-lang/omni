# W4-B 切片 1 实施计划：前端 /agent-log 页 + 后端 cost-luru skill（双轨配合）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给老板一个"显示器"看 W4-A 沉淀的 477 条 mcp.tool_calls + 在前端打分；同时把"录成本"标准话术固化成项目内 skill，前后端在同一条数据流上配合。

**Architecture:** 双轨并行：
- **后端轨**：knowledge-engine 加 `/api/v1/mcp/tool-calls` REST router（list / detail / rate 三 endpoint，复用 W4-A 的 `pattern_lib` 与 `mcp.tool_calls` 表）+ `.claude/skills/cost-luru/SKILL.md`（项目内 markdown，编排录成本 5 步 SOP）
- **前端轨**：`/agent-log` 页 = 24h 概览卡 + tool_calls 主表 + trace 抽屉 + 👍/👎/重做评分按钮；前端 3 个 API proxy route 转发到 KE（`_shared.ts` 模式）
- **配合点**：cost-luru 跑一次 → mcp.tool_calls 至少留 2 条（record_cost + query_costs）→ /agent-log 实时看见 + 评分回写 patterns.md

**Tech Stack:** FastAPI · asyncpg · pytest-asyncio · Next.js 14 App Router · shadcn/ui（Card/Badge/Button/Sheet）· lucide-react · Claude Code skill markdown

---

## 起手就要看的文件（implementer 必读）

### 设计文档与历史 plan
- `docs/superpowers/specs/2026-05-03-omni-agent-uplift-design.md`
  - §3.3 line 503-515（6 业务 skill 清单，cost-luru 不在原 6 个里——本切片新增"录成本"专项 skill，跟 daily-store-pulse 等 6 个并列）
  - §6.3 line 671-690（调试三件套，/agent-log 页职责）
  - §7.4 line 753-765（反馈循环：rate → patterns.md）
- `docs/superpowers/plans/2026-05-06-omni-agent-uplift-W4a-plan.md`（W4-A plan 格式范本，6 task / 1801 行）
- `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md` §二十一（W4-A 落地总结，看 4 tool 现状）

### 后端必读现有资产（reuse_existing_prompts 强制约束）
- `services/knowledge-engine/app/mcp/tools/cost_admin.py`（**record_cost 实现**，cost-luru skill 必须 1:1 引用其入参规范：`category in {product, logistics, partner_quote}`、`unit_cost: str`、`quantity_per_unit: str`，禁止 float）
- `services/knowledge-engine/app/mcp/tools/feedback.py`（**rate_tool_call 实现**，T1 评分 endpoint 内部要复用其逻辑）
- `services/knowledge-engine/app/mcp/pattern_lib.py`（`append_successful_pattern / append_failed_pattern` helper，T1 评分 endpoint 复用）
- `services/knowledge-engine/app/database.py`（`get_pool()` asyncpg 入口）
- `services/knowledge-engine/app/routers/accounting.py`（FastAPI router 写法范本，含 prefix / tags / asyncpg 调法）
- `services/knowledge-engine/app/main.py:72-80`（include_router 注册位置）
- `services/knowledge-engine/scripts/import_costs.py` + `cost_template.csv`（cost 批量导入 SOP，cost-luru skill 借鉴话术）
- `services/knowledge-engine/app/mcp/cli_approve.py`（**Human Gate 批驳 CLI**，cost-luru skill 步骤 3 要写明 CLI 用法）

### 前端必读现有资产
- `frontend/src/app/api/omni/_shared.ts`（**`serviceBase().knowledge`** + `fetchJson<T>`，T2 三个 proxy route 必复用，禁止重写）
- `frontend/src/app/api/omni/activity/route.ts`（GET 路由范本：`runtime='nodejs'` + `dynamic='force-dynamic'`）
- `frontend/src/app/decisions/page.tsx`（**前端页风格 + StatCard + 状态 Badge 配色 + filter bar 模板**，T3 的 /agent-log 页直接借鉴布局）
- `frontend/src/app/cost/page.tsx`（cost 相关页风格参考）
- `frontend/src/components/ui/`（shadcn 组件目录，确认 Card/Badge/Button 已就位 + 是否有 Sheet/Drawer）
- `frontend/package.json`（已有 lucide-react / recharts / framer-motion / @base-ui/react，**没有** vitest/jest/playwright，本切片前端不写单测）
- `frontend/src/components/app-sidebar.tsx`（侧边栏菜单注册位置，/agent-log 要加进去）

### 数据库 schema（必看，禁止瞎猜）
- `migrations/016_mcp_audit.sql:5-21` — **mcp.tool_calls 完整列**：
  ```
  id UUID, tool_name TEXT, args JSONB, result JSONB,
  status TEXT,            -- pending|approved|rejected|completed|error|orphaned
  require_approval BOOL, duration_ms INT, error TEXT,
  user_rating TEXT,       -- good|bad|redo|null
  rating_note TEXT, model_used TEXT,
  tokens_input INT, tokens_output INT,
  created_at TIMESTAMPTZ, completed_at TIMESTAMPTZ
  ```
  注意：**没有 `trace` 字段**（trace 嵌在 `result` JSONB 里），写查询时不要 `SELECT trace`
- `migrations/015_cost_items.sql` — accounting.cost_items（record_cost 写入目标）

### 项目内 skill 约定
- 项目内 `.claude/skills/` 目录**不存在**，T4 必须新建
- 全局 skill 范本：`C:\Users\Administrator\.claude\skills\brainstorming\SKILL.md`（看 frontmatter 结构）
- CLAUDE.md 已有"老板响应词约定"line 31-42（**含 `录成本 / 加成本 / 录入物流费` 已有约定**），cost-luru skill 必须跟 CLAUDE.md 这条规则一致

---

## 关键决策（已锁定，禁止再讨论）

1. **前端不直读 PG**（修正老板拍板时基于的"前端有 PG 直连"假设）：现有 `/api/omni/*` 全是 HTTP 调后端模式，前端无 pg/postgres npm 包。**KE 加 3 个 REST endpoint，前端走 HTTP**。维持架构一致 + 评分逻辑可复用 W4-A 已有 `pattern_lib`
2. **不加新 MCP tool**：本切片只加 KE REST endpoint + 前端页 + 项目内 skill，**doctor expected_tools 维持 27**
3. **评分 endpoint 内部复用 rate_tool_call 逻辑**：T1 抽出 `app/services/agent_log_service.py:rate_tool_call_logic(call_id, rating, note)` 给 router + 给 mcp tool 共用，避免重复代码
4. **skill 装项目内**：`E:\agent\omni\.claude\skills\cost-luru\SKILL.md`（同进 git，老板换电脑/同事接手能用）。**不**装全局 `~/.claude/skills/`
5. **cost-luru 不写代码**：纯 markdown 编排，话术 → record_cost → 等 Gate 批 → query_costs 验，5 步走停在每步等老板反馈
6. **前端无测试基建**：项目无 vitest/jest，T2/T3 前端 task 改用"`npm run dev` 启服务 + curl + 浏览器人工验证"代替单测
7. **后端 TDD**：T1 走 pytest TDD（写测试 → 失败 → 实现 → 通过）
8. **/agent-log 数据范围**：默认列最近 7 天 + 100 条；24h 概览只算最近 24h；评分写 user_rating + append patterns.md
9. **trace 字段位置**：嵌在 `mcp.tool_calls.result` JSONB 里（W2 起 LLM tool 写入），前端从 `result.trace` 取，不是顶级字段
10. **不做之列**（W4-B 后续切片处理）：/inbox / /cost 增强 / 5 业务 skill / W4 加分 5 tool / cron weekly_self_review / 修 codify e2e / trace schema 改革
11. **个人自用约束**：不上线 / 不多人 / 不分布式 / 不灰度 / 不写 SLA
12. **写作风格强制**（feedback_writing_style）：所有用户可见文案 + skill 内容 + 错误 hint 都说人话、反幻觉、去 AI 化（"录 sku-X 物流费 5 块" 不是"成功创建一项物流类成本记录"）
13. **/agent-log 加进 sidebar**：T3 末尾改 `frontend/src/components/app-sidebar.tsx` 加菜单项
14. **commit 信号**：每 task 末尾一次 commit，commit message 用 `feat(W4-B)` / `feat(skill)` 前缀，跟 W4-A 的 `feat(mcp): ...（W4-A T2）` 风格一致

---

## 文件结构

### 待建（后端 — 4 个 .py + 0 个 .sql）
- `services/knowledge-engine/app/services/agent_log_service.py` — `list_tool_calls() / get_tool_call() / rate_tool_call_logic()`（~120 行）
- `services/knowledge-engine/app/routers/mcp_tool_calls.py` — FastAPI router 3 endpoint（~80 行）
- `services/knowledge-engine/app/schemas/mcp_tool_calls.py` — Pydantic models（~40 行）
- `services/knowledge-engine/tests/test_router_mcp_tool_calls.py` — TDD 测试（~150 行）

### 待改（后端 — 2 个）
- `services/knowledge-engine/app/main.py:80` — 加 `app.include_router(mcp_tool_calls_router)`（+1 行 import + +1 行 include）
- `services/knowledge-engine/app/mcp/tools/feedback.py` — 重构 rate_tool_call 内部调 `agent_log_service.rate_tool_call_logic`（不破坏 mcp tool 接口，~10 行 delta）

### 待建（前端 — 4 个 .ts/.tsx）
- `frontend/src/app/api/omni/agent-log/route.ts` — GET list（~40 行）
- `frontend/src/app/api/omni/agent-log/[id]/route.ts` — GET detail（~30 行）
- `frontend/src/app/api/omni/agent-log/[id]/rate/route.ts` — POST rate（~40 行）
- `frontend/src/app/agent-log/page.tsx` — 页面主体（~400 行 TSX）

### 待改（前端 — 1 个）
- `frontend/src/components/app-sidebar.tsx` — 加 `/agent-log` 菜单项（+5 行）

### 待建（skill — 2 个 .md）
- `.claude/skills/cost-luru/SKILL.md` — 主文档（~200 行）
- `.claude/skills/cost-luru/examples.md` — 5 个真实话术 → tool 调用映射示例（~80 行）

### 待改（settings — 1 个）
- `.claude/settings.local.json` — 确认 `mcp__omni__record_cost` / `mcp__omni__query_costs` 已 grant（已 W3a/W2 时加，**预期不需要新加**，T5 验证）

---

## 已知坑（W3a/W3b/W3c/W4-A 期间踩的，防重踩）

1. **fixture sync 写法跑不通**：用 `@pytest_asyncio.fixture(scope="module", autouse=True)` async 写法
2. **PowerShell 5.1 `\"` 不是合法转义**：容器内调 `docker exec ... bash -c "..."` 包装跑容器内 bash
3. **pytest 命令必须带 PYTHONPATH + cwd**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/... -v"`
4. **改 KE 代码后必须 `up -d --no-deps --force-recreate knowledge-engine`**：bind mount 的代码改了容器要拉新进程才生效（main.py / routers/ 更敏感）
5. **trace 不在顶级**：mcp.tool_calls.result 是 JSONB，trace 嵌里面（如 generate_brief 的 result 里有 `trace: {provider, model, ...}`）。前端取 `row.result?.trace`
6. **asyncpg 返 Record 不是 dict**：转 dict 用 `dict(row)` 或显式列名访问，JSONB 字段返 Python str 要 `json.loads()` 二次解析（KE 现有代码用 `asyncpg.init_connection(..., codec=...)` 应已注册 jsonb codec — 看 `app/database.py` 验证；如果没注册手动 `json.loads(row["result"])`）
7. **uuid 入参必须 UUID 类型**：`pool.fetchrow(... WHERE id=$1, uuid.UUID(call_id))`，传 str 会 `InvalidTextRepresentationError`
8. **pattern_lib 写盘是 sync IO**：`open(..., "a", encoding="utf-8")` 直接调，不要 aiofiles
9. **前端 API route `dynamic = 'force-dynamic'` 必加**：否则 Next.js build 阶段会预渲染（`/agent-log` 是动态的不能缓存）
10. **shadcn Sheet 组件可能没装**：T3 写抽屉时先看 `frontend/src/components/ui/` 有没有 sheet.tsx，没有就用 `@base-ui/react` 的 Dialog 或自写一个简单的右侧 panel（不要 `npx shadcn add sheet` 因为这切片不引新组件库）
11. **Next.js dynamic route 参数解构**：14.x App Router `[id]/route.ts` 用 `({ params }: { params: { id: string } })`，注意是同步 destructure 不是 await（next 15 才异步）
12. **rate API 写盘失败要回滚**：T1 实现里如果 `pattern_lib.append_successful_pattern` 抛错（host 文件系统满 / permission），DB 已写 user_rating 怎么办？决策：捕获异常返 `{ok:true, warning:"pattern 写盘失败但 DB 已记录"}`，**不回滚 DB**（评分本身已生效，pattern 是辅助）
13. **24h 概览查询用 `created_at >= NOW() - INTERVAL '24 hours'`**：不要用 timezone naive 的 Python datetime
14. **skill description 必须可触发**：cost-luru SKILL.md frontmatter description 写得模糊 Claude Code 不会触发（W4-A codify 学到的教训）。用"录入成本（物流/包装/原料/供应商报价）..."直接命中关键词
15. **lucide-react 图标按需 import**：`import { Activity, ThumbsUp, ThumbsDown, RotateCcw } from 'lucide-react'`，禁止整包 import
16. **rating_note 可空**：DB 列允许 NULL，前端不填 note 时传空字符串 ""，KE 写 `note or ""`
17. **list endpoint 默认排序 `created_at DESC`**：老板要看最近的在最上面
18. **status filter 多选**：list endpoint 接 `status=completed,error` 这种 CSV 拆开 `IN ($1, $2)` 查（asyncpg 不支持 IN 数组，用 `= ANY($1::text[])`）

---

## 任务总览（5 task）

| Task | 名称 | 类型 | 估时 |
|---|---|---|---|
| T1 | KE 加 mcp.tool_calls REST router（list / detail / rate 3 endpoint） | 后端 TDD | 90 min |
| T2 | 前端 3 个 API proxy route | 前端 | 30 min |
| T3 | 前端 /agent-log 页（24h 概览 + 主表 + 抽屉 + 评分按钮 + sidebar） | 前端 | 120 min |
| T4 | skill cost-luru（项目内 .claude/skills/） | skill markdown | 60 min |
| T5 | e2e 验证（双轨跑一遍）+ commit + 更新 memory | 收尾 | 30 min |

总计：5 task / ~5.5 小时（subagent-driven 模式）。

---

## Task 1: KE 加 mcp.tool_calls REST router（list / detail / rate）

**Goal:** 给前端开 HTTP 通路，3 个 endpoint 走 FastAPI，复用 asyncpg pool + W4-A 的 pattern_lib。TDD 跑通。

**Files:**
- Create: `services/knowledge-engine/app/services/agent_log_service.py`
- Create: `services/knowledge-engine/app/routers/mcp_tool_calls.py`
- Create: `services/knowledge-engine/app/schemas/mcp_tool_calls.py`
- Create: `services/knowledge-engine/tests/test_router_mcp_tool_calls.py`
- Modify: `services/knowledge-engine/app/main.py:80`
- Modify: `services/knowledge-engine/app/mcp/tools/feedback.py`（rate_tool_call 内部改调 service helper）

### Step 1: 写测试 fixture + list endpoint 测试

写 `services/knowledge-engine/tests/test_router_mcp_tool_calls.py`：

```python
"""Tests for /api/v1/mcp/tool-calls REST router (W4-B 切片 1 T1)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import get_pool
from app.main import app


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed_tool_calls():
    """T1 测试前清表 + 塞 5 条已知数据。"""
    pool = get_pool()
    # 清旧测试数据（只删 tool_name='__t1_seed__' 的，不动真实数据）
    await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_seed_%'")
    now = datetime.now(timezone.utc)
    seed_ids = []
    for i, (tool, status, rating, dur) in enumerate([
        ("__t1_seed_query_costs", "completed", "good", 120),
        ("__t1_seed_record_cost", "completed", None, 80),
        ("__t1_seed_generate_brief", "completed", "bad", 5400),
        ("__t1_seed_search_kb", "error", None, 3000),
        ("__t1_seed_record_cost", "pending", None, None),
    ]):
        new_id = uuid.uuid4()
        await pool.execute(
            """INSERT INTO mcp.tool_calls
               (id, tool_name, args, result, status, require_approval,
                duration_ms, user_rating, created_at)
               VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7, $8, $9)""",
            new_id, tool, json.dumps({"sku_id": "SKU-A"}),
            json.dumps({"ok": True, "trace": {"provider": "anthropic"}}) if status == "completed" else None,
            status, status == "pending", dur, rating,
            now - timedelta(minutes=i * 10),
        )
        seed_ids.append(str(new_id))
    yield seed_ids
    await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_seed_%'")


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ─── list endpoint ────────────────────────────────────────────────────────


async def test_list_returns_recent_calls(client, _seed_tool_calls):
    """GET /api/v1/mcp/tool-calls 返最近调用，DESC 排序，含 summary_24h。"""
    resp = await client.get("/api/v1/mcp/tool-calls?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "summary_24h" in body
    seed_rows = [r for r in body["data"] if r["tool_name"].startswith("__t1_seed_")]
    assert len(seed_rows) == 5  # 全在
    # DESC 排序：第一条是 i=0 的（最近）
    assert seed_rows[0]["tool_name"] == "__t1_seed_query_costs"
    # summary_24h 字段齐全
    s = body["summary_24h"]
    assert "success_rate" in s
    assert "avg_duration_ms" in s
    assert "pending_count" in s
    assert "rating_dist" in s


async def test_list_filter_by_status(client, _seed_tool_calls):
    """status=error 过滤。"""
    resp = await client.get("/api/v1/mcp/tool-calls?status=error&limit=10")
    assert resp.status_code == 200
    seed = [r for r in resp.json()["data"] if r["tool_name"].startswith("__t1_seed_")]
    assert len(seed) == 1
    assert seed[0]["tool_name"] == "__t1_seed_search_kb"


async def test_list_filter_by_tool_name(client, _seed_tool_calls):
    resp = await client.get("/api/v1/mcp/tool-calls?tool_name=__t1_seed_record_cost&limit=10")
    assert resp.status_code == 200
    seed = [r for r in resp.json()["data"] if r["tool_name"].startswith("__t1_seed_")]
    assert len(seed) == 2  # 一条 completed 一条 pending


# ─── detail endpoint ──────────────────────────────────────────────────────


async def test_detail_returns_full_row(client, _seed_tool_calls):
    """GET /api/v1/mcp/tool-calls/{id} 返完整行含 result.trace。"""
    target = _seed_tool_calls[0]  # __t1_seed_query_costs (completed + good)
    resp = await client.get(f"/api/v1/mcp/tool-calls/{target}")
    assert resp.status_code == 200
    row = resp.json()["data"]
    assert row["tool_name"] == "__t1_seed_query_costs"
    assert row["user_rating"] == "good"
    assert row["result"]["trace"]["provider"] == "anthropic"
    assert row["args"]["sku_id"] == "SKU-A"


async def test_detail_404(client):
    bogus = uuid.uuid4()
    resp = await client.get(f"/api/v1/mcp/tool-calls/{bogus}")
    assert resp.status_code == 404


# ─── rate endpoint ────────────────────────────────────────────────────────


async def test_rate_writes_user_rating(client, _seed_tool_calls):
    """POST /api/v1/mcp/tool-calls/{id}/rate 写 user_rating + append patterns.md。"""
    target = _seed_tool_calls[1]  # __t1_seed_record_cost (no rating yet)
    resp = await client.post(
        f"/api/v1/mcp/tool-calls/{target}/rate",
        json={"rating": "good", "note": "录得对"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["rating"] == "good"
    # 验证 DB 真写了
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT user_rating, rating_note FROM mcp.tool_calls WHERE id=$1",
        uuid.UUID(target),
    )
    assert row["user_rating"] == "good"
    assert row["rating_note"] == "录得对"


async def test_rate_invalid_rating(client, _seed_tool_calls):
    target = _seed_tool_calls[2]
    resp = await client.post(
        f"/api/v1/mcp/tool-calls/{target}/rate",
        json={"rating": "awesome"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_rating"


async def test_rate_call_not_found(client):
    bogus = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/mcp/tool-calls/{bogus}/rate",
        json={"rating": "good"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 1: 写上面这个 test 文件**

```bash
# 文件创建后立刻验证 import 不挂
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c 'from tests import test_router_mcp_tool_calls'"
```

Expected: 不报错（虽然 fixture/router 还没建，但 import 本身要过）。如报错说"No module named 'app.routers.mcp_tool_calls'" 是预期的（下面 Step 3 写）。

- [ ] **Step 2: 跑测试预期失败**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_router_mcp_tool_calls.py -v"
```

Expected: 7 个测试全 ERROR 或 FAIL（route 还没建 / endpoint 不存在）。

### Step 3: 写 Pydantic schemas

写 `services/knowledge-engine/app/schemas/mcp_tool_calls.py`：

```python
"""Schemas for /api/v1/mcp/tool-calls REST router (W4-B 切片 1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallRow(BaseModel):
    """mcp.tool_calls 一行（list 用精简版，detail 用全字段）。"""
    id: str
    tool_name: str
    status: str
    require_approval: bool
    duration_ms: int | None = None
    user_rating: str | None = None
    rating_note: str | None = None
    model_used: str | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    # detail-only
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class Summary24h(BaseModel):
    """24h 概览统计。"""
    total: int
    success_rate: float  # 0.0-1.0
    avg_duration_ms: int | None
    pending_count: int
    rating_dist: dict[str, int]  # {good, bad, redo, none}


class ToolCallListResponse(BaseModel):
    data: list[ToolCallRow]
    total: int
    summary_24h: Summary24h


class ToolCallDetailResponse(BaseModel):
    data: ToolCallRow


class RateRequest(BaseModel):
    rating: Literal["good", "bad", "redo"]
    note: str = Field(default="", max_length=500)


class RateResponse(BaseModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    hint: str | None = None
```

- [ ] **Step 3: 创建 schemas 文件**

### Step 4: 写 service layer（list / get / rate logic 复用 pattern_lib）

写 `services/knowledge-engine/app/services/agent_log_service.py`：

```python
"""Agent log service：聚合 mcp.tool_calls 查询 + 评分写入。

复用 W4-A 的 pattern_lib。被 router (前端入口) 和 mcp.tools.feedback (Claude Code
入口) 共同调，避免逻辑重复。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.database import get_pool
from app.mcp import pattern_lib

logger = logging.getLogger(__name__)

_VALID_RATINGS = {"good", "bad", "redo"}


def _row_to_dict(row, *, include_full: bool) -> dict[str, Any]:
    """asyncpg.Record → dict，include_full=True 时含 args/result。"""
    d = {
        "id": str(row["id"]),
        "tool_name": row["tool_name"],
        "status": row["status"],
        "require_approval": row["require_approval"],
        "duration_ms": row["duration_ms"],
        "user_rating": row["user_rating"],
        "rating_note": row["rating_note"],
        "model_used": row["model_used"],
        "error": row["error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }
    if include_full:
        # asyncpg 默认对 JSONB 自动 decode 成 Python dict（KE 已注册 codec）
        # 万一返 str 兜底 json.loads
        args = row["args"]
        if isinstance(args, str):
            args = json.loads(args)
        result = row["result"]
        if isinstance(result, str):
            result = json.loads(result)
        d["args"] = args
        d["result"] = result
    return d


async def list_tool_calls(
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    tool_name: str | None = None,
    since_hours: int = 168,  # 默认 7 天
) -> dict[str, Any]:
    """返 {data, total, summary_24h}."""
    pool = get_pool()
    where = ["created_at >= NOW() - ($1 || ' hours')::interval"]
    params: list[Any] = [str(since_hours)]
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        where.append(f"status = ANY(${len(params) + 1}::text[])")
        params.append(statuses)
    if tool_name:
        where.append(f"tool_name = ${len(params) + 1}")
        params.append(tool_name)

    where_sql = " AND ".join(where)
    rows = await pool.fetch(
        f"""SELECT id, tool_name, args, result, status, require_approval,
                   duration_ms, error, user_rating, rating_note, model_used,
                   created_at, completed_at
              FROM mcp.tool_calls
             WHERE {where_sql}
             ORDER BY created_at DESC
             LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}""",
        *params, limit, offset,
    )
    total_row = await pool.fetchrow(
        f"SELECT COUNT(*) AS c FROM mcp.tool_calls WHERE {where_sql}", *params,
    )

    # 24h summary 单查（不受 since_hours 影响）
    s_rows = await pool.fetch(
        """SELECT status, user_rating, duration_ms
             FROM mcp.tool_calls
            WHERE created_at >= NOW() - INTERVAL '24 hours'""",
    )
    s_total = len(s_rows)
    s_completed = sum(1 for r in s_rows if r["status"] == "completed")
    s_pending = sum(1 for r in s_rows if r["status"] == "pending")
    durs = [r["duration_ms"] for r in s_rows if r["duration_ms"] is not None]
    avg_dur = int(sum(durs) / len(durs)) if durs else None
    rating_dist = {"good": 0, "bad": 0, "redo": 0, "none": 0}
    for r in s_rows:
        rating_dist[r["user_rating"] or "none"] = rating_dist.get(r["user_rating"] or "none", 0) + 1

    return {
        "data": [_row_to_dict(r, include_full=False) for r in rows],
        "total": total_row["c"],
        "summary_24h": {
            "total": s_total,
            "success_rate": (s_completed / s_total) if s_total else 0.0,
            "avg_duration_ms": avg_dur,
            "pending_count": s_pending,
            "rating_dist": rating_dist,
        },
    }


async def get_tool_call(call_id: str) -> dict[str, Any] | None:
    """返单行（含 args/result/trace）or None。"""
    try:
        cid = uuid.UUID(call_id)
    except (ValueError, TypeError):
        return None
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, tool_name, args, result, status, require_approval,
                  duration_ms, error, user_rating, rating_note, model_used,
                  created_at, completed_at
             FROM mcp.tool_calls WHERE id=$1""",
        cid,
    )
    if row is None:
        return None
    return _row_to_dict(row, include_full=True)


async def rate_tool_call_logic(
    call_id: str,
    rating: str,
    note: str = "",
) -> dict[str, Any]:
    """评分核心逻辑：写 DB + append patterns.md。

    复用方：
    - app/routers/mcp_tool_calls.py POST /rate （前端入口）
    - app/mcp/tools/feedback.py rate_tool_call MCP tool（Claude Code 入口）
    """
    if rating not in _VALID_RATINGS:
        return {
            "ok": False,
            "error": "invalid_rating",
            "hint": f"rating 必须是 {sorted(_VALID_RATINGS)} 之一",
        }

    try:
        cid = uuid.UUID(call_id)
    except (ValueError, TypeError):
        return {
            "ok": False,
            "error": "invalid_call_id",
            "hint": "call_id 必须是 uuid 字符串",
        }

    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE mcp.tool_calls SET user_rating=$1, rating_note=$2 "
        "WHERE id=$3 RETURNING tool_name",
        rating, note, cid,
    )
    if row is None:
        return {
            "ok": False,
            "error": "call_not_found",
            "hint": f"call_id={call_id} 不存在",
        }

    tool_name = row["tool_name"]
    warning = None
    try:
        if rating == "good":
            pattern_lib.append_successful_pattern(
                tool_call_id=call_id, tool_name=tool_name, note=note,
            )
        else:
            pattern_lib.append_failed_pattern(
                tool_call_id=call_id, tool_name=tool_name, note=note,
            )
    except Exception as exc:
        logger.warning("pattern_lib append failed: %s", exc)
        warning = f"pattern 写盘失败但 DB 已记录: {exc}"

    out = {
        "ok": True,
        "result": {"call_id": call_id, "rating": rating, "tool_name": tool_name},
    }
    if warning:
        out["warning"] = warning
    return out
```

- [ ] **Step 4: 创建 service 文件**

### Step 5: 写 router

写 `services/knowledge-engine/app/routers/mcp_tool_calls.py`：

```python
"""REST router for mcp.tool_calls (W4-B 切片 1).

GET    /api/v1/mcp/tool-calls         list 最近调用 + 24h summary
GET    /api/v1/mcp/tool-calls/{id}    单行详情含 args/result/trace
POST   /api/v1/mcp/tool-calls/{id}/rate  评分（写 user_rating + append patterns.md）

不调 LLM、不走 Human Gate。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.mcp_tool_calls import (
    RateRequest,
    RateResponse,
    ToolCallDetailResponse,
    ToolCallListResponse,
)
from app.services.agent_log_service import (
    get_tool_call,
    list_tool_calls,
    rate_tool_call_logic,
)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-tool-calls"])


@router.get("/tool-calls")
async def list_calls(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    tool_name: str | None = None,
    since_hours: int = Query(168, ge=1, le=720),
) -> dict:
    return await list_tool_calls(
        limit=limit, offset=offset, status=status_filter,
        tool_name=tool_name, since_hours=since_hours,
    )


@router.get("/tool-calls/{call_id}")
async def get_call(call_id: str) -> dict:
    row = await get_tool_call(call_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tool_call {call_id} 不存在",
        )
    return {"data": row}


@router.post("/tool-calls/{call_id}/rate")
async def rate_call(call_id: str, payload: RateRequest) -> dict:
    result = await rate_tool_call_logic(
        call_id=call_id, rating=payload.rating, note=payload.note,
    )
    if not result.get("ok"):
        if result.get("error") == "call_not_found":
            raise HTTPException(status_code=404, detail=result)
        raise HTTPException(status_code=400, detail=result)
    return result
```

- [ ] **Step 5: 创建 router 文件**

### Step 6: 注册 router 到 main.py

改 `services/knowledge-engine/app/main.py`，在 line 80 后加：

```python
from app.routers.mcp_tool_calls import router as mcp_tool_calls_router  # 顶部 import 区
# ...
app.include_router(mcp_tool_calls_router)  # 跟其他 include_router 排一起
```

- [ ] **Step 6: 改 main.py 注册 router**

### Step 7: 重构 feedback.py 复用 service

改 `services/knowledge-engine/app/mcp/tools/feedback.py`，把核心逻辑替换为调 `agent_log_service`：

```python
"""W4-A T2: rate_tool_call MCP tool (W4-B T1 后内部调 agent_log_service)。"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services.agent_log_service import rate_tool_call_logic

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def rate_tool_call(call_id: str, rating: str, note: str = "") -> dict:
    """对一个历史 tool_call 打分（good/bad/redo）。

    Args:
        call_id: mcp.tool_calls.id（uuid str）
        rating: good | bad | redo
        note: 可选备注

    Returns:
        {ok, result: {call_id, rating, tool_name}}（出错时 {ok:false, error, hint}）
    """
    result = await rate_tool_call_logic(call_id=call_id, rating=rating, note=note)
    if result.get("ok"):
        logger.info("rate_tool_call call_id=%s rating=%s tool=%s",
                    call_id[:8], rating, result["result"]["tool_name"])
    return result
```

- [ ] **Step 7: 改 feedback.py 复用 service**

### Step 8: force-recreate 容器 + 跑测试

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" up -d --no-deps --force-recreate knowledge-engine
Start-Sleep -Seconds 5
docker logs omni-knowledge-engine --tail 20
```

Expected: `Application startup complete` + `MCP server` 之类日志，没 ImportError。

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_router_mcp_tool_calls.py -v"
```

Expected: 7 个测试全 PASS。如果 `test_rate_writes_user_rating` 因 patterns.md 写盘失败要看 host bind mount 是否到位（`docker exec omni-knowledge-engine ls /app/agent_state/`）。

- [ ] **Step 8: 重启容器 + 跑 pytest 全绿**

### Step 9: 容器外手测三 endpoint

```powershell
# list
curl "http://localhost:8002/api/v1/mcp/tool-calls?limit=5" | python -m json.tool

# detail（拿一个真实 id）
$id = (curl "http://localhost:8002/api/v1/mcp/tool-calls?limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
curl "http://localhost:8002/api/v1/mcp/tool-calls/$id" | python -m json.tool

# rate（用上面那个 id）
curl -X POST "http://localhost:8002/api/v1/mcp/tool-calls/$id/rate" `
  -H "Content-Type: application/json" `
  -d '{"rating":"good","note":"T1 手测"}' | python -m json.tool
```

Expected: 三次 200，rate 后查 host `data/agent_state/successful_patterns.md` 看新增一行（带 T1 手测 note）。手测留痕后用 `git checkout data/agent_state/successful_patterns.md` 还原（force-add 的 placeholder）。

- [ ] **Step 9: 容器外 curl 三 endpoint 手测**

### Step 10: T1 commit

```bash
cd /e/agent/omni
git add services/knowledge-engine/app/services/agent_log_service.py \
        services/knowledge-engine/app/routers/mcp_tool_calls.py \
        services/knowledge-engine/app/schemas/mcp_tool_calls.py \
        services/knowledge-engine/tests/test_router_mcp_tool_calls.py \
        services/knowledge-engine/app/main.py \
        services/knowledge-engine/app/mcp/tools/feedback.py
git commit -m "feat(W4-B): KE /api/v1/mcp/tool-calls REST router 3 endpoint（W4-B T1）"
```

- [ ] **Step 10: T1 commit**

---

## Task 2: 前端 3 个 API proxy route

**Goal:** Next.js 端 `/api/omni/agent-log/*` 三 route 转发到 KE，复用 `_shared.ts` 模式。

**Files:**
- Create: `frontend/src/app/api/omni/agent-log/route.ts`
- Create: `frontend/src/app/api/omni/agent-log/[id]/route.ts`
- Create: `frontend/src/app/api/omni/agent-log/[id]/rate/route.ts`

### Step 1: list route

写 `frontend/src/app/api/omni/agent-log/route.ts`：

```typescript
import { fetchJson, serviceBase } from '../_shared'
import type { NextRequest } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const base = serviceBase()
  const sp = req.nextUrl.searchParams
  const qs = new URLSearchParams()
  for (const k of ['limit', 'offset', 'status', 'tool_name', 'since_hours']) {
    const v = sp.get(k)
    if (v != null) qs.set(k, v)
  }
  try {
    const data = await fetchJson<{ data: any[]; total: number; summary_24h: any }>(
      `${base.knowledge}/api/v1/mcp/tool-calls?${qs.toString()}`,
    )
    return Response.json({ success: true, ...data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
```

- [ ] **Step 1: 创建 list route**

### Step 2: detail route

写 `frontend/src/app/api/omni/agent-log/[id]/route.ts`：

```typescript
import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(_req: Request, ctx: { params: { id: string } }) {
  const base = serviceBase()
  const { id } = ctx.params
  try {
    const data = await fetchJson<{ data: any }>(
      `${base.knowledge}/api/v1/mcp/tool-calls/${encodeURIComponent(id)}`,
    )
    return Response.json({ success: true, ...data })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    const isNotFound = /404|不存在|not.*found/i.test(msg)
    return Response.json(
      { success: false, error: msg },
      { status: isNotFound ? 404 : 502 },
    )
  }
}
```

- [ ] **Step 2: 创建 detail route**

### Step 3: rate route

写 `frontend/src/app/api/omni/agent-log/[id]/rate/route.ts`：

```typescript
import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface RateBody {
  rating: 'good' | 'bad' | 'redo'
  note?: string
}

export async function POST(req: Request, ctx: { params: { id: string } }) {
  const base = serviceBase()
  const { id } = ctx.params
  let body: RateBody
  try {
    body = await req.json()
  } catch {
    return Response.json({ success: false, error: 'invalid_json' }, { status: 400 })
  }
  try {
    const data = await fetchJson<{ ok: boolean; result?: any; error?: string }>(
      `${base.knowledge}/api/v1/mcp/tool-calls/${encodeURIComponent(id)}/rate`,
      {
        method: 'POST',
        body: JSON.stringify({ rating: body.rating, note: body.note ?? '' }),
      },
    )
    return Response.json({ success: true, ...data })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return Response.json({ success: false, error: msg }, { status: 502 })
  }
}
```

- [ ] **Step 3: 创建 rate route**

### Step 4: 启 dev server + 手测三 route

```powershell
# 假设 dev-start.ps1 已起；如未起，单独起 frontend：
# cd E:\agent\omni\frontend; npm run dev
# 等 "Ready" 提示

# list
curl "http://localhost:3000/api/omni/agent-log?limit=3" | python -m json.tool

# detail（拿真 id）
$id = (curl "http://localhost:3000/api/omni/agent-log?limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
curl "http://localhost:3000/api/omni/agent-log/$id" | python -m json.tool

# rate
curl -X POST "http://localhost:3000/api/omni/agent-log/$id/rate" `
  -H "Content-Type: application/json" `
  -d '{"rating":"good","note":"T2 proxy 手测"}' | python -m json.tool
```

Expected: 三次 200，跟 T1 直调 KE 数据一致。

- [ ] **Step 4: 浏览器/curl 手测三 proxy route**

### Step 5: T2 commit

```bash
git add frontend/src/app/api/omni/agent-log/
git commit -m "feat(W4-B): 前端 3 个 agent-log API proxy route（W4-B T2）"
```

- [ ] **Step 5: T2 commit**

---

## Task 3: 前端 /agent-log 页

**Goal:** 写主页 = 24h 概览 4 卡 + 主表 + trace 抽屉 + 评分按钮 + sidebar 入口。借鉴 `decisions/page.tsx` 风格。

**Files:**
- Create: `frontend/src/app/agent-log/page.tsx`
- Modify: `frontend/src/components/app-sidebar.tsx`（加菜单项）

### Step 1: 看 sidebar 现有菜单结构

```bash
# 先 Read 现有 app-sidebar.tsx 找到菜单数组定义
```

具体行号实施时再定，预期结构是 `const items = [{ title, url, icon }, ...]`。

- [ ] **Step 1: 阅读 app-sidebar.tsx 找菜单数组**

### Step 2: 写 page.tsx 主体（含 24h 概览 + 主表 + 抽屉 + 评分按钮）

写 `frontend/src/app/agent-log/page.tsx`：

```tsx
'use client'

import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Activity, ThumbsUp, ThumbsDown, RotateCcw, X,
  CheckCircle2, XCircle, Clock, Loader2,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ToolCallRow {
  id: string
  tool_name: string
  status: string
  require_approval: boolean
  duration_ms: number | null
  user_rating: string | null
  rating_note: string | null
  model_used: string | null
  error: string | null
  created_at: string
  completed_at: string | null
  args?: Record<string, unknown>
  result?: Record<string, unknown>
}

interface Summary24h {
  total: number
  success_rate: number
  avg_duration_ms: number | null
  pending_count: number
  rating_dist: Record<string, number>
}

interface ListResp {
  success: boolean
  data: ToolCallRow[]
  total: number
  summary_24h: Summary24h
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  completed: { label: '完成',   cls: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
  pending:   { label: '待批',   cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  approved:  { label: '已批',   cls: 'bg-blue-100 text-blue-700 border-blue-200' },
  rejected:  { label: '驳回',   cls: 'bg-rose-100 text-rose-700 border-rose-200' },
  error:     { label: '错',     cls: 'bg-red-100 text-red-700 border-red-200' },
  orphaned:  { label: '孤儿',   cls: 'bg-gray-100 text-gray-700 border-gray-200' },
}

const RATING_BADGE: Record<string, { icon: string; cls: string }> = {
  good: { icon: '👍', cls: 'bg-green-50 text-green-700 border-green-200' },
  bad:  { icon: '👎', cls: 'bg-red-50 text-red-700 border-red-200' },
  redo: { icon: '🔁', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
}

function fmtDur(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60_000).toFixed(1)}min`
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMin = Math.floor((now.getTime() - d.getTime()) / 60_000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)} 小时前`
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AgentLogPage() {
  const [rows, setRows] = useState<ToolCallRow[]>([])
  const [summary, setSummary] = useState<Summary24h | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [openRow, setOpenRow] = useState<ToolCallRow | null>(null)
  const [rating, setRating] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const qs = statusFilter ? `?status=${statusFilter}&limit=100` : '?limit=100'
      const resp = await fetch(`/api/omni/agent-log${qs}`)
      const data: ListResp = await resp.json()
      if (data.success) {
        setRows(data.data)
        setSummary(data.summary_24h)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [statusFilter])

  async function openDetail(id: string) {
    setOpenId(id)
    setOpenRow(null)
    const resp = await fetch(`/api/omni/agent-log/${id}`)
    const data = await resp.json()
    if (data.success) setOpenRow(data.data)
  }

  async function submitRating(id: string, r: 'good' | 'bad' | 'redo') {
    setRating(id)
    try {
      const note = r !== 'good' ? (window.prompt('备注（可选）：') ?? '') : ''
      const resp = await fetch(`/api/omni/agent-log/${id}/rate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: r, note }),
      })
      const data = await resp.json()
      if (data.success && data.ok) {
        setRows((prev) => prev.map((x) => x.id === id ? { ...x, user_rating: r, rating_note: note } : x))
        if (openRow?.id === id) setOpenRow({ ...openRow, user_rating: r, rating_note: note })
      }
    } finally {
      setRating(null)
    }
  }

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <Activity className="w-7 h-7 text-violet-600" />
            Agent 日志
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            看 omni 跑了啥 / 给好坏打分 / 自动累积到 patterns.md
          </p>
        </div>
      </div>

      {/* 24h Summary */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="24h 调用" value={summary.total} icon={<Activity className="w-4 h-4" />} />
          <StatCard label="成功率" value={`${(summary.success_rate * 100).toFixed(0)}%`} icon={<CheckCircle2 className="w-4 h-4 text-emerald-600" />} />
          <StatCard label="平均耗时" value={fmtDur(summary.avg_duration_ms)} icon={<Clock className="w-4 h-4 text-blue-600" />} />
          <StatCard label="待批 / 评分" value={`${summary.pending_count} / 👍${summary.rating_dist.good ?? 0} 👎${summary.rating_dist.bad ?? 0}`} icon={<ThumbsUp className="w-4 h-4 text-violet-600" />} />
        </div>
      )}

      {/* Status filter */}
      <div className="flex gap-1.5 mb-4 flex-wrap">
        {[
          { key: '',         label: '全部' },
          { key: 'completed', label: '完成' },
          { key: 'pending',   label: '待批' },
          { key: 'error',     label: '错误' },
        ].map((f) => (
          <button
            key={f.key}
            onClick={() => setStatusFilter(f.key)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${
              statusFilter === f.key
                ? 'bg-violet-600 text-white shadow'
                : 'bg-white border border-gray-200 text-gray-600 hover:border-violet-300'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Main table */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-gray-300" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center text-sm text-gray-500">
            没记录
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => (
            <div
              key={r.id}
              className="flex items-center gap-3 px-4 py-3 bg-white border border-gray-200 rounded-lg hover:border-violet-300 hover:shadow-sm transition cursor-pointer"
              onClick={() => openDetail(r.id)}
            >
              <code className="text-xs text-gray-400 font-mono w-16 truncate">{r.id.slice(0, 8)}</code>
              <span className="font-medium text-gray-900 flex-1 truncate">{r.tool_name}</span>
              <Badge className={STATUS_BADGE[r.status]?.cls ?? 'bg-gray-100'}>
                {STATUS_BADGE[r.status]?.label ?? r.status}
              </Badge>
              <span className="text-xs text-gray-500 w-16 text-right">{fmtDur(r.duration_ms)}</span>
              <span className="text-xs text-gray-400 w-24 text-right">{fmtTime(r.created_at)}</span>
              {r.user_rating && (
                <Badge className={RATING_BADGE[r.user_rating]?.cls}>
                  {RATING_BADGE[r.user_rating]?.icon}
                </Badge>
              )}
              <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                <Button size="sm" variant="ghost" disabled={rating === r.id || r.user_rating === 'good'}
                        onClick={() => submitRating(r.id, 'good')}>
                  <ThumbsUp className="w-3.5 h-3.5" />
                </Button>
                <Button size="sm" variant="ghost" disabled={rating === r.id || r.user_rating === 'bad'}
                        onClick={() => submitRating(r.id, 'bad')}>
                  <ThumbsDown className="w-3.5 h-3.5" />
                </Button>
                <Button size="sm" variant="ghost" disabled={rating === r.id || r.user_rating === 'redo'}
                        onClick={() => submitRating(r.id, 'redo')}>
                  <RotateCcw className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Detail drawer (right side panel, simple inline implementation) */}
      {openId && (
        <div className="fixed inset-0 z-40" onClick={() => { setOpenId(null); setOpenRow(null) }}>
          <div className="absolute inset-0 bg-black/30" />
          <div
            className="absolute top-0 right-0 h-full w-full md:w-[640px] bg-white shadow-2xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">tool_call 详情</h3>
              <button onClick={() => { setOpenId(null); setOpenRow(null) }} className="text-gray-400 hover:text-gray-700">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              {openRow == null ? (
                <Loader2 className="w-6 h-6 animate-spin text-gray-300 mx-auto my-12" />
              ) : (
                <>
                  <DetailRow label="ID"       value={openRow.id} mono />
                  <DetailRow label="tool"     value={openRow.tool_name} />
                  <DetailRow label="status"   value={openRow.status} />
                  <DetailRow label="model"    value={openRow.model_used ?? '—'} />
                  <DetailRow label="耗时"     value={fmtDur(openRow.duration_ms)} />
                  <DetailRow label="开始"     value={fmtTime(openRow.created_at)} />
                  <DetailRow label="评分"     value={openRow.user_rating ?? '未评'} />
                  {openRow.rating_note && <DetailRow label="备注" value={openRow.rating_note} />}
                  {openRow.error && <DetailRow label="错误" value={openRow.error} mono />}
                  <DetailJson label="args"   value={openRow.args} />
                  <DetailJson label="result" value={openRow.result} />
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-4 flex items-center gap-3">
        <div className="text-gray-400">{icon}</div>
        <div>
          <div className="text-xs text-gray-500">{label}</div>
          <div className="text-lg font-semibold text-gray-900">{value}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-gray-500 w-16 shrink-0">{label}</span>
      <span className={`flex-1 ${mono ? 'font-mono text-xs' : 'text-gray-900'}`}>{value}</span>
    </div>
  )
}

function DetailJson({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null
  return (
    <div>
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto whitespace-pre-wrap break-words">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}
```

- [ ] **Step 2: 创建 /agent-log/page.tsx**

### Step 3: 注册到 sidebar

打开 `frontend/src/components/app-sidebar.tsx`，找到菜单项数组（路径 A 桥接代码已引入决策日志/巡店等），按现有模式加：

```tsx
// 假设结构如：const navItems = [{ title: '决策日志', href: '/decisions', icon: ClipboardCheck }, ...]
// 找到合适分组后插入：
{ title: 'Agent 日志', href: '/agent-log', icon: Activity },
```

**注意**：`Activity` 图标已 `import { Activity } from 'lucide-react'`，如未导入需补。具体插入位置看现有 sidebar 5 段重排（reference_omni_assets memory 提示 W3 时已重排）。

- [ ] **Step 3: 改 sidebar 加菜单项**

### Step 4: 浏览器验收 + 截图

启 dev server（如未起）：

```powershell
# 假设已起，访问：
# http://localhost:3000/agent-log
```

**验收清单**：
- [ ] 24h 概览 4 卡显示数据（total / success_rate / avg_duration_ms / pending_count + rating_dist）
- [ ] 主表列出 100 条最近调用（DESC 排序）
- [ ] 状态 filter 切换（全部 / 完成 / 待批 / 错误）后表更新
- [ ] 点行打开右侧抽屉，显示 args + result JSON
- [ ] 评分按钮 👍 点了表里 badge 出现 + 抽屉里"评分"行更新
- [ ] 评分点 👎 弹 prompt 让填备注，填了之后写入
- [ ] 评分后查 host `data/agent_state/successful_patterns.md` 看新增行
- [ ] sidebar 有"Agent 日志"菜单项，点能跳转

如果有任何一项不通过，修代码而不是说"已验证"。

- [ ] **Step 4: 浏览器跑通 8 项验收**

### Step 5: T3 commit

```bash
git add frontend/src/app/agent-log/page.tsx \
        frontend/src/components/app-sidebar.tsx
git commit -m "feat(W4-B): /agent-log 页 + sidebar 入口（W4-B T3）"
```

- [ ] **Step 5: T3 commit**

---

## Task 4: skill cost-luru（项目内 .claude/skills/）

**Goal:** 写项目内 markdown skill 把"录成本"标准 SOP 固化，让老板说"录 sku-A 物流费 5 块"自动触发 record_cost → Gate → query_costs 验证 5 步走。

**Files:**
- Create: `.claude/skills/cost-luru/SKILL.md`
- Create: `.claude/skills/cost-luru/examples.md`

### Step 1: 写 SKILL.md（frontmatter + 主文档）

写 `E:\agent\omni\.claude\skills\cost-luru\SKILL.md`：

```markdown
---
name: cost-luru
description: 录入成本（物流/包装/原料/供应商报价）。老板说"录 sku-X 物流费 5 块"、"加成本 包装 0.8"、"录运费"等，触发标准录成本 5 步走 SOP，调用 record_cost 走 Human Gate，批后调 query_costs 验证。
---

# cost-luru：录成本标准 SOP

> 这是 omni-vibe 项目内 skill。当老板提到"录成本/加成本/录入物流费/录运费/sku-X 加 X 块"等话术时，按本 SOP 走 5 步，**不要一气呵成跑完，每步停下来等老板反馈**。

## 触发场景（5 类话术）

| 话术 | 解析 | tool 调用 |
|---|---|---|
| "录 sku-A 物流费 5 块" | sku_id=SKU-A, category=logistics, item_name=物流费, unit_cost=5 | record_cost(...) |
| "sku-B 加成本 包装 0.8" | sku_id=SKU-B, category=product, item_name=包装, unit_cost=0.8 | record_cost(...) |
| "顺丰华东 8 块每单" | sku_id=None（共享）, category=logistics, item_name=顺丰华东, unit_cost=8, unit=单 | record_cost(...) |
| "C 厂商品报价 12 块/箱 24 瓶" | sku_id=None, category=partner_quote, vendor=C 厂, unit=箱, quantity_per_unit=24, unit_cost=12 | record_cost(...) |
| "改 sku-A 物流费 6 块"（已存在） | 先 query_costs 找旧条 → disable_cost_item 停旧 → record_cost 录新 | 3 tool 链 |

## 标准 5 步 SOP

### Step 1: 解析话术 → 推参数

按上面"触发场景"表把老板说的拆成 record_cost 入参。**关键约束**：

- `category` 必须是 `product` / `logistics` / `partner_quote` 之一（不是其他词）
- `unit_cost` 必须是字符串（"0.50" 而不是 0.5），避免 float 误差
- `quantity_per_unit` 默认 "1"，老板说"一箱 24 瓶"才填 "24"
- `unit` 默认 "件"，常见还有 "次"/"箱"/"单"
- `sku_id` 可空（共享成本如顺丰运费 → 全 SKU 用）
- `valid_from` 默认今天，老板说"从昨天开始算"才显式填

**解析完先复述给老板看**，让老板确认参数：

> "我打算录：SKU-A，物流类，「物流费」¥5/件，从今天起。对吗？"

### Step 2: 调 record_cost

老板确认后调：

```python
record_cost(
    sku_id="SKU-A",          # 或 None
    category="logistics",    # product | logistics | partner_quote
    item_name="物流费",
    unit_cost="5",
    currency="CNY",          # 默认
    unit="件",               # 默认
    quantity_per_unit="1",   # 默认
    vendor=None,             # 老板说了供应商才填
    valid_from=None,         # None 默认今天
    valid_to=None,
    notes=None,
)
```

**记住**：record_cost 走 Human Gate（require_approval=True），返回会带 `pending_approval_id`。

### Step 3: 提示老板批 Gate

返回结果给老板看，**告诉他怎么批**：

> "已写入 pending（id 前 8 位：abcd1234），你批一下：
> ```
> docker exec omni-knowledge-engine python -m app.mcp.cli_approve list
> docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve abcd1234 --note "OK"
> ```
> 或者去前端 `/agent-log` 看（如果已开 /inbox 页）。批完跟我说『批好了』。"

如果老板说 `驳/不要/算了` → 用 cli_approve reject 让他驳。

### Step 4: 老板批好后，调 query_costs 验证

```python
query_costs(sku_id="SKU-A", category="logistics")  # 或 sku_id=None 看共享
```

把结果给老板看，**确认刚录的那条在不在**：

> "查到 SKU-A 物流类下 3 条，最新一条「物流费 ¥5/件 从今天起」就是刚录的，✅"

### Step 5: 提示下一步

询问老板要不要继续录别的，或进 sku 全链路（CLAUDE.md 5 步走）。

- 如果老板说"还要录 X"→ 回 Step 1 解析
- 如果老板说"算利润"→ 调 compute_margin
- 如果老板说"OK"→ skill 完成

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `invalid_category` | category 不是 3 选 1 | 跟老板确认是 product/logistics/partner_quote 哪个 |
| `invalid_decimal` | unit_cost 含非数字 / 负数 | 让老板重说价格 |
| `cost_item_not_found_or_already_inactive` | disable 时找不到 | query_costs 看看 id 对不对 |
| Gate 超时（默认 1h） | 老板 1 小时没批 | 提醒老板在 cli_approve list 里看 / 重调 record_cost |

## 反例（**禁止**）

- ❌ 不复述参数直接调 record_cost — 老板可能听错或想改
- ❌ 用 float 而不是 str 传 unit_cost
- ❌ 一气呵成跑完 5 步不停 — 必须每步停下等老板反馈
- ❌ 调用前没先 query_costs 看是否已存在同名条目 — 容易录重复（同一个 SKU 同名不同 category 是允许的，但同 SKU 同名同 category 应先 disable 旧的）
- ❌ 用模糊话术回老板（"已成功录入数据" → ❌；"录好了 SKU-A 物流费 5 块/件" → ✅）

## 已知约束

- record_cost / disable_cost_item 都走 Human Gate（W3a 锁定，本 skill 不绕过）
- 一次 record_cost 只录一条，老板说"批量录 3 条" → skill 拆 3 次走 5 步
- import_costs.py 是 CSV 批量入口，超过 10 条建议老板用脚本而不是 skill：
  ```
  docker exec omni-knowledge-engine python /app/scripts/import_costs.py /app/scripts/cost_template.csv
  ```

## 跟 CLAUDE.md 的关系

CLAUDE.md "老板响应词约定" line 40 写过：
> 录成本 / 加成本 / 录入物流费 → 调 `record_cost(...)`，老板用 `python -m app.mcp.cli_approve approve <id>` 批

本 skill 是这条约定的展开 SOP（更详细 + 5 步走 + 错误处理）。两边话术冲突时以 CLAUDE.md 为准。
```

- [ ] **Step 1: 写 SKILL.md**

### Step 2: 写 examples.md（5 个真实话术 → 调用映射）

写 `E:\agent\omni\.claude\skills\cost-luru\examples.md`：

```markdown
# cost-luru 真实话术示例

下面 5 个 case 来自老板日常用语。Claude 解析时按"触发场景表"拆参数。

---

## Case 1: 单品物流费

**老板说**："录 sku-a 顺丰运费 5 块"

**解析**：
- sku_id=SKU-A
- category=logistics
- item_name=顺丰运费
- unit_cost="5"
- vendor="顺丰"

**复述**：
> "录 SKU-A 物流类「顺丰运费」¥5/件，供应商顺丰，从今天起。对吗？"

**调用**：
```
record_cost(sku_id="SKU-A", category="logistics", item_name="顺丰运费",
            unit_cost="5", vendor="顺丰")
```

---

## Case 2: 共享物流费（不绑 SKU）

**老板说**："顺丰华东全店都是 8 块"

**解析**：
- sku_id=None（共享）
- category=logistics
- item_name=顺丰华东
- unit_cost="8"

**复述**：
> "录共享物流费「顺丰华东」¥8/件，所有 SKU 都用。对吗？"

**调用**：
```
record_cost(sku_id=None, category="logistics", item_name="顺丰华东",
            unit_cost="8")
```

---

## Case 3: 包装料

**老板说**："SKU-B 瓶身 0.5"

**解析**：
- sku_id=SKU-B
- category=product
- item_name=瓶身
- unit_cost="0.5"

**复述**：
> "录 SKU-B 产品类「瓶身」¥0.5/件。对吗？"

**调用**：
```
record_cost(sku_id="SKU-B", category="product", item_name="瓶身",
            unit_cost="0.5")
```

---

## Case 4: 厂家报价（按箱）

**老板说**："C 厂报价 12 块一箱 24 瓶"

**解析**：
- sku_id=None（报价不绑特定 SKU）
- category=partner_quote
- item_name=C 厂报价
- unit_cost="12"
- unit="箱"
- quantity_per_unit="24"
- vendor="C 厂"

**复述**：
> "录 C 厂报价：¥12/箱（每箱 24 瓶），供应商 C 厂。对吗？"

**调用**：
```
record_cost(sku_id=None, category="partner_quote", item_name="C 厂报价",
            unit_cost="12", unit="箱", quantity_per_unit="24", vendor="C 厂")
```

---

## Case 5: 改价（先停旧再录新）

**老板说**："SKU-A 物流费涨到 6 块了"

**解析**：先 query_costs 找旧条 → disable 旧 → record 新

**步骤**：

1. **查旧**：
   ```
   query_costs(sku_id="SKU-A", category="logistics")
   ```
   找到 `cost_item_id=abc-123`（item_name="物流费"，unit_cost=5）

2. **复述给老板**：
   > "找到旧条「物流费 ¥5」（id abc12345），新价 ¥6 替换它。要我先停旧再录新吗？"

3. **老板确认后停旧**（Gate 批一次）：
   ```
   disable_cost_item(cost_item_id="abc-123-...", reason="物流费涨价")
   ```

4. **批好后录新**（再 Gate 批一次）：
   ```
   record_cost(sku_id="SKU-A", category="logistics", item_name="物流费",
               unit_cost="6")
   ```

5. **验**：
   ```
   query_costs(sku_id="SKU-A", category="logistics")
   ```
   确认旧条 is_active=False，新条 unit_cost=6。
```

- [ ] **Step 2: 写 examples.md**

### Step 3: 验证 skill 触发

启 Claude Code（如老板已在 omni 项目里），说测试话术：

- "录 SKU-A 物流费 5 块"

Expected: Claude Code 应该按 SKILL.md 5 步走，**Step 1 复述给老板**，停下来等老板回答（不直接调 record_cost）。

如果 Claude 没触发 cost-luru skill 而是裸调 record_cost，看：
1. `.claude/skills/cost-luru/SKILL.md` 路径对不对
2. frontmatter `description` 是不是太抽象（重写让"录入成本/物流费/录运费"等关键词显眼）

- [ ] **Step 3: Claude Code 里测话术触发 skill**

### Step 4: T4 commit

```bash
git add .claude/skills/cost-luru/
git commit -m "feat(skill): cost-luru 录成本标准 5 步 SOP（W4-B T4）"
```

- [ ] **Step 4: T4 commit**

---

## Task 5: e2e 双轨配合验证 + 收尾

**Goal:** 双轨跑一遍：cost-luru skill 触发 → record_cost → cli_approve 批 → query_costs 验 → /agent-log 看到这 3 条调用 → 给 query_costs 评 👍 → patterns.md 写盘。**配合点跑通**才算切片完成。

**Files:**
- Modify: `.claude/settings.local.json`（如缺 grant）
- Update memory: `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`（加 §二十二）

### Step 1: 验证 settings.local.json grant

```powershell
cat E:\agent\omni\.claude\settings.local.json
```

应包含（W3a/W4-A 时已加）：
- `mcp__omni__record_cost`
- `mcp__omni__query_costs`
- `mcp__omni__rate_tool_call`

如果有缺失，加进 `permissions.allow` 数组。

- [ ] **Step 1: 验证或补 grant**

### Step 2: e2e 走一遍 cost-luru skill 全链路

在 Claude Code 里说：

> "录 SKU-CHILI-OIL-300 物流费 4 块"

跟着 skill 5 步走：
1. Claude 复述 → 老板说"对的"
2. Claude 调 record_cost → 返回 pending id
3. 老板用 CLI 批：
   ```powershell
   docker exec omni-knowledge-engine python -m app.mcp.cli_approve list
   docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve <short_id> --note "T5 e2e"
   ```
4. Claude 调 query_costs(sku_id="SKU-CHILI-OIL-300") 验证
5. Claude 提示下一步

**预期**：mcp.tool_calls 表新增至少 3 条（record_cost / query_costs，rate_tool_call 还没调）。

- [ ] **Step 2: e2e cost-luru 5 步走**

### Step 3: 浏览器打开 /agent-log 看刚跑的调用

访问 `http://localhost:3000/agent-log`，应看到：
- 表顶部新增 record_cost（status=completed） + query_costs（status=completed）两行（按时间 DESC）
- 24h 概览 total +2 起码

- [ ] **Step 3: /agent-log 看到 e2e 调用**

### Step 4: 在 /agent-log 给 query_costs 那行评 👍

点 query_costs 行末尾 👍 按钮 → 看：
- 表里 user_rating badge 变 👍
- host 上 `data/agent_state/successful_patterns.md` 文件新增一行（带 query_costs + tool_call_id）

- [ ] **Step 4: 评分写盘验证**

### Step 5: 还原 e2e 留痕（patterns.md 占位回滚）

```bash
cd /e/agent/omni
git checkout data/agent_state/successful_patterns.md  # 回到 placeholder 状态
```

- [ ] **Step 5: 还原占位**

### Step 6: 更新 memory（加 §二十二 W4-B 切片 1 落地总结）

打开 `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`，在 §二十一末尾追加：

```markdown
## 二十二、W4-B 切片 1 落地总结（2026-05-06，subagent-driven 模式）

### W4-B 切片 1 commit 序列（all on `feat/mcp-w1`，2026-05-06）

待补（T1-T5 实施完后填实际 hash）

### W4-B 切片 1 范围（最终拍板）

**做：双轨配合切片**
- KE 加 3 个 REST endpoint（GET list / GET detail / POST rate）走 `/api/v1/mcp/tool-calls`
- 前端 /agent-log 页：24h 概览 + 主表 + 抽屉 + 评分按钮 + sidebar 入口
- 项目内 skill `.claude/skills/cost-luru/SKILL.md` + examples.md（录成本 5 步 SOP）

**不做（→ W4-B 后续切片）**：/inbox / /cost 增强 / 5 业务 skill / W4 加分 5 tool / cron / 修 codify e2e

### 关键技术决策

- **前端无 PG 直连，走 KE REST**：现有 /api/omni/* 全 HTTP 模式，无 pg npm 包；KE 加 endpoint 维持架构一致
- **rate 逻辑抽 service 复用**：`agent_log_service.rate_tool_call_logic` 给 router (前端) + mcp tool feedback (Claude Code) 共用
- **cost-luru 装项目内**：`.claude/skills/`（同进 git，跨设备/同事接手能用）
- **doctor 维持 27**：本切片不加 MCP tool，只加 REST endpoint + 前端 + skill

### 起 W4-B 切片 2 时的环境状态

- branch `feat/mcp-w1`，工作区干净
- 累计 41 commit on `feat/mcp-w1`（W4-A 36 + W4-B 切片 1 plan 1 + 实施 5 = 5 task → 5 commits）
- doctor 27/27 全绿
- 4 容器 + frontend dev server Up
- 双轨可在 /agent-log 上联动观察
```

- [ ] **Step 6: 更新 memory**

### Step 7: T5 final commit

```bash
git add .claude/settings.local.json  # 如有改
git add docs/superpowers/plans/2026-05-06-omni-agent-uplift-W4b-slice1-plan.md  # plan 本身
git commit -m "chore(W4-B): 切片 1 收尾 + e2e 验证 + memory 更新（W4-B T5）"
```

memory 文件不入 git（在 `~/.claude/projects/`），不需要 add。

- [ ] **Step 7: T5 commit**

---

## 自检（Self-Review）

实施完所有 task 后逐项确认：

- [ ] **Spec coverage**：
  - [x] /agent-log list/detail/rate → T1+T2+T3
  - [x] 24h 概览 → T1 service `summary_24h` + T3 StatCard
  - [x] 评分按钮 → T3 submitRating + T1 rate endpoint + W4-A pattern_lib
  - [x] 抽屉 trace 详情 → T3 detail drawer + T1 get_tool_call
  - [x] cost-luru skill → T4
  - [x] 配合点（cost-luru 跑 → /agent-log 看 → 评分）→ T5 e2e
  - [x] sidebar 入口 → T3 Step 3

- [ ] **Placeholder scan**：搜 plan 全文有无 TBD/TODO/"似 Task N"。如有，inline 修。

- [ ] **Type consistency**：
  - `ToolCallRow` (frontend ts) ↔ `ToolCallRow` (backend pydantic) 字段对齐
  - `Summary24h` 字段对齐（total / success_rate / avg_duration_ms / pending_count / rating_dist）
  - `RateRequest`/`RateBody` rating 限定 `'good'|'bad'|'redo'` 两边一致
  - `rate_tool_call_logic` 函数签名 `(call_id, rating, note="")` 在 service / router / feedback.py 一致

- [ ] **关键约束**：
  - [x] 个人自用，不上线 → 无 SLA / 灰度 / 分布式代码
  - [x] skill 装项目内（不是全局）
  - [x] /agent-log 走 HTTP（不是 pg 直连）
  - [x] 写作风格说人话（cost-luru SKILL.md / 错误 hint / 复述话术全过审）
  - [x] subagent-driven 模式（每 task fresh subagent）

如有任何一项不通过，**inline 修 plan 而不是说"已通过"**。

---

## 执行交接

Plan 写完后老板拍：

**1. Subagent-Driven (推荐)** — 5 task 各起 fresh subagent，task 间 review

**2. Inline Execution** — 当前 session 跑完，每 task 后 checkpoint

如选 Subagent-Driven → 调 `superpowers:subagent-driven-development` skill
如选 Inline Execution → 调 `superpowers:executing-plans` skill
