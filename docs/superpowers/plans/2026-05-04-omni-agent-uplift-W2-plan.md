# Omni Agent 化升级 W2（算账 + 编排 + 媒体）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 W1 已建的 MCP server 框架上加 5 个新 tool（`query_costs` / `compute_margin` / `generate_brief` / `generate_image` / `generate_video`），所有 LLM tool result 必带 `trace` 字段（final_prompt + model + params + cost）+ `next_step_hint` 字段（提议下一步），让老板在 Claude Code 里少打字驱动 sku 出片标准链路（brief → 3 分镜图 → 多段分镜视频）。

**Architecture:** 沿用 W1 模式——`@tool_with_audit` 装饰器 + `app.services.ai_hub_client` 走 hub + `tool_models.yaml` 切模型。**不引入 Human Gate 真启用**（W1 stub 保留给 W3 发布类不可逆 tool；W2 5 tool 全 `require_approval=False`，靠 review-after iterate 闭环）。**不引入 run_sku_orch / inbox UI / 状态机表**（Claude 主大脑当编排器）。视频走 A 方案（每段独立生成，不自动拼接，老板下载交剪辑）。

**Tech Stack:** Python 3.11+, FastAPI, FastMCP 3.2.x, asyncpg, asyncio.gather 并发, PostgreSQL 16 with `accounting.cost_items` 表（migration 015 已上）, Claude Sonnet 4.6 / GPT-Image-2 / Seedance 2.0（三家 provider 走 ai-provider-hub 统一入口）。Windows 11 + PowerShell 5.1。knowledge-engine 容器 8002。ai-provider-hub 容器 8001（A2 后已容器化）。

---

## 前置条件（开 T1 前必满足）

1. **W1 + A2 已落地**：`feat/mcp-w1` 分支 commit 至 `f0a2592` 或更新；`docker ps` 显示 `omni-knowledge-engine` 与 `omni-ai-provider-hub` 都 Up；`docker exec omni-knowledge-engine python -m app.mcp.doctor` 5 项全绿。
2. **必读上下文**：
   - `docs/superpowers/specs/2026-05-03-omni-agent-uplift-design.md` §3.2 W2 行 + §6 trace + §7 review-after iterate
   - `docs/superpowers/plans/2026-05-03-omni-agent-uplift-W1-plan.md` —— W1 task 模式参考
   - `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md` §十一 W2 锁定决策（含 Gate 改 W3，每 tool 必带 trace + next_step_hint）

---

## 文件结构（W2 全量）

### 新增（10 个）

| 路径 | 行数估 | 责任 |
|---|---|---|
| `services/knowledge-engine/app/mcp/trace.py` | ~70 | `build_trace()` + `attach_next_step()` 工具函数（4 个 LLM tool 复用） |
| `services/knowledge-engine/app/mcp/utils.py` | ~40 | `decimal_to_jsonable()` 递归把 Decimal 转 str（`compute_margin` 用） |
| `services/knowledge-engine/app/mcp/orphan.py` | ~50 | 启动期孤儿清理 `mark_orphans(threshold_minutes=5)` |
| `services/knowledge-engine/app/mcp/tools/accounting.py` | ~180 | `query_costs` + `compute_margin` |
| `services/knowledge-engine/app/mcp/tools/media.py` | ~280 | `generate_brief` + `generate_image` + `generate_video` |
| `services/knowledge-engine/tests/test_mcp_trace.py` | ~80 | trace.py 单测 |
| `services/knowledge-engine/tests/test_mcp_utils.py` | ~60 | utils.py 单测（Decimal 序列化） |
| `services/knowledge-engine/tests/test_mcp_orphan.py` | ~70 | orphan 清理集成测（hits dev DB） |
| `services/knowledge-engine/tests/test_mcp_accounting.py` | ~140 | query_costs / compute_margin 集成测 |
| `services/knowledge-engine/tests/test_mcp_media.py` | ~200 | generate_brief / image / video 集成测（含 hub mock） |

### 修改（6 个）

| 路径 | 改动 |
|---|---|
| `services/knowledge-engine/app/mcp/audit.py` | `except Exception` → `except BaseException`；CancelledError 不吞，re-raise；`_finalize_error` 不阻塞 cancel |
| `services/knowledge-engine/app/mcp/server.py` | import 注册 accounting + media tools |
| `services/knowledge-engine/app/mcp/doctor.py` | expected_tools 从 5 升到 10 |
| `services/knowledge-engine/app/main.py` | lifespan 启动调 `mark_orphans()` |
| `services/knowledge-engine/app/services/ai_hub_client.py` | 加 `generate_image_v2` / `generate_video_v2`（多分类 refs + 首尾帧） |
| `services/knowledge-engine/config/tool_models.yaml` | 加 4 个 keyed override |

### 项目级（1 个）

| 路径 | 改动 |
|---|---|
| `E:\agent\omni\CLAUDE.md` | 新建（项目级 Claude Code 指令）：sku 出片标准链路 + 老板响应词约定 |

---

## 任务

### 任务 0：Sanity check + 前置阻塞排除

**目的**：W2 真要调 LLM / 视频 API，必须先确认 hub 端 api_key 就绪，否则后续 task 全废。

**Files:**（无改动，纯验证）

- [ ] **Step 1：检查 hub providers api_key 状态**

```powershell
curl.exe -s http://127.0.0.1:8001/api/v1/ai/providers | python -m json.tool
```

预期可用：
- `openai.api_key_set: true` ✅（image / chat 备用）
- `gemini.api_key_set: true` ✅（chat 主用：gemini-3-flash-preview）
- `seedance.api_key_set`：**这次必须 true**（W2 video 必需）

事实背景（不要再绕路）：
- 老板的 Anthropic 是 Claude Code Max 订阅，**不是** API key 形式 → hub 端调不到 anthropic chat
- 起步 chat 默认 → `gemini/gemini-3-flash-preview`（B 路径，老板拍）
- video → `seedance/seedance-2-0`（A 路径，老板拍）

- [ ] **Step 2：如 seedance.api_key_set=false，老板补 SEEDANCE key**

```powershell
# 1) 编辑 services\ai-provider-hub\.env（不入 git），加：
#    SEEDANCE_API_KEY=<老板的 key>
notepad "E:\agent\omni\services\ai-provider-hub\.env"

# 2) 容器 recreate 拉新 env
docker compose -f "E:\agent\omni\docker-compose.yml" up -d --no-deps --force-recreate ai-provider-hub
Start-Sleep -Seconds 8

# 3) 复验
curl.exe -s http://127.0.0.1:8001/api/v1/ai/providers | python -c "import json,sys; d=json.load(sys.stdin); print('seedance:', d['providers']['seedance']['api_key_set'])"
```

Expected: `seedance: True`

如老板暂时找不到 key，**T9 暂留 stub**：generate_video tool 实现但 hub 调用走 try/except，hub 报"no api key"时返 `{ok: False, error: "video provider 未配 key", hint: "..."}`，不阻塞 W2 整体落地。

- [ ] **Step 3：sku_id 选定一只测试用的真实 SKU**

```powershell
docker exec omni-knowledge-engine python -c "
import asyncio
from app.database import init_pool, close_pool

async def main():
    await init_pool()
    try:
        from app.database import get_pool
        rows = await get_pool().fetch('SELECT sku_id, name, sale_price FROM mvp_sku LIMIT 5')
        for r in rows: print(dict(r))
    finally:
        await close_pool()

asyncio.run(main())
"
```

把第一行的 `sku_id` 记下，后续 T4/T5/T6 e2e 用同一个。

- [ ] **Step 4：cost_items 至少有这只 sku 的几行成本（如没有，先插测试数据）**

```powershell
docker exec omni-knowledge-engine python -c "
import asyncio
from app.database import init_pool, close_pool, get_pool

SKU = '<把 Step 3 拿到的 sku_id 填这里>'

async def main():
    await init_pool()
    try:
        rows = await get_pool().fetch(
            'SELECT category, item_name, unit_cost FROM accounting.cost_items '
            \"WHERE (sku_id=$1 OR sku_id IS NULL) AND is_active=TRUE\", SKU)
        for r in rows: print(dict(r))
        if not rows:
            print('!! 没数据，T4 e2e 前需插测试行')
    finally:
        await close_pool()

asyncio.run(main())
"
```

如返回 0 行，**记到 plan 备注**：T4 e2e 前要么手插几行 cost_items 测试数据，要么 e2e 跑空集 case。

- [ ] **Step 5：commit T0 不需要——这是验证步骤**

记录到 commit message 草稿：选了路径 A 还是 B、用哪个 sku_id 做测试。

---

### 任务 1：audit.py 异常处理升级 + 启动期孤儿清理

**Files:**
- Modify: `services/knowledge-engine/app/mcp/audit.py`
- Create: `services/knowledge-engine/app/mcp/orphan.py`
- Create: `services/knowledge-engine/tests/test_mcp_orphan.py`
- Modify: `services/knowledge-engine/app/main.py`

- [ ] **Step 1：写孤儿清理测试（先红）**

`services/knowledge-engine/tests/test_mcp_orphan.py`:
```python
"""T1：启动期孤儿清理测试。"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.database import get_pool, init_pool, close_pool
from app.mcp.orphan import mark_orphans


@pytest.fixture(scope="module", autouse=True)
def _pool():
    asyncio.run(init_pool())
    yield
    asyncio.run(close_pool())


@pytest.mark.asyncio
async def test_smoke_mark_orphans_marks_old_pending():
    """超过 threshold 的 pending 会被改成 orphaned。"""
    pool = get_pool()
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)

    await pool.execute(
        "INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval, created_at) "
        "VALUES ($1, '_smoke_orphan_old', '{}'::jsonb, 'pending', FALSE, $2), "
        "       ($3, '_smoke_orphan_new', '{}'::jsonb, 'pending', FALSE, NOW())",
        old_id, old_time, new_id,
    )

    n = await mark_orphans(threshold_minutes=5)
    assert n >= 1

    rows = await pool.fetch(
        "SELECT id, status FROM mcp.tool_calls WHERE id = ANY($1)", [old_id, new_id]
    )
    by_id = {r["id"]: r["status"] for r in rows}
    assert by_id[old_id] == "orphaned"
    assert by_id[new_id] == "pending"

    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name LIKE '_smoke_orphan_%'"
    )
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_orphan.py -v
```

