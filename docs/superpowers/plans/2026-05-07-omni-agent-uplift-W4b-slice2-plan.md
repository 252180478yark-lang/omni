# W4-B 切片 2 实施计划：前端 /inbox 待批页（替代 cli_approve CLI）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve <id>` 这条 CLI 痛点搬到前端按钮。每次老板要批 cost / disable_cost_item / refresh_project_context / codify_pattern_to_skill 都不用敲容器命令，桌面或手机直接 /inbox 看待批 → 点批/驳。

**Architecture:** 跟切片 1 同构（后端 REST + 前端 proxy + page）：
- **后端轨**：knowledge-engine 加 `/api/v1/mcp/human-gates` REST router（list / approve / reject 3 endpoint）+ `app/services/inbox_service.py`（list_pending_with_calls / approve_gate / reject_gate，包 short_id 解析）。批/驳逻辑直接复用 `app/mcp/human_gate.py:approve()/reject()`，不重写底层。
- **前端轨**：`/inbox` 页 = pending 卡片列表 + 批/驳按钮（备注选填）+ 自动 refresh；前端 3 个 API proxy route 走切片 1 的"裸 fetch + JSONResponse 透传 status"模式
- **跟切片 1 的关系**：复用 schemas/ 包结构 + JSONResponse 错误格式 + 裸 fetch proxy 模式 + sidebar 入口风格，不引入新基建

**Tech Stack:** FastAPI · asyncpg · pytest-asyncio · Next.js 14 App Router · shadcn/ui（Card/Badge/Button）· lucide-react

---

## 起手就要看的文件（implementer 必读）

### 设计文档与历史 plan
- `docs/superpowers/plans/2026-05-06-omni-agent-uplift-W4b-slice1-plan.md`（切片 1 plan，本切片照葫芦画瓢，结构 1:1 对应）
- `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md` §二十二（切片 1 落地总结，看坑清单防重踩）
- `docs/superpowers/specs/2026-05-03-omni-agent-uplift-design.md` §5（Human Gate 设计，本切片不动设计只加 UI 通路）

### 后端必读现有资产（reuse_existing 强制约束）
- `services/knowledge-engine/app/mcp/human_gate.py`（**Human Gate 真实现**，本切片底层全复用：`list_pending() / approve(gate_id, note) / reject(gate_id, note)` 已就位）
- `services/knowledge-engine/app/mcp/cli_approve.py`（**short_id 解析逻辑**，T1 inbox_service 抽取此处的 `_resolve_id` 模式：`len(short_or_full) >= 32` 走全 uuid 否则前缀扫 pending）
- `services/knowledge-engine/app/services/agent_log_service.py`（**切片 1 service 模板**，T1 的 inbox_service 完全照此结构：错误格式 `{ok:false, error, hint}` + asyncpg pool）
- `services/knowledge-engine/app/routers/mcp_tool_calls.py`（**切片 1 router 模板**，T1 的 human_gates router 1:1 照此：`JSONResponse(content=result, status_code=...)` 透传错误，不用 HTTPException）
- `services/knowledge-engine/app/schemas/mcp_tool_calls.py`（**切片 1 schemas 模板**，T1 的 schemas 照此：rating 用 `str` 不用 `Literal[]`，用 service 层校验避开 FastAPI 422 包装）
- `services/knowledge-engine/app/main.py:82`（include_router 注册位置，加 human_gates_router 在 mcp_tool_calls_router 之后）
- `services/knowledge-engine/tests/test_router_mcp_tool_calls.py`（**切片 1 测试模板**，T1 测试 1:1 照此：fixture seed + httpx ASGITransport + 清理）
- `services/knowledge-engine/tests/test_mcp_human_gate.py`（**human_gate 集成测试模板**，看怎么 INSERT 一条 mcp.tool_calls + mcp.human_gates 做 fixture）

### 前端必读现有资产
- `frontend/src/app/api/omni/_shared.ts`（`serviceBase().knowledge` + `fetchJson<T>`，T2 list 用 `fetchJson`；approve/reject 走裸 fetch）
- `frontend/src/app/api/omni/agent-log/route.ts`（**list proxy 模板**，T2 list 1:1 照此）
- `frontend/src/app/api/omni/agent-log/[id]/rate/route.ts`（**裸 fetch + 透传 status 模板**，T2 approve/reject 1:1 照此 — 关键点：`Response.json({success:r.ok, ...data}, {status:r.status})` 不用 `fetchJson` 因为它会吞 KE 4xx 结构化错误的 hint）
- `frontend/src/app/agent-log/page.tsx`（**前端页风格 + 抽屉 + StatCard + alert 失败 UX 模板**，T3 1:1 借鉴布局，删抽屉部分简化为单页卡片列表）
- `frontend/src/components/app-sidebar.tsx:124-126`（sidebar 注册位置：在 `/agent-log` 那条菜单后加 `/inbox`，归"投放与复盘"或独立加"待批"分组）
- `frontend/src/components/ui/`（shadcn 组件目录，Card/Badge/Button 已就位）

### 数据库 schema（必看，禁止瞎猜）
- `migrations/017_mcp_human_gates.sql`（W3a 加的迁移，确认建表 SQL 与下面一致）
- **mcp.human_gates 完整列**（已 docker exec verify 过）：
  ```
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
  tool_call_id    UUID REFERENCES mcp.tool_calls(id) ON DELETE CASCADE
  summary         TEXT NOT NULL
  decision        TEXT                  -- 'approved' | 'rejected' | NULL(=pending)
  decision_note   TEXT
  decided_at      TIMESTAMPTZ
  timeout_seconds INTEGER NOT NULL DEFAULT 3600
  created_at      TIMESTAMPTZ DEFAULT NOW()

  INDEX idx_human_gates_pending ON (decision) WHERE decision IS NULL
  ```
  **关键**：pending 的判别是 `decision IS NULL`，不是有"pending"字面值。timeout 后 human_gate.py 会 UPDATE decision='rejected' + note 拼 `[timeout]`，所以"超时"也是 rejected 不在 list 出现。

