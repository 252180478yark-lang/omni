# W3b 实施计划：scout 5 tool + KB 管理 2 tool

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 omni MCP server 加 7 个 tool（5 scout fetch + 2 KB 管理），让 Claude Code agent 能直接拉抖店罗盘 / 巨量云图数据 + 管 KB 元数据，doctor 升 13 → 20。

**Architecture:** 5 个 fetch tool 直读 mvp_* 表的最近一天入库数据（不去 trigger scout-agent runbook 重跑，避免 cookies/polling 复杂度）。2 个 KB 管理 tool 走 cli_approve Gate（同 record_cost 模式）。所有 tool 复用 W3a 已落地的 `tool_with_audit` / `human_gate` / `cli_approve` 基建。

**Tech Stack:** FastMCP 3.x · asyncpg · pytest-asyncio · pydantic · 复用 W1/W2/W3a 全部 helpers

---

## 起手就要看的文件（implementer 必读）

- **design doc**：`docs/superpowers/specs/2026-05-03-omni-agent-uplift-design.md` §3.2 W3 行（line 466-482）
- **memory 进度**：`C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md` §十六 W3b 起手清单 + §十七 SOP+A 教训
- **memory scout 状态**：`C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_scout_runbooks_status.md`
- **W3a plan 范本**：`docs/superpowers/plans/2026-05-04-omni-agent-uplift-W3a-plan.md`
- **W3a 已用基建**：
  - `services/knowledge-engine/app/mcp/audit.py` — `tool_with_audit` 装饰器
  - `services/knowledge-engine/app/mcp/human_gate.py` — DB poll 真实现
  - `services/knowledge-engine/app/mcp/cli_approve.py` — list/approve/reject/tail
  - `services/knowledge-engine/app/mcp/tools/cost_admin.py` — T 类 tool 范本（参考）
  - `services/knowledge-engine/app/mcp/tools/kb.py` — F 类 tool 范本（W1 现状）

---

## 关键决策（已锁定，禁止再讨论）

1. **5 scout tool 全部读 mvp_* 表已入库的最近数据**（fast，秒级返回），**不**去 trigger scout-agent runbook 重跑。理由：runbook trigger 是异步 + cookies 状态可能失效 + 30-60s polling 增加复杂度。memory 实锤 8 套件 A-H 已 success 跑过 + 数据已入库（2026-05-03）。数据陈旧老板自己去 scout-agent 前端 trigger。
2. **F 类 5 tool 不走 Gate**（require_approval=False，纯查询）
3. **T 类 2 KB 管理走 cli_approve Gate**（require_approval=True，同 record_cost / disable_cost_item 模式）
4. **复用 W3a 全部基建**：禁止新建 scout 客户端 / 新 helper / 新 prompt 模板
5. **个人自用，禁止过度工程**：不写微服务 / 灰度 / SLA / 分布式
6. **每 tool 必返 trace 字段**（model/params/cost_estimate）
7. **doctor expected_tools 13 → 20**

---

## 文件结构

### 待建（1 个）
- `services/knowledge-engine/app/mcp/tools/scout.py` — 5 个 scout fetch tool 集中（~250 行含注释）

### 待扩（2 个）
- `services/knowledge-engine/app/mcp/tools/kb.py` — W1 已有 search_kb / list_kbs，加 `kb_upload_doc` / `kb_set_role`（+~100 行）
- `services/knowledge-engine/app/mcp/server.py` — import scout 模块（+1 行）

### 待改（2 个）
- `services/knowledge-engine/app/mcp/doctor.py` — `expected_tools` 13 → 20（+ tool 列表加 7 个）
- `services/knowledge-engine/app/mcp/tools/__init__.py` — docstring 更新（+~10 行）

### 待建测试（2 个）
- `services/knowledge-engine/tests/test_mcp_scout.py` — 5 scout tool 测试（~200 行）
- `services/knowledge-engine/tests/test_mcp_kb_admin.py` — 2 KB 管理 tool 测试（~150 行）

---

## 已知坑（W3a 期间踩的，防重踩）

1. **fixture sync 写法不能跑通**：用 `@pytest_asyncio.fixture(scope='module', autouse=True)` async pattern。参考 `tests/test_mcp_audit.py`。**禁止**用 `asyncio.run(init_pool())` 形式的 sync fixture。
2. **PowerShell 5.1 `\"` 不是合法转义**：在 host 上跑命令时用 PS 单引号包 + Python 字符串拼接，禁止 `bash -c "...python -c \"..."\"`。容器内调命令用 `docker exec` 直接 + Python 双引号字符串。
3. **pytest 命令必须带 PYTHONPATH + cwd**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_xxx.py -v"`。仅 `docker exec ... pytest` 跑不通。
4. **bind mount 改 docker-compose 后必须 `up -d --no-deps --force-recreate`**：仅 `docker restart` 不够。但 W3b 不改 docker-compose，仅改 Python 源码，restart 即可。
5. **测试 vs 实现 name 冲突**：测试模板用的字段名（如 `name`/`kb_id`）跟函数 positional arg 重名时，函数签名加 `/` 标记 posonly，或测试用 keyword-only 调用。
6. **FastMCP schema 反射**：`@tool_with_audit` 已经显式 copy `__signature__` 和 `__annotations__`（`audit.py` line 124-125），新 tool 只要正常写函数签名就 OK。
7. **F 类 vs T 类的 timeout_seconds**：T 类传 `timeout_seconds=3600`（1 小时给老板批），F 类不需要。
8. **summary_fn 给 T 类**：CLI list 时显示给老板看的卡片（参考 `cost_admin.py:25` `_record_cost_summary`）。

---

## 任务总览（9 task）

| Task | 名称 | 类型 | tool 数 | 估时 |
|---|---|---|---|---|
| T1 | fetch_compass_store_daily | F | 1 | 30 min |
| T2 | fetch_compass_sku_detail | F | 1 | 30 min |
| T3 | fetch_compass_search_traffic | F | 1 | 30 min |
| T4 | fetch_yuntu_5a | F | 1 | 30 min |
| T5 | fetch_yuntu_brand_mind | F | 1 | 30 min |
| T6 | kb_upload_doc | T（走 Gate） | 1 | 60 min |
| T7 | kb_set_role | T（走 Gate） | 1 | 45 min |
| T8 | doctor expected_tools=20 + tools/__init__.py | chore | 0 | 15 min |
| T9 | e2e 容器内自检 + 老板侧 grant 累积清单 | chore | 0 | 30 min |

总计：9 task / ~5 小时落地（subagent-driven 模式，每 task fresh subagent）。

---

## Task 1: fetch_compass_store_daily

**Goal:** 读 mvp_daily_metric 中 source_runbook 以 `compass/` 开头且 sku_id='' 的最近一天数据（全店日报）。

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/scout.py`
- Test: `services/knowledge-engine/tests/test_mcp_scout.py`

**接口约定**：

```python
async def fetch_compass_store_daily(date: str | None = None) -> dict:
    """读最近一天罗盘全店日报（source_runbook LIKE 'compass/%' AND sku_id='')。

    Args:
        date: ISO 日期（"2026-05-03"）。None = DB 中最近一天有数据的日期。

    Returns:
        {
            "ok": True,
            "result": {
                "date": "2026-05-03",
                "metrics": [
                    {"metric_name": "gmv_paid", "value": "12345.60", "source_runbook": "compass/sell-analysis"},
                    ...
                ],
                "count": N,
            },
            "trace": {"db_query": "SELECT ...", "row_count": N},
        }

    错误：
        - 数据库无该日期数据 → {"ok": False, "error": "no_data", "hint": "..."}
        - 无效日期 → {"ok": False, "error": "invalid_date", "hint": "..."}
    """