Expected: `ImportError: cannot import name 'mark_orphans' from 'app.mcp.orphan'`

- [ ] **Step 3：建 orphan.py**

`services/knowledge-engine/app/mcp/orphan.py`:
```python
"""W2 T1：启动期孤儿清理。

mcp.tool_calls 中长时间停在 status='pending' 的记录是被 cancel 杀掉
（容器重启 / Ctrl-C / asyncio.CancelledError）的孤儿。
启动期把超过 threshold 的标 'orphaned'，便于审计 + 不污染 monitor。
"""
from __future__ import annotations

import logging

from app.database import get_pool

logger = logging.getLogger(__name__)


async def mark_orphans(threshold_minutes: int = 5) -> int:
    """把 pending 超 threshold 分钟的记录改成 orphaned。返回受影响行数。"""
    pool = get_pool()
    rec = await pool.fetchrow(
        f"""
        UPDATE mcp.tool_calls
        SET status='orphaned', completed_at=NOW(),
            error=COALESCE(error, '') || '[startup orphan cleanup]'
        WHERE status='pending'
          AND created_at < NOW() - INTERVAL '{int(threshold_minutes)} minutes'
        RETURNING id
        """
    )
    n = 0
    if rec:
        # asyncpg 没有 rowcount on UPDATE...RETURNING；走 fetch 数行
        rows = await pool.fetch(
            f"""
            SELECT id FROM mcp.tool_calls
            WHERE status='orphaned' AND completed_at >= NOW() - INTERVAL '1 minute'
            """
        )
        n = len(rows)
    if n:
        logger.warning("启动孤儿清理：%d 条 pending → orphaned (>%d min)", n, threshold_minutes)
    return n
```

**注意**：上面用的是变量内插 INTERVAL 字符串（不能用 `$1` 因为 PG 不接受参数化的 interval literal）；threshold_minutes 已 int 强转防注入。

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_orphan.py -v
```

Expected: PASS

- [ ] **Step 5：升级 audit.py 异常处理**

把 `services/knowledge-engine/app/mcp/audit.py` 中：
```python
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                logger.exception("tool %s raised", tool_name)
                err_msg = f"{type(exc).__name__}: {exc}"
                await _finalize_error(pool, tool_call_id, err_msg, start)
                return {"ok": False, "error": err_msg, "hint": "tool 内部异常，看 server 日志定位"}
```

替换为：
```python
            try:
                result = await fn(*args, **kwargs)
            except asyncio.CancelledError:
                # cancel 不吞：标 cancelled 后 re-raise，不破坏 task 取消语义
                await _finalize_error(pool, tool_call_id, "cancelled", start)
                raise
            except BaseException as exc:  # 含 KeyboardInterrupt / SystemExit
                logger.exception("tool %s raised", tool_name)
                err_msg = f"{type(exc).__name__}: {exc}"
                await _finalize_error(pool, tool_call_id, err_msg, start)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                return {"ok": False, "error": err_msg, "hint": "tool 内部异常，看 server 日志定位"}
```

文件顶上加：
```python
import asyncio
```

- [ ] **Step 6：在 main.py lifespan 接孤儿清理**

打开 `services/knowledge-engine/app/main.py`，找到 lifespan 函数（W1 已建包 mcp_http_app 的那个）。在 `init_pool()` 之后、yield 之前加：
```python
    from app.mcp.orphan import mark_orphans
    try:
        await mark_orphans(threshold_minutes=5)
    except Exception:
        logger.exception("startup orphan cleanup failed (continuing)")
```

具体位置：找到现有的类似 `await init_pool()` 行，紧跟其后加。

- [ ] **Step 7：跑全部 mcp 相关测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_audit.py tests/test_mcp_orphan.py -v
```

Expected: 全 PASS

- [ ] **Step 8：commit**

```powershell
cd E:\agent\omni
git add services/knowledge-engine/app/mcp/audit.py `
        services/knowledge-engine/app/mcp/orphan.py `
        services/knowledge-engine/app/main.py `
        services/knowledge-engine/tests/test_mcp_orphan.py
git commit -m "feat(mcp): orphan cleanup + audit BaseException (W2 T1)"
```

---

### 任务 2：trace.py + utils.py（4 个 LLM tool 共用基建）

**Files:**
- Create: `services/knowledge-engine/app/mcp/trace.py`
- Create: `services/knowledge-engine/app/mcp/utils.py`
- Create: `services/knowledge-engine/tests/test_mcp_trace.py`
- Create: `services/knowledge-engine/tests/test_mcp_utils.py`

- [ ] **Step 1：写 trace 测试**

`services/knowledge-engine/tests/test_mcp_trace.py`:
```python
"""T2：trace 工具函数。"""
from app.mcp.trace import build_trace, attach_next_step


def test_build_trace_minimal():
    t = build_trace(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt="hello",
        params={"temperature": 0.3},
        cost_estimate="1 quota call",
    )
    assert t["model"] == "claude-sonnet-4-6"
    assert t["model_provider"] == "anthropic"
    assert t["final_prompt"] == "hello"
    assert t["params"] == {"temperature": 0.3}
    assert t["cost_estimate"] == "1 quota call"


def test_build_trace_truncates_long_prompt():
    long = "x" * 50_000
    t = build_trace(
        provider="anthropic", model="m", prompt=long, params={}, cost_estimate=""
    )
    # prompt 太长截断防止 audit 表 jsonb 行爆
    assert len(t["final_prompt"]) <= 16_384
    assert t["final_prompt"].endswith("...[truncated]")


def test_attach_next_step_adds_field():
    result = {"ok": True, "result": {"x": 1}, "trace": {"model": "m"}}
    out = attach_next_step(
        result,
        suggested_tool="generate_image",
        suggested_args={"prompts": ["a"]},
        human_text="出图",
    )
    assert out["next_step_hint"]["suggested_tool"] == "generate_image"
    assert out["next_step_hint"]["human_text"] == "出图"
    # 不破坏原 result
    assert out["result"] == {"x": 1}
```

`services/knowledge-engine/tests/test_mcp_utils.py`:
```python
"""T2：utils（Decimal 序列化）。"""
import json
from decimal import Decimal

from app.mcp.utils import decimal_to_jsonable


def test_decimal_to_jsonable_scalar():
    assert decimal_to_jsonable(Decimal("12.345")) == "12.345"


def test_decimal_to_jsonable_nested_dict():
    src = {"price": Decimal("9.99"), "qty": 3, "child": {"cost": Decimal("0.50")}}
    out = decimal_to_jsonable(src)
    assert out == {"price": "9.99", "qty": 3, "child": {"cost": "0.50"}}
    # 验证可被 json.dumps
    json.dumps(out)


def test_decimal_to_jsonable_list():
    src = [Decimal("1"), {"a": Decimal("2")}, [Decimal("3")]]
    out = decimal_to_jsonable(src)
    assert out == ["1", {"a": "2"}, ["3"]]
    json.dumps(out)


def test_decimal_to_jsonable_passthrough_other_types():
    assert decimal_to_jsonable(None) is None
    assert decimal_to_jsonable("hi") == "hi"
    assert decimal_to_jsonable(42) == 42
    assert decimal_to_jsonable(3.14) == 3.14
    assert decimal_to_jsonable(True) is True
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_trace.py tests/test_mcp_utils.py -v
```

Expected: ImportError on both modules.

- [ ] **Step 3：实现 trace.py**

`services/knowledge-engine/app/mcp/trace.py`:
```python
"""W2 T2：tool trace 工具函数（design doc §6 review-after iterate 必带字段）。

每个 LLM tool 的 result 必须含 trace（让老板诊断 + Claude 大脑判断重跑参数）。
建工具函数避免每个 tool 自己拼。
"""
from __future__ import annotations

from typing import Any

_PROMPT_MAX_LEN = 16_384


def build_trace(
    *,
    provider: str,
    model: str,
    prompt: str,
    params: dict[str, Any],
    cost_estimate: str,
) -> dict[str, Any]:
    """构造 trace 字段。

    Args:
        provider: e.g. "anthropic" / "openai" / "seedance"
        model: 实际调的 model（来自 tool_models.yaml 解析后）
        prompt: 完整 final prompt（system + user 拼好；过长截断）
        params: 关键参数（temperature / top_p / max_tokens 等）
        cost_estimate: 人话费用描述，如 "1 quota call" / "¥0.5" / "¥15"

    Returns:
        {model_provider, model, final_prompt, params, cost_estimate}
    """
    p = prompt or ""
    if len(p) > _PROMPT_MAX_LEN:
        p = p[:_PROMPT_MAX_LEN] + "...[truncated]"
    return {
        "model_provider": provider,
        "model": model,
        "final_prompt": p,
        "params": dict(params),
        "cost_estimate": cost_estimate,
    }