---

## 关键决策（已锁定，禁止再讨论）

1. **复用 human_gate.py 不重写底层**：`approve()/reject()` 已是 idempotent UPDATE（`WHERE decision IS NULL`，二次批返 False），直接调，不抽 service 重写
2. **list 只返 pending（decision IS NULL）**：默认行为；不加 historical 过滤（看历史用 /agent-log 看 require_approval=true 的 tool_calls 串起来）
3. **short_id 解析在 service 层，router 不接 short_id**：URL `/api/v1/mcp/human-gates/{id}/approve` 接受 full uuid OR 8-char short_id，service 内部 `_resolve_id` 解析；CLI 兼容性同时保留
4. **批驳错误格式跟切片 1 对齐**：`{ok:false, error: "gate_not_found" | "ambiguous_short_id" | "already_decided", hint: "..."}` + `JSONResponse(status_code=404|409|400)` 透传
5. **不做 list filter / 历史**：切片 2 只解决 pending UI，list 历史走 /agent-log 二次查（require_approval=true 的 tool_calls 已可见）
6. **不加新 MCP tool**：本切片只加 KE REST endpoint + 前端页，**doctor expected_tools 维持 27**
7. **前端不轮询**：默认 page 加载查一次，加手动 "刷新" 按钮 + 批/驳后自动 reload；不引 SWR/polling 避免长连接基建（auto refresh 每 30s 的可加但优先级低，先 P1 干掉痛点）
8. **批/驳备注是选填 prompt（仿 /agent-log redo 评分备注）**：批默认 note=""，驳必填 note（理由），用 `window.prompt` 凑合（个人自用，UI 不抠细节）
9. **/inbox 加进 sidebar**：T3 末尾改 `frontend/src/components/app-sidebar.tsx`，加在 `/agent-log` 那行附近（推荐"投放与复盘"分组下，跟 Agent 日志相邻）
10. **后端 TDD**：T1 走 pytest TDD（先测试再实现）；前端无单测（项目无 vitest/jest），人工验
11. **个人自用约束**：不上线 / 不多人 / 不分布式 / 不灰度 / 不写 SLA
12. **commit 信号**：每 task 末尾一次 commit，`feat(W4-B): ... (W4-B 切片 2 T<n>)` 风格
13. **写作风格强制**（feedback_writing_style）：所有 user-facing 文案/错误 hint 都说人话（"已批 / 等批 / 驳了"，不是"审批已通过 / 待审批 / 已拒绝"）

---

## 文件结构

### 待建（后端 — 4 个）
- `services/knowledge-engine/app/services/inbox_service.py` — `list_pending() / approve_gate() / reject_gate()` + `_resolve_id()`（~120 行）
- `services/knowledge-engine/app/routers/human_gates.py` — FastAPI router 3 endpoint（~70 行）
- `services/knowledge-engine/app/schemas/human_gates.py` — Pydantic models（~40 行）
- `services/knowledge-engine/tests/test_router_human_gates.py` — TDD 测试（~180 行）

### 待改（后端 — 1 个）
- `services/knowledge-engine/app/main.py` — 加 `from app.routers.human_gates import router as human_gates_router` + `app.include_router(human_gates_router)`（+2 行）

### 待建（前端 — 4 个）
- `frontend/src/app/api/omni/inbox/route.ts` — GET list（~30 行）
- `frontend/src/app/api/omni/inbox/[id]/approve/route.ts` — POST 裸 fetch（~35 行）
- `frontend/src/app/api/omni/inbox/[id]/reject/route.ts` — POST 裸 fetch（~35 行）
- `frontend/src/app/inbox/page.tsx` — 页面主体（~250 行 TSX）

### 待改（前端 — 1 个）
- `frontend/src/components/app-sidebar.tsx` — 加 `/inbox` 菜单项（+1 行）

### 待改（settings — 1 个）
- `.claude/settings.local.json` — 切片 2 不加 MCP tool，**预期不需要新 grant**（T4 验证）

---

## 已知坑（前面切片踩的，防重踩）

1. **PowerShell 5.1 `\"` 不是合法转义**：`docker exec ... bash -c "..."` 包装跑容器内 bash
2. **pytest 命令必须带 PYTHONPATH + cwd**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/... -v"`
3. **改 KE 代码后必须 `up -d --no-deps --force-recreate knowledge-engine`**：bind mount 的代码改了容器要拉新进程才生效
4. **uuid 入参必须 UUID 类型**：`pool.execute(... WHERE id=$1, uuid.UUID(gate_id))`
5. **fetchJson 吞结构化上游错误**（切片 1 T2f 教训）：approve/reject route 必须用裸 fetch + 透传 status，不用 `_shared.ts` 的 `fetchJson`
6. **HTTPException(detail=...) 包错误格式**（切片 1 T1 教训）：用 `JSONResponse(content=result, status_code=...)` 直接透传 service 返的 dict
7. **rating 用 Literal[] 触发 422 绕过错误格式**（切片 1 T1 教训）：本切片 note 字段直接 `str = Field(default="", max_length=500)` 即可（不用 Literal）
8. **测试 fixture 污染共享状态**：本切片不写 patterns.md（不调 pattern_lib），但要清理 mcp.human_gates seed 数据（fixture teardown 用 `WHERE summary LIKE '__t1_seed_%'`）
9. **decision 路径双向都是 UPDATE WHERE decision IS NULL**：approve/reject 已 idempotent，二次调返 `False`（rec=None），service 层翻译成 `{ok:false, error: "already_decided"}` + 409
10. **short_id 撞前缀**：scan pending list 找匹配，>1 个返 `{ok:false, error: "ambiguous_short_id", hint: "短 id 撞了，发完整 uuid"}` + 400；0 个返 `{ok:false, error: "gate_not_found"}` + 404
11. **Next.js dynamic route 参数**：14.x App Router `[id]/approve/route.ts` 用 `({ params }: { params: { id: string } })` 同步 destructure
12. **shell 中文走 CP936 错位**（切片 1 T5 教训）：本切片 e2e 验证如要测中文 note，用 `--data-binary @file.json` + `Content-Type: application/json; charset=utf-8`，不要直接 `-d '{"note":"中文"}'`
13. **lucide-react 按需 import**：`import { Inbox, CheckCircle2, XCircle, RefreshCw } from 'lucide-react'`，禁止整包 import
14. **前端 API route `dynamic = 'force-dynamic'` 必加**：否则 Next.js build 阶段会预渲染
15. **/inbox 页加载失败要 alert（切片 1 T3f 教训）**：list fetch 失败 / approve/reject 失败 silent 不行，必须 `window.alert(data.hint ?? data.error ?? '失败')` 显式告知