```

- [ ] **Step 1: 写 failing test（先造一行 _smoke 数据，跑 tool 看返回）**

写入 `services/knowledge-engine/tests/test_mcp_scout.py`：

```python
"""W3b: scout 5 tool 测试。

数据库 fixture：用 _smoke_W3b_ 前缀的 sku_id 行隔离，module teardown 清理。
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.mcp.tools.scout import (
    fetch_compass_store_daily,
)

SMOKE_PREFIX = "_smoke_W3b_"
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    pool = get_pool()
    # 清理可能残留的 _smoke_ 行
    await pool.execute(
        "DELETE FROM mvp_daily_metric WHERE sku_id LIKE $1 OR sku_id = $2",
        SMOKE_PREFIX + "%",
        "",  # 全店日报 sku_id 是空串
    )
    # 先插全店日报数据（sku_id='', 当作 _smoke_W3b_global_）
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('', $1, 'gmv_paid', 12345.6, 'compass/sell-analysis', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('', $1, 'visit_uv', 8765, 'compass/business-part', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    yield
    # teardown：清理 _smoke 数据
    await pool.execute(
        "DELETE FROM mvp_daily_metric WHERE source_run_id LIKE $1",
        SMOKE_PREFIX + "%",
    )
    await close_pool()


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_returns_yesterday():
    result = await fetch_compass_store_daily(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    res = result["result"]
    assert res["date"] == YESTERDAY.isoformat()
    assert res["count"] >= 2
    metric_names = {m["metric_name"] for m in res["metrics"]}
    assert "gmv_paid" in metric_names
    assert "visit_uv" in metric_names
    assert all("compass/" in m["source_runbook"] for m in res["metrics"])


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_default_latest():
    """date=None 时返回最近一天有数据的日期。"""
    result = await fetch_compass_store_daily()
    assert result["ok"] is True
    # 应该至少返回我们插的 _smoke 数据
    assert result["result"]["count"] >= 2


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_no_data():
    """查 1990-01-01（铁定无数据）应返回 no_data 错误。"""
    result = await fetch_compass_store_daily(date="1990-01-01")
    assert result["ok"] is False
    assert result["error"] == "no_data"


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_invalid_date():
    """非 ISO 日期返回 invalid_date。"""
    result = await fetch_compass_store_daily(date="not-a-date")
    assert result["ok"] is False
    assert result["error"] == "invalid_date"
```

- [ ] **Step 2: 跑测试看 fail（fetch_compass_store_daily 还没实现）**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_scout.py -v -k store_daily"
```

期望：`ImportError: cannot import name 'fetch_compass_store_daily' from 'app.mcp.tools.scout'`

- [ ] **Step 3: 写最小实现**

写入 `services/knowledge-engine/app/mcp/tools/scout.py`：

```python
"""W3b: 5 个 scout fetch tool。

直读 mvp_* 表的最近一天入库数据，不去 trigger scout-agent runbook 重跑
（cookies 状态/异步 polling 复杂度高）。memory 实锤 8 套件 A-H 已 success
跑过 + 数据已入库（2026-05-03）。

5 个 tool：
- fetch_compass_store_daily(date?) — 全店日报
- fetch_compass_sku_detail(sku_id, date?) — 单 SKU
- fetch_compass_search_traffic(date?) — 搜索流量营销
- fetch_yuntu_5a(date?) — 5A 资产
- fetch_yuntu_brand_mind(date?) — 品牌心智
"""
from __future__ import annotations

from datetime import date as date_cls

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp


def _parse_date(date_str: str | None) -> date_cls | None:
    """解析 ISO 日期，None 透传，非法抛 ValueError。"""
    if date_str is None:
        return None
    return date_cls.fromisoformat(date_str)


@tool_with_audit(mcp, require_approval=False)
async def fetch_compass_store_daily(date: str | None = None) -> dict:
    """读罗盘全店日报最近一天数据（source_runbook LIKE 'compass/%' AND sku_id='')。

    Args:
        date: ISO 日期（"2026-05-03"）。None = DB 中最近一天有数据的日期。

    Returns:
        {ok, result: {date, metrics: [{metric_name, value, source_runbook}], count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式（如 2026-05-03），给的是 {date!r}: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval(
            """
            SELECT MAX(date) FROM mvp_daily_metric
            WHERE source_runbook LIKE 'compass/%' AND sku_id = ''
            """
        )
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_daily_metric 中无 compass 全店日报数据；先去 scout-agent 跑 runbook A",
            }
        target_date = latest

    rows = await pool.fetch(
        """
        SELECT metric_name, value, source_runbook
        FROM mvp_daily_metric
        WHERE source_runbook LIKE 'compass/%' AND sku_id = '' AND date = $1
        ORDER BY source_runbook, metric_name
        """,
        target_date,
    )
    if not rows:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"date={target_date.isoformat()} 无 compass 全店日报数据",
        }

    metrics = [
        {
            "metric_name": r["metric_name"],
            "value": str(r["value"]) if r["value"] is not None else None,
            "source_runbook": r["source_runbook"],
        }
        for r in rows
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "metrics": metrics,
            "count": len(metrics),
        },
        "trace": {
            "db_query": "mvp_daily_metric WHERE source_runbook LIKE 'compass/%' AND sku_id=''",
            "row_count": len(metrics),
        },
    }
```

- [ ] **Step 4: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_scout.py -v -k store_daily"
```

期望：4 个测试全 PASS（test_fetch_compass_store_daily_returns_yesterday / default_latest / no_data / invalid_date）。

- [ ] **Step 5: 注册到 server.py**

修改 `services/knowledge-engine/app/mcp/server.py`，在 import 链路加：

```python
from app.mcp.tools import scout as _scout  # noqa: E402, F401  # W3b T1+
```

放在 `from app.mcp.tools import sop as _sop  # noqa: E402, F401  # W3a T10` 后面。

KE 容器需要 restart 让 server 重载：

```bash
docker restart omni-knowledge-engine
```

等 5 秒后跑 doctor 看 tool 是否 registered（此时 expected_tools 仍是 13，会报 mismatch；T8 才升 20）：

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

期望：tools registered 出现 14 个（含 fetch_compass_store_daily），但 doctor 期望 13 个会 warn / fail。这是预期，T8 会修。

- [ ] **Step 6: commit**

```bash
git add services/knowledge-engine/app/mcp/tools/scout.py services/knowledge-engine/tests/test_mcp_scout.py services/knowledge-engine/app/mcp/server.py
git commit -m "$(cat <<'EOF'
feat(mcp): fetch_compass_store_daily 读罗盘全店日报最近数据 (W3b T1)

W3b 5 scout fetch tool 第 1 个。直读 mvp_daily_metric 表
source_runbook LIKE 'compass/%' AND sku_id='' 的最近一天数据，不
trigger scout-agent runbook 重跑（cookies/polling 复杂度）。

Args: date? (ISO 格式，None=最近一天)
Returns: {ok, result: {date, metrics, count}, trace}

测试覆盖：指定日期 / 默认最近 / 无数据 / 非法日期 4 个 case，全 pass。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- mvp_daily_metric 主键 (sku_id, date, metric_name) UNIQUE，测试 fixture 重跑要先 DELETE
- 全店日报的 sku_id 是空字符串 `''`（不是 NULL），WHERE 条件 `sku_id = ''` 不是 `IS NULL`
- value 列是 numeric(20,6)，asyncpg 返 Decimal，序列化用 `str(Decimal)` 不要 float（精度损失）

---

## Task 2: fetch_compass_sku_detail

**Goal:** 读 mvp_daily_metric 中指定 sku_id 且 source_runbook LIKE 'compass/%' 的最近一天数据。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/scout.py`（追加新函数）
- Modify: `services/knowledge-engine/tests/test_mcp_scout.py`（追加新测试）

**接口**：

```python
async def fetch_compass_sku_detail(sku_id: str, date: str | None = None) -> dict:
    """读指定 SKU 的罗盘数据最近一天。

    Args:
        sku_id: SKU id（必填）
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {sku_id, date, metrics, count}, trace}
    """
```

- [ ] **Step 1: 写 failing test（追加到 test_mcp_scout.py）**

在 `setup_pool` fixture 内追加 SKU 数据：

```python
    # 在 setup_pool fixture 末尾、yield 前追加：
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_smoke_W3b_sku_X', $1, 'sku_gmv', 999.99, 'compass/sell-analysis', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_smoke_W3b_sku_X', $1, 'sku_visit', 88, 'compass/sell-analysis', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
```

更新 import：

```python
from app.mcp.tools.scout import (
    fetch_compass_store_daily,
    fetch_compass_sku_detail,
)
```

新测试：

```python
@pytest.mark.asyncio
async def test_fetch_compass_sku_detail_returns_sku():
    result = await fetch_compass_sku_detail(
        sku_id="_smoke_W3b_sku_X",
        date=YESTERDAY.isoformat(),
    )
    assert result["ok"] is True
    res = result["result"]
    assert res["sku_id"] == "_smoke_W3b_sku_X"
    assert res["date"] == YESTERDAY.isoformat()
    metric_names = {m["metric_name"] for m in res["metrics"]}
    assert "sku_gmv" in metric_names
    assert "sku_visit" in metric_names


@pytest.mark.asyncio
async def test_fetch_compass_sku_detail_no_data_for_sku():
    result = await fetch_compass_sku_detail(
        sku_id="_smoke_W3b_nonexistent_sku",
        date=YESTERDAY.isoformat(),
    )
    assert result["ok"] is False
    assert result["error"] == "no_data"


@pytest.mark.asyncio
async def test_fetch_compass_sku_detail_default_latest():
    result = await fetch_compass_sku_detail(sku_id="_smoke_W3b_sku_X")
    assert result["ok"] is True
    assert result["result"]["count"] >= 2
```