def attach_next_step(
    result: dict[str, Any],
    *,
    suggested_tool: str | None,
    suggested_args: dict[str, Any] | None = None,
    human_text: str = "",
) -> dict[str, Any]:
    """给 tool result 加 next_step_hint 字段。

    Args:
        result: 已含 ok/result/trace 的 dict
        suggested_tool: 建议下一步调哪个 tool；None 表示链路到此结束
        suggested_args: 给老板看的建议入参（参考用，老板可改）
        human_text: 给老板的 1 句话说明（"出 3 张分镜图，~¥1.5"）
    """
    result["next_step_hint"] = {
        "suggested_tool": suggested_tool,
        "suggested_args": suggested_args or {},
        "human_text": human_text,
    }
    return result
```

- [ ] **Step 4：实现 utils.py**

`services/knowledge-engine/app/mcp/utils.py`:
```python
"""W2 T2：tool 通用 utils。

- decimal_to_jsonable：递归把 Decimal 转 str（compute_margin 算账输出 Decimal，
  必须转 str 才能进 mcp.tool_calls.result jsonb）
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def decimal_to_jsonable(obj: Any) -> Any:
    """递归把 Decimal → str；其他类型透传。"""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(decimal_to_jsonable(v) for v in obj)
    return obj
```

- [ ] **Step 5：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_trace.py tests/test_mcp_utils.py -v
```

Expected: 全 PASS

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/trace.py `
        services/knowledge-engine/app/mcp/utils.py `
        services/knowledge-engine/tests/test_mcp_trace.py `
        services/knowledge-engine/tests/test_mcp_utils.py
git commit -m "feat(mcp): trace + decimal utils for W2 LLM tools (W2 T2)"
```

---

### 任务 3：tool_models.yaml 扩 + CLAUDE.md 项目级指令

**Files:**
- Modify: `services/knowledge-engine/config/tool_models.yaml`
- Create: `E:\agent\omni\CLAUDE.md`

- [ ] **Step 1：扩 tool_models.yaml**

打开 `services/knowledge-engine/config/tool_models.yaml`，把内容替换为：
```yaml
# tool → 模型映射（design doc §2.5）
# W1：仅 __default__ 起作用
# W2：4 个 LLM tool 各自 keyed override（独立切模型）

__default__:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.3

# W2 keyed override
# 注意：老板的 Anthropic 是 Claude Code Max 订阅（主大脑用），不是 API key →
# hub 端 tool 内部 LLM **不能用 anthropic**。chat 走 gemini-3-flash-preview。
# image: openai/gpt-image-2；video: seedance/seedance-2-0（老板填 SEEDANCE_API_KEY）。

compute_margin:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.1   # 解读类，要稳

generate_brief:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.5   # 文案要发挥

generate_image:
  provider: openai
  model: gpt-image-2

generate_video:
  provider: seedance
  model: seedance-2-0
  duration: 8
```

如某 tool 跑下来发现 gemini-3-flash 中文质量不够好，单独把那一行 provider/model 切到 openai/gpt-5.4-mini（一行 yaml + 容器 restart 即生效，无需改代码）。

- [ ] **Step 2：建项目根 CLAUDE.md**

`E:\agent\omni\CLAUDE.md`:
```markdown
# omni-vibe Claude Code 指令

> 这文件是给 Claude Code（agent 主大脑）看的，不是产品文档。

## omni MCP server

omni 暴露 10 个 tool（W1 5 个 + W2 5 个）：
- 查询：`list_skus`, `get_sku`, `list_kbs`, `search_kb`, `list_briefs`, `query_costs`
- 算账：`compute_margin`
- 生成：`generate_brief`, `generate_image`, `generate_video`

调用见 `services/knowledge-engine/app/mcp/tools/`。

## sku 出片标准链路（老板说"sku-X 全链路"时按此走）

1. 调 `query_costs(sku_id)` 拿成本
2. 调 `compute_margin(sku_id, channel)` 算利润，给老板审；老板满意进 3
3. 调 `generate_brief(sku_id, channel)` 出 brief，给老板审；老板满意进 4
4. 调 `generate_image(prompts=[3 个分镜 prompt], face_refs/product_refs)` 出 3 张分镜图，给老板审；老板满意进 5
5. 调 `generate_video(segments=[3 段 prompt + 首尾帧链], face_refs, product_refs)` 出 3 段视频，给老板下载

每步跑完把 result + trace + next_step_hint 都给老板看。**不要一气呵成跑完整套**——每步停下来等老板反馈。

## 老板响应词约定

| 老板说 | 含义 | Claude 应做 |
|---|---|---|
| OK / 继续 / 赞 / 通过 / 进下一步 | 当前 step 满意，进下一步 | 按 next_step_hint.suggested_tool + suggested_args 调下一个 tool |
| 重来 / 改 / 不行 / 重跑 | 当前 step 不满意 | 用同 tool 重调，参数照老板新说法改（如老板说"prompt 加 X"，把 X 加进 prompt） |
| 第 N 张重来 / 第 N 段重做 | 局部重跑 | 只重调那一段（generate_image 单独一个 prompt；generate_video 单独一个 segment） |
| 跳过 X / 不要这步 | 跳一步 | 不调 X，按链路下一步走 |
| 全链路 / 跑通 | 触发标准链路 | 从 step 1 query_costs 起按上面 5 步走，每步停下等老板反馈 |

## 已知约束

- 不调 `run_sku_orch` —— W2 没这个 tool，编排靠对话
- LLM tool 必返 `trace` 字段，老板要看 final_prompt 才能调 prompt 重跑
- video 多段并发跑（asyncio.gather），typically 30-60s 每段；并发后总时间 ≈ 单段
- 所有 W2 tool 都不走 Human Gate（W1 stub 保留给 W3）

## 调试

- 容器内自检：`docker exec omni-knowledge-engine python -m app.mcp.doctor`
- 审计表：`SELECT tool_name, status, duration_ms FROM mcp.tool_calls ORDER BY created_at DESC LIMIT 20`
- ai-provider-hub 状态：`curl http://localhost:8001/api/v1/ai/providers`
```

- [ ] **Step 3：重启 KE 容器让 yaml 生效**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine python -m app.mcp.doctor
```

Expected: doctor 5 项全绿；`tool_models.yaml: keys=['__default__','compute_margin','generate_brief','generate_image','generate_video']`。

- [ ] **Step 4：commit**

```powershell
git add services/knowledge-engine/config/tool_models.yaml CLAUDE.md
git commit -m "feat(mcp): tool_models.yaml W2 keyed override + project CLAUDE.md (W2 T3)"
```

---

### 任务 4：query_costs tool（纯 DB 查询）

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/accounting.py`（部分；T5 续写）
- Create: `services/knowledge-engine/tests/test_mcp_accounting.py`（部分；T5 续写）
- Modify: `services/knowledge-engine/app/mcp/server.py`（注册 tool）

- [ ] **Step 1：写 query_costs 测试**

`services/knowledge-engine/tests/test_mcp_accounting.py`（新建）:
```python
"""T4 + T5：accounting tools 集成测（hits dev DB）。"""
import asyncio
from decimal import Decimal

import pytest
from app.database import get_pool, init_pool, close_pool
from app.mcp.tools.accounting import query_costs


@pytest.fixture(scope="module", autouse=True)
def _pool():
    asyncio.run(init_pool())
    yield
    asyncio.run(close_pool())


@pytest.fixture(scope="module", autouse=True)
def _seed_data():
    """插测试 cost_items；module teardown 清。"""
    async def _setup():
        pool = get_pool()
        await pool.execute(
            """
            INSERT INTO accounting.cost_items
                (sku_id, category, item_name, unit_cost, currency, unit, quantity_per_unit, vendor, is_active)
            VALUES
                ('_smoke_sku_001', 'product', '_smoke 瓶身', 0.80, 'CNY', '个', 1, '_smoke 厂', TRUE),
                ('_smoke_sku_001', 'product', '_smoke 标签', 0.15, 'CNY', '张', 1, '_smoke 印刷', TRUE),
                (NULL, 'logistics', '_smoke 顺丰华东', 4.50, 'CNY', '件', 1, '_smoke 物流', TRUE)
            """
        )
    asyncio.run(_setup())
    yield
    async def _cleanup():
        pool = get_pool()
        await pool.execute("DELETE FROM accounting.cost_items WHERE item_name LIKE '_smoke %'")
    asyncio.run(_cleanup())


@pytest.mark.asyncio
async def test_smoke_query_costs_returns_sku_and_shared():
    r = await query_costs(sku_id="_smoke_sku_001")
    assert r["ok"] is True
    items = r["result"]["cost_items"]
    # 至少 3 行：2 product (sku) + 1 logistics (shared)
    smoke = [i for i in items if i["item_name"].startswith("_smoke ")]
    assert len(smoke) >= 3
    # 验证字段都是 jsonable（unit_cost 应为 str）
    for i in smoke:
        assert isinstance(i["unit_cost"], str)


@pytest.mark.asyncio
async def test_smoke_query_costs_unknown_sku_returns_only_shared():
    r = await query_costs(sku_id="_smoke_sku_does_not_exist_999")
    assert r["ok"] is True
    items = r["result"]["cost_items"]
    smoke = [i for i in items if i["item_name"].startswith("_smoke ")]
    # 共享（sku_id IS NULL）的物流应在结果里
    cats = [i["category"] for i in smoke]
    assert "logistics" in cats


@pytest.mark.asyncio
async def test_smoke_query_costs_inactive_excluded():
    pool = get_pool()
    await pool.execute(
        "INSERT INTO accounting.cost_items (sku_id, category, item_name, unit_cost, is_active) "
        "VALUES ('_smoke_sku_001', 'product', '_smoke 已停', 9.99, FALSE)"
    )
    try:
        r = await query_costs(sku_id="_smoke_sku_001")
        names = [i["item_name"] for i in r["result"]["cost_items"]]
        assert "_smoke 已停" not in names
    finally:
        await pool.execute("DELETE FROM accounting.cost_items WHERE item_name='_smoke 已停'")
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_accounting.py -v
```

Expected: ImportError on `app.mcp.tools.accounting`.

- [ ] **Step 3：实现 query_costs**

`services/knowledge-engine/app/mcp/tools/accounting.py`（新建，T5 在此续写）:
```python
"""W2 T4 + T5：accounting tools。