---

## 任务总览（4 task）

| Task | 名称 | 类型 | 估时 |
|---|---|---|---|
| T1 | KE 加 human_gates REST router（list / approve / reject 3 endpoint） | 后端 TDD | 90 min |
| T2 | 前端 3 个 API proxy route | 前端 | 30 min |
| T3 | 前端 /inbox 页 + sidebar 入口 | 前端 | 90 min |
| T4 | e2e 验证 + commit + 更新 memory | 收尾 | 30 min |

总计：4 task / ~4 小时（subagent-driven 模式）。比切片 1 少 1 个 task（无 skill markdown），整体规模约 70%。

---

## Task 1: KE 加 human_gates REST router（list / approve / reject）

**Goal:** 给前端开 HTTP 通路，3 个 endpoint 走 FastAPI，复用 `human_gate.py` 底层 + asyncpg pool。TDD 跑通 + 错误路径覆盖。

**Files:**
- Create: `services/knowledge-engine/app/services/inbox_service.py`
- Create: `services/knowledge-engine/app/routers/human_gates.py`
- Create: `services/knowledge-engine/app/schemas/human_gates.py`
- Create: `services/knowledge-engine/tests/test_router_human_gates.py`
- Modify: `services/knowledge-engine/app/main.py`

### Step 1: 写 schemas

写 `services/knowledge-engine/app/schemas/human_gates.py`：

```python
"""Schemas for /api/v1/mcp/human-gates REST router (W4-B 切片 2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GateRow(BaseModel):
    """mcp.human_gates 一行（带 join 出来的 tool_name / args 摘要）。"""
    id: str
    short_id: str  # id[:8] 给前端按钮当展示
    tool_call_id: str
    tool_name: str | None = None
    summary: str
    args_preview: dict[str, Any] | None = None
    timeout_seconds: int
    created_at: datetime
    age_seconds: int  # NOW() - created_at，前端展示 "X 分钟前"


class ListPendingResponse(BaseModel):
    data: list[GateRow]
    total: int


class ApproveRequest(BaseModel):
    """approve / reject 共用：note 选填，max 500."""
    note: str = Field(default="", max_length=500)


class GateActionResponse(BaseModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    hint: str | None = None
```

- [x] **Step 1: 写上面这个 schemas 文件**

### Step 2: 写 inbox_service

写 `services/knowledge-engine/app/services/inbox_service.py`：

```python
"""Service layer for /api/v1/mcp/human-gates REST router (W4-B 切片 2).

职责：
- 列待批 gate（含 join tool_calls 拿 tool_name + args 摘要）
- 批 / 驳一条 gate（带 short_id 解析 + 错误格式规范）

底层调用 app/mcp/human_gate.py 的 approve/reject（已 idempotent）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.database import get_pool
from app.mcp import human_gate

logger = logging.getLogger(__name__)


async def list_pending() -> dict[str, Any]:
    """列出未决定的 gate（join mcp.tool_calls 拿 tool_name / args 摘要）。"""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT g.id, g.tool_call_id, g.summary, g.timeout_seconds, g.created_at,
               t.tool_name, t.args
          FROM mcp.human_gates g
          JOIN mcp.tool_calls t ON t.id = g.tool_call_id
         WHERE g.decision IS NULL
         ORDER BY g.created_at ASC
        """
    )
    now = datetime.now(timezone.utc)
    data = []
    for r in rows:
        created = r["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = int((now - created).total_seconds())
        gate_id = str(r["id"])
        data.append(
            {
                "id": gate_id,
                "short_id": gate_id[:8],
                "tool_call_id": str(r["tool_call_id"]),
                "tool_name": r["tool_name"],
                "summary": r["summary"],
                "args_preview": r["args"] if isinstance(r["args"], dict) else None,
                "timeout_seconds": int(r["timeout_seconds"]),
                "created_at": r["created_at"],
                "age_seconds": age,
            }
        )
    return {"data": data, "total": len(data)}


async def _resolve_gate_id(short_or_full: str) -> dict[str, Any]:
    """short_id (8+ chars) 或全 uuid → 全 uuid。

    Returns:
        {"ok":True, "id": "<full uuid>"} 或
        {"ok":False, "error": "gate_not_found"|"ambiguous_short_id", "hint": "..."}
    """
    pool = get_pool()
    s = (short_or_full or "").strip()
    if not s:
        return {"ok": False, "error": "gate_not_found", "hint": "id 不能为空"}

    if len(s) >= 32:
        # 完整 uuid（去横杠 32 位）
        try:
            full = str(uuid.UUID(s))
        except ValueError:
            return {
                "ok": False,
                "error": "gate_not_found",
                "hint": f"'{s[:16]}...' 不是合法 uuid",
            }
        # 不在此处过滤 decision IS NULL：让 human_gate.approve/reject 的 idempotent
        # 行为决定 already_decided。本层只判 gate 是否存在。
        row = await pool.fetchrow(
            "SELECT id FROM mcp.human_gates WHERE id=$1",
            uuid.UUID(full),
        )
        if row is None:
            return {
                "ok": False,
                "error": "gate_not_found",
                "hint": f"gate {full[:8]} 不存在",
            }
        return {"ok": True, "id": full}

    # short_id：扫 pending 找前缀匹配
    rows = await pool.fetch(
        "SELECT id::text AS id_str FROM mcp.human_gates WHERE decision IS NULL"
    )
    matches = [r["id_str"] for r in rows if r["id_str"].startswith(s)]
    if len(matches) == 1:
        return {"ok": True, "id": matches[0]}
    if len(matches) > 1:
        return {
            "ok": False,
            "error": "ambiguous_short_id",
            "hint": f"short_id '{s}' 撞了 {len(matches)} 条，发完整 uuid",
        }
    return {
        "ok": False,
        "error": "gate_not_found",
        "hint": f"没找到 short_id '{s}' 的待批 gate",
    }


async def approve_gate(gate_id: str, note: str = "") -> dict[str, Any]:
    """批一条 gate。返回 {ok:true, result:{id, note}} 或 {ok:false, error, hint}."""
    resolved = await _resolve_gate_id(gate_id)
    if not resolved.get("ok"):
        return resolved
    full_id = resolved["id"]
    success = await human_gate.approve(full_id, note)
    if not success:
        return {
            "ok": False,
            "error": "already_decided",
            "hint": f"gate {full_id[:8]} 已批/驳，无法重复",
        }
    return {
        "ok": True,
        "result": {"id": full_id, "decision": "approved", "note": note},
    }


async def reject_gate(gate_id: str, note: str = "") -> dict[str, Any]:
    """驳一条 gate。同 approve_gate 错误格式。"""
    resolved = await _resolve_gate_id(gate_id)
    if not resolved.get("ok"):
        return resolved
    full_id = resolved["id"]
    success = await human_gate.reject(full_id, note)
    if not success:
        return {
            "ok": False,
            "error": "already_decided",
            "hint": f"gate {full_id[:8]} 已批/驳，无法重复",
        }
    return {
        "ok": True,
        "result": {"id": full_id, "decision": "rejected", "note": note},
    }
```