- [ ] **Step 2: 跑测试看 fail**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_scout.py -v -k sku_detail"
```

期望：`ImportError: cannot import name 'fetch_compass_sku_detail'`

- [ ] **Step 3: 写实现（追加到 scout.py）**

```python
@tool_with_audit(mcp, require_approval=False)
async def fetch_compass_sku_detail(sku_id: str, date: str | None = None) -> dict:
    """读指定 SKU 的罗盘最近一天数据。

    Args:
        sku_id: SKU id（必填，如 'SKU-367991-0002'）
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {sku_id, date, metrics, count}, trace}
    """
    if not sku_id or not sku_id.strip():
        return {
            "ok": False,
            "error": "invalid_sku_id",
            "hint": "sku_id 不能为空",
        }
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval(
            """
            SELECT MAX(date) FROM mvp_daily_metric
            WHERE source_runbook LIKE 'compass/%' AND sku_id = $1
            """,
            sku_id,
        )
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": f"mvp_daily_metric 中无 sku_id={sku_id} 的 compass 数据",
            }
        target_date = latest

    rows = await pool.fetch(
        """
        SELECT metric_name, value, source_runbook
        FROM mvp_daily_metric
        WHERE source_runbook LIKE 'compass/%' AND sku_id = $1 AND date = $2
        ORDER BY source_runbook, metric_name
        """,
        sku_id,
        target_date,
    )
    if not rows:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"sku_id={sku_id} date={target_date.isoformat()} 无 compass 数据",
        }

    metrics = [
        {
            "metric_name": r["metric_name"],
            "value": str(r["value"]) if r["value"] is not None else None,
            "source_runbook": r["source_runbook"],
        }
        for r in rows
    ]
    return {
        "ok": True,
        "result": {
            "sku_id": sku_id,
            "date": target_date.isoformat(),
            "metrics": metrics,
            "count": len(metrics),
        },
        "trace": {
            "db_query": "mvp_daily_metric WHERE source_runbook LIKE 'compass/%' AND sku_id=$1",
            "row_count": len(metrics),
        },
    }
```

- [ ] **Step 4: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_scout.py -v -k sku_detail"
```

期望：3 个测试全 PASS。

- [ ] **Step 5: KE restart**

```bash
docker restart omni-knowledge-engine
```

- [ ] **Step 6: commit**

```bash
git add services/knowledge-engine/app/mcp/tools/scout.py services/knowledge-engine/tests/test_mcp_scout.py
git commit -m "$(cat <<'EOF'
feat(mcp): fetch_compass_sku_detail 读单 SKU 罗盘数据 (W3b T2)

W3b 5 scout 第 2 个。WHERE sku_id=$1 AND source_runbook LIKE 'compass/%'。
跟 fetch_compass_store_daily 同模式（区别仅 sku_id 是否空字符串）。

Args: sku_id (必填), date? (None=最近一天)
Returns: {ok, result: {sku_id, date, metrics, count}, trace}

3 个测试 case：指定 SKU+日期 / 默认最近 / 不存在 SKU 返 no_data。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- sku_id 空串 `''` 在 mvp_daily_metric 表里专门表示"全店"，加 `if not sku_id.strip()` 提前 reject
- 同 SKU 同日期同 metric_name 是 UNIQUE，重测前要 DELETE（fixture 已处理）

---

## Task 3: fetch_compass_search_traffic

**Goal:** 读罗盘搜索/流量/营销相关 source_runbook 的最近一天数据。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/scout.py`
- Modify: `services/knowledge-engine/tests/test_mcp_scout.py`

**接口**：

```python
async def fetch_compass_search_traffic(date: str | None = None) -> dict:
    """读罗盘搜索/流量/营销最近一天数据（source_runbook IN search/business-part/...）。"""
```

**source_runbook 范围**（参考 `services/scout-agent/runbooks/compass/` 目录文件名）：

- `compass/search-drainage-terms`（搜索词流量）
- `compass/business-part`（生意参谋分版）

注：design doc 写"搜索/流量/营销"，但实际入库的 source_runbook 名以 mvp_daily_metric 表为准。可以用 `source_runbook IN (...)` 或 `LIKE 'compass/search%' OR LIKE 'compass/business%'`。

- [ ] **Step 1: 写 failing test**

```python
# 在 setup_pool fixture 内追加：
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('', $1, 'search_uv', 1234, 'compass/search-drainage-terms', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('', $1, 'paid_clicks', 567, 'compass/business-part', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )

# 更新 import：
from app.mcp.tools.scout import (
    fetch_compass_store_daily,
    fetch_compass_sku_detail,
    fetch_compass_search_traffic,
)

# 新测试：
@pytest.mark.asyncio
async def test_fetch_compass_search_traffic_returns():
    result = await fetch_compass_search_traffic(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    res = result["result"]
    metric_names = {m["metric_name"] for m in res["metrics"]}
    assert "search_uv" in metric_names
    assert "paid_clicks" in metric_names
    # 验证 source_runbook 都是 search/business 类
    sources = {m["source_runbook"] for m in res["metrics"]}
    assert all(
        s.startswith("compass/search") or s.startswith("compass/business")
        for s in sources
    )


@pytest.mark.asyncio
async def test_fetch_compass_search_traffic_default_latest():
    result = await fetch_compass_search_traffic()
    assert result["ok"] is True
    assert result["result"]["count"] >= 2
```

- [ ] **Step 2: 跑测试看 fail**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_scout.py -v -k search_traffic"
```

- [ ] **Step 3: 写实现**

追加到 `scout.py`：

```python
_SEARCH_TRAFFIC_PREFIXES = ("compass/search", "compass/business")