- query_costs：纯 DB 查 accounting.cost_items（migration 015）
- compute_margin：DB 查成本 + Python 算账（确定性）+ LLM 写解读
"""
from __future__ import annotations

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.mcp.utils import decimal_to_jsonable


@tool_with_audit(mcp, require_approval=False)
async def query_costs(sku_id: str) -> dict:
    """查 SKU 的有效成本项（含共享成本如物流）。纯 DB 查询，无 LLM 调用。

    Args:
        sku_id: SKU id

    Returns:
        {"ok": True, "result": {"cost_items": [{id, sku_id, category, item_name,
            unit_cost, currency, unit, quantity_per_unit, vendor, valid_from,
            valid_to, notes}, ...]}}

        category 取值：product | logistics | partner_quote
        sku_id 为 None 的行表示共享成本（如全 SKU 共用的物流费）
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, sku_id, category, item_name, unit_cost, currency, unit,
               quantity_per_unit, vendor, valid_from, valid_to, notes
        FROM accounting.cost_items
        WHERE (sku_id = $1 OR sku_id IS NULL)
          AND is_active = TRUE
          AND valid_from <= CURRENT_DATE
          AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
        ORDER BY (sku_id IS NULL), category, valid_from DESC
        """,
        sku_id,
    )
    items = [decimal_to_jsonable(dict(r)) for r in rows]
    # UUID / date 也 str 化
    for i in items:
        if i.get("id") is not None:
            i["id"] = str(i["id"])
        if i.get("valid_from") is not None:
            i["valid_from"] = str(i["valid_from"])
        if i.get("valid_to") is not None:
            i["valid_to"] = str(i["valid_to"])
    return {"ok": True, "result": {"cost_items": items}}
```

- [ ] **Step 4：注册 tool 到 server**

打开 `services/knowledge-engine/app/mcp/server.py`，在 W1 import 列表底下加：
```python
from app.mcp.tools import accounting as _accounting_tools  # noqa: F401  registers query_costs / compute_margin
```

如果 server.py 已用了某 import all 模式（看现有结构），按它的模式接进来。

- [ ] **Step 5：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_accounting.py -v
```

Expected: 3 PASS

- [ ] **Step 6：跑 doctor 验证 6 tool 注册**

```powershell
docker exec omni-knowledge-engine python -m app.mcp.doctor
```

Expected: `6 tools registered: all 6 ok`（W1 5 + query_costs 1）。如 doctor 还硬编码 5，T10 一并改。

- [ ] **Step 7：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/accounting.py `
        services/knowledge-engine/app/mcp/server.py `
        services/knowledge-engine/tests/test_mcp_accounting.py
git commit -m "feat(mcp): query_costs tool (W2 T4)"
```

---

### 任务 5：compute_margin tool（DB + Python 算 + LLM 解读）

**关键设计**：**LLM 不做数学**——成本、利润、净利率都用 Python 算（Decimal 精确）；LLM 只写自然语言"解读 + 建议"附在 result 里。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/accounting.py`（续写 compute_margin）
- Modify: `services/knowledge-engine/tests/test_mcp_accounting.py`（加 compute_margin 测）

- [ ] **Step 1：写 compute_margin 测试**

在 `services/knowledge-engine/tests/test_mcp_accounting.py` 文件末尾追加：
```python
from app.mcp.tools.accounting import compute_margin


# 复用 _seed_data fixture 的 _smoke_sku_001（成本：瓶身 0.80 + 标签 0.15 + 物流 4.50 = 5.45）

@pytest.mark.asyncio
async def test_smoke_compute_margin_basic_math():
    """sale_price=29.9 / cost=5.45 → margin=24.45 / margin_pct ≈ 0.818。

    LLM 解读字段允许波动；但数字字段必须是确定性。
    """
    r = await compute_margin(
        sku_id="_smoke_sku_001",
        channel="douyin",
        sale_price="29.90",
        qty=1,
        channel_fee_rate="0.05",   # 抖音典型扣点
        skip_llm=True,             # 仅算账，跳过 LLM 写解读（测试隔离）
    )
    assert r["ok"] is True
    breakdown = r["result"]["breakdown"]
    # cost 总和
    assert breakdown["cost_total"] == "5.45"
    # gmv = sale_price * qty
    assert breakdown["gmv"] == "29.90"
    # channel_fee = gmv * channel_fee_rate = 29.90 * 0.05 = 1.495
    assert breakdown["channel_fee"] == "1.4950"
    # net_profit = gmv - cost_total - channel_fee = 29.90 - 5.45 - 1.495 = 22.955
    assert breakdown["net_profit"] == "22.9550"
    # margin_pct = net_profit / gmv ≈ 0.7677
    assert breakdown["margin_pct"].startswith("0.76")


@pytest.mark.asyncio
async def test_smoke_compute_margin_no_costs_returns_warning():
    r = await compute_margin(
        sku_id="_smoke_sku_does_not_exist_999",
        channel="douyin",
        sale_price="9.99",
        qty=1,
        skip_llm=True,
    )
    assert r["ok"] is True
    # cost_total 至少含共享成本物流 4.50；如全无，breakdown 仍要返
    assert "cost_total" in r["result"]["breakdown"]


@pytest.mark.asyncio
async def test_smoke_compute_margin_trace_fields_present():
    r = await compute_margin(
        sku_id="_smoke_sku_001", channel="douyin",
        sale_price="29.90", qty=1, skip_llm=True,
    )
    # 即使 skip_llm，trace 也要有（写"skipped"）
    assert "trace" in r
    assert r["trace"]["model"]
    # next_step_hint 链路终点：margin 后建议 generate_brief
    assert r["next_step_hint"]["suggested_tool"] == "generate_brief"
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_accounting.py::test_smoke_compute_margin_basic_math -v
```

Expected: ImportError or AttributeError on compute_margin.

- [ ] **Step 3：实现 compute_margin**

在 `services/knowledge-engine/app/mcp/tools/accounting.py` 文件末尾追加：
```python
import json
from decimal import Decimal, ROUND_HALF_UP

from app.mcp.model_config import get_model
from app.mcp.trace import attach_next_step, build_trace
from app.services.ai_hub_client import AIHubClient


def _to_dec(x) -> Decimal:
    return Decimal(str(x))


@tool_with_audit(mcp, require_approval=False)
async def compute_margin(
    sku_id: str,
    channel: str,
    sale_price: str | None = None,
    qty: int = 1,
    channel_fee_rate: str = "0.05",
    skip_llm: bool = False,
) -> dict:
    """算 SKU 在某渠道的净利率。LLM 不做数学，只写解读。

    Args:
        sku_id: SKU id
        channel: 渠道（douyin/tmall/jd 等）
        sale_price: 售价（str 输入避 float 误差）；None 则查 mvp_sku.sale_price
        qty: 数量（默认 1）
        channel_fee_rate: 渠道扣点（默认 0.05 = 5%）
        skip_llm: 测试用，跳过 LLM 解读

    Returns:
        {"ok": True,
         "result": {"breakdown": {gmv, cost_total, channel_fee, net_profit,
                                 margin_pct, items: [...]},
                    "interpretation": "..."},  # LLM 写的人话
         "trace": {...},
         "next_step_hint": {suggested_tool: "generate_brief", ...}}
    """
    pool = get_pool()

    # 1. 拿成本（复用 query_costs 内部 SQL 直接查，避免装饰器嵌套）
    cost_rows = await pool.fetch(
        """
        SELECT category, item_name, unit_cost, quantity_per_unit
        FROM accounting.cost_items
        WHERE (sku_id = $1 OR sku_id IS NULL)
          AND is_active = TRUE
          AND valid_from <= CURRENT_DATE
          AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
        """,
        sku_id,
    )

    cost_items = []
    cost_total = Decimal("0")
    for r in cost_rows:
        line = _to_dec(r["unit_cost"]) / _to_dec(r["quantity_per_unit"])
        cost_total += line
        cost_items.append({
            "category": r["category"],
            "item_name": r["item_name"],
            "line_cost": str(line.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        })

    # 2. 拿售价（如未给）
    if sale_price is None:
        srow = await pool.fetchrow(
            "SELECT sale_price FROM mvp_sku WHERE sku_id = $1", sku_id
        )
        sale_price = str(srow["sale_price"]) if srow and srow["sale_price"] else "0"

    sale_dec = _to_dec(sale_price)
    qty_dec = _to_dec(qty)
    fee_rate = _to_dec(channel_fee_rate)

    # 3. 算账
    gmv = sale_dec * qty_dec
    channel_fee = (gmv * fee_rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    cost_subtotal = (cost_total * qty_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net_profit = (gmv - cost_subtotal - channel_fee).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    margin_pct = (net_profit / gmv).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if gmv > 0 else Decimal("0")

    breakdown = {
        "sku_id": sku_id,
        "channel": channel,
        "qty": qty,
        "sale_price": str(sale_dec),
        "channel_fee_rate": str(fee_rate),
        "gmv": str(gmv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "cost_total": str(cost_subtotal),
        "channel_fee": str(channel_fee),
        "net_profit": str(net_profit),
        "margin_pct": str(margin_pct),
        "items": cost_items,
    }

    # 4. LLM 写解读（不让它算数学）
    model_cfg = get_model("compute_margin")
    interpretation = ""
    final_prompt = ""
    cost_estimate = "skipped"

    if not skip_llm:
        sys_msg = (
            "你是调味品工厂的财务助理。下面给你一组已算好的成本/利润数字"
            "（精确，不要重算）。用 2-3 句话写解读：(a) 净利率落在什么档位"
            "（健康/边缘/亏本）；(b) 成本结构里最大的占比是什么；"
            "(c) 如果想提净利 5 个点，最现实的杠杆点是什么。"
            "说人话，不要废话，不要复述数字。"
        )
        user_msg = "数据：\n" + json.dumps(breakdown, ensure_ascii=False, indent=2)
        final_prompt = sys_msg + "\n\n" + user_msg
        client = AIHubClient()
        try:
            resp = await client.chat(
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                provider=model_cfg.get("provider", "gemini"),
                model=model_cfg.get("model", "gemini-3-flash-preview"),
                temperature=model_cfg.get("temperature", 0.1),
                max_tokens=600,
                enforce_human_voice=True,
            )
            # ai-provider-hub chat response shape: {choices:[{message:{content:...}}], ...}
            # 实际 schema 看 hub 现状；fallback 取 .text 或第一个 message
            interpretation = (
                ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
                or resp.get("text")
                or resp.get("content")
                or ""
            ).strip()
            cost_estimate = "1 quota call (~few hundred tokens)"
        except Exception as exc:
            interpretation = f"[LLM 解读失败: {type(exc).__name__}: {exc}]"
            cost_estimate = "0 (LLM 调用失败)"

    result = {
        "ok": True,
        "result": {"breakdown": breakdown, "interpretation": interpretation},
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt or "[skipped]",
            params={
                "temperature": model_cfg.get("temperature", 0.1),
                "max_tokens": 600,
            },
            cost_estimate=cost_estimate,
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_brief",
        suggested_args={"sku_id": sku_id, "channel": channel},
        human_text=f"利润 OK 的话出 brief（generate_brief，~1 quota call）",
    )
```

**注意**：上述 `model_cfg.get("provider")` 假设 `get_model` 返 dict；若 W1 已实现成对象，按对象属性访问改写（看 `app/mcp/model_config.py`）。

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_accounting.py -v
```

Expected: 全 PASS（3 个 query_costs + 3 个 compute_margin）

- [ ] **Step 5：手动 e2e 一个 LLM 路径（不 skip_llm）**

```powershell
docker exec omni-knowledge-engine python -c "
import asyncio
from app.database import init_pool, close_pool
from app.mcp.tools.accounting import compute_margin

async def main():
    await init_pool()
    try:
        r = await compute_margin(sku_id='_smoke_sku_001', channel='douyin',
                                  sale_price='29.90', qty=1, skip_llm=False)
        print('breakdown:', r['result']['breakdown'])
        print('interpretation:', r['result']['interpretation'])
        print('trace.model:', r['trace']['model'])
        print('cost:', r['trace']['cost_estimate'])
    finally:
        await close_pool()
asyncio.run(main())
"
```

Expected: interpretation 含人话 2-3 句解读；trace.cost_estimate 含 'quota'。

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/accounting.py `
        services/knowledge-engine/tests/test_mcp_accounting.py
git commit -m "feat(mcp): compute_margin tool with deterministic math + LLM interp (W2 T5)"
```

---

### 任务 6：generate_brief tool（LLM 出 brief + trace + next_step_hint）

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/media.py`（部分；T8/T9 续写）
- Create: `services/knowledge-engine/tests/test_mcp_media.py`（部分；T8/T9 续写）
- Modify: `services/knowledge-engine/app/mcp/server.py`（注册 media tools）

- [ ] **Step 1：写 generate_brief 测试**

`services/knowledge-engine/tests/test_mcp_media.py`（新建）:
```python
"""T6/T8/T9：media tools 集成测。"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from app.database import init_pool, close_pool
from app.mcp.tools.media import generate_brief