- [x] **Step 2: 写上面这个 inbox_service 文件**

### Step 3: 写 router

写 `services/knowledge-engine/app/routers/human_gates.py`：

```python
"""REST router for mcp.human_gates (W4-B 切片 2).

3 endpoint：
- GET  /api/v1/mcp/human-gates                      列待批
- POST /api/v1/mcp/human-gates/{id}/approve         批（含 short_id 解析）
- POST /api/v1/mcp/human-gates/{id}/reject          驳

错误格式（gate_not_found / ambiguous_short_id / already_decided）由 service layer
返 {ok:false, error:..., hint:...}；router 直接 JSONResponse 透传。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.human_gates import ApproveRequest
from app.services.inbox_service import (
    approve_gate,
    list_pending,
    reject_gate,
)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-human-gates"])


@router.get("/human-gates")
async def list_gates() -> dict:
    return await list_pending()


@router.post("/human-gates/{gate_id}/approve")
async def approve_endpoint(gate_id: str, payload: ApproveRequest):
    result = await approve_gate(gate_id, payload.note)
    if not result.get("ok"):
        code = _error_to_status(result.get("error"))
        return JSONResponse(content=result, status_code=code)
    return result


@router.post("/human-gates/{gate_id}/reject")
async def reject_endpoint(gate_id: str, payload: ApproveRequest):
    result = await reject_gate(gate_id, payload.note)
    if not result.get("ok"):
        code = _error_to_status(result.get("error"))
        return JSONResponse(content=result, status_code=code)
    return result


def _error_to_status(err: str | None) -> int:
    if err == "gate_not_found":
        return 404
    if err == "ambiguous_short_id":
        return 400
    if err == "already_decided":
        return 409
    return 400
```

- [x] **Step 3: 写上面这个 router 文件**

### Step 4: include router

改 `services/knowledge-engine/app/main.py`：

参考切片 1 line 22 + line 82 的位置，加：

```python
from app.routers.human_gates import router as human_gates_router  # 加在 mcp_tool_calls_router import 之后
# ...
app.include_router(human_gates_router)  # 加在 mcp_tool_calls_router include 之后
```

- [x] **Step 4: 改 main.py 加 import + include_router**

### Step 5: 写测试

写 `services/knowledge-engine/tests/test_router_human_gates.py`：