@tool_with_audit(mcp, require_approval=False)
async def fetch_compass_search_traffic(date: str | None = None) -> dict:
    """读罗盘搜索/流量/营销相关数据最近一天。

    覆盖 source_runbook：compass/search-* + compass/business-*
    （搜索词、流量分版、广告/营销类，按入库 source_runbook 名筛选）

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {date, metrics, count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    where_runbook = " OR ".join(
        f"source_runbook LIKE '{prefix}%'" for prefix in _SEARCH_TRAFFIC_PREFIXES
    )

    if target_date is None:
        latest = await pool.fetchval(
            f"SELECT MAX(date) FROM mvp_daily_metric WHERE ({where_runbook})"
        )
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_daily_metric 中无 compass search/business 数据",
            }
        target_date = latest

    rows = await pool.fetch(
        f"""
        SELECT sku_id, metric_name, value, source_runbook
        FROM mvp_daily_metric
        WHERE ({where_runbook}) AND date = $1
        ORDER BY source_runbook, sku_id, metric_name
        """,
        target_date,
    )
    if not rows:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"date={target_date.isoformat()} 无 compass search/business 数据",
        }

    metrics = [
        {
            "sku_id": r["sku_id"] or None,  # 空串归一为 None 表示全店
            "metric_name": r["metric_name"],
            "value": str(r["value"]) if r["value"] is not None else None,
            "source_runbook": r["source_runbook"],
        }
        for r in rows
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "metrics": metrics,
            "count": len(metrics),
        },
        "trace": {
            "db_query": f"mvp_daily_metric WHERE ({where_runbook})",
            "row_count": len(metrics),
        },
    }
```

- [ ] **Step 4: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_scout.py -v -k search_traffic"
```

- [ ] **Step 5: KE restart + commit**

```bash
docker restart omni-knowledge-engine
git add services/knowledge-engine/app/mcp/tools/scout.py services/knowledge-engine/tests/test_mcp_scout.py
git commit -m "$(cat <<'EOF'
feat(mcp): fetch_compass_search_traffic 读罗盘搜索/流量/营销 (W3b T3)

W3b 5 scout 第 3 个。覆盖 source_runbook 前缀 compass/search-* 和
compass/business-*（搜索词流量 / 生意参谋分版）。

跟 store_daily 区别：
- 不限定 sku_id（全店 + 单 SKU 都返）
- WHERE 用 OR 拼多个 source_runbook prefix

返回 metrics 含 sku_id 字段（空串归一为 None 表示全店）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- WHERE 拼接 `OR LIKE` 用 f-string 拼安全（prefix 字符串是常量，无注入风险）。如果 implementer 想更稳，用 `WHERE source_runbook ~ '^compass/(search|business)-'` 也行（PG 正则）
- mvp_daily_metric 的 sku_id NULL vs '' 都可能出现，归一为 None 让上层用户体验一致

---

## Task 4: fetch_yuntu_5a

**Goal:** 读 mvp_5a_asset_daily 表最近一天数据（5A 资产 + 行业平均）。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/scout.py`
- Modify: `services/knowledge-engine/tests/test_mcp_scout.py`

**接口**：

```python
async def fetch_yuntu_5a(date: str | None = None) -> dict:
    """读云图 5A 资产最近一天。

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {
            "ok": True,
            "result": {
                "date": "2026-05-03",
                "rows": [
                    {
                        "brand_id": "...",
                        "sku_id": "..." | "",
                        "o_count": 1234, "a1_aware": 5678, "a2_appeal": ...,
                        "a3_ask": ..., "a4_act": ..., "a5_advocate": ...,
                        "total_5a": ..., "industry_avg": {...}
                    },
                    ...
                ],
                "count": N,
            },
            "trace": {...},
        }
    """
```

- [ ] **Step 1: 写 failing test**

在 `setup_pool` fixture 内追加：

```python
    await pool.execute(
        "DELETE FROM mvp_5a_asset_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
    await pool.execute(
        """
        INSERT INTO mvp_5a_asset_daily
            (date, brand_id, sku_id, o_count, a1_aware, a2_appeal, a3_ask, a4_act,
             a5_advocate, total_5a, o_industry_avg, a1_industry_avg, a2_industry_avg,
             a3_industry_avg, a4_industry_avg, a5_industry_avg, total_industry_avg)
        VALUES ($1, '_smoke_W3b_brand', '', 1000, 500, 200, 100, 50, 30, 880,
                10000, 5000, 2000, 1000, 500, 300, 8800)
        """,
        YESTERDAY,
    )
```

teardown 加：

```python
    await pool.execute(
        "DELETE FROM mvp_5a_asset_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
```

新测试：

```python
from app.mcp.tools.scout import (
    fetch_compass_store_daily,
    fetch_compass_sku_detail,
    fetch_compass_search_traffic,
    fetch_yuntu_5a,
)


@pytest.mark.asyncio
async def test_fetch_yuntu_5a_returns_brand_row():
    result = await fetch_yuntu_5a(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    res = result["result"]
    assert res["date"] == YESTERDAY.isoformat()
    smoke_rows = [r for r in res["rows"] if r["brand_id"] == "_smoke_W3b_brand"]
    assert len(smoke_rows) == 1
    row = smoke_rows[0]
    assert row["o_count"] == 1000
    assert row["a3_ask"] == 100
    assert row["total_5a"] == 880
    assert row["industry_avg"]["a3_industry_avg"] == 1000


@pytest.mark.asyncio
async def test_fetch_yuntu_5a_default_latest():
    result = await fetch_yuntu_5a()
    assert result["ok"] is True
    assert result["result"]["count"] >= 1
```

- [ ] **Step 2: 跑测试看 fail**

- [ ] **Step 3: 写实现**

```python
@tool_with_audit(mcp, require_approval=False)
async def fetch_yuntu_5a(date: str | None = None) -> dict:
    """读云图 5A 资产最近一天。

    返回每个 (brand_id, sku_id) 组合一行，含 O/A1-A5/total 数值
    + 行业平均（industry_avg 子对象）。

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {date, rows: [{brand_id, sku_id, o_count, a1_aware, ..., industry_avg}], count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval("SELECT MAX(date) FROM mvp_5a_asset_daily")
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_5a_asset_daily 表无数据；先去 scout-agent 跑 yuntu/spu-5a runbook",
            }
        target_date = latest

    rows_db = await pool.fetch(
        """
        SELECT date, brand_id, sku_id,
               o_count, a1_aware, a2_appeal, a3_ask, a4_act, a5_advocate, total_5a,
               o_industry_avg, a1_industry_avg, a2_industry_avg, a3_industry_avg,
               a4_industry_avg, a5_industry_avg, total_industry_avg
        FROM mvp_5a_asset_daily
        WHERE date = $1
        ORDER BY brand_id, sku_id
        """,
        target_date,
    )
    if not rows_db:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"mvp_5a_asset_daily 在 date={target_date.isoformat()} 无数据",
        }

    rows = [
        {
            "brand_id": r["brand_id"],
            "sku_id": r["sku_id"] or None,
            "o_count": r["o_count"],
            "a1_aware": r["a1_aware"],
            "a2_appeal": r["a2_appeal"],
            "a3_ask": r["a3_ask"],
            "a4_act": r["a4_act"],
            "a5_advocate": r["a5_advocate"],
            "total_5a": r["total_5a"],
            "industry_avg": {
                "o_industry_avg": r["o_industry_avg"],
                "a1_industry_avg": r["a1_industry_avg"],
                "a2_industry_avg": r["a2_industry_avg"],
                "a3_industry_avg": r["a3_industry_avg"],
                "a4_industry_avg": r["a4_industry_avg"],
                "a5_industry_avg": r["a5_industry_avg"],
                "total_industry_avg": r["total_industry_avg"],
            },
        }
        for r in rows_db
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "rows": rows,
            "count": len(rows),
        },
        "trace": {
            "db_query": "mvp_5a_asset_daily WHERE date=$1",
            "row_count": len(rows),
        },
    }
```

- [ ] **Step 4: 跑测试看 pass**

- [ ] **Step 5: KE restart + commit**

```bash
docker restart omni-knowledge-engine
git add services/knowledge-engine/app/mcp/tools/scout.py services/knowledge-engine/tests/test_mcp_scout.py
git commit -m "$(cat <<'EOF'
feat(mcp): fetch_yuntu_5a 读云图 5A 资产 (W3b T4)

W3b 5 scout 第 4 个。读 mvp_5a_asset_daily 表，每行含品牌 + 可选 sku
的 O/A1-A5/total 数值，industry_avg 子对象含行业基准。

返回 rows 排序：brand_id, sku_id（确定性顺序方便 diff）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- `o_count`/`a1_aware` 等是 bigint，asyncpg 直接返 int（不像 numeric 返 Decimal），无需 str()
- `sku_id` 默认是空串 `''` 不是 NULL，归一为 None 让用户清楚"全品牌行"
- industry_avg 7 个字段单独 nest，避免主对象太大

---

## Task 5: fetch_yuntu_brand_mind

**Goal:** 读 mvp_brand_mind_daily 表最近一天（品牌心智 3 指标 + 资产/排名等）。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/scout.py`
- Modify: `services/knowledge-engine/tests/test_mcp_scout.py`

**接口**：

```python
async def fetch_yuntu_brand_mind(date: str | None = None) -> dict:
    """读云图品牌心智最近一天。

    返回 {brand_id, sku_id, brand_assoc_count, industry_share, industry_rank,
          reputation, preference, dwell, connection, increase}。

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {date, rows, count}, trace}
    """