@pytest.fixture(scope="module", autouse=True)
def _pool():
    asyncio.run(init_pool())
    yield
    asyncio.run(close_pool())


@pytest.mark.asyncio
async def test_smoke_generate_brief_returns_brief_and_trace():
    """mock hub.chat 验 brief tool 链路：调 → 解析 → trace + hint。"""
    fake_hub_resp = {
        "choices": [
            {"message": {"content": "# 抖音渠道 Brief\n\n卖点：...\n场景：..."}}
        ]
    }
    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.chat = AsyncMock(return_value=fake_hub_resp)
        r = await generate_brief(sku_id="_smoke_sku_001", channel="douyin")

    assert r["ok"] is True
    assert "Brief" in r["result"]["brief_md"] or "brief" in r["result"]["brief_md"].lower()
    assert r["trace"]["model"]
    assert r["trace"]["final_prompt"]
    assert r["next_step_hint"]["suggested_tool"] == "generate_image"
    # 建议 args 含 prompts list 让老板出分镜
    assert "prompts" in r["next_step_hint"]["suggested_args"]


@pytest.mark.asyncio
async def test_smoke_generate_brief_handles_hub_failure():
    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.chat = AsyncMock(side_effect=RuntimeError("hub down"))
        r = await generate_brief(sku_id="_smoke_sku_001", channel="douyin")
    # tool_with_audit 的 BaseException 路径会接住 → ok=False
    assert r["ok"] is False
    assert "hub down" in r["error"]
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_media.py::test_smoke_generate_brief_returns_brief_and_trace -v
```

Expected: ImportError on `app.mcp.tools.media`.

- [ ] **Step 3：实现 generate_brief（写在 media.py）**

`services/knowledge-engine/app/mcp/tools/media.py`（新建）:
```python
"""W2 T6/T8/T9：media tools。

- generate_brief：基于 sku metadata + 渠道特点 + KB context → Claude → markdown brief
- generate_image：多 prompt 一次出多张分镜（gpt-image-2，多类 refs）  ← T8
- generate_video：多 segment 并发跑 Seedance 各段（首尾帧 + refs）   ← T9

每个 LLM tool 返 result + trace + next_step_hint。
"""
from __future__ import annotations

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.services.ai_hub_client import AIHubClient


_CHANNEL_PROFILES = {
    "douyin": "抖音电商：竖版 9:16，前 3 秒强钩子，价格锚点 + 痛点切入；忌过长 brief（≤300 字）",
    "tmall": "天猫店铺：详情页长图文，强调品质 + 资质 + 用户证言；2-4 段，每段含一个购买理由",
    "jd": "京东自营：物流 + 售后承诺为主；强调正品 / 配送 / 服务",
}


def _channel_profile(channel: str) -> str:
    return _CHANNEL_PROFILES.get(channel, f"渠道 {channel}（未配 profile，按通用电商写）")


@tool_with_audit(mcp, require_approval=False)
async def generate_brief(
    sku_id: str,
    channel: str,
    extra_context: str | None = None,
) -> dict:
    """出渠道 brief（markdown）。基于 sku metadata + 渠道 profile + 可选 extra context。

    Args:
        sku_id: SKU id
        channel: 渠道（douyin / tmall / jd / ...）
        extra_context: 额外提示（如"主推健康"/"对标 X 品牌"）

    Returns:
        {ok, result: {brief_md}, trace, next_step_hint(generate_image)}
    """
    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT sku_id, name, category, sale_price, description "
        "FROM mvp_sku WHERE sku_id = $1",
        sku_id,
    )
    if not sku:
        return {
            "ok": False,
            "error": f"sku_id 未找到: {sku_id}",
            "hint": "调 list_skus 看现有 sku_id",
        }

    sku_md = (
        f"- 名称：{sku['name']}\n"
        f"- 品类：{sku['category']}\n"
        f"- 售价：{sku['sale_price']}\n"
        f"- 描述：{sku['description'] or '（无）'}\n"
    )

    sys_msg = (
        "你是调味品工厂老板的渠道运营。给一只 SKU 写一份渠道 brief。"
        "brief 用 markdown 格式，含：核心卖点（3 条）/ 目标人群 / "
        "主场景 / 文案钩子（1 句）/ 拍摄分镜建议（3 个分镜的 1 句话描述）。"
        "说人话，不要废话，不要"亲""家人们"等套话。"
    )
    user_msg = (
        f"## SKU\n{sku_md}\n"
        f"## 渠道\n{_channel_profile(channel)}\n"
    )
    if extra_context:
        user_msg += f"\n## 额外要求\n{extra_context}\n"

    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model("generate_brief")
    client = AIHubClient()
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        temperature=model_cfg.get("temperature", 0.5),
        max_tokens=1200,
        enforce_human_voice=True,
    )
    brief_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    # 从 brief 文本里抠 3 个分镜建议作为 generate_image 的初始 prompts
    # 简单粗暴：按行扫"分镜"或"shot"或"场景 N"；找不到就给 placeholder
    suggested_prompts: list[str] = []
    for line in brief_md.split("\n"):
        s = line.strip()
        if not s:
            continue
        if any(k in s for k in ("分镜", "shot", "场景")) and len(s) > 6:
            suggested_prompts.append(s.lstrip("-*0123456789. ").strip())
            if len(suggested_prompts) >= 3:
                break
    if len(suggested_prompts) < 3:
        suggested_prompts = [
            f"{sku['name']} 主图：产品居中，{channel} 风格",
            f"{sku['name']} 使用场景：日常厨房，自然光",
            f"{sku['name']} 细节特写：质感 + 包装",
        ]

    result = {
        "ok": True,
        "result": {"brief_md": brief_md},
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.5),
                "max_tokens": 1200,
            },
            cost_estimate="1 quota call (~1k tokens)",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_image",
        suggested_args={
            "prompts": suggested_prompts,
            "face_refs": [],
            "product_refs": [],   # 老板补 sku 主图 url
            "aspect_ratio": "9:16" if channel == "douyin" else "1:1",
        },
        human_text=(
            "出 3 张分镜图（gpt-image-2，~¥1.5 / 3 张）；"
            "如要保产品一致，product_refs 填 sku 主图 url"
        ),
    )