```python
"""Tests for /api/v1/mcp/human-gates REST router (W4-B 切片 2 T1)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import close_pool, get_pool, init_pool
from app.main import app


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed_gates():
    """T1 测试前清表 + 塞 3 条 pending + 1 条 already-decided。"""
    await init_pool()
    pool = get_pool()
    # 清旧测试数据
    await pool.execute(
        "DELETE FROM mcp.human_gates WHERE summary LIKE '__t1_slice2_seed_%'"
    )
    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_slice2_seed_%'"
    )

    now = datetime.now(timezone.utc)
    # 先建 4 条 tool_calls
    tc_ids = [str(uuid.uuid4()) for _ in range(4)]
    for i, tc_id in enumerate(tc_ids):
        await pool.execute(
            """INSERT INTO mcp.tool_calls
               (id, tool_name, args, status, require_approval, created_at)
               VALUES ($1, $2, $3::jsonb, 'pending', TRUE, $4)""",
            uuid.UUID(tc_id),
            f"__t1_slice2_seed_record_cost_{i}",
            json.dumps({"sku_id": "SKU-T1S2", "category": "logistics"}),
            now - timedelta(minutes=i * 5),
        )

    # 建 4 条 gates: 3 pending + 1 already approved
    gate_ids = [str(uuid.uuid4()) for _ in range(4)]
    for i, (gid, tc_id) in enumerate(zip(gate_ids, tc_ids)):
        decision = None if i < 3 else "approved"
        await pool.execute(
            """INSERT INTO mcp.human_gates
               (id, tool_call_id, summary, timeout_seconds, decision,
                decision_note, decided_at, created_at)
               VALUES ($1, $2, $3, 3600, $4, $5, $6, $7)""",
            uuid.UUID(gid),
            uuid.UUID(tc_id),
            f"__t1_slice2_seed_summary_{i}",
            decision,
            "测试 seed" if decision else None,
            now if decision else None,
            now - timedelta(minutes=i * 5),
        )

    yield {"pending": gate_ids[:3], "decided": gate_ids[3], "tc_ids": tc_ids}

    # teardown
    await pool.execute(
        "DELETE FROM mcp.human_gates WHERE summary LIKE '__t1_slice2_seed_%'"
    )
    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_slice2_seed_%'"
    )
    await close_pool()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ─── list endpoint ────────────────────────────────────────────────────────


async def test_list_returns_pending_only(client, _seed_gates):
    """GET /api/v1/mcp/human-gates 只返 pending（decision IS NULL）。"""
    resp = await client.get("/api/v1/mcp/human-gates")
    assert resp.status_code == 200
    body = resp.json()
    seed_rows = [r for r in body["data"] if r["summary"].startswith("__t1_slice2_seed_")]
    assert len(seed_rows) == 3  # 只 3 条 pending
    # 确认字段齐全
    row = seed_rows[0]
    assert "short_id" in row
    assert len(row["short_id"]) == 8
    assert "tool_name" in row
    assert "args_preview" in row
    assert "age_seconds" in row
    assert row["age_seconds"] >= 0


async def test_list_excludes_decided(client, _seed_gates):
    """已批的 gate 不在 list 里。"""
    resp = await client.get("/api/v1/mcp/human-gates")
    body = resp.json()
    decided_id = _seed_gates["decided"]
    ids = [r["id"] for r in body["data"]]
    assert decided_id not in ids


# ─── approve endpoint ─────────────────────────────────────────────────────


async def test_approve_with_full_uuid(client, _seed_gates):
    """POST /api/v1/mcp/human-gates/{full_uuid}/approve."""
    target = _seed_gates["pending"][0]
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{target}/approve",
        json={"note": "OK"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["decision"] == "approved"
    # 验 DB 真写
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT decision, decision_note FROM mcp.human_gates WHERE id=$1",
        uuid.UUID(target),
    )
    assert row["decision"] == "approved"
    assert row["decision_note"] == "OK"


async def test_approve_with_short_id(client, _seed_gates):
    """short_id (8 char) 走前缀匹配。"""
    target_full = _seed_gates["pending"][1]
    short = target_full[:8]
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{short}/approve",
        json={"note": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_approve_already_decided_returns_409(client, _seed_gates):
    """二次批返 409 already_decided。"""
    target = _seed_gates["decided"]  # 这条已 approved
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{target}/approve",
        json={"note": "重批"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "already_decided"


async def test_approve_not_found_returns_404(client):
    """完全不存在的 uuid 返 404."""
    bogus = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{bogus}/approve",
        json={"note": ""},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "gate_not_found"


async def test_approve_invalid_id_format(client):
    """非 uuid 非合法 short_id 返 404 gate_not_found（不是 422，service 层兜）."""
    resp = await client.post(
        "/api/v1/mcp/human-gates/zzz/approve",
        json={"note": ""},
    )
    # short_id 'zzz' 没匹配任何 pending，返 gate_not_found 404
    assert resp.status_code == 404


# ─── reject endpoint ──────────────────────────────────────────────────────


async def test_reject_with_full_uuid(client, _seed_gates):
    target = _seed_gates["pending"][2]
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{target}/reject",
        json={"note": "不行，参数不对"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["decision"] == "rejected"
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT decision, decision_note FROM mcp.human_gates WHERE id=$1",
        uuid.UUID(target),
    )
    assert row["decision"] == "rejected"
    assert row["decision_note"] == "不行，参数不对"
```

- [x] **Step 5: 写测试文件**

```bash
# 文件创建后立刻验证 import 不挂
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c 'from tests import test_router_human_gates'"
```

Expected: 不报错（虽然 router 还没建，import 本身要过；如果报"No module named 'app.routers.human_gates'"是预期的 — 说明 step 3 还没生效，docker recreate 后再跑）。

### Step 6: 重启 KE 容器 + 跑测试

- [x] **Step 6: 重启 KE 容器**

```bash
docker compose -f E:/agent/omni/docker-compose.yml up -d --no-deps --force-recreate knowledge-engine
```

等 5-10 秒等启动完。

- [x] **Step 7: 跑测试**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_router_human_gates.py -v"
```

Expected: 7 个测试全 PASS。

- [x] **Step 8: doctor 复查 27 tool 没动**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected: `27/27 tools OK`。

- [x] **Step 9: T1 commit**

```bash
git add services/knowledge-engine/app/services/inbox_service.py \
        services/knowledge-engine/app/routers/human_gates.py \
        services/knowledge-engine/app/schemas/human_gates.py \
        services/knowledge-engine/tests/test_router_human_gates.py \
        services/knowledge-engine/app/main.py
git commit -m "feat(W4-B): KE /api/v1/mcp/human-gates REST router 3 endpoint（W4-B 切片 2 T1）