```

- [ ] **Step 1: 写 failing test**

fixture 内追加：

```python
    await pool.execute(
        "DELETE FROM mvp_brand_mind_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
    await pool.execute(
        """
        INSERT INTO mvp_brand_mind_daily
            (date, brand_id, sku_id, brand_assoc_count, industry_share,
             industry_rank, reputation, preference, dwell, connection, increase)
        VALUES ($1, '_smoke_W3b_brand', '', 555, 0.123456, 7, 0.85, 0.72,
                300, 150, 50)
        """,
        YESTERDAY,
    )
```

teardown 加：

```python
    await pool.execute(
        "DELETE FROM mvp_brand_mind_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
```

测试：

```python
from app.mcp.tools.scout import (
    fetch_compass_store_daily,
    fetch_compass_sku_detail,
    fetch_compass_search_traffic,
    fetch_yuntu_5a,
    fetch_yuntu_brand_mind,
)


@pytest.mark.asyncio
async def test_fetch_yuntu_brand_mind_returns_smoke():
    result = await fetch_yuntu_brand_mind(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    smoke_rows = [r for r in result["result"]["rows"] if r["brand_id"] == "_smoke_W3b_brand"]
    assert len(smoke_rows) == 1
    row = smoke_rows[0]
    assert row["brand_assoc_count"] == 555
    assert row["industry_rank"] == 7
    # numeric(8,6) 转 Decimal 序列化为 str
    assert row["reputation"] == "0.850000"
    assert row["preference"] == "0.720000"


@pytest.mark.asyncio
async def test_fetch_yuntu_brand_mind_default_latest():
    result = await fetch_yuntu_brand_mind()
    assert result["ok"] is True
    assert result["result"]["count"] >= 1
```

- [ ] **Step 2: 跑测试看 fail**

- [ ] **Step 3: 写实现**

```python
@tool_with_audit(mcp, require_approval=False)
async def fetch_yuntu_brand_mind(date: str | None = None) -> dict:
    """读云图品牌心智最近一天数据。

    返回每个 (brand_id, sku_id) 一行：品牌资产关联数 + 行业份额 + 行业排名 +
    品牌心智 3 指标（reputation 美誉度 / preference 偏好度 / connection 联结度）+
    停留 / 渗透 / 增长。

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {date, rows, count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval("SELECT MAX(date) FROM mvp_brand_mind_daily")
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_brand_mind_daily 表无数据；先去 scout-agent 跑 yuntu brand-mind runbook",
            }
        target_date = latest

    rows_db = await pool.fetch(
        """
        SELECT brand_id, sku_id, brand_assoc_count, industry_share,
               industry_rank, reputation, preference, dwell, connection, increase
        FROM mvp_brand_mind_daily
        WHERE date = $1
        ORDER BY brand_id, sku_id
        """,
        target_date,
    )
    if not rows_db:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"mvp_brand_mind_daily 在 date={target_date.isoformat()} 无数据",
        }

    rows = [
        {
            "brand_id": r["brand_id"],
            "sku_id": r["sku_id"] or None,
            "brand_assoc_count": r["brand_assoc_count"],
            "industry_share": str(r["industry_share"]) if r["industry_share"] is not None else None,
            "industry_rank": r["industry_rank"],
            "reputation": str(r["reputation"]) if r["reputation"] is not None else None,
            "preference": str(r["preference"]) if r["preference"] is not None else None,
            "dwell": r["dwell"],
            "connection": r["connection"],
            "increase": r["increase"],
        }
        for r in rows_db
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "rows": rows,
            "count": len(rows),
        },
        "trace": {
            "db_query": "mvp_brand_mind_daily WHERE date=$1",
            "row_count": len(rows),
        },
    }
```

- [ ] **Step 4: 跑测试看 pass**

- [ ] **Step 5: KE restart + commit**

```bash
docker restart omni-knowledge-engine
git add services/knowledge-engine/app/mcp/tools/scout.py services/knowledge-engine/tests/test_mcp_scout.py
git commit -m "$(cat <<'EOF'
feat(mcp): fetch_yuntu_brand_mind 读品牌心智 3 指标 (W3b T5)

W3b 5 scout 第 5 个，最后一个 fetch tool。读 mvp_brand_mind_daily
表，含 reputation/preference/connection 3 个核心心智指标 + 行业份额
+ 行业排名 + dwell/increase 等。

numeric(8,6) 字段（industry_share/reputation/preference）保持 Decimal
精度 → str(Decimal)，避免 float 误差。bigint/integer 字段直接返。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- numeric(8,6) 字段 asyncpg 返 Decimal，序列化用 str() 防 float 精度损失
- bigint 字段（brand_assoc_count）和 integer 字段（industry_rank/dwell/connection/increase）直接 int，不要 str()
- Decimal("0.85") 序列化是 "0.85"，但 numeric(8,6) 数据库存 "0.850000"——测试 assert 用 "0.850000"（DB 返的精度版本）

---

## Task 6: kb_upload_doc（T 类，走 Gate）

**Goal:** 上传文件入指定 KB（require_approval=True，CLI 批后才真正调 ingestion）。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/kb.py`（追加 kb_upload_doc）
- Test: `services/knowledge-engine/tests/test_mcp_kb_admin.py`（新建）

**接口**：

```python
async def kb_upload_doc(
    kb_id: str,
    file_path: str,
    title: str | None = None,
    source_type: str = "doc",
) -> dict:
    """上传文件入 KB（require_approval=True，CLI 批后才执行 ingestion）。

    Args:
        kb_id: KB id
        file_path: 容器内文件绝对路径（或 mount 挂的路径）
        title: 文档标题，None 用 file 名
        source_type: doc/manual/runbook 等（同 ingest router）

    Returns:
        {ok, result: {task_id, kb_id, file_path, ...}, trace}
    """
```

- [ ] **Step 1: 写 failing test**

写 `services/knowledge-engine/tests/test_mcp_kb_admin.py`：

```python
"""W3b T6/T7: KB 管理 tool 测试。"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.mcp.tools.kb import kb_upload_doc, kb_set_role
from app.mcp import human_gate

SMOKE_PREFIX = "_smoke_W3b_kb_"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    pool = get_pool()
    # 准备一个测试 KB（如果还没的话）
    smoke_kb_id = str(uuid.uuid4())
    await pool.execute(
        """
        INSERT INTO knowledge.knowledge_bases
            (id, name, description, embedding_provider, embedding_model, dimension, kb_role)
        VALUES ($1, $2, '_smoke W3b test KB', 'gemini', 'gemini-embedding-2-preview', 1536, 'general')
        """,
        uuid.UUID(smoke_kb_id),
        SMOKE_PREFIX + "kb",
    )
    yield smoke_kb_id
    # teardown
    await pool.execute(
        "DELETE FROM knowledge.knowledge_bases WHERE name LIKE $1",
        SMOKE_PREFIX + "%",
    )
    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name IN ('kb_upload_doc', 'kb_set_role') AND args::text LIKE $1",
        "%" + SMOKE_PREFIX + "%",
    )
    await pool.execute(
        "DELETE FROM mcp.human_gates WHERE summary LIKE $1",
        "%" + SMOKE_PREFIX + "%",
    )
    await close_pool()


@pytest.mark.asyncio
async def test_kb_upload_doc_rejected_when_no_approval(setup_pool):
    """走 Gate 但没人批 → timeout 后返 rejected_by_user。"""
    kb_id = setup_pool
    # 写入一个临时小文件
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("smoke W3b kb_upload_doc test content\n")
        tmp_path = f.name

    try:
        # timeout 设很短让测试不慢
        # 注意：tool_with_audit 的 timeout_seconds 是装饰器参数，无法在调用时改。
        # 用 monkeypatch 注入 mock human_gate 直接返 rejected。
        original_request = human_gate.request_approval

        async def mock_rejected(**kwargs):
            return {"decision": "rejected", "decision_note": "test mock"}

        human_gate.request_approval = mock_rejected
        try:
            result = await kb_upload_doc(kb_id=kb_id, file_path=tmp_path)
        finally:
            human_gate.request_approval = original_request

        assert result["ok"] is False
        assert result["error"] == "rejected_by_user"
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_kb_upload_doc_approved_creates_task(setup_pool):
    """Gate 批准 → 真调 ingestion，返 task_id。"""
    kb_id = setup_pool
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("approved upload smoke content\n这是中文内容用于测试 ingestion 抽取。")
        tmp_path = f.name

    try:
        original_request = human_gate.request_approval

        async def mock_approved(**kwargs):
            return {"decision": "approved", "decision_note": "test approved"}

        human_gate.request_approval = mock_approved
        try:
            result = await kb_upload_doc(
                kb_id=kb_id, file_path=tmp_path, title="_smoke_W3b_doc"
            )
        finally:
            human_gate.request_approval = original_request

        assert result["ok"] is True
        assert "task_id" in result["result"]
        task_id = result["result"]["task_id"]
        assert isinstance(task_id, str) and len(task_id) > 0
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_kb_upload_doc_invalid_kb(setup_pool):
    """kb_id 不存在 → 在 Gate 前就 reject（kb 校验）。"""
    fake_kb = str(uuid.uuid4())
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("any content")
        tmp_path = f.name

    try:
        original_request = human_gate.request_approval

        async def mock_approved(**kwargs):
            return {"decision": "approved"}

        human_gate.request_approval = mock_approved
        try:
            result = await kb_upload_doc(kb_id=fake_kb, file_path=tmp_path)
        finally:
            human_gate.request_approval = original_request

        assert result["ok"] is False
        assert result["error"] == "kb_not_found"
    finally:
        os.unlink(tmp_path)
```

- [ ] **Step 2: 跑测试看 fail**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_kb_admin.py -v -k upload"
```

期望：`ImportError: cannot import name 'kb_upload_doc'`

- [ ] **Step 3: 写实现（追加到 kb.py）**

```python
import os

from app.services import ingestion


def _kb_upload_summary(args: dict) -> str:
    """Gate 卡片摘要：上传 X 入 KB Y"""
    fp = args.get("file_path", "?")
    base = os.path.basename(fp) if fp != "?" else "?"
    kb = args.get("kb_id", "?")[:8]
    return f"上传 {base} 入 KB={kb}"


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_kb_upload_summary,
    timeout_seconds=3600,
)
async def kb_upload_doc(
    kb_id: str,
    file_path: str,
    title: str | None = None,
    source_type: str = "doc",
) -> dict:
    """上传文件入 KB（require_approval=True，CLI 批后才执行 ingestion）。

    内部走 services.ingestion.submit_ingestion_task，跟 router /ingest 一致。

    Args:
        kb_id: KB id（uuid str）
        file_path: 文件绝对路径（容器内可访问）
        title: 文档标题，None 自动用文件名
        source_type: doc/manual/runbook 等

    Returns:
        {ok, result: {task_id, kb_id, title, ...}, trace}
    """
    # 校验 KB
    kb = await ingestion.get_kb(kb_id)
    if not kb:
        return {
            "ok": False,
            "error": "kb_not_found",
            "hint": f"kb_id={kb_id} 不存在；用 list_kbs 查可用 id",
        }

    # 读文件
    if not os.path.exists(file_path):
        return {
            "ok": False,
            "error": "file_not_found",
            "hint": f"file_path={file_path} 容器内不存在；确认 bind mount 路径",
        }
    if os.path.isdir(file_path):
        return {
            "ok": False,
            "error": "is_directory",
            "hint": f"file_path={file_path} 是目录不是文件",
        }
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        return {
            "ok": False,
            "error": "binary_file_unsupported",
            "hint": (
                "kb_upload_doc 当前只支持 UTF-8 文本（.txt/.md/.json）。"
                "二进制（PDF/DOCX）请走前端 /api/v1/knowledge/documents/ingest 上传。"
            ),
        }

    auto_title = title or os.path.basename(file_path)
    task_id = await ingestion.submit_ingestion_task(
        kb_id=kb_id,
        title=auto_title,
        text=text,
        source_url=f"file://{file_path}",
        source_type=source_type,
    )

    return {
        "ok": True,
        "result": {
            "task_id": task_id,
            "kb_id": kb_id,
            "kb_name": kb.get("name"),
            "title": auto_title,
            "source_type": source_type,
            "char_count": len(text),
        },
        "trace": {
            "ingestion_task_id": task_id,
            "submit_via": "ingestion.submit_ingestion_task",
        },
    }
```

注意：`ingestion.get_kb` 当前签名是 `async def get_kb(kb_id: str) -> dict | None`（line 95-103）。如果不存在请确认 ingestion.py 是否真有这函数。如果只有 `list_kbs`，先在 list 里 find by id：

```python
all_kbs = await ingestion.list_kbs()
kb = next((k for k in all_kbs if k["id"] == kb_id), None)
```

implementer 看 `services/knowledge-engine/app/services/ingestion.py` 确认。

- [ ] **Step 4: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_kb_admin.py -v -k upload"
```

期望：3 个 PASS。

- [ ] **Step 5: 加到 server.py 注册（kb 已注册，无需新加 import）**

kb_upload_doc 在 `tools/kb.py` 内，server.py 已经 `import kb` 了，新函数定义被装饰器自动注册。无需改 server.py。

```bash
docker restart omni-knowledge-engine
```

- [ ] **Step 6: commit**

```bash
git add services/knowledge-engine/app/mcp/tools/kb.py services/knowledge-engine/tests/test_mcp_kb_admin.py
git commit -m "$(cat <<'EOF'
feat(mcp): kb_upload_doc 走 Gate 上传文件入 KB (W3b T6)

W3b 第 1 个 T 类 tool（require_approval=True，CLI 批后才执行）。

实现路径：
1. 校验 kb_id 存在（防止 ingestion 后 dangling task）
2. 读 file_path 文件 utf-8 文本（仅支持文本类，二进制走前端）
3. 调 services.ingestion.submit_ingestion_task

Gate summary 卡片："上传 X.md 入 KB=12345678"，CLI 批/驳后才进 ingestion。

测试覆盖：rejected timeout / approved 真创建 task / kb_not_found 提前
reject。用 monkeypatch 替换 human_gate.request_approval 模拟批/驳，
不让测试真等老板按 CLI（参考 W3a T6/T8 同模式）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- `submit_ingestion_task` 的具体签名要看 ingestion.py 实际代码。implementer 写实现前先读 `services/knowledge-engine/app/services/ingestion.py:218` 行附近，确认参数名（kb_id/title/text/source_url/source_type/metadata/skip_chunking）。如果跟 plan 写的不一致以代码为准。
- `human_gate.request_approval` 替换是 module-level monkeypatch；测试不用 pytest fixture monkeypatch 因为 tool_with_audit 装饰器在 import 时就 bind 了 human_gate 模块的引用。直接赋值替换 module 属性才生效。
- 测试 cleanup 要清 `mcp.tool_calls` 和 `mcp.human_gates` 两表的 _smoke_ 行，否则下次跑 module fixture 不干净。

---

## Task 7: kb_set_role（T 类，走 Gate）

**Goal:** 改 KB 的 kb_role（require_approval=True）。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/kb.py`
- Modify: `services/knowledge-engine/tests/test_mcp_kb_admin.py`

**接口**：

```python
async def kb_set_role(kb_id: str, kb_role: str) -> dict:
    """改 KB 角色（require_approval=True）。

    合法 kb_role：authoritative / methodology / personal_log /
    template / private_doc / general（同 ingestion.py _VALID_KB_ROLES）

    Args:
        kb_id: KB id
        kb_role: 新角色

    Returns:
        {ok, result: {kb_id, kb_role, name, ...}, trace}
    """
```

- [ ] **Step 1: 写 failing test**

在 `test_mcp_kb_admin.py` 追加：

```python
@pytest.mark.asyncio
async def test_kb_set_role_approved(setup_pool):
    kb_id = setup_pool
    original_request = human_gate.request_approval

    async def mock_approved(**kwargs):
        return {"decision": "approved"}

    human_gate.request_approval = mock_approved
    try:
        result = await kb_set_role(kb_id=kb_id, kb_role="template")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is True
    assert result["result"]["kb_role"] == "template"

    # 验证 DB 真写入
    pool = get_pool()
    role = await pool.fetchval(
        "SELECT kb_role FROM knowledge.knowledge_bases WHERE id = $1",
        uuid.UUID(kb_id),
    )
    assert role == "template"


@pytest.mark.asyncio
async def test_kb_set_role_invalid_role(setup_pool):
    kb_id = setup_pool
    original_request = human_gate.request_approval

    async def mock_approved(**kwargs):
        return {"decision": "approved"}

    human_gate.request_approval = mock_approved
    try:
        result = await kb_set_role(kb_id=kb_id, kb_role="not_a_real_role")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is False
    assert result["error"] == "invalid_kb_role"


@pytest.mark.asyncio
async def test_kb_set_role_kb_not_found(setup_pool):
    fake_kb = str(uuid.uuid4())
    original_request = human_gate.request_approval

    async def mock_approved(**kwargs):
        return {"decision": "approved"}

    human_gate.request_approval = mock_approved
    try:
        result = await kb_set_role(kb_id=fake_kb, kb_role="general")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is False
    assert result["error"] == "kb_not_found"


@pytest.mark.asyncio
async def test_kb_set_role_rejected(setup_pool):
    kb_id = setup_pool
    original_request = human_gate.request_approval

    async def mock_rejected(**kwargs):
        return {"decision": "rejected", "decision_note": "test reject"}

    human_gate.request_approval = mock_rejected
    try:
        result = await kb_set_role(kb_id=kb_id, kb_role="template")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is False
    assert result["error"] == "rejected_by_user"
```

更新 import：

```python
from app.mcp.tools.kb import kb_upload_doc, kb_set_role
```

- [ ] **Step 2: 跑测试看 fail**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_kb_admin.py -v -k set_role"
```

- [ ] **Step 3: 写实现（追加到 kb.py）**

```python
_VALID_KB_ROLES = {
    "authoritative", "methodology", "personal_log",
    "template", "private_doc", "general",
}


def _kb_set_role_summary(args: dict) -> str:
    return f"改 KB={args.get('kb_id', '?')[:8]} → role={args.get('kb_role', '?')}"


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_kb_set_role_summary,
    timeout_seconds=3600,
)
async def kb_set_role(kb_id: str, kb_role: str) -> dict:
    """改 KB 角色（require_approval=True）。

    合法角色：authoritative / methodology / personal_log /
    template / private_doc / general

    Args:
        kb_id: KB id
        kb_role: 新角色

    Returns:
        {ok, result: {kb_id, kb_role, name}, trace}
    """
    if kb_role not in _VALID_KB_ROLES:
        return {
            "ok": False,
            "error": "invalid_kb_role",
            "hint": f"kb_role 必须是 {sorted(_VALID_KB_ROLES)} 之一，给的是 {kb_role!r}",
        }

    # 校验 KB 存在
    existing = await ingestion.get_kb(kb_id)
    if not existing:
        return {
            "ok": False,
            "error": "kb_not_found",
            "hint": f"kb_id={kb_id} 不存在",
        }

    updated = await ingestion.update_kb_role(kb_id, kb_role)
    if not updated:
        return {
            "ok": False,
            "error": "update_failed",
            "hint": "ingestion.update_kb_role 返回 None；DB 写入失败",
        }

    return {
        "ok": True,
        "result": {
            "kb_id": kb_id,
            "kb_role": kb_role,
            "name": updated.get("name"),
            "old_kb_role": existing.get("kb_role"),
        },
        "trace": {
            "db_query": "UPDATE knowledge.knowledge_bases SET kb_role=$1 WHERE id=$2",
            "old_role": existing.get("kb_role"),
            "new_role": kb_role,
        },
    }
```

- [ ] **Step 4: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_kb_admin.py -v -k set_role"
```

- [ ] **Step 5: KE restart + commit**

```bash
docker restart omni-knowledge-engine
git add services/knowledge-engine/app/mcp/tools/kb.py services/knowledge-engine/tests/test_mcp_kb_admin.py
git commit -m "$(cat <<'EOF'
feat(mcp): kb_set_role 走 Gate 改 KB 角色 (W3b T7)

W3b 第 2 个 T 类 tool。包装 ingestion.update_kb_role，require_approval
=True，CLI 批后才执行 UPDATE。

合法角色（同 ingestion._VALID_KB_ROLES）：authoritative / methodology /
personal_log / template / private_doc / general。

返回时含 old_kb_role 让老板审计变更轨迹。

测试 4 case：approved 真改 / invalid_role 提前 reject / kb_not_found
提前 reject / rejected 老板驳。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- `_VALID_KB_ROLES` 在 ingestion.py 已经定义（line ~50 附近）。implementer 可以选择 `from app.services.ingestion import _VALID_KB_ROLES` 复用，避免双份维护。但如果 ingestion 内是 module-private，复制一份在 kb.py 也 OK（短期不会增），加 comment 指向源头即可。
- `update_kb_role` 已有 (line 105 ingestion.py)，直接调，不写新 SQL
- `existing.get("kb_role")` 取旧 role 给 trace.old_role，方便老板看审计

---

## Task 8: doctor expected_tools=20 + tools/__init__.py 更新

**Goal:** doctor 升 expected_tools 13 → 20，列出新 7 个 tool 名；tools/__init__.py 注释更新。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/doctor.py`
- Modify: `services/knowledge-engine/app/mcp/tools/__init__.py`

- [ ] **Step 1: 看 doctor 当前实现**

```bash
docker exec omni-knowledge-engine cat /app/app/mcp/doctor.py | head -60
```

找到 `expected_tools` 常量（W3a T12 已设为 13）。

- [ ] **Step 2: 改 expected_tools = 20，加 7 个新 tool 名**

修改 `services/knowledge-engine/app/mcp/doctor.py`，在 `_EXPECTED_TOOLS` 列表追加 7 个：

```python
_EXPECTED_TOOLS = [
    # W1 5
    "list_skus", "get_sku", "list_kbs", "search_kb", "list_briefs",
    # W2 5
    "query_costs", "compute_margin", "generate_brief",
    "generate_image", "generate_video",
    # W3a 3
    "gather_brief_context", "record_cost", "disable_cost_item",
    # W3b 7
    "fetch_compass_store_daily",
    "fetch_compass_sku_detail",
    "fetch_compass_search_traffic",
    "fetch_yuntu_5a",
    "fetch_yuntu_brand_mind",
    "kb_upload_doc",
    "kb_set_role",
]
```

注：列表常量名以代码为准（可能是 `EXPECTED_TOOLS` / `EXPECTED_TOOL_NAMES`）。

- [ ] **Step 3: 更新 tools/__init__.py docstring**

修改 `services/knowledge-engine/app/mcp/tools/__init__.py`：

```python
"""W1 + W2 + W3a + W3b tools。

注册顺序：在 `app.mcp.server` import 时通过 `import app.mcp.tools.<x>` 等触发副作用。

20 tool 总览：
- W1 (5): list_skus, get_sku, list_kbs, search_kb, list_briefs
- W2 (5): query_costs, compute_margin, generate_brief, generate_image, generate_video
- W3a (3): gather_brief_context, record_cost, disable_cost_item
- W3b (7): fetch_compass_store_daily, fetch_compass_sku_detail,
           fetch_compass_search_traffic, fetch_yuntu_5a, fetch_yuntu_brand_mind,
           kb_upload_doc, kb_set_role
"""
```

- [ ] **Step 4: KE restart + 跑 doctor**

```bash
docker restart omni-knowledge-engine
sleep 5
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

期望输出：

```
omni MCP doctor 报告
  [OK  ] DB pool
  [OK  ] mcp schema tables: found 2/2
  [OK  ] tool_models.yaml: keys=['__default__', ...]
  [OK  ] prompt templates: all 8 ok
  [OK  ] 20 tools registered: all 20 ok
  [OK  ] /mcp HTTP: status=200

结论：全绿 ✓
```

- [ ] **Step 5: commit**

```bash
git add services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/app/mcp/tools/__init__.py
git commit -m "$(cat <<'EOF'
feat(mcp): doctor expected_tools=20 + tools/__init__.py 加 W3b 注释 (W3b T8)

W3b 7 tool 全部注册到 server，doctor 升 13 → 20。新增 5 scout fetch
+ 2 KB 管理 tool，全部走标准 tool_with_audit 装饰器，注册顺序由
server.py 的 import scout/kb 触发。

跑 doctor 期望 [OK] 20 tools registered: all 20 ok。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- doctor 检查 tool 名时是从 FastMCP 实例的注册表取，跟 _EXPECTED_TOOLS 列表 set 比对。新加的 7 个 tool 名必须跟 `@tool_with_audit` 装饰的函数名完全一致（fetch_compass_store_daily 等）。
- 如果 doctor 报"missing tool: X"——说明 server.py 没 import 包含 X 的 tool 模块。检查 import 顺序：W3b T1 的 step 5 加的 `from app.mcp.tools import scout as _scout` 必须在。

---

## Task 9: e2e 容器内自检 + 老板侧 grant 累积清单

**Goal:** 容器内跑全 7 tool 一遍 sanity + 给老板列出需要 grant 的 mcp__omni__ 权限清单。

**Files:**
- Create: `services/knowledge-engine/scripts/_w3b_e2e.py`（容器内 e2e 脚本，**临时调试不入 commit**，跑完删）
- Modify: `.claude/settings.local.json`（grant 7 个新 tool 权限）

- [ ] **Step 1: 写容器内 e2e 脚本**

```python
# services/knowledge-engine/scripts/_w3b_e2e.py（临时 throwaway，跑完删）
"""W3b e2e 容器内自检：跑 5 scout fetch + 2 KB 管理（mock Gate 批准）。

用法：
    docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python scripts/_w3b_e2e.py"
"""
import asyncio
import os
import tempfile

from app.database import init_pool, close_pool
from app.mcp import human_gate
from app.mcp.tools.scout import (
    fetch_compass_store_daily,
    fetch_compass_sku_detail,
    fetch_compass_search_traffic,
    fetch_yuntu_5a,
    fetch_yuntu_brand_mind,
)
from app.mcp.tools.kb import kb_upload_doc, kb_set_role


async def main():
    await init_pool()

    print("\n=== T1 fetch_compass_store_daily ===")
    r = await fetch_compass_store_daily()
    print(f"ok={r['ok']}, count={r.get('result', {}).get('count', 0) if r.get('result') else 'N/A'}")

    print("\n=== T2 fetch_compass_sku_detail ===")
    r = await fetch_compass_sku_detail(sku_id="SKU-367991-0002")
    print(f"ok={r['ok']}, error={r.get('error', 'none')}")

    print("\n=== T3 fetch_compass_search_traffic ===")
    r = await fetch_compass_search_traffic()
    print(f"ok={r['ok']}, count={r.get('result', {}).get('count', 0) if r.get('result') else 'N/A'}")

    print("\n=== T4 fetch_yuntu_5a ===")
    r = await fetch_yuntu_5a()
    print(f"ok={r['ok']}, count={r.get('result', {}).get('count', 0) if r.get('result') else 'N/A'}")

    print("\n=== T5 fetch_yuntu_brand_mind ===")
    r = await fetch_yuntu_brand_mind()
    print(f"ok={r['ok']}, count={r.get('result', {}).get('count', 0) if r.get('result') else 'N/A'}")

    print("\n=== T6/T7 KB 管理（mock Gate 批准） ===")
    # 先取一个真 KB id
    from app.services import ingestion
    kbs = await ingestion.list_kbs()
    if not kbs:
        print("无 KB，跳过 T6/T7")
    else:
        target = kbs[0]
        print(f"用 KB id={target['id'][:8]} name={target['name']}")

        # mock gate 批准
        original_request = human_gate.request_approval

        async def mock_approved(**kwargs):
            print(f"  [mock gate] approved: {kwargs.get('summary')}")
            return {"decision": "approved"}

        human_gate.request_approval = mock_approved
        try:
            # T6 上传一个临时 .txt
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
                f.write("W3b e2e 自检文档\n这是 kb_upload_doc 的临时测试。")
                tmp = f.name
            r = await kb_upload_doc(kb_id=target["id"], file_path=tmp, title="_w3b_e2e_doc")
            print(f"  T6 kb_upload_doc: ok={r['ok']}, task_id={r.get('result', {}).get('task_id', 'none')}")
            os.unlink(tmp)

            # T7 改 role 来回切（先改成 general，再改回原 role）
            original_role = target.get("kb_role") or "general"
            r = await kb_set_role(kb_id=target["id"], kb_role="general" if original_role != "general" else "template")
            print(f"  T7 kb_set_role to {r.get('result', {}).get('kb_role')}: ok={r['ok']}")
            # 改回原 role
            r2 = await kb_set_role(kb_id=target["id"], kb_role=original_role)
            print(f"  T7 kb_set_role back to {original_role}: ok={r2['ok']}")
        finally:
            human_gate.request_approval = original_request

    print("\n=== W3b e2e 完成 ===")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 跑容器内 e2e**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python scripts/_w3b_e2e.py"
```

期望：
- T1-T5 不报错（如果 mvp_* 表数据少可能 ok=False error=no_data，可接受）
- T6 mock gate 批 + 真创建 ingestion task_id
- T7 mock gate 批 + 真改 role 来回切

- [ ] **Step 3: 删 throwaway 脚本**

```bash
rm services/knowledge-engine/scripts/_w3b_e2e.py
```

- [ ] **Step 4: 给 settings.local.json 加 grant**

修改 `.claude/settings.local.json`，在 `permissions.allow` 列表追加：

```json
"mcp__omni__fetch_compass_store_daily",
"mcp__omni__fetch_compass_sku_detail",
"mcp__omni__fetch_compass_search_traffic",
"mcp__omni__fetch_yuntu_5a",
"mcp__omni__fetch_yuntu_brand_mind",
"mcp__omni__kb_upload_doc",
"mcp__omni__kb_set_role"
```

按现有 `mcp__omni__*` 列表的格式 + 顺序追加。

- [ ] **Step 5: commit settings + W3b 收尾**

```bash
git add .claude/settings.local.json
git commit -m "$(cat <<'EOF'
chore(claude): grant W3b 7 tool 权限 (W3b T9)

老板侧 e2e 不再每次提示批准。grant 5 scout fetch + 2 KB 管理（T 类
仍走 cli_approve Gate 二次确认）。

容器内 e2e 自检通过：5 scout 读 mvp_* 表 + 2 KB 管理 mock gate 批。

W3b 落地完毕，HEAD 即下个 commit。doctor 20/20 OK。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: 老板侧客户端 e2e（在 Claude Code 里测）**

老板自己在 Claude Code 里跑：

```
查抖店全店日报
查 SKU-367991-0002 的罗盘数据
看云图 5A 资产
看品牌心智
查搜索流量数据
```

如果 prompt 里"查"触发 Claude 调对应 tool，看返回是否合理。grant 已加，不会卡审。

T 类 tool（kb_upload_doc / kb_set_role）走 cli_approve Gate：

```
帮我把 X.md 入到 KB Y
帮我把 KB Y 的 role 改成 template
```

老板侧另开 PowerShell 跑 `docker exec omni-knowledge-engine python -m app.mcp.cli_approve tail`，看 Gate 卡片，按 approve/reject。

**容易撞的坑**：
- `_w3b_e2e.py` 是 throwaway 标记前缀 `_`；W3a-X 经验 W3a 期间留了 8 个 `_w3a_*` 后期清理成本——这次 step 3 直接删，不要留
- settings.local.json 顺序不重要但保持跟 W1/W2/W3a 一致风格
- 老板侧 e2e 需要 mvp_daily_metric / mvp_5a_asset_daily / mvp_brand_mind_daily 有真实数据。memory 实锤 2026-05-03 已跑过 → 看 `SELECT MAX(date) FROM mvp_5a_asset_daily;` 确认数据新鲜度。如太老（>7 天）建议老板先去 scout-agent 跑一次 runbook G/H

---

## Self-Review

### 1. Spec coverage check

design doc §3.2 W3 行 13 tool 中，W3a 已加 0 个，W3b 加 7 个，**W3c 待加 6 个**（summarize_text / parse_long_doc_with_gemini / query_template_chunks / generate_recording_insights / list_recordings / get_recording）。

W3b 范围明确：
- ✅ fetch_compass_store_daily — T1
- ✅ fetch_compass_sku_detail — T2
- ✅ fetch_compass_search_traffic — T3
- ✅ fetch_yuntu_5a — T4
- ✅ fetch_yuntu_brand_mind — T5
- ✅ kb_upload_doc — T6
- ✅ kb_set_role — T7

### 2. Placeholder scan

- [x] 无 "TBD" / "TODO" / "fill in details"
- [x] 每 task 含完整测试代码 + 实现代码
- [x] 每 commit 含完整 commit message
- [x] 每 task 含 commands + expected output

### 3. Type / 签名 consistency

- `fetch_compass_store_daily(date: str | None = None)` 跟 `fetch_compass_search_traffic(date: str | None = None)` 同型 ✓
- `fetch_yuntu_5a` / `fetch_yuntu_brand_mind` 都返 `{rows: [...]}` 结构（不是 metrics），跟 compass 系列的 `{metrics: [...]}` 区分（5A/brand_mind 是宽表行，metric 是 KV pair）✓
- `kb_upload_doc` / `kb_set_role` 都用 `tool_with_audit(require_approval=True, summary_fn=..., timeout_seconds=3600)` 同 W3a record_cost / disable_cost_item 模式 ✓
- `ingestion.get_kb` 假设存在；implementer 看代码确认。如果不存在 fallback 到 list_kbs + filter（plan T6 step 3 注释提了）

### 4. 已知风险 / 待补

- **mvp_daily_metric 实际入库的 source_runbook 名**可能跟 plan 假设的 "compass/sell-analysis" / "compass/business-part" / "compass/search-drainage-terms" 不完全一致。implementer 跑 T1 测试前先 `SELECT DISTINCT source_runbook FROM mvp_daily_metric;` 看真实名字。如果 prefix 不是 compass/* 而是别的，T1 的 WHERE 条件要调。
- T6 `submit_ingestion_task` 签名要看代码确认（plan 写的参数列表是基于 router /ingest 的 form payload 推测）
- T9 e2e 老板侧需要 grant + scout 数据新鲜，缺一不可——已在 step 6 提了

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-05-omni-agent-uplift-W3b-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 9 个 task 每个 fresh subagent + 二阶 review，跟 W3a 节奏一致。预估 5 小时完整跑完。

**2. Inline Execution** — 在当前 session 跑，batch + checkpoint，老板可中途审。预估 4 小时（少 subagent context 切换开销，但可能漏掉 W3a 那种"plan 字面 vs 实测偏差"自动 catch）。

**Which approach?**