```

- [ ] **Step 4：注册 media tools**

打开 `services/knowledge-engine/app/mcp/server.py`，在 `_accounting_tools` import 之后加：
```python
from app.mcp.tools import media as _media_tools  # noqa: F401
```

- [ ] **Step 5：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_media.py -v
```

Expected: 2 PASS

- [ ] **Step 6：跑 doctor 验 7 tool 注册**

```powershell
docker exec omni-knowledge-engine python -m app.mcp.doctor
```

Expected: `7 tools registered: all 7 ok`（如 doctor 还硬编码 5/6，T10 一并改）。

- [ ] **Step 7：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/media.py `
        services/knowledge-engine/app/mcp/server.py `
        services/knowledge-engine/tests/test_mcp_media.py
git commit -m "feat(mcp): generate_brief tool with trace + next_step_hint (W2 T6)"
```

---

### 任务 7：ai_hub_client v2 接口（多类 refs + 首尾帧）

**目的**：`AIHubClient.generate_image` 当前只接 `refs: list[str]` 单一类；W2 要分 face/product/style 三类，video 还要首尾帧。新增 v2 方法不破 v1。

**关键**：先验证 hub 端实际接口能传啥，再决定 client v2 body schema。

**Files:**
- Modify: `services/knowledge-engine/app/services/ai_hub_client.py`
- Modify: `services/knowledge-engine/tests/test_mcp_media.py`（加 v2 mock 测试）

- [ ] **Step 1：先 inspect hub 现有 image / video schema**

```powershell
curl.exe -s http://127.0.0.1:8001/openapi.json | python -c "
import json, sys
spec = json.load(sys.stdin)
for p in ['/api/v1/ai/images/generate', '/api/v1/ai/videos/generate']:
    print('=== ', p)
    op = spec.get('paths', {}).get(p, {}).get('post', {})
    rb = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema', {})
    print(json.dumps(rb, indent=2, ensure_ascii=False)[:2000])
"
```

把输出贴进 commit message 草稿，知道 hub 实际收什么。

**典型预期**（基于 ai-provider-hub 通用做法 + Seedance/gpt-image-2 文档）：
- `/images/generate` body：`{prompt, model, n?, reference_images?, aspect_ratio?, ...}`
- `/videos/generate` body：`{prompt, model, duration?, reference_images?, first_frame?, last_frame?, ...}`

如 hub 不支持 first_frame / last_frame，**两条路**：
- a) 在 hub 端先扩接口（services/ai-provider-hub），再回 W2 这一步
- b) W2 暂用 reference_images 模拟（把 first_frame 也当 ref 传，丢失一些精确度），W3 再补正

实施时记下选了哪条。

- [ ] **Step 2：写 v2 单测**

在 `services/knowledge-engine/tests/test_mcp_media.py` 末尾追加：
```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_hub_client import AIHubClient


@pytest.mark.asyncio
async def test_smoke_generate_image_v2_passes_face_and_product_refs():
    captured = {}

    class FakeResp:
        def raise_for_status(self): return None
        def json(self): return {"images": [{"url": "https://fake/1.png"}]}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json=None, **kw):
            captured["url"] = url
            captured["body"] = json
            return FakeResp()

    with patch("app.services.ai_hub_client.httpx.AsyncClient", return_value=FakeClient()):
        client = AIHubClient()
        r = await client.generate_image_v2(
            prompt="产品图",
            face_refs=["https://face/a.png"],
            product_refs=["https://prod/b.png"],
            style_refs=None,
            aspect="9:16",
            n=1,
            model="gpt-image-2",
            provider="openai",
        )
    assert r["images"][0]["url"] == "https://fake/1.png"
    body = captured["body"]
    # face / product 都要在 body 里某种形式表达
    flat = json.dumps(body, ensure_ascii=False)
    assert "face/a.png" in flat
    assert "prod/b.png" in flat


@pytest.mark.asyncio
async def test_smoke_generate_video_v2_passes_first_last_frame():
    captured = {}

    class FakeResp:
        def raise_for_status(self): return None
        def json(self): return {"task_id": "t-001", "status": "pending"}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json=None, **kw):
            captured["body"] = json
            return FakeResp()

    with patch("app.services.ai_hub_client.httpx.AsyncClient", return_value=FakeClient()):
        client = AIHubClient()
        r = await client.generate_video_v2(
            prompt="慢镜头",
            first_frame="https://x/a.png",
            last_frame="https://x/b.png",
            duration_sec=8,
            face_refs=["https://face/m.png"],
            product_refs=None,
            aspect="9:16",
            model="seedance-2-0",
            provider="seedance",
        )
    assert r["task_id"] == "t-001"
    flat = json.dumps(captured["body"], ensure_ascii=False)
    assert "x/a.png" in flat
    assert "x/b.png" in flat
```

- [ ] **Step 3：实现 v2 方法（添加到 `ai_hub_client.py`）**

打开 `services/knowledge-engine/app/services/ai_hub_client.py`，在 class `AIHubClient` 末尾追加（文件最后一个方法 `wait_for_video` 之后）：
```python
    async def generate_image_v2(
        self,
        prompt: str,
        *,
        face_refs: list[str] | None = None,
        product_refs: list[str] | None = None,
        style_refs: list[str] | None = None,
        aspect: str = "9:16",
        n: int = 1,
        model: str = "gpt-image-2",
        provider: str = "openai",
        extra: dict[str, Any] | None = None,
    ) -> dict:
        """W2: image gen with multi-class refs.

        Body shape（如 hub 不支持分类 refs，全部合并到 reference_images，并用
        ref_roles 字段告知类别——按 hub openapi 实际选）：
        """
        # 把所有 ref 拼一个 list，附加 ref_roles 元数据让 hub 知道哪个是哪类
        refs: list[str] = []
        ref_roles: list[str] = []
        for r in face_refs or []:
            refs.append(r); ref_roles.append("face")
        for r in product_refs or []:
            refs.append(r); ref_roles.append("product")
        for r in style_refs or []:
            refs.append(r); ref_roles.append("style")

        body: dict[str, Any] = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "n": n,
            "aspect_ratio": aspect,
        }
        if refs:
            body["reference_images"] = refs
            body["ref_roles"] = ref_roles
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/images/generate", json=body)
            r.raise_for_status()
            return r.json()

    async def generate_video_v2(
        self,
        prompt: str,
        *,
        first_frame: str | None = None,
        last_frame: str | None = None,
        duration_sec: int = 8,
        face_refs: list[str] | None = None,
        product_refs: list[str] | None = None,
        aspect: str = "9:16",
        model: str = "seedance-2-0",
        provider: str = "seedance",
        extra: dict[str, Any] | None = None,
    ) -> dict:
        """W2: video gen with first/last frame + multi-class refs."""
        body: dict[str, Any] = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "duration": duration_sec,
            "aspect_ratio": aspect,
        }
        if first_frame:
            body["first_frame"] = first_frame
        if last_frame:
            body["last_frame"] = last_frame
        refs: list[str] = []
        ref_roles: list[str] = []
        for r in face_refs or []:
            refs.append(r); ref_roles.append("face")
        for r in product_refs or []:
            refs.append(r); ref_roles.append("product")
        if refs:
            body["reference_images"] = refs
            body["ref_roles"] = ref_roles
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/videos/generate", json=body)
            r.raise_for_status()
            return r.json()
```

**注意**：上述 body 用 `ref_roles` 数组与 `reference_images` 并列。如 Step 1 发现 hub 实际期望另一种 schema（如 `face_image_url` / `product_image_url` 单字段），就按 hub 改 v2。**先以 hub openapi 为准**。

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_media.py -v
```

Expected: 4 PASS（2 brief + 2 v2 client）

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/services/ai_hub_client.py `
        services/knowledge-engine/tests/test_mcp_media.py
git commit -m "feat(ai-hub): generate_image_v2/video_v2 with multi-class refs (W2 T7)"
```

---

### 任务 8：generate_image tool（多 prompt 并发 + 4 类 refs）

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`（追加 generate_image）
- Modify: `services/knowledge-engine/tests/test_mcp_media.py`（追加测试）

- [ ] **Step 1：写测试**

在 `services/knowledge-engine/tests/test_mcp_media.py` 末尾追加：
```python
from app.mcp.tools.media import generate_image


@pytest.mark.asyncio
async def test_smoke_generate_image_runs_multiple_prompts_concurrently():
    """3 个 prompt 一次返 3 张图。"""
    fake_responses = [
        {"images": [{"url": f"https://fake/img{i}.png"}]} for i in range(3)
    ]

    async def fake_v2(prompt, **kw):
        # 用 prompt 末位匹配返回
        for i in range(3):
            if str(i) in prompt:
                return fake_responses[i]
        return fake_responses[0]

    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.generate_image_v2 = AsyncMock(side_effect=fake_v2)
        r = await generate_image(
            prompts=["分镜 0", "分镜 1", "分镜 2"],
            face_refs=None,
            product_refs=["https://prod.png"],
            style_refs=None,
        )
    assert r["ok"] is True
    images = r["result"]["images"]
    assert len(images) == 3
    urls = [i["url"] for i in images]
    assert all("fake/img" in u for u in urls)
    assert r["next_step_hint"]["suggested_tool"] == "generate_video"