list/approve/reject 复用 human_gate.py 底层 + service 层包 short_id
解析 + JSONResponse 透传错误格式。7 测试 PASS。doctor 27/27."
```

---

## Task 2: 前端 3 个 API proxy route

**Goal:** 把 KE REST 暴露给浏览器（前端无 KE 直连，全走 Next.js API route 转发）。

**Files:**
- Create: `frontend/src/app/api/omni/inbox/route.ts`
- Create: `frontend/src/app/api/omni/inbox/[id]/approve/route.ts`
- Create: `frontend/src/app/api/omni/inbox/[id]/reject/route.ts`

### Step 1: list proxy

写 `frontend/src/app/api/omni/inbox/route.ts`：

```typescript
import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET() {
  const base = serviceBase()
  try {
    const data = await fetchJson<{ data: any[]; total: number }>(
      `${base.knowledge}/api/v1/mcp/human-gates`,
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

- [x] **Step 1: 写 list proxy**

### Step 2: approve proxy（裸 fetch + 透传 status）

写 `frontend/src/app/api/omni/inbox/[id]/approve/route.ts`：

```typescript
import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface Body {
  note?: string
}

export async function POST(req: Request, ctx: { params: { id: string } }) {
  const base = serviceBase()
  const { id } = ctx.params
  let body: Body
  try {
    body = await req.json()
  } catch {
    return Response.json({ success: false, error: 'invalid_json' }, { status: 400 })
  }
  try {
    const r = await fetch(
      `${base.knowledge}/api/v1/mcp/human-gates/${encodeURIComponent(id)}/approve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: body.note ?? '' }),
        cache: 'no-store',
      },
    )
    const data = await r.json().catch(() => ({}))
    return Response.json({ success: r.ok, ...data }, { status: r.status })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return Response.json({ success: false, error: msg }, { status: 502 })
  }
}
```

- [x] **Step 2: 写 approve proxy**

### Step 3: reject proxy（同 approve，URL 改 /reject）

写 `frontend/src/app/api/omni/inbox/[id]/reject/route.ts`：1:1 复制 approve 的代码，把 URL 里 `/approve` 改成 `/reject`。

- [x] **Step 3: 写 reject proxy**

### Step 4: 起 dev server 验

```bash
cd E:/agent/omni/frontend && npm run dev
```

另起 shell 测：

```bash
# list（应返 success:true + data 数组）
curl http://localhost:3000/api/omni/inbox

# approve 不存在的 id（应返 success:false + status 404 + hint）
curl -X POST http://localhost:3000/api/omni/inbox/00000000-0000-0000-0000-000000000000/approve \
  -H "Content-Type: application/json" \
  -d '{"note":"test"}'
```

Expected: list 200 + `{success:true, data:[...], total:N}`；approve 404 + `{success:false, ok:false, error:"gate_not_found", hint:"..."}`。

- [x] **Step 4: dev server 验 list + approve（404 路径）**

### Step 5: T2 commit

```bash
git add frontend/src/app/api/omni/inbox/
git commit -m "feat(W4-B): 前端 3 个 inbox API proxy route（W4-B 切片 2 T2）

list 走 fetchJson；approve/reject 走裸 fetch + Response.json 透传 status，
保留 KE 的 hint 不被 _shared.ts 吞。"
```

---

## Task 3: 前端 /inbox 页 + sidebar 入口

**Goal:** /inbox 页：pending 列表 + 批/驳按钮 + 备注 prompt + 自动刷新。sidebar 加菜单。

**Files:**
- Create: `frontend/src/app/inbox/page.tsx`
- Modify: `frontend/src/components/app-sidebar.tsx`

### Step 1: 写 /inbox 页

写 `frontend/src/app/inbox/page.tsx`（参考 `/agent-log/page.tsx` 风格但简化为单页卡片列表）：

```tsx
'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Inbox, CheckCircle2, XCircle, RefreshCw, Loader2, Clock,
} from 'lucide-react'

interface GateRow {
  id: string
  short_id: string
  tool_call_id: string
  tool_name: string | null
  summary: string
  args_preview: Record<string, unknown> | null
  timeout_seconds: number
  created_at: string
  age_seconds: number
}

interface ListResp {
  success: boolean
  data: GateRow[]
  total: number
  error?: string
}

function fmtAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