@pytest.mark.asyncio
async def test_smoke_generate_image_partial_failure_returns_error_marker():
    async def fake_v2(prompt, **kw):
        if "fail" in prompt:
            raise RuntimeError("hub 5xx")
        return {"images": [{"url": "https://ok.png"}]}

    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.generate_image_v2 = AsyncMock(side_effect=fake_v2)
        r = await generate_image(prompts=["ok 1", "fail 2", "ok 3"])

    assert r["ok"] is True   # 整体不挂；逐 prompt 看
    images = r["result"]["images"]
    assert len(images) == 3
    err_idx = [i for i, x in enumerate(images) if x.get("error")]
    assert err_idx == [1]
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_media.py::test_smoke_generate_image_runs_multiple_prompts_concurrently -v
```

Expected: ImportError on generate_image.

- [ ] **Step 3：实现 generate_image**

在 `services/knowledge-engine/app/mcp/tools/media.py` 末尾追加：
```python
import asyncio


@tool_with_audit(mcp, require_approval=False)
async def generate_image(
    prompts: list[str],
    face_refs: list[str] | None = None,
    product_refs: list[str] | None = None,
    style_refs: list[str] | None = None,
    aspect_ratio: str = "9:16",
    n_per_prompt: int = 1,
) -> dict:
    """多 prompt 并发出多张图（gpt-image-2）。

    Args:
        prompts: prompt 列表（典型 3 张分镜）
        face_refs / product_refs / style_refs: 三类参考图 url 列表
        aspect_ratio: 画幅（默认 9:16 抖音竖版）
        n_per_prompt: 每个 prompt 出几张（默认 1）

    Returns:
        {ok, result: {images: [{prompt, url} | {prompt, error}, ...]},
         trace, next_step_hint(generate_video)}
    """
    model_cfg = get_model("generate_image")
    client = AIHubClient()

    async def _one(prompt: str):
        try:
            resp = await client.generate_image_v2(
                prompt=prompt,
                face_refs=face_refs,
                product_refs=product_refs,
                style_refs=style_refs,
                aspect=aspect_ratio,
                n=n_per_prompt,
                model=model_cfg.get("model", "gpt-image-2"),
                provider=model_cfg.get("provider", "openai"),
            )
            urls = []
            for img in resp.get("images") or resp.get("data") or []:
                urls.append(img.get("url") or img.get("image_url") or "")
            return {"prompt": prompt, "urls": [u for u in urls if u]}
        except Exception as exc:
            return {"prompt": prompt, "error": f"{type(exc).__name__}: {exc}"}

    results = await asyncio.gather(*(_one(p) for p in prompts))

    # flatten 用 url（前端展示）；保留 prompt 关联
    images = []
    for r in results:
        if r.get("error"):
            images.append({"prompt": r["prompt"], "error": r["error"]})
        else:
            for u in r["urls"]:
                images.append({"prompt": r["prompt"], "url": u})
            if not r["urls"]:
                images.append({"prompt": r["prompt"], "error": "hub 无返回 url"})

    cost_per = "¥0.5" if model_cfg.get("provider") == "openai" else "未知"
    cost_estimate = f"~{len(prompts) * n_per_prompt} × {cost_per}"

    result = {
        "ok": True,
        "result": {"images": images, "count": len(images)},
        "trace": build_trace(
            provider=model_cfg.get("provider", "openai"),
            model=model_cfg.get("model", "gpt-image-2"),
            prompt="\n---\n".join(prompts),
            params={
                "aspect_ratio": aspect_ratio,
                "n_per_prompt": n_per_prompt,
                "face_refs": face_refs or [],
                "product_refs": product_refs or [],
                "style_refs": style_refs or [],
            },
            cost_estimate=cost_estimate,
        ),
    }

    # next_step_hint：用刚出的图作为下一段视频的 first_frame
    valid_urls = [i["url"] for i in images if "url" in i]
    segments_hint = []
    for i, url in enumerate(valid_urls[:3]):
        nxt = valid_urls[i + 1] if i + 1 < len(valid_urls[:3]) else None
        segments_hint.append({
            "prompt": f"段 {i+1}：从这张图运镜 8 秒",
            "first_frame": url,
            "last_frame": nxt,
            "duration_s": 8,
        })

    return attach_next_step(
        result,
        suggested_tool="generate_video",
        suggested_args={
            "segments": segments_hint,
            "face_refs": face_refs or [],
            "product_refs": product_refs or [],
            "aspect_ratio": aspect_ratio,
        },
        human_text=(
            f"用这 {len(valid_urls)} 张图做底跑分镜视频（Seedance 2.0，"
            f"~¥15/段 × {len(segments_hint)} 段）"
        ),
    )
```

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_media.py -v
```

Expected: 全 PASS

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/media.py `
        services/knowledge-engine/tests/test_mcp_media.py
git commit -m "feat(mcp): generate_image tool (multi-prompt + 3-class refs) (W2 T8)"
```

---

### 任务 9：generate_video tool（多 segment 并发 + 首尾帧 + Seedance polling）

**关键**：Seedance 是异步生成（返 task_id 后 poll），单段典型 30-60s；多段 `asyncio.gather` 并发。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`（追加 generate_video）
- Modify: `services/knowledge-engine/tests/test_mcp_media.py`（追加测试）

- [ ] **Step 1：写测试**

在 `services/knowledge-engine/tests/test_mcp_media.py` 末尾追加：
```python
from app.mcp.tools.media import generate_video


@pytest.mark.asyncio
async def test_smoke_generate_video_runs_segments_concurrently():
    async def fake_v2(prompt, **kw):
        return {"task_id": f"t-{prompt[:5]}", "status": "pending"}

    async def fake_wait(task_id, **kw):
        return {"status": "succeeded", "task_id": task_id,
                "data": {"video_url": f"https://fake/{task_id}.mp4"}}

    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.generate_video_v2 = AsyncMock(side_effect=fake_v2)
        MC.return_value.wait_for_video = AsyncMock(side_effect=fake_wait)
        segments = [
            {"prompt": "段 1 慢推镜", "first_frame": "https://x/a.png",
             "last_frame": "https://x/b.png", "duration_s": 8},
            {"prompt": "段 2 横移", "first_frame": "https://x/b.png",
             "last_frame": "https://x/c.png", "duration_s": 8},
        ]
        r = await generate_video(segments=segments, face_refs=None,
                                  product_refs=["https://prod.png"])
    assert r["ok"] is True
    out = r["result"]["segments"]
    assert len(out) == 2
    assert all("video_url" in s or s.get("error") for s in out)
    # 链路终点
    assert r["next_step_hint"]["suggested_tool"] is None


@pytest.mark.asyncio
async def test_smoke_generate_video_handles_seg_failure():
    async def fake_v2(prompt, **kw):
        if "fail" in prompt:
            raise RuntimeError("seedance 5xx")
        return {"task_id": "t-1"}

    async def fake_wait(task_id, **kw):
        return {"status": "succeeded", "data": {"video_url": "https://ok.mp4"}}

    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.generate_video_v2 = AsyncMock(side_effect=fake_v2)
        MC.return_value.wait_for_video = AsyncMock(side_effect=fake_wait)
        r = await generate_video(segments=[
            {"prompt": "ok 段"}, {"prompt": "fail 段"},
        ])
    out = r["result"]["segments"]
    assert len(out) == 2
    assert sum(1 for s in out if s.get("error")) == 1
    assert sum(1 for s in out if s.get("video_url")) == 1
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_media.py::test_smoke_generate_video_runs_segments_concurrently -v
```

Expected: ImportError on generate_video.

- [ ] **Step 3：实现 generate_video**

在 `services/knowledge-engine/app/mcp/tools/media.py` 末尾追加：
```python
@tool_with_audit(mcp, require_approval=False)
async def generate_video(
    segments: list[dict],
    face_refs: list[str] | None = None,
    product_refs: list[str] | None = None,
    aspect_ratio: str = "9:16",
) -> dict:
    """多段分镜视频，并发跑 Seedance；不自动拼接（老板下载多段交剪辑）。

    Args:
        segments: [{prompt, first_frame?, last_frame?, duration_s?}, ...]
        face_refs / product_refs: 全段共用的人脸 / 产品参考
        aspect_ratio: 画幅

    Returns:
        {ok, result: {segments: [{prompt, video_url, duration} | {prompt, error}, ...]},
         trace, next_step_hint(None — 链路终点)}
    """
    model_cfg = get_model("generate_video")
    provider = model_cfg.get("provider", "seedance")
    model = model_cfg.get("model", "seedance-2-0")
    client = AIHubClient()

    async def _one(seg: dict):
        try:
            start_resp = await client.generate_video_v2(
                prompt=seg["prompt"],
                first_frame=seg.get("first_frame"),
                last_frame=seg.get("last_frame"),
                duration_sec=int(seg.get("duration_s", 8)),
                face_refs=face_refs,
                product_refs=product_refs,
                aspect=aspect_ratio,
                model=model,
                provider=provider,
            )
            task_id = (
                start_resp.get("task_id")
                or (start_resp.get("data") or {}).get("task_id")
            )
            if not task_id:
                # 同步返结果（少见）
                url = start_resp.get("video_url") or (start_resp.get("data") or {}).get("video_url")
                return {"prompt": seg["prompt"], "video_url": url,
                        "duration": seg.get("duration_s", 8)}
            done = await client.wait_for_video(task_id, max_seconds=600, poll=5.0)
            data = done.get("data") or done
            url = data.get("video_url") or data.get("url")
            if data.get("status") in ("failed", "error"):
                return {"prompt": seg["prompt"],
                        "error": f"seedance {data.get('status')}: "
                                  f"{data.get('error') or data.get('message') or ''}"}
            return {"prompt": seg["prompt"], "video_url": url,
                    "duration": seg.get("duration_s", 8), "task_id": task_id}
        except Exception as exc:
            return {"prompt": seg["prompt"], "error": f"{type(exc).__name__}: {exc}"}

    out = await asyncio.gather(*(_one(s) for s in segments))

    cost_per = "¥15" if provider == "seedance" else "未知"
    cost_estimate = f"~{len(segments)} × {cost_per}"

    result = {
        "ok": True,
        "result": {"segments": out, "count": len(out)},
        "trace": build_trace(
            provider=provider,
            model=model,
            prompt="\n---\n".join(s["prompt"] for s in segments),
            params={
                "aspect_ratio": aspect_ratio,
                "segment_count": len(segments),
                "face_refs": face_refs or [],
                "product_refs": product_refs or [],
                "first_last_frames": [
                    {"first": s.get("first_frame"), "last": s.get("last_frame")}
                    for s in segments
                ],
            },
            cost_estimate=cost_estimate,
        ),
    }
    return attach_next_step(
        result,
        suggested_tool=None,
        suggested_args={},
        human_text="全链路完成。下载各段视频自己交剪辑（不自动拼接）。",
    )
```

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_media.py -v
```

Expected: 全 PASS（brief 2 + image 2 + video 2 + v2 client 2 = 8）

- [ ] **Step 5：跑 doctor 看 9 tool（注意 doctor 需 T10 改）**

```powershell
docker exec omni-knowledge-engine python -m app.mcp.doctor
```

Expected: `9 tools registered`（如还卡 5/6/7，T10 改）

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/media.py `
        services/knowledge-engine/tests/test_mcp_media.py
git commit -m "feat(mcp): generate_video tool (concurrent segments + first/last frame) (W2 T9)"
```

---

### 任务 10：doctor 升级 + e2e 验收 + W2 收尾

**Files:**
- Modify: `services/knowledge-engine/app/mcp/doctor.py`
- Modify: `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`

- [ ] **Step 1：升级 doctor.expected_tools 到 10**

打开 `services/knowledge-engine/app/mcp/doctor.py`，找到 expected tools 定义（W1 写的 5 项硬编码 list）。把它改成动态从 `mcp.list_tools()` 数 + 检查至少包含这 10 个：
```python
EXPECTED_TOOLS = {
    # W1
    "list_skus", "get_sku", "list_kbs", "search_kb", "list_briefs",
    # W2
    "query_costs", "compute_margin", "generate_brief",
    "generate_image", "generate_video",
}
```

并把检查逻辑从 `len == 5` 改为 `set(registered) >= EXPECTED_TOOLS`。具体代码改动按 W1 doctor.py 现状定。

- [ ] **Step 2：跑 doctor 全绿**

```powershell
docker exec omni-knowledge-engine python -m app.mcp.doctor
```

Expected:
```
[OK  ] DB pool
[OK  ] mcp schema tables: found 2/2
[OK  ] tool_models.yaml: keys=['__default__','compute_margin','generate_brief','generate_image','generate_video']
[OK  ] 10 tools registered: all 10 ok
[OK  ] /mcp HTTP: status=200
结论：全绿 ✓
```

- [ ] **Step 3：跑全部 W1 + W2 测试**

```powershell
docker exec omni-knowledge-engine pytest tests/test_mcp_audit.py tests/test_mcp_config.py tests/test_mcp_tools.py tests/test_mcp_orphan.py tests/test_mcp_trace.py tests/test_mcp_utils.py tests/test_mcp_accounting.py tests/test_mcp_media.py -v
```

Expected: 全 PASS（W1 20 + W2 ~16 ≈ 36 测试）。

- [ ] **Step 4：在 Claude Code 客户端 e2e 5 个 W2 tool**

老板手动操作（同 W1 e2e 流程）：
1. 在 Claude Code 里说"查 sku-X 的成本" → Claude 调 `query_costs` → 老板批 grant → 验证返成本列表
2. "算 sku-X 在抖音渠道净利率" → `compute_margin` → 验证 breakdown 数字 + LLM 解读
3. "给 sku-X 出抖音 brief" → `generate_brief` → 验证 brief md + next_step_hint 提议出图
4. "用刚才提议的 prompts 出 3 张分镜图" → `generate_image` → 验证 3 张 url
5. "用这 3 张图跑分镜视频，每段 8s" → `generate_video` → 验证多段 url

每一步老板审 trace + next_step_hint 是否合理；不合理记到 memory 待 W3 修缮。

`.claude/settings.local.json` 应自动累积 5 个新 grant（mcp__omni__query_costs / compute_margin / generate_brief / generate_image / generate_video）。

- [ ] **Step 5：审计表 sanity**

```powershell
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c `
"SELECT tool_name, status, duration_ms FROM mcp.tool_calls WHERE tool_name IN ('query_costs','compute_margin','generate_brief','generate_image','generate_video') ORDER BY created_at DESC LIMIT 20"
```

Expected: 最近 5+ 行 `completed`；不应有 `pending` 孤儿（启动期 mark_orphans 已处理）。

- [ ] **Step 6：更新 memory（W2 完成 → W3 起手）**

打开 `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`：

§二 当前阶段，把 `[ ] W2 落地` 改 `[x]`，添加 `[ ] W3 落地：专家模型 + 跨服务 + 录音管理（13 tool）` 作为新 next。

§十一（W2 落地计划）改成"W2 完成（commit 序列见 §七 W2）"，把详细 plan 移到 §七 历史区。

§七（落地总结）下加 **W2 commit 序列**：把这次 W2 的 ~10 个 commit 列出来。

§十二（最后更新）加新条：
```
2026-MM-DD — W2 落地（10 个 task / ~10 commits on feat/mcp-w1）；5 个新 tool 全 e2e 通过；trace + next_step_hint 让老板少打字驱动 sku 全链路；W2 没建 Gate 基建（保留 W1 stub 给 W3）。下一步 W3：调 writing-plans skill 出 W3 plan。
```

加 §十三（下次 /clear 后第一件事：W3 plan）：列 W3 13 个 tool 范围（design doc §3.2 W3 行）+ Gate 真启用基建（inbox UI 决策）+ 跨服务（video-analysis / scout-agent）调用模式。

- [ ] **Step 7：commit memory + final commit**

```powershell
git add services/knowledge-engine/app/mcp/doctor.py
git commit -m "feat(mcp): doctor expected_tools to 10 (W1 5 + W2 5) (W2 T10)"
```

memory 文件不入 git（在 `C:\Users\Administrator\.claude\projects\` 下，是 Claude Code 用户目录）；直接保存即可。

- [ ] **Step 8：跑一次全量 doctor + 测试 + push（可选）**

```powershell
docker exec omni-knowledge-engine python -m app.mcp.doctor
docker exec omni-knowledge-engine pytest tests/test_mcp_*.py -v
git log --oneline -15  # 确认 W2 ~10 commits 都在
```

如确认 OK，问老板要不要 push `feat/mcp-w1` 到 origin（git push -u origin feat/mcp-w1）。

- [ ] **Step 9：宣告 W2 完成**

向老板汇报：
- W2 5 tool e2e 全通
- doctor 10/10 绿
- mcp.tool_calls 审计完整
- 没建 Gate 基建（W3 才上）
- 下一步：调 writing-plans skill 出 W3 plan（13 tool + Gate 真启用 + 跨服务调用）

---

## 自检（plan 写完后我自己过一遍）

### 1. Spec 覆盖

| design doc §3.2 W2 行 tool | 本 plan task | 备注 |
|---|---|---|
| query_costs | T4 | ✓ 纯 DB |
| compute_margin | T5 | ✓ Python 算 + LLM 解读 |
| run_sku_orch | **删** | brainstorming 锁定（Claude 大脑当编排器）|
| get_sku_orch_status | **删** | 同上 |
| generate_brief | T6 | ✓ + next_step_hint |
| generate_image | T8 | ✓ 多 prompt + 3 类 refs |
| generate_video | T9 | ✓ 多 segment + 首尾帧 |

### 2. Placeholder 扫

- ✅ 每个 task 的 step 都含完整代码 / 完整命令 / 完整 expected
- ✅ 没有"TBD" / "implement later" / "类似 task X" / "add validation"
- ⚠️ T7 step 1（hub openapi 检查）依赖**实际 hub schema**——故意留这个验证步，不能写死
- ⚠️ T0 step 4 的 sku_id 留空让实施者填——这是必要的，每台 dev DB 数据不同

### 3. 类型一致

- `build_trace(provider, model, prompt, params, cost_estimate)` 在 trace.py 定义；T5/T6/T8/T9 调用都对齐 ✓
- `attach_next_step(result, *, suggested_tool, suggested_args, human_text)` 同上 ✓
- `decimal_to_jsonable` 在 utils.py 定义；T4/T5 调用都用同名 ✓
- `generate_image_v2` 接 `face_refs / product_refs / style_refs / aspect / n / model / provider`；T8 generate_image 调用对齐 ✓
- `generate_video_v2` 接 `first_frame / last_frame / duration_sec / face_refs / product_refs / aspect / model / provider`；T9 调用对齐 ✓

### 4. 工期检查

- T0 (0.5h) + T1 (1h) + T2 (1h) + T3 (0.5h) = 3h 基础设施
- T4 (1h) + T5 (3h) + T6 (3h) + T7 (2h) + T8 (3h) + T9 (4h) = 16h tools
- T10 (2h) 收尾
- 总 21h ≈ 3 个工作日（vs 老板预期 5 天，留缓冲给 hub schema 不匹配 / api_key 阻塞 / Decimal 边界等）

---

## 执行选择

Plan 完整保存到 `docs/superpowers/plans/2026-05-04-omni-agent-uplift-W2-plan.md`。两种执行方式：

**1. Subagent-Driven（推荐）** — 每个 task 派一个 fresh subagent；review-after-each-task；快速迭代
**2. Inline Execution** — 在当前 session 一口气推进；每 2-3 个 task 暂停审

老板选哪个，启动后按 W1 节奏走（每 task commit 一次）。