function fmtTimeout(s: number): string {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

export default function InboxPage() {
  const [rows, setRows] = useState<GateRow[]>([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const resp = await fetch('/api/omni/inbox')
      const data: ListResp = await resp.json()
      if (data.success) {
        setRows(data.data)
      } else {
        window.alert(data.error ?? '加载失败')
      }
    } catch (err) {
      window.alert('网络异常：' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  async function actOn(id: string, kind: 'approve' | 'reject') {
    const note =
      kind === 'reject'
        ? (window.prompt('驳回理由（必填）：') ?? '').trim()
        : (window.prompt('备注（可选）：') ?? '').trim()
    if (kind === 'reject' && !note) {
      window.alert('驳回必须填理由')
      return
    }
    setActing(id)
    try {
      const resp = await fetch(`/api/omni/inbox/${id}/${kind}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      })
      const data = await resp.json()
      if (data.success && data.ok) {
        // 从列表删掉这一条，避免双批
        setRows((prev) => prev.filter((r) => r.id !== id))
      } else {
        window.alert(data.hint ?? data.error ?? `${kind} 失败`)
      }
    } catch (err) {
      window.alert('网络异常：' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="px-6 py-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <Inbox className="w-7 h-7 text-amber-600" />
            待批
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            omni 要做的事得你点头 / 不点超时自动驳
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {/* Empty / Loading */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-gray-300" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Inbox className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <div className="text-sm text-gray-500">暂无待批</div>
            <div className="text-xs text-gray-400 mt-1">
              omni 跑到 require_approval 的 tool 时会出现在这里
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <Card key={r.id} className="hover:border-amber-300 transition">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <code className="text-xs text-gray-400 font-mono">{r.short_id}</code>
                      <Badge className="bg-amber-100 text-amber-700 border-amber-200">
                        {r.tool_name ?? '?'}
                      </Badge>
                      <span className="text-xs text-gray-400 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {fmtAge(r.age_seconds)} · 超时 {fmtTimeout(r.timeout_seconds)}
                      </span>
                    </div>
                    <div className="text-sm text-gray-900 mb-2">{r.summary}</div>
                    {r.args_preview && (
                      <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-words">
                        {JSON.stringify(r.args_preview, null, 2)}
                      </pre>
                    )}
                  </div>
                  <div className="flex flex-col gap-2 shrink-0">
                    <Button
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      disabled={acting === r.id}
                      onClick={() => actOn(r.id, 'approve')}
                    >
                      <CheckCircle2 className="w-4 h-4 mr-1" />
                      批
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-rose-300 text-rose-700 hover:bg-rose-50"
                      disabled={acting === r.id}
                      onClick={() => actOn(r.id, 'reject')}
                    >
                      <XCircle className="w-4 h-4 mr-1" />
                      驳
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [x] **Step 1: 写 /inbox 页**

### Step 2: sidebar 加菜单项

改 `frontend/src/components/app-sidebar.tsx`，在 line 125 `/agent-log` 那条之前加：

```typescript
  { href: '/inbox', icon: Inbox, label: '待批', hint: '点头让 omni 做要紧的事 / 不点超时自动驳' },
```

确认 import 行加上 `Inbox` 图标（搜文件 line 1-30 的 lucide-react import 列表，加进去）。

- [x] **Step 2: 改 sidebar 加菜单 + 加 Inbox import**

### Step 3: 浏览器验

dev server 应已起。打开 `http://localhost:3000/inbox`：

- [x] **Step 3a: 看到"暂无待批"空状态**（如果没 pending gate）
- [x] **Step 3b: 点 sidebar"待批"菜单能跳到 /inbox**
- [x] **Step 3c: 点"刷新"按钮 loading 转一下回来**

如果想看到真 pending 卡片，跳到 T4 e2e 那步先建一条。

### Step 4: T3 commit

```bash
git add frontend/src/app/inbox/ frontend/src/components/app-sidebar.tsx
git commit -m "feat(W4-B): /inbox 待批页 + sidebar 入口（W4-B 切片 2 T3）

pending gate 卡片列表 + 批/驳按钮 + 备注 prompt + 失败 alert。
sidebar 加'待批'菜单项（在 Agent 日志附近）。"
```

---

## Task 4: e2e 验证 + commit + 更新 memory

**Goal:** 真造一条 record_cost gate 走前端流程批掉，然后 mock 一条走前端驳掉，验通路。最后 memory + plan 状态更新 + commit。

### Step 1: 起一条真 record_cost pending（容器内调 mcp tool）

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c '
import asyncio, json
from app.database import init_pool, close_pool
from app.mcp.tools.cost_admin import record_cost

async def main():
    await init_pool()
    try:
        # require_approval=True 会写 mcp.tool_calls + mcp.human_gates
        # 注意：这 await 会卡在 human_gate.request_approval poll 里，timeout 60s 即可
        result = await asyncio.wait_for(
            record_cost(
                sku_id=\"SKU-T4-INBOX-E2E\",
                category=\"logistics\",
                name=\"前端 inbox e2e 测试\",
                unit_cost=\"3.5\",
                quantity_per_unit=\"1\",
            ),
            timeout=10,
        )
        print(json.dumps(result, ensure_ascii=False))
    except asyncio.TimeoutError:
        print(\"[ok] gate created, request_approval still polling — will rejected by next test cleanup\")
    finally:
        await close_pool()

asyncio.run(main())
'"
```

Expected: print "[ok] gate created..." 因为我们故意 timeout 10s 不批。这时 mcp.human_gates 表里有一条 pending。

> **关键**：上面这条 gate 现在还在 polling（request_approval 等批/驳），如果 KE 容器内的 asyncio task 一直没人批它要么超时 1h 要么人批/驳。下面 step 用前端批掉它就清干净了。

- [ ] **Step 1: 容器调 record_cost 起 pending gate（10s timeout 故意不等批）**

### Step 2: 浏览器走前端批（带备注）

打开 `http://localhost:3000/inbox`：

- [ ] **Step 2a: 列表里看到刚那条 SKU-T4-INBOX-E2E 待批 gate**
- [ ] **Step 2b: 点"批" → prompt 备注输 "T4 e2e 通路验证" → 卡片消失**
- [ ] **Step 2c: 容器侧 record_cost 调用应已收到 approved，return 真 INSERT**

验证 DB 真写 cost_item（用 query_costs 或直接查表）：

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "
SELECT sku_id, category, name, unit_cost, created_at
FROM accounting.cost_items
WHERE sku_id='SKU-T4-INBOX-E2E'
ORDER BY created_at DESC
LIMIT 5
"
```

Expected: 至少 1 行 logistics, 3.5。

验证 gate 已 approved + note 写入：

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "
SELECT g.id::text, g.summary, g.decision, g.decision_note, g.decided_at
FROM mcp.human_gates g
JOIN mcp.tool_calls t ON t.id=g.tool_call_id
WHERE t.tool_name='record_cost' AND t.args::text LIKE '%SKU-T4-INBOX-E2E%'
ORDER BY g.created_at DESC LIMIT 1
"
```

Expected: decision='approved', decision_note='T4 e2e 通路验证'。

- [ ] **Step 2: 浏览器批通 + DB 验证 cost_item + gate 状态**

### Step 3: 起第二条 + 走前端驳

重复 Step 1 调一次 record_cost 起第二条 gate（SKU 改 SKU-T4-INBOX-REJECT 区分）。

打开 /inbox，找到这条点"驳" → prompt 输 "T4 e2e 驳回理由" → 卡片消失。

验证：

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "
SELECT g.summary, g.decision, g.decision_note
FROM mcp.human_gates g
JOIN mcp.tool_calls t ON t.id=g.tool_call_id
WHERE t.args::text LIKE '%SKU-T4-INBOX-REJECT%'
ORDER BY g.created_at DESC LIMIT 1
"
```

Expected: decision='rejected', decision_note='T4 e2e 驳回理由'。

确认这条 SKU-T4-INBOX-REJECT 没产生 cost_item：

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "
SELECT COUNT(*) FROM accounting.cost_items WHERE sku_id='SKU-T4-INBOX-REJECT'
"
```

Expected: count=0。

- [ ] **Step 3: 浏览器驳通 + DB 验证 gate 已驳 + cost_item 没写**

### Step 4: e2e 留痕清理

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "
DELETE FROM accounting.cost_items WHERE sku_id IN ('SKU-T4-INBOX-E2E', 'SKU-T4-INBOX-REJECT');
DELETE FROM mcp.human_gates WHERE summary LIKE '%SKU-T4-INBOX%';
DELETE FROM mcp.tool_calls WHERE args::text LIKE '%SKU-T4-INBOX%';
"
```

- [ ] **Step 4: e2e 留痕清理（DB 删 SKU-T4-INBOX-* 全部数据）**

### Step 5: 错误路径快测

```bash
# (a) approve 不存在的 uuid → 404
curl -i -X POST http://localhost:3000/api/omni/inbox/00000000-0000-0000-0000-000000000000/approve \
  -H "Content-Type: application/json" -d '{"note":"x"}' 2>&1 | grep -E "HTTP|gate_not_found"

# (b) 起一条 gate 后 approve 一次（应 200），再 approve 一次（应 409）
# 此处需要先有真 gate，省略详细，T1 测试已覆盖
```

Expected: (a) HTTP/1.1 404 + body 含 `"error":"gate_not_found"`。

- [ ] **Step 5: 错误路径 curl 快测（gate_not_found 404）**

### Step 6: 更新 memory

更新 `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`：

1. line 28 标 W4-B 切片 2 [x] 落地（含 commit hash 占位 `<待填>`）
2. 末尾追加新章节 §二十三 「W4-B 切片 2 落地总结」，结构对应切片 1 §二十二（commit 序列 / 范围 / 关键技术决策 / 踩的坑 / e2e 实测 / 留缮项 / 起切片 3 时的环境状态）

具体内容由 implementer 根据实际跑下来的情况填。

- [ ] **Step 6: 更新 memory §二十三**

### Step 7: T4 commit + push

```bash
git add docs/superpowers/plans/2026-05-07-omni-agent-uplift-W4b-slice2-plan.md \
        services/knowledge-engine/app/services/inbox_service.py \
        services/knowledge-engine/app/routers/human_gates.py \
        services/knowledge-engine/app/schemas/human_gates.py \
        services/knowledge-engine/tests/test_router_human_gates.py \
        services/knowledge-engine/app/main.py \
        frontend/src/app/api/omni/inbox/ \
        frontend/src/app/inbox/ \
        frontend/src/components/app-sidebar.tsx
# 已分别 commit 过的文件 git 会自动跳过
git status  # 确认还有什么没 commit 的
git log --oneline -10  # 看切片 2 几个 commit 都在
```

如果 settings.local.json 有改也带上（切片 2 不应该有新 grant，但万一）。

确认 commit 序列大致：

```
plan(W4-B): 切片 2 实施计划
feat(W4-B): KE /api/v1/mcp/human-gates REST router 3 endpoint（W4-B 切片 2 T1）
feat(W4-B): 前端 3 个 inbox API proxy route（W4-B 切片 2 T2）
feat(W4-B): /inbox 待批页 + sidebar 入口（W4-B 切片 2 T3）
chore(W4-B): 切片 2 收尾 e2e + memory + plan（W4-B 切片 2 T4）
```

- [ ] **Step 7: 收尾 commit + git log 确认**

### Step 8: 留给老板的口头报告

汇报：
- 切片 2 5 commit 落地，HEAD `<新 hash>`
- /inbox 通路验证 OK：批/驳前端按钮真 → DB → cost_item 落 / 不落
- 错误路径覆盖：404 gate_not_found / 409 already_decided / 400 ambiguous_short_id
- doctor 27/27 维持
- W4-B 切片 3 候选（按价值）：
  1. 5 业务 skill（cost-luru 之外）— 待 cost-luru 真触发实测后铺
  2. /cost 增强（record_cost UI + 列表筛选）
  3. cron weekly_self_review
  4. 修 codify e2e

- [ ] **Step 8: 给老板报告 + 等切片 3 拍板**

---

## 完成判据（全部 ✓ 才算切片 2 done）

- [ ] T1 所有 step ✓ + 7 测试 PASS + doctor 27/27
- [ ] T2 所有 step ✓ + curl 验通 list/approve 路径
- [ ] T3 所有 step ✓ + 浏览器看到 sidebar 菜单 + /inbox 空状态
- [ ] T4 所有 step ✓ + e2e 真造批/驳跑通 + DB 验证一致 + 留痕清理 + memory §二十三 写入
- [ ] git log 看 ~5 commit on `feat/mcp-w1` 含 plan
- [ ] 工作树 clean（除 .claude/settings.local.json 这种本身就常变的）

---

## 风险与回退

- **如 T1 测试出现 fixture 卡住**（前面 切片 1 T1 没遇到，但 conftest.py 行为可能有差）：先单跑 `pytest tests/test_router_human_gates.py::test_list_returns_pending_only -v -s` 看 stdout
- **如 T2 dev server 起不来**（端口占用）：`netstat -ano | findstr :3000`，kill 占用进程
- **如 T3 sidebar 改完 hot reload 没刷**：`Ctrl-Shift-R` 硬刷一下，或 dev server 重启
- **如 T4 record_cost 调用 timeout 没起到 gate**（人工误操作）：直接手 INSERT mcp.human_gates 一条 pending 也行，关键看前端通路：
  ```sql
  -- 假设有个 tool_call_id（先 INSERT 一条 mcp.tool_calls 拿 id，或用现有 require_approval=true 的）
  INSERT INTO mcp.human_gates (tool_call_id, summary, timeout_seconds)
  VALUES (<tc_id>, '__t4_manual_seed', 3600);
  ```
- **回退**：切片 2 commit 串都在 `feat/mcp-w1`，一次 `git reset --hard <切片 1 末尾 hash 7acc385>` 即可全撤。但本切片不破坏 W4-A/切片 1 任何资产，不需要回退基本逻辑。
