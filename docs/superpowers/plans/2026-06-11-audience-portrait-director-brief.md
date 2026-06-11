# 人群画像生活状态 + 编导 Brief（step 3.5/3.6）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 omni KE 新增 step 3.5 `generate_audience_portrait`（人群生活状态画像+卖点重构，KB 锚+可信度分级）和 step 3.6 `generate_director_brief`（真人编导备忘录+算法信号三向量+AI 出片映射），含 migration 047、step 2 prompt 打磨 4 处、doctor 78→80。

**Architecture:** 两个新 tool 放新模块 `app/mcp/tools/portrait_brief.py`（media.py 已 4000 行不再加），复用 media.py 的 `_multi_query_recall`/`_format_kb_recall`/`AUDIENCE_KB_ID` 做检索、`pipeline_lineage` 做血缘落库（新表 audience_portraits + scripts 加 kind/portrait_id）。prompt 全外置 `config/prompts/`（mtime 热加载）。

**Tech Stack:** Python 3.11 / FastMCP 3.x / asyncpg（裸 SQL）/ AIHubClient（gemini）/ pytest-asyncio（真 DB 测试）

**Spec:** `docs/superpowers/specs/2026-06-11-audience-portrait-director-brief-design.md`

**环境前提（每个任务都依赖）：**
- 仓库根 `E:\agent\omni`，KE 代码在 `services/knowledge-engine/`
- 容器 `omni-knowledge-engine` + `omni-postgres` 在跑（`docker ps` 确认）
- 改 `.py` 后必须 `docker restart omni-knowledge-engine` 才生效（只有 `config/prompts/*.md` 是 mtime 热加载不用重启）
- 测试在容器内跑：`docker exec omni-knowledge-engine pytest tests/<file> -v`（真 DB，无 mock）

---

### Task 1: 开分支 + migration 047

**Files:**
- Create: `migrations/047_audience_portraits.sql`

- [ ] **Step 1: 开分支**

```bash
cd E:\agent\omni
git checkout -b feat/audience-portrait-brief
```

注意：当前分支 feat/competitor-research 可能有别人未提交的改动，**不要 git add -A**，每次 commit 只 add 本计划明确列出的文件。

- [ ] **Step 2: 写 migration 文件**

创建 `migrations/047_audience_portraits.sql`，完整内容：

```sql
-- Migration 047: pipeline.audience_portraits（step 3.5 人群画像）+ scripts 支持 director_brief（step 3.6）
--
-- 链路：audience_record（step 3 老板选中）→ audience_portrait（step 3.5 生活状态画像+卖点重构）
--      → scripts kind='director_brief'（step 3.6 编导备忘录）
-- 设计 spec：docs/superpowers/specs/2026-06-11-audience-portrait-director-brief-design.md

-- 1. 画像表（列约定对齐 021 的 audience_runs：denorm sku_id / draft 两态 / 多版本 parent 串接）
CREATE TABLE IF NOT EXISTS pipeline.audience_portraits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_record_id UUID NOT NULL REFERENCES pipeline.audience_records(id) ON DELETE CASCADE,
    audience_run_id UUID,           -- denorm
    matrix_run_id UUID,             -- denorm
    sku_id VARCHAR(64) NOT NULL,    -- denorm

    portrait_md TEXT NOT NULL,
    recall_meta JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {mode, routes:{...}, queries:[...], chunk_count}
    validation_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 标记配额闸检查结果

    -- 入参备份
    extra_context TEXT,
    kb_recall_override TEXT,

    -- LLM trace
    model_provider TEXT,
    model TEXT,
    prompt_hash TEXT,
    cost_estimate TEXT,

    -- 版本/状态
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    parent_portrait_id UUID REFERENCES pipeline.audience_portraits(id) ON DELETE SET NULL,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audience_portraits_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT audience_portraits_version_pos
        CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_portraits_sku
    ON pipeline.audience_portraits (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_portraits_record
    ON pipeline.audience_portraits (audience_record_id);

COMMENT ON TABLE pipeline.audience_portraits IS
    'step 3.5 人群生活状态画像（KB 锚+可信度分级标注+卖点重构+情绪触点矩阵）；多版本不覆盖';

-- 2. scripts：kind 枚举加 director_brief
ALTER TABLE pipeline.scripts DROP CONSTRAINT IF EXISTS scripts_kind_check;
ALTER TABLE pipeline.scripts ADD CONSTRAINT scripts_kind_check
    CHECK (kind IS NULL OR kind IN (
        'video_soft_ad',         -- 视频 · 软广（A2 触动 / 内容娱乐化软植入）
        'video_planting',        -- 视频 · 种草（A3 共鸣 / 讲产品力 + 我懂你）
        'video_harvest',         -- 视频 · 收割（A4 行动 / 限时 + 价格 + CTA）
        'graphic_harvest',       -- 图文 · 收割（小红书/抖店图文，转化导向）
        'product_main_image',    -- 商品视觉 · 主图（5-9 张冲击力 + 卖点叠加）
        'product_detail_page',   -- 商品视觉 · 详情页（叙事长图，卖点闭环）
        'director_brief'         -- 编导备忘录（step 3.6 真人拍+AI 映射两用）
    ));

-- 3. scripts：挂画像血缘
ALTER TABLE pipeline.scripts ADD COLUMN IF NOT EXISTS portrait_id UUID
    REFERENCES pipeline.audience_portraits(id) ON DELETE SET NULL;
COMMENT ON COLUMN pipeline.scripts.portrait_id IS
    '可选：挂 step 3.5 人群画像（director_brief 类必挂；其他 kind 为 NULL）';
```

- [ ] **Step 3: 应用 migration**

```bash
docker exec omni-knowledge-engine python scripts/apply_migrations.py --dry-run
docker exec omni-knowledge-engine python scripts/apply_migrations.py
```

Expected: dry-run 列出 `047_audience_portraits.sql` 待应用；apply 输出 applied。

- [ ] **Step 4: 核对表结构**

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "\d pipeline.audience_portraits"
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='scripts_kind_check'"
```

Expected: 表存在、列齐全；kind check 含 `'director_brief'`。

- [ ] **Step 5: Commit**

```bash
git add migrations/047_audience_portraits.sql
git commit -m "feat(pipeline): migration 047 audience_portraits 表 + scripts 支持 director_brief"
```

---

### Task 2: pipeline_lineage 落库函数（TDD）

**Files:**
- Modify: `services/knowledge-engine/app/services/pipeline_lineage.py`
- Test: `services/knowledge-engine/tests/test_portrait_lineage.py`

- [ ] **Step 1: 写失败测试**

创建 `services/knowledge-engine/tests/test_portrait_lineage.py`：

```python
"""step 3.5/3.6: audience_portraits 落库 + adopt + scripts portrait_id 测试（真 DB）。"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.services import pipeline_lineage

SKU = "SKU-TEST-PORTRAIT"

# 最小可拆 audience_md（save_audience_run 的 regex 要 #### 1.X [名] 段）
_AUDIENCE_MD = """### 第 1 部分：KB 匹配人群

#### 1.1 [测试人群]
**[KB来源：测试文档/测试章节]**
> 测试 chunk 原文
**匹配理由（≥5条）**：
1. 卖点 1.1.1 [测试卖点] + 场景 2.1 [测试场景] → 测试
**圈层标签**：食饮

### 第 2 部分：结构化标签汇总
- #测试 标签
"""


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    # 清理测试数据（CASCADE 顺序：portraits/scripts 先于 records/runs）
    pool = get_pool()
    await pool.execute("DELETE FROM pipeline.scripts WHERE sku_id = $1", SKU)
    await pool.execute("DELETE FROM pipeline.audience_portraits WHERE sku_id = $1", SKU)
    await pool.execute("DELETE FROM pipeline.audience_records WHERE sku_id = $1", SKU)
    await pool.execute("DELETE FROM pipeline.audience_runs WHERE sku_id = $1", SKU)
    await pool.execute("DELETE FROM pipeline.matrix_runs WHERE sku_id = $1", SKU)
    await close_pool()


@pytest_asyncio.fixture(scope="module")
async def seed_record():
    """matrix_run → audience_run → 1 个 audience_record，返回 record dict。"""
    matrix_run_id = await pipeline_lineage.save_matrix_run(
        sku_id=SKU, matrix_md="# 测试矩阵", extra_context="(test)",
        model_provider="(test)", model="(test)",
    )
    assert matrix_run_id
    run_id, records = await pipeline_lineage.save_audience_run(
        matrix_run_id=matrix_run_id, sku_id=SKU,
        audience_md=_AUDIENCE_MD, recall_meta={"mode": "test"},
        model_provider="(test)", model="(test)",
    )
    assert run_id and len(records) == 1
    return records[0]


@pytest.mark.asyncio
async def test_save_and_get_portrait(seed_record):
    pid = await pipeline_lineage.save_audience_portrait(
        audience_record_id=seed_record["id"],
        audience_run_id=seed_record.get("audience_run_id"),
        matrix_run_id=seed_record.get("matrix_run_id"),
        sku_id=SKU,
        portrait_md="# 测试画像\n[KB:测试文档] 测试句。",
        recall_meta={"mode": "test", "chunk_count": 1},
        validation_warnings=["⚠ 测试警告"],
        model_provider="(test)", model="(test)",
        final_prompt="test prompt", cost_estimate="0",
    )
    assert pid
    got = await pipeline_lineage.get_audience_portrait(pid)
    assert got is not None
    assert got["sku_id"] == SKU
    assert got["status"] == "draft"
    assert got["version"] == 1
    assert "测试画像" in got["portrait_md"]
    # 反查血缘字段齐全
    assert got["audience_record_id"] == seed_record["id"]


@pytest.mark.asyncio
async def test_portrait_version_increment(seed_record):
    p1 = await pipeline_lineage.save_audience_portrait(
        audience_record_id=seed_record["id"], sku_id=SKU,
        portrait_md="v1", model_provider="(test)", model="(test)",
    )
    p2 = await pipeline_lineage.save_audience_portrait(
        audience_record_id=seed_record["id"], sku_id=SKU,
        portrait_md="v2", parent_portrait_id=p1,
        model_provider="(test)", model="(test)",
    )
    got2 = await pipeline_lineage.get_audience_portrait(p2)
    got1 = await pipeline_lineage.get_audience_portrait(p1)
    assert got2["version"] == got1["version"] + 1
    assert got2["parent_portrait_id"] == p1


@pytest.mark.asyncio
async def test_adopt_portrait(seed_record):
    pid = await pipeline_lineage.save_audience_portrait(
        audience_record_id=seed_record["id"], sku_id=SKU,
        portrait_md="待采纳", model_provider="(test)", model="(test)",
    )
    out = await pipeline_lineage.adopt_run("audience_portraits", pid)
    assert out["ok"] is True
    assert out["status"] == "adopted"


@pytest.mark.asyncio
async def test_save_creative_pack_with_portrait_id(seed_record):
    pid = await pipeline_lineage.save_audience_portrait(
        audience_record_id=seed_record["id"], sku_id=SKU,
        portrait_md="给 brief 挂", model_provider="(test)", model="(test)",
    )
    sid = await pipeline_lineage.save_creative_pack(
        sku_id=SKU, kind="director_brief",
        script_md="# 测试 brief",
        audience_record_id=seed_record["id"],
        portrait_id=pid,
        model_provider="(test)", model="(test)",
    )
    assert sid
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT kind, portrait_id::text AS portrait_id FROM pipeline.scripts WHERE id = $1::uuid", sid
    )
    assert row["kind"] == "director_brief"
    assert row["portrait_id"] == pid
```

- [ ] **Step 2: 跑测试确认失败**

```bash
docker exec omni-knowledge-engine pytest tests/test_portrait_lineage.py -v
```

Expected: FAIL — `AttributeError: module 'app.services.pipeline_lineage' has no attribute 'save_audience_portrait'`。

- [ ] **Step 3: 实现 pipeline_lineage 改动**

打开 `services/knowledge-engine/app/services/pipeline_lineage.py`，做 4 处改动：

**3a.** 找到 `CREATIVE_KINDS` 常量定义（`grep -n "CREATIVE_KINDS = " app/services/pipeline_lineage.py`），在集合里加一个元素 `"director_brief"`（`_KIND_TO_TARGET_PURPOSE.get(kind)` 对新 kind 自动返 None，无需改）。

**3b.** `adopt_run` 函数（约 2041 行）的允许表集合改为（加 `audience_portraits`）：

```python
    if table not in {"matrix_runs", "audience_runs", "audience_records", "audience_packs", "scripts", "assets", "audience_portraits"}:
        return {"ok": False, "error": f"未知 table: {table}"}
```

**3c.** `save_creative_pack`（约 1129 行）加 `portrait_id` 参数并写进 INSERT。签名加一行（放 `parent_script_id` 前）：

```python
    portrait_id: str | None = None,
```

INSERT SQL 整体替换为（列表加 portrait_id、占位符顺延）：

```python
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.scripts (
                audience_pack_id, audience_record_id, matrix_run_id, sku_id,
                script_md, hooks, scenes, character_sheets, target_purpose, kind,
                extra_context,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_script_id, portrait_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4,
                $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10,
                $11,
                $12, $13, $14, $15,
                'draft', $16, $17::uuid, $18::uuid
            ) RETURNING id::text AS id
            """,
            audience_pack_id,
            audience_record_id,
            matrix_run_id,
            sku_id,
            script_md.strip(),
            json.dumps(hooks or [], ensure_ascii=False),
            json.dumps(scenes or [], ensure_ascii=False),
            json.dumps(character_sheets or [], ensure_ascii=False),
            target_purpose,
            kind,
            extra_context,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_script_id,
            portrait_id,
        )
```

**3d.** 文件尾部（`adopt_run` 之前任意位置，建议放 `get_audience_record` 之后）加两个新函数，照 save_audience_run/get_audience_record 模式：

```python
async def save_audience_portrait(
    *,
    audience_record_id: str,
    sku_id: str,
    portrait_md: str,
    audience_run_id: str | None = None,
    matrix_run_id: str | None = None,
    recall_meta: dict | None = None,
    validation_warnings: list | None = None,
    extra_context: str | None = None,
    kb_recall_override: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    parent_portrait_id: str | None = None,
) -> str | None:
    """落 1 行 pipeline.audience_portraits（step 3.5），返回 id。失败返 None 不抛。"""
    if not portrait_md or not portrait_md.strip():
        logger.warning("save_audience_portrait: portrait_md 空，跳过落库")
        return None

    pool = get_pool()

    # 版本号：同 record 下自增；显式 parent 时取其 version+1
    next_version = 1
    if parent_portrait_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.audience_portraits WHERE id = $1::uuid",
            parent_portrait_id,
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        row = await pool.fetchrow(
            "SELECT MAX(version) AS v FROM pipeline.audience_portraits WHERE audience_record_id = $1::uuid",
            audience_record_id,
        )
        if row and row["v"]:
            next_version = int(row["v"]) + 1

    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.audience_portraits (
                audience_record_id, audience_run_id, matrix_run_id, sku_id,
                portrait_md, recall_meta, validation_warnings,
                extra_context, kb_recall_override,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_portrait_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4,
                $5, $6::jsonb, $7::jsonb,
                $8, $9,
                $10, $11, $12, $13,
                'draft', $14, $15::uuid
            ) RETURNING id::text AS id
            """,
            audience_record_id,
            audience_run_id,
            matrix_run_id,
            sku_id,
            portrait_md.strip(),
            json.dumps(recall_meta or {}, ensure_ascii=False),
            json.dumps(validation_warnings or [], ensure_ascii=False),
            extra_context,
            kb_recall_override,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_portrait_id,
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_audience_portrait failed: %s", exc)
        return None


async def get_audience_portrait(portrait_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, audience_record_id::text, audience_run_id::text,
               matrix_run_id::text, sku_id,
               portrait_md, recall_meta, validation_warnings,
               extra_context, status, version, parent_portrait_id::text,
               model_provider, model, cost_estimate, created_at, updated_at
        FROM pipeline.audience_portraits
        WHERE id = $1::uuid
        """,
        portrait_id,
    )
    return dict(row) if row else None
```

- [ ] **Step 4: 重启容器 + 跑测试确认通过**

```bash
docker restart omni-knowledge-engine
# 等 10s 容器起来
docker exec omni-knowledge-engine pytest tests/test_portrait_lineage.py -v
```

Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/tests/test_portrait_lineage.py
git commit -m "feat(pipeline): save/get_audience_portrait + adopt 扩表 + scripts 挂 portrait_id"
```

---

### Task 3: step 3.5 prompt 文件（audience_portrait.{system,user}.md）

**Files:**
- Create: `services/knowledge-engine/config/prompts/audience_portrait.system.md`
- Create: `services/knowledge-engine/config/prompts/audience_portrait.user.md`

- [ ] **Step 1: 写 system prompt**

创建 `services/knowledge-engine/config/prompts/audience_portrait.system.md`，完整内容（方法论源自老板手搓的《产品人群画像匹配 V4.1》，裁剪产品化）：

```markdown
# 角色与唯一任务

你是 15 年消费者洞察专家（服务过尼尔森、凯度、阿里妈妈级别的洞察项目），现在为一家调味品厂做**单个人群的深度画像**。

**唯一任务**：针对老板从 step 3 人群匹配里选中的**这一个人群**，基于 KB 召回的真实资料，输出「生活状态画像 + 该人群专属卖点重构 + 情绪触点矩阵」。像纪录片导演一样描述这个人——让读者眼前浮现一个活生生的人，且每个判断都可溯源。

# 严格边界（任何一条违反 = 重写）

- ❌ 不写投放圈包标签 / DMP 勾选路径 / 预算 / ROI 预测 / 投放渠道建议（那是 step 4 的事）
- ❌ 不写完整视频脚本 / 分镜 / 标题（那是 step 3.6 的事；你只产出画像和情绪原料）
- ❌ 不分析其他人群、不做人群对比（只深挖选中的这一个）
- ❌ 不重写 KB 原文当成自己的发现（引用要标来源）
- ❌ 禁 AI 化套话：赋能 / 打通 / 闭环 / 抢占心智 / 触达矩阵 / 极致 / 匠心 / 一站式

# 可信度分级标注（铁律——本工具存在的根基）

老板的核心要求：**生活状态不能臆想、不能编造，必须贴合真实**。KB 里是数据/标签/内容偏好，"他周三晚上几点在干嘛"这种细节必然要推演——推演不是问题，**不标记的推演才是问题**。

每个事实性陈述句，句尾必须带三选一标记：

1. `[KB:文档名]` —— KB 召回原文直接支撑（数据、标签、内容偏好、量级）
2. `🧠推演` —— 从 KB 锚点出发的合理推演，**必须写明从哪个锚点推的**。
   格式：`🧠 由 [KB:文档名]「原文要点」推演`。
   例：`晚 10 点后刷美食视频放松 🧠 由 [KB:赛博食客圈层]「深夜美食内容播放峰值」推演`
3. `⚠️推测` —— 没有 KB 锚点、纯行业常识的猜测（**全文 ≤5 处**，超了说明资料不够，老实写进第 4 部分信息缺口）

**配额硬约束**：
- 第 1 部分每个小节（1.1-1.5），`[KB:...]` 标记的句子占比 ≥50%
- `⚠️推测` 全文 ≤5 处
- 无标记的事实性陈述 = 违规

# 纪录片导演原则

- 具体到**能拍出来**的程度：不写"他注重健康"，写"他下单前会把配料表截图发家庭群问一句'这个行吗'"
- 真实感 > 理想化：普通人的生活有油渍、有将就、有口是心非
- 时间锚具体：周几 + 几点 + 在哪 + 手里干着什么
- 说人话，短句

# 输出结构（严格 5 部分）

## 第 0 部分 · 人群速写

150 字一段话：这是谁、KB 给的量级/属性、一句话生活底色。全部 `[KB:...]` 锚出。

## 第 1 部分 · 生活状态画像（核心）

### 1.1 身份与日常节奏
工作日 + 周末两条时间轴（从起床到睡前，6-10 个时间点），每个时间点一行：时间 + 在哪 + 干什么 + 此刻心态。刷手机/可被内容触达的窗口标 ⭐（最佳窗口标 ⭐⭐）。

### 1.2 生活场景库（≥6 个）
每个场景按此格式：
- **场景名**：[时间精确到周几+几点] + [地点精确到房间/位置] + [人物状态：情绪+身体+前因] + [正在发生的事，2-3 句]
- **可承载卖点**：矩阵 X.Y [卖点名]（引用上游卖点矩阵的节号）

### 1.3 内容消费与触媒（KB 最有料的小节，硬锚优先）
- 常驻平台 + 使用时段
- 爱看的内容形态/品类（什么会停下来看完、什么会划走）
- **算法信号原料**（给 step 3.6 用，全部标来源）：
  - 高频内容元素：这群人信息流里常出现的画面元素/场景/人物类型
  - 标签云/话题词：他们会搜、会点、会评论的词
  - BGM 风格偏好：他们爱看的内容通常配什么音乐

### 1.4 消费决策
怎么知道新产品 → 犹豫什么 → 什么触发下单；价格敏感度；谁影响他（家人/博主/评论区）。

### 1.5 情绪底色
在意什么、焦虑什么、**"心里一直有但不怎么说的东西"**（亏欠/心疼/逞强/我也没办法——这是 step 3.6 找"起伏"的原料）。

## 第 2 部分 · 该人群专属卖点重构

从上游卖点矩阵挑 **3-5 个对这群人最响的卖点**，每个输出：

- **原始卖点**：矩阵 X.Y [卖点名]
- **三层拆解**：功能层（它是什么）→ 利益层（他得到什么）→ 价值观层（他成为什么样的人）
- **匹配度**：🔥1-5（5=直击他最深的需求/焦虑，1=他无感），一句话理由（关联第 1 部分哪条生活状态）
- **对这群人说的那句话**：口语、≤20 字、**主语是人不是产品**（不说"这酱油零添加"，说"你爸也能吃这个"）

## 第 3 部分 · 情绪触点矩阵

- **正向触点 ≥4 个**：触点类型（渴望/恐惧/补偿/安心/归属/好奇…）｜触发场景（引用 1.2 场景库）｜内心独白（一句口语）｜对应卖点（第 2 部分哪条）
- **负向阻断点 ≥3 个**：阻断情绪｜典型内心独白｜**化解话术**（一句能拍进视频的话，不是营销话术）
- **最佳触达时间窗**：引用 1.1 时间轴的 ⭐ 窗口，说明各窗口适合什么情绪基调的内容

## 第 4 部分 · 信息缺口

- KB 哪块没料（哪个小节推演占比高）
- 本文 ⚠️推测 用了几处、分别在哪
- 建议补什么资料（具体到资料类型，如"该圈层的小红书决策路径报告"）

# 输出前强制自检（任一不过必须重写对应部分）

- [ ] 每个事实性陈述句都有 [KB:]/🧠/⚠️ 标记之一
- [ ] 第 1 部分每小节 [KB:] 占比 ≥50%；⚠️ 全文 ≤5 处
- [ ] 每处 🧠推演 都写了从哪个 KB 锚点推的
- [ ] 时间轴/场景与该人群 KB 属性（年龄/城市/消费力）不矛盾
- [ ] 生活细节具体到"能拍出来"（有时间锚、地点锚、动作）
- [ ] 第 2 部分每条"对这群人说的那句话"主语是人不是产品
- [ ] 没写圈包/预算/渠道/完整脚本
- [ ] 没有 AI 化套话
```

- [ ] **Step 2: 写 user prompt**

创建 `services/knowledge-engine/config/prompts/audience_portrait.user.md`，完整内容：

```markdown
## ① 产品基本信息

{sku_md}

## ② 卖点矩阵（step 2 输出，第 2 部分卖点重构从这里挑）

{matrix_md}

## ③ 老板选中的人群（step 3 输出，本次唯一深挖对象）

- 人群名：{audience_name}
- KB 来源：{audience_kb_doc}
- 圈层标签：{audience_layer_tags}
- step 3 匹配理由：
{audience_match_reasons_md}
- step 3 的 KB 原文段：
> {audience_kb_chunk}

## ④ 四路定向 KB 召回（本圈层深挖 / 生活维度扫描 / 八大情绪交叉 / 卖点反打）

> 这是 tool 内部对**这一个人群**做的定向二次召回（跟 step 3 的广撒网相反，这轮是深挖）。
> 写画像时**只能用这里 + ③ 的 KB 原文当 [KB:] 锚点**；这里没有的，要么 🧠推演（写明锚点）要么 ⚠️推测（≤5 处）要么进第 4 部分缺口。

{kb_recall}

## ⑤ 额外要求

{extra_context}

---

请按 system prompt「输出结构」严格输出 5 部分（第 0 速写 / 第 1 生活状态画像 5 小节 / 第 2 卖点重构 3-5 条 / 第 3 情绪触点矩阵 / 第 4 信息缺口）。

输出前按「输出前强制自检」逐条核对，不达标必须重写。
```

- [ ] **Step 3: 验证模板可渲染（占位符齐全）**

```bash
docker exec omni-knowledge-engine python -c "
from app.mcp import prompts
s = prompts.load('audience_portrait.system')
u = prompts.render('audience_portrait.user', sku_md='x', matrix_md='x', audience_name='x', audience_kb_doc='x', audience_layer_tags='x', audience_match_reasons_md='x', audience_kb_chunk='x', kb_recall='x', extra_context='x')
print('system', len(s), 'user', len(u))
"
```

Expected: 打印两个长度，无 KeyError/FileNotFoundError。

- [ ] **Step 4: Commit**

```bash
git add services/knowledge-engine/config/prompts/audience_portrait.system.md services/knowledge-engine/config/prompts/audience_portrait.user.md
git commit -m "feat(prompts): step 3.5 人群画像提示词（V4.1 产品化：可信度分级+卖点重构+情绪触点）"
```

---

### Task 4: step 3.5 tool `generate_audience_portrait`（TDD）

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/portrait_brief.py`
- Test: `services/knowledge-engine/tests/test_portrait_brief_tools.py`

- [ ] **Step 1: 写失败测试**

创建 `services/knowledge-engine/tests/test_portrait_brief_tools.py`：

```python
"""step 3.5/3.6 tool 测试：错误路径 + 确定性校验函数（不调 LLM）。"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool
from app.mcp.tools.portrait_brief import (
    generate_audience_portrait,
    generate_director_brief,
    _validate_portrait_markers,
    _validate_brief,
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_portrait_record_not_found():
    out = await generate_audience_portrait(
        audience_record_id="00000000-0000-0000-0000-000000000000"
    )
    assert out["ok"] is False
    assert "audience_record" in out["error"]


@pytest.mark.asyncio
async def test_brief_portrait_not_found():
    out = await generate_director_brief(
        portrait_id="00000000-0000-0000-0000-000000000000"
    )
    assert out["ok"] is False
    assert "portrait" in out["error"]


def test_validate_portrait_markers_quota():
    # 1 处 KB、1 处推演、6 处推测 → 触发 ⚠️ 超额 + KB 占比不足两条警告
    md = (
        "## 第 1 部分\n"
        "他早上喝粥 [KB:测试文档]。\n"
        "他中午吃面 🧠 由 [KB:测试文档]「面食偏好」推演。\n"
        + "他可能喜欢爬山 ⚠️推测。\n" * 6
        + "## 第 2 部分\n"
    )
    warnings = _validate_portrait_markers(md)
    assert any("⚠️" in w or "推测" in w for w in warnings)


def test_validate_portrait_markers_clean():
    md = (
        "## 第 1 部分\n"
        "他早上喝粥 [KB:测试文档]。\n"
        "他中午吃面 [KB:测试文档]。\n"
        "他晚上散步 🧠 由 [KB:测试文档]「夜间活跃」推演。\n"
        "## 第 2 部分\n"
    )
    assert _validate_portrait_markers(md) == []


def test_validate_brief_missing_sections_and_banned():
    md = "# 随便写的\n家人们这个好物绝绝子，赶紧下单！"
    warnings = _validate_brief(md, include_ai_mapping=True)
    assert any("第 0 部分" in w for w in warnings)   # 缺人群描述节
    assert any("第 5 部分" in w for w in warnings)   # 要 AI 映射但缺
    assert any("禁用词" in w for w in warnings)      # 命中禁用词


def test_validate_brief_clean():
    md = (
        "## 第 0 部分 · 这条视频拍给谁\nx\n"
        "## 第 1 部分 · 今天拍什么\nx\n"
        "## 第 2 部分 · 分段拍摄备忘\nx\n"
        "## 第 3 部分 · 算法信号三向量\nx\n"
        "## 第 4 部分 · 发的时候\nx\n"
        "## 自检结果\nx\n"
    )
    assert _validate_brief(md, include_ai_mapping=False) == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
docker exec omni-knowledge-engine pytest tests/test_portrait_brief_tools.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.mcp.tools.portrait_brief'`。

- [ ] **Step 3: 创建模块 + 实现 step 3.5 tool 与两个校验函数**

创建 `services/knowledge-engine/app/mcp/tools/portrait_brief.py`（本 Task 先写到 generate_audience_portrait 为止；generate_director_brief 在 Task 6 加，但 Step 1 测试 import 了它——所以本步先放一个最小占位实现，Task 6 替换为完整版）：

```python
"""sku-pipeline step 3.5 + 3.6：人群生活状态画像 + 编导 brief。

- generate_audience_portrait：老板选中 audience_record → 四路定向 KB 召回 →
  生活状态画像（可信度分级标注）+ 专属卖点重构 + 情绪触点矩阵 → 落 pipeline.audience_portraits
- generate_director_brief：画像 → V7.2 产品化编导备忘录（一件事/起伏≠反转/卖点种情绪/
  算法信号三向量/可选 AI 出片映射）→ 落 pipeline.scripts kind='director_brief'

设计 spec：docs/superpowers/specs/2026-06-11-audience-portrait-director-brief-design.md
"""
from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

from app.database import get_pool
from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.mcp.tools.media import (
    AUDIENCE_KB_ID,
    _format_kb_recall,
    _multi_query_recall,
)
from app.services import pipeline_lineage, rag_chain
from app.services.ai_hub_client import AIHubClient

# ============ step 3.5 检索 ============

# 路②固定生活维度后缀（spec §4.2）
_LIFE_DIMENSIONS = [
    "日常作息", "内容偏好", "触媒习惯", "消费决策", "价格敏感",
    "家庭角色", "节点场景", "兴趣爱好", "标签云", "热点内容", "BGM 偏好",
]
_EMOTION_CROWDS = [
    "一触即疯", "怀旧梦核", "血脉觉醒", "打破诡谲",
    "多巴胺爽感", "唤醒自愈", "重塑内核", "超绝松弛感",
]


async def _portrait_recall(record: dict, matrix_md: str) -> tuple[str, dict]:
    """四路定向召回（spec §4.2 表），返回 (kb_recall_md, recall_meta)。"""
    name = record.get("name") or ""
    kb_doc = record.get("kb_doc") or ""
    layer_tags = record.get("layer_tags") or []

    # 路①：本圈层深挖 —— 直打来源文档，context_window 拉邻块（≤30）
    route1_queries = [q for q in {f"{kb_doc} {name}".strip(), name} if q]
    route1: list[dict] = []
    for q in route1_queries:
        try:
            hits = await rag_chain.retrieve_multi_kb(
                q, [AUDIENCE_KB_ID],
                top_k_per_kb=15, total_limit=15,
                rerank=True, context_window=True,
            )
            for h in hits:
                h.setdefault("query_origin", q)
            route1.extend(hits)
        except Exception:
            logger.exception("portrait route1 recall failed: %s", q)
    # 去重 + 截断
    seen: set = set()
    route1_dedup = []
    for h in route1:
        if h.get("id") in seen:
            continue
        seen.add(h.get("id"))
        route1_dedup.append(h)
    route1_dedup = route1_dedup[:30]

    # 路②：生活维度扫描（≤24）
    route2_queries = [f"{name} {d}" for d in _LIFE_DIMENSIONS]
    for tag in layer_tags[:2]:
        route2_queries += [f"{tag} 内容偏好", f"{tag} 消费决策"]
    route2 = await _multi_query_recall(
        queries=route2_queries, kb_id=AUDIENCE_KB_ID,
        top_k_per_query=2, max_chunks=24,
    )

    # 路③：八大情绪交叉（≤12）
    route3_queries = [f"{name} {e}" for e in _EMOTION_CROWDS[:4]] + [
        "8大情绪人群 " + name, "情绪人群 画像 " + (layer_tags[0] if layer_tags else "食饮"),
    ]
    route3 = await _multi_query_recall(
        queries=route3_queries, kb_id=AUDIENCE_KB_ID,
        top_k_per_query=2, max_chunks=12,
    )

    # 路④：卖点反打 —— 从 matrix 抓 USP/推荐主打行做 query（≤12）
    usp_lines = re.findall(r"(?:USP|推荐主打)[^\n]{0,60}", matrix_md or "")[:4]
    route4_queries = [re.sub(r"[#*`\[\]【】]", " ", l).strip() for l in usp_lines if l.strip()]
    route4 = (
        await _multi_query_recall(
            queries=route4_queries, kb_id=AUDIENCE_KB_ID,
            top_k_per_query=2, max_chunks=12,
        )
        if route4_queries else []
    )

    # 合并去重（路① 优先保留）
    merged: list[dict] = []
    seen2: set = set()
    for h in route1_dedup + route2 + route3 + route4:
        if h.get("id") in seen2:
            continue
        seen2.add(h.get("id"))
        merged.append(h)

    meta = {
        "mode": "four_route",
        "routes": {
            "circle_deep": len(route1_dedup),
            "life_dims": len(route2),
            "emotion_cross": len(route3),
            "usp_resonance": len(route4),
        },
        "queries": route1_queries + route2_queries + route3_queries + route4_queries,
        "chunk_count": len(merged),
    }
    return _format_kb_recall(merged), meta


# ============ 确定性校验 ============

_KB_MARK_RE = re.compile(r"\[KB[:：][^\]]+\]")
_INFER_MARK_RE = re.compile(r"🧠")
_SPECULATE_MARK_RE = re.compile(r"⚠️?推测|⚠推测")


def _validate_portrait_markers(portrait_md: str) -> list[str]:
    """标记配额闸（spec §4.2 防臆想三道闸之二）。返回警告列表（空 = 过）。"""
    warnings: list[str] = []
    # 只查第 1 部分（生活状态画像）区段
    m = re.search(r"第\s*1\s*部分(.*?)(?=第\s*2\s*部分|$)", portrait_md, re.S)
    section1 = m.group(1) if m else portrait_md
    kb_n = len(_KB_MARK_RE.findall(section1))
    infer_n = len(_INFER_MARK_RE.findall(section1))
    spec_total = len(_SPECULATE_MARK_RE.findall(portrait_md))
    marked = kb_n + infer_n + len(_SPECULATE_MARK_RE.findall(section1))
    if marked == 0:
        warnings.append("⚠ 第 1 部分没有任何可信度标记（[KB:]/🧠/⚠️），违反防臆想铁律，建议重跑")
    elif kb_n / marked < 0.5:
        warnings.append(
            f"⚠ 第 1 部分 [KB:] 占比 {kb_n}/{marked} 不足 50%——检索没召回到足够的料，"
            "建议补圈层 KB 后重跑（不要硬用）"
        )
    if spec_total > 5:
        warnings.append(f"⚠ 全文 ⚠️推测 共 {spec_total} 处（>5），该人群 KB 料薄，建议补料后重跑")
    return warnings


# V7.2 禁用词 8 类（确定性扫描；标题/正文/置顶都查）
_BANNED_WORDS = [
    "品质生活", "匠心", "臻选", "焕新", "赋能", "甄选", "尊享",
    "家人们", "宝子们", "绝绝子", "YYDS", "闭眼入",
    "不买后悔", "手慢无", "赶紧下单", "你值得拥有", "无限回购",
    "治疗", "治愈", "预防疾病", "抗癌", "排毒", "杀菌", "消炎",
    "劣质", "有毒", "黑心", "致癌", "科技与狠活",
    "全网最低", "双击666", "点赞关注不迷路", "评论区扣1",
]
_BRIEF_REQUIRED_SECTIONS = ["第 0 部分", "第 1 部分", "第 2 部分", "第 3 部分", "第 4 部分"]


def _validate_brief(brief_md: str, *, include_ai_mapping: bool) -> list[str]:
    """brief 结构 + 禁用词确定性校验。返回警告列表（空 = 过）。"""
    warnings: list[str] = []
    for sec in _BRIEF_REQUIRED_SECTIONS:
        if sec not in brief_md:
            warnings.append(f"⚠ 缺「{sec}」——结构不完整，建议重跑")
    if include_ai_mapping and "第 5 部分" not in brief_md:
        warnings.append("⚠ include_ai_mapping=True 但缺「第 5 部分」AI 出片映射，建议重跑")
    if "自检" not in brief_md:
        warnings.append("⚠ 缺尾部自检段——可能输出被截断，建议重跑或调低篇幅")
    hits = [w for w in _BANNED_WORDS if w in brief_md]
    if hits:
        warnings.append(f"⚠ 命中禁用词：{hits}——人工复核或重跑")
    return warnings


# ============ step 3.5 tool ============

@tool_with_audit(mcp, require_approval=False)
async def generate_audience_portrait(
    audience_record_id: str,
    extra_context: str | None = None,
    kb_recall_override: str | None = None,
) -> dict:
    """生成人群生活状态画像（sku-pipeline step 3.5）。

    输入老板从 step 3 选中的 audience_record，对该人群做四路定向 KB 二次召回
    （本圈层深挖 / 生活维度扫描 / 八大情绪交叉 / 卖点反打），输出 5 部分画像：

    - 第 0 部分：人群速写
    - 第 1 部分：生活状态画像（时间轴/场景库/触媒+算法信号原料/消费决策/情绪底色）
    - 第 2 部分：该人群专属卖点重构（三层拆解 + 对这群人说的那句话）
    - 第 3 部分：情绪触点矩阵（正向/负向阻断+化解/触达时间窗）
    - 第 4 部分：信息缺口

    防臆想铁律：每句标 [KB:文档名] / 🧠推演 / ⚠️推测；配额闸超标会在
    validation_warnings 里提示补 KB 重跑。

    返回后自动落库 pipeline.audience_portraits（draft，多版本不覆盖）。

    Args:
        audience_record_id: step 3 落库的人群 record id（老板选中的那个）
        extra_context: 一次性临时要求（如"重点写她周末的状态"）
        kb_recall_override: 显式覆盖 KB 召回（老板手贴 chunks 时用）

    Returns:
        {ok, result: {portrait_md, portrait_id, sku_id, audience_record_id,
         recall_meta, validation_warnings}, trace, next_step_hint(generate_director_brief)}
    """
    record = await pipeline_lineage.get_audience_record(audience_record_id)
    if not record:
        return {
            "ok": False,
            "error": f"audience_record 未找到: {audience_record_id}",
            "hint": "先跑 generate_audience_match（step 3），或调 pipeline_list_audience_records 看现有 record",
        }
    sku_id = record.get("sku_id")
    matrix_run_id = record.get("matrix_run_id")
    audience_run_id = record.get("audience_run_id")

    matrix_run = await pipeline_lineage.get_matrix_run(matrix_run_id) if matrix_run_id else None
    matrix_md = (matrix_run or {}).get("matrix_md") or ""
    if not matrix_md:
        return {
            "ok": False,
            "error": f"该 record 的上游卖点矩阵缺失（matrix_run_id={matrix_run_id}）",
            "hint": "链路断了：先跑 step 2 generate_selling_points_matrix",
        }

    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications, "
        "owner_selling_points, platform_status, growth_class "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    sku_md = (
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类，调味品）'}\n"
        f"- 规格：{sku['specifications'] or '（无）'}\n"
    ) if sku else f"- sku_id：{sku_id}（mvp_sku 查无，仅按矩阵推进）\n"

    # === 检索 ===
    if kb_recall_override and kb_recall_override.strip():
        kb_recall_md = kb_recall_override.strip()
        recall_meta = {"mode": "override", "queries": [], "chunk_count": 0}
    else:
        kb_recall_md, recall_meta = await _portrait_recall(record, matrix_md)

    # === LLM ===
    reasons = record.get("match_reasons") or []
    reasons_md = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(reasons)) or "  （无）"
    sys_msg = prompts.load("audience_portrait.system")
    user_msg = prompts.render(
        "audience_portrait.user",
        sku_md=sku_md,
        matrix_md=matrix_md.strip(),
        audience_name=record.get("name") or "（未命名）",
        audience_kb_doc=record.get("kb_doc") or "（无）",
        audience_layer_tags=" / ".join(record.get("layer_tags") or []) or "（无）",
        audience_match_reasons_md=reasons_md,
        audience_kb_chunk=(record.get("kb_chunk_text") or "（无）").strip(),
        kb_recall=kb_recall_md,
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_audience_portrait")
    client = AIHubClient(timeout=300.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3.1-pro-preview"),
        temperature=model_cfg.get("temperature", 0.4),
        max_tokens=model_cfg.get("max_tokens", 10000),
        enforce_human_voice=True,
    )
    portrait_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    validation_warnings = _validate_portrait_markers(portrait_md)

    portrait_id = await pipeline_lineage.save_audience_portrait(
        audience_record_id=audience_record_id,
        audience_run_id=audience_run_id,
        matrix_run_id=matrix_run_id,
        sku_id=sku_id,
        portrait_md=portrait_md,
        recall_meta=recall_meta,
        validation_warnings=validation_warnings,
        extra_context=extra_context,
        kb_recall_override=kb_recall_override,
        model_provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3.1-pro-preview"),
        final_prompt=final_prompt,
        cost_estimate="1 quota call (~6-10k tokens) + 四路定向 KB 召回",
    )

    result = {
        "ok": True,
        "result": {
            "portrait_md": portrait_md,
            "portrait_id": portrait_id,
            "sku_id": sku_id,
            "audience_record_id": audience_record_id,
            "audience_name": record.get("name"),
            "recall_meta": recall_meta,
            "validation_warnings": validation_warnings,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3.1-pro-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.4),
                "max_tokens": model_cfg.get("max_tokens", 10000),
                "audience_kb_id": AUDIENCE_KB_ID,
                "queries_used": len(recall_meta.get("queries") or []),
                "chunks_recalled": recall_meta.get("chunk_count"),
                "portrait_id": portrait_id,
            },
            cost_estimate="1 quota call (~6-10k tokens) + 四路定向 KB 召回",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_director_brief",
        suggested_args={"portrait_id": portrait_id},
        human_text="step 3.6 编导 brief — 老板审完画像（生活状态贴不贴真实、卖点重构对不对味）后，"
                   "调 generate_director_brief 出编导备忘录（可传 idea_seed='想拍的事'）",
    )


# ============ step 3.6 tool（Task 6 实现完整版，此处占位保证 import 不挂）============

@tool_with_audit(mcp, require_approval=False)
async def generate_director_brief(
    portrait_id: str,
    idea_seed: str | None = None,
    include_ai_mapping: bool = True,
    extra_context: str | None = None,
    num_variants: int = 1,
) -> dict:
    """（Task 6 替换为完整实现）"""
    portrait = await pipeline_lineage.get_audience_portrait(portrait_id)
    if not portrait:
        return {
            "ok": False,
            "error": f"portrait 未找到: {portrait_id}",
            "hint": "先跑 generate_audience_portrait（step 3.5）",
        }
    return {"ok": False, "error": "not_implemented_yet", "hint": "Task 6 实现"}
```

- [ ] **Step 4: 跑测试**

```bash
docker restart omni-knowledge-engine
docker exec omni-knowledge-engine pytest tests/test_portrait_brief_tools.py -v
```

Expected: 6 passed（两个 not-found 路径 + 4 个校验函数用例）。

- [ ] **Step 5: Commit**

```bash
git add services/knowledge-engine/app/mcp/tools/portrait_brief.py services/knowledge-engine/tests/test_portrait_brief_tools.py
git commit -m "feat(mcp): step 3.5 generate_audience_portrait（四路定向召回+标记配额闸+血缘落库）"
```

---

### Task 5: step 3.6 prompt 文件（director_brief.{system,user}.md）

**Files:**
- Create: `services/knowledge-engine/config/prompts/director_brief.system.md`
- Create: `services/knowledge-engine/config/prompts/director_brief.user.md`

- [ ] **Step 1: 写 system prompt**

创建 `services/knowledge-engine/config/prompts/director_brief.system.md`，完整内容（方法论源自老板手搓的《抖音种草视频生成器 V7.2》，产品化 + 新增三向量/AI 映射）：

```markdown
# 角色

你给一家调味品厂的**真人编导**写「今天拍什么」备忘录。

你不是脚本生成器。你的参照物**不是**电视广告、微电影、小红书、B 站 vlog——是**抖音上播放量百万的、普通人拍的生活视频**。编导拿到你的备忘录，今天就能拍。

# 火的生活视频四大特征（你的全部输出都要长这样）

1. **一件事原则**：不是完整故事，不需要起承转合。生活里的一件事：我妈收到快递、今天下班做顿饭、跟爸视频被气到。观众点进来直接看这件事正在发生。
2. **对话是断的、碎的、真实的**：说一半被打断、同时干着别的随口接一句、嘟囔被录进去、隔着墙喊话。没人面对面完整说一段话。
3. **镜头像"碰巧录到的"**：手机架在某处画面固定人进进出出；或拿着手机跟拍有点晃；角度可以很奇怪；经常有画外音。
4. **文字和声音都很"粗"**：字幕是随便加的白字黄字；BGM 随便选的热门歌；环境声是全部声音——炒菜声、电视声、门响。

# 工作流（六步，按顺序想）

1. **看看这群人的日子**：读画像第 1 部分，想象一个具体人的一天。从很小很具体的场景找素材。感受画像 1.5 里"心里一直有但不怎么说的东西"。
2. **想一件事**：从画像场景库挑一件事拍（老板给了 idea_seed 就围绕它）。framework >3 件事 → 砍到 2 件以内。
3. **找自然的"起伏"**（核心）：**起伏≠反转**。起伏是"以为 A 结果 B 的小偏离"：
   - 要：嘴上嘟囔"乱花钱"，做饭时顺手就用上了｜闺女问"好吃吗"，老妈没直接回答说了句不相关的｜做完饭那瓶酱油不知不觉被挪到最顺手的位置
   - 不要：激烈抱怨→尝一口→表情大变"天哪太好了"｜老妈含泪说"好吃谢谢闺女"｜把旧调料全扔了只留新的
   - **两次"偏"就够**：第一次可以大（好笑/无语），第二次要小、要安静（一个画面、一个动作，甚至什么都没说）。起伏从**人物关系和性格**来（嘴硬的妈 vs 默默做的爸），不从剧情来。
4. **想想大家怎么说话怎么做**（90% 真实感在这）：中国家庭说话特点——关心说成"念叨"、心疼说成"嫌弃"、感动说出来变成"怼"（"就这？"但转头就用上了）、很多感情不说靠做。说话时手不闲着、眼睛不一定看对方。
5. **把 1-2 个卖点"种"在情绪里**：用画像第 2 部分**重构后的那句话**（不是原始卖点）。卖点不是被"说"出来的，是观众在情绪高点自己"发现"的。三种嵌入方式：
   - **A 对话的情绪缝隙**：有情绪的对话间隙，某人随口带出一句——**主语是人不是产品**（"你爸能吃这个"✓｜"这个酱油没加糖"✗）
   - **B 观众正在笑的画面**：好笑瞬间画面里恰好看到产品信息（包装文字停留两秒，做饭动作的自然节奏）
   - **C 结尾安静的画面**：最后几秒没人说话，产品自然在那儿，观众在"品味"不是"接收"
6. **产品放在哪**：产品=灶台上那把铲子。它在那儿，镜头偶尔扫到，没人专门看它一眼。这件事里产品放不进去 → 在备忘录里明说"建议换一件事"。

# 台词死规矩

1. 一句话 ≤15 字。家里人不说长句
2. 该打断就打断，该说一半就说一半
3. 语气词必须有："嗐""哎""嗯""行了""得了"
4. **没有人在家里跟家人"介绍"一个东西。永远不会。**
5. 感情越重话越少。最触动的瞬间可能是沉默
6. **一句话只带一件事**：一句台词里产品相关信息点 ≤1 个（卖点/价格/来源/成分各算一个）
7. **全片台词产品相关信息 ≤2 句**。其余卖点让包装、场景、动作自己说
8. 人不会复述刚听到的卖点：转述时只记"谁给的"（"闺女买的那个"），不记卖点

对照（要左边，不要右边）：
- "行了行了知道了" ｜ "我知道了妈妈，谢谢你的关心"
- （夹了口菜）"嗯。"（停了一下）"还行。" ｜ "这个味道真的很不错诶！"
- "你那个别用了，用这个"（没解释为什么） ｜ "这个是有机的没有添加剂对身体更好"
- 嘴里嘟囔"又乱花钱"，第二天做饭就用上了 ｜ "虽然一开始我不理解，但用了之后发现真的很好"

# 画面与产品死规矩

- 不追求好看，追求真实：灶台有油渍、桌上有杂物、人穿旧 T 恤睡裤棉拖
- 手机拍的特征：偶尔对焦不准、晃一下、手指挡镜头
- **不拍"新旧对比"**：不拍旧产品被扔/被替换+新产品摆上（平台判"贬低同类"风险）
- **必须有一个"跟产品完全无关的真实细节"**（火的关键）：老爸偷夹菜被拍手、冰箱上贴着孙子的奖状、"今天遛弯碰见老李了"——增真实感、给评论区供素材、反广告质疑
- 产品出现 ≥全片 1/3 处；镜头不为产品移过去；没人"展示"产品（拿起是因为要用）；品牌名台词不说（包装自己出现）；全片不给产品特写；产品出现前后节奏完全一样

# 算法信号三向量（第 3 部分专用规则）

抖音把内容分发给谁，靠它从视频里读出的信号（视觉识别/文本理解/BGM 归类）。你要把信号设计成显性交付物，编导有意识地埋：

- **画面向量**：必须入画的可识别视觉元素（场景/道具/人物类型/动作），每个元素标"对应该人群哪个内容偏好"——只能从画像 1.3 算法信号原料锚出，标 [KB:...] 或 🧠
- **文案向量**：标题/字幕/话题标签/评论引导词里的人群信号词——用这群人**自己会搜会说的词**（画像 1.3 标签云），不是营销词
- **音乐向量**：BGM 风格方向 + 2-3 个曲风候选，按人群年龄段/情绪基调（画像第 3 部分）。表面"随手选的热门歌"，实际选这群人信息流里正在火的那种
- **最高优先级：信号不破坏真实感**。凡要硬塞道具/硬改台词才能加的信号一律砍——完播和互动本身就是最强算法信号，内容假了三向量再准也白搭

# 禁用词（全文含标题/置顶，出现即违规）

- 广告味：品质生活/匠心/臻选/焕新/赋能/甄选/尊享/好物
- 假口语：家人们/宝子们/绝绝子/YYDS/闭眼入/天花板
- 卖货味：不买后悔/手慢无/赶紧下单/你值得拥有/无限回购
- 医疗违禁：治疗/治愈/预防疾病/降血糖血压/抗癌/排毒/杀菌/消炎
- 踩同行：劣质/有毒/黑心/致癌/科技与狠活
- 绝对词：最/第一/唯一/100%/全网最低
- 诱导：双击666/点赞关注不迷路/评论区扣1
- AI 味：在这个XX的时代/你是否曾经/不仅更是/值得一提的是

# 输出结构（严格按此顺序，标题原样）

## 第 0 部分 · 这条视频拍给谁

300-500 字人群描述：他是谁/量级/生活状态要点/爱看什么内容/情绪底色/为什么这个产品跟他有关。
**只许从输入的画像浓缩，不许新增画像里没有的事实。**

## 第 1 部分 · 今天拍什么

- 拍给谁看的：[一句大白话]
- 拍的是什么事：[一句话，**不出现产品名**，像跟朋友说"今天拍个我妈收快递嘟囔的那种"]
- 看完观众心里是什么感觉：[一两个词]
- 两次"偏"在哪：[第一次偏：…（好笑/无语/心酸）；第二次偏：…（安静地品）]
- 想种的卖点：[1-2 个，写画像第 2 部分**重构后的那句话** + 各藏在哪个瞬间（A/B/C 哪种嵌入）]
- 产品大概在什么地方出现：[简单说]

## 第 2 部分 · 分段拍摄备忘

每段格式：
```
### 第 X 段（大概 X 秒）
- 拍什么：[大白话]
- 手机放哪/谁拍：[大白话]
- 说了什么：[台词，遵守台词死规矩。没人说话写"安静"+环境声]
- 注意的事：[可选]
- 💭 刷到这里的人在想什么：[必须是生活情感，不是对产品的看法]
```

## 第 3 部分 · 算法信号三向量

- 画面向量：[元素清单，每条 → 对应内容偏好 + 来源标记]
- 文案向量：[信号词清单 + 用在哪（标题/字幕/话题）+ 来源标记]
- 音乐向量：[风格方向 + 2-3 曲风候选 + 来源标记]

## 第 4 部分 · 发的时候

- 标题（3 个候选，不提产品，套用文案向量信号词）
- 封面：[截哪个画面 + ≤8 字]
- 评论区置顶：[像博主自己说的碎碎念/自嘲/追问。**不放链接、不提价格、不罗列卖点**]

## 第 5 部分 · AI 出片映射（仅当任务要求包含时输出；不要求则整节跳过）

逐段输出（与第 2 部分的段一一对应）：
```
### 段 X 映射
- image_prompt（首帧 · 英文 · 100-180 字）：本段第 0 秒静止入帧，动作开始前的预备态。画面向量元素自然入画。
- last_frame_prompt（尾帧 · 英文 · 80-150 字）：本段最后 0.5 秒静止出帧，动作完成态。
- motion_prompt（运动 · 英文 · 60-160 字）：首帧→尾帧的可见视觉运动，带时间锚（0-2s.../2-3.5s...），每段至少 1 个动机性可见动作（伸手取物/转头≥10°/明显笑），不写情绪叙事意图。
```
全局视觉锚（一次，所有段共用）——**短视频真人感锚，禁电影锚**：
- 风格：Vertical 9:16 iPhone handheld video frame, natural indoor light, subtle handheld micro-shake, slightly off-center framing, ordinary natural skin texture, visible pores, no AI face smoothing, authentic lived-in appearance
- 禁：cinematic / Kodak Portra / 50mm / Rule of thirds / shallow DOF / 3D render
- 负向词：AI face, plastic skin, oversaturated, distorted hands, extra fingers, blurry text, watermark, brand logo text, cartoon rendering

## 自检结果（逐项打勾输出 ✓/✗，有 ✗ 必须先改再交付）

1. 去掉产品，这条视频还能发吗？还有人看吗？
2. 有没有"只有这群人才会会心一笑/心里一酸"的细节？
3. 两次"偏"是从人物真实反应来的，不是硬编的反转？
4. 有没有一个"跟产品完全无关但特别真实"的小细节？
5. 台词产品信息全片 ≤2 句、单句 ≤1 个信息点？
6. 带产品信息的台词，主语是"人"不是"产品"？
7. 没有"新旧对比"画面？
8. 没有人在"介绍"或"评价"产品？最后几秒没有广告收尾感？
9. 禁用词全文扫过（含标题/置顶）？
10. 三向量每条都有 [KB:...] 或 🧠 来源标记，没有拍脑袋编的话题标签？
11. 三向量没有破坏真实感（没硬塞道具/硬改台词）？
12. 第 0 部分没有画像之外的新事实？
```

- [ ] **Step 2: 写 user prompt**

创建 `services/knowledge-engine/config/prompts/director_brief.user.md`，完整内容：

```markdown
## ① 产品基本信息

{sku_md}

## ② 人群画像（step 3.5 输出 · 你的唯一事实来源）

> 第 0 部分人群描述只许从这里浓缩；卖点用第 2 部分"重构后的那句话"；
> 起伏从 1.5 情绪底色和场景库来；三向量从 1.3 算法信号原料和第 3 部分情绪触点来。

人群名：{audience_name}

{portrait_md}

## ③ 老板想拍的事（idea_seed）

{idea_seed}

（"（无）"= 你从画像 1.2 场景库自己挑**一件事**；给了就围绕它展开，但一件事原则不变）

## ④ AI 出片映射开关

{ai_mapping_directive}

## ⑤ 额外要求

{extra_context}

---

按 system prompt「输出结构」严格输出。先在心里走完六步工作流再动笔。
输出最后必须带「自检结果」12 项逐项打勾；有 ✗ 先改再交付。
```

- [ ] **Step 3: 验证模板可渲染**

```bash
docker exec omni-knowledge-engine python -c "
from app.mcp import prompts
s = prompts.load('director_brief.system')
u = prompts.render('director_brief.user', sku_md='x', audience_name='x', portrait_md='x', idea_seed='x', ai_mapping_directive='x', extra_context='x')
print('system', len(s), 'user', len(u))
"
```

Expected: 打印两个长度，无异常。注意：system 里有 ``` 代码块和 {} 字符——system 走 `prompts.load`（不 format），只有 user 走 render，user 里不能出现裸 `{`/`}`（上面内容已确认只有占位符）。

- [ ] **Step 4: Commit**

```bash
git add services/knowledge-engine/config/prompts/director_brief.system.md services/knowledge-engine/config/prompts/director_brief.user.md
git commit -m "feat(prompts): step 3.6 编导 brief 提示词（V7.2 产品化：起伏≠反转+卖点种情绪+三向量+AI 映射）"
```

---

### Task 6: step 3.6 tool `generate_director_brief` 完整实现

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/portrait_brief.py`（替换 Task 4 的占位实现）

- [ ] **Step 1: 替换占位实现为完整版**

把 Task 4 写的 `generate_director_brief` 占位函数整体替换为：

```python
@tool_with_audit(mcp, require_approval=False)
async def generate_director_brief(
    portrait_id: str,
    idea_seed: str | None = None,
    include_ai_mapping: bool = True,
    extra_context: str | None = None,
    num_variants: int = 1,
) -> dict:
    """生成编导备忘录（sku-pipeline step 3.6）。

    输入 step 3.5 的人群画像，输出 V7.2 风格「今天拍什么」备忘录（真人编导直接能拍）：
    第 0 人群描述 / 第 1 今天拍什么（一件事+两次偏+卖点藏哪）/ 第 2 分段拍摄备忘 /
    第 3 算法信号三向量（画面/文案/音乐，让抖音算法把内容映射对人群）/ 第 4 发的时候 /
    第 5 AI 出片映射（可关；格式对齐 step 6/7 新链输入）/ 尾部 12 项自检。

    落库 pipeline.scripts（kind='director_brief'，挂 portrait_id 全血缘，多版本不覆盖）。

    Args:
        portrait_id: step 3.5 落库的画像 id
        idea_seed: 可选"想拍的事"（如"闺女给妈寄酱油"）；不给则 LLM 从画像场景库自选一件事
        include_ai_mapping: 默认 True 带第 5 部分 AI 出片映射；False 省 token
        extra_context: 一次性临时要求
        num_variants: 1-3 个创意方案并行（temperature 递增 +0.1）

    Returns:
        {ok, result: {variants:[{script_id, brief_md, variant_label, validation_warnings}],
         sku_id, portrait_id}, trace, next_step_hint}
    """
    portrait = await pipeline_lineage.get_audience_portrait(portrait_id)
    if not portrait:
        return {
            "ok": False,
            "error": f"portrait 未找到: {portrait_id}",
            "hint": "先跑 generate_audience_portrait（step 3.5），或查 pipeline.audience_portraits",
        }
    sku_id = portrait.get("sku_id")
    record = await pipeline_lineage.get_audience_record(portrait["audience_record_id"])
    audience_name = (record or {}).get("name") or "（未命名人群）"

    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, specifications FROM mvp_sku WHERE id = $1", sku_id
    )
    sku_md = (
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类，调味品）'}\n"
        f"- 规格：{sku['specifications'] or '（无）'}\n"
    ) if sku else f"- sku_id：{sku_id}\n"

    ai_directive = (
        "本次任务**要求输出第 5 部分 AI 出片映射**（逐段 image/last_frame/motion prompt + 全局真人感锚）。"
        if include_ai_mapping
        else "本次任务**不要输出第 5 部分**（整节跳过，自检第 5 部分相关项写 N/A）。"
    )

    sys_msg = prompts.load("director_brief.system")
    user_msg = prompts.render(
        "director_brief.user",
        sku_md=sku_md,
        audience_name=audience_name,
        portrait_md=(portrait.get("portrait_md") or "").strip(),
        idea_seed=idea_seed.strip() if idea_seed else "（无）",
        ai_mapping_directive=ai_directive,
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_director_brief")
    _n = max(1, min(3, int(num_variants or 1)))
    _base_temp = float(model_cfg.get("temperature", 0.7))
    _provider = model_cfg.get("provider", "gemini")
    _model = model_cfg.get("model", "gemini-3.1-pro-preview")
    _max_tokens = model_cfg.get("max_tokens", 12000)

    async def _call_one(variant_idx: int) -> dict:
        temp = round(_base_temp + variant_idx * 0.1, 2)
        _client = AIHubClient(timeout=300.0)
        _resp = await _client.chat(
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            provider=_provider,
            model=_model,
            temperature=temp,
            max_tokens=_max_tokens,
            enforce_human_voice=True,
        )
        md = (
            ((_resp.get("choices") or [{}])[0].get("message") or {}).get("content")
            or _resp.get("text")
            or _resp.get("content")
            or ""
        ).strip()
        warnings = _validate_brief(md, include_ai_mapping=include_ai_mapping)
        sid = await pipeline_lineage.save_creative_pack(
            sku_id=sku_id,
            kind="director_brief",
            script_md=md,
            audience_record_id=portrait.get("audience_record_id"),
            audience_run_id=portrait.get("audience_run_id"),
            matrix_run_id=portrait.get("matrix_run_id"),
            portrait_id=portrait_id,
            extra_context=extra_context,
            model_provider=_provider,
            model=_model,
            final_prompt=final_prompt,
            cost_estimate=f"1 quota call (~6-12k tokens, temp={temp})",
        )
        label = chr(ord("A") + variant_idx)
        return {
            "script_id": sid,
            "brief_md": md,
            "variant_label": f"方案 {label}",
            "validation_warnings": warnings,
        }

    raw_variants = await asyncio.gather(*[_call_one(i) for i in range(_n)])
    variants = list(raw_variants)

    result = {
        "ok": True,
        "result": {
            "variants": variants,
            "sku_id": sku_id,
            "portrait_id": portrait_id,
            "audience_name": audience_name,
            "include_ai_mapping": include_ai_mapping,
        },
        "trace": build_trace(
            provider=_provider,
            model=_model,
            prompt=final_prompt,
            params={
                "temperature": _base_temp,
                "max_tokens": _max_tokens,
                "num_variants": _n,
                "include_ai_mapping": include_ai_mapping,
                "idea_seed": idea_seed,
            },
            cost_estimate=f"{_n} quota call(s) (~6-12k tokens each)",
        ),
    }
    if include_ai_mapping:
        return attach_next_step(
            result,
            suggested_tool="generate_storyboard_images",
            suggested_args={"sku_id": sku_id},
            human_text="老板审完 brief：真人拍 → 直接发编导；AI 拍 → 把第 5 部分各段 image_prompt "
                       "喂 generate_storyboard_images（step 6 新链，挂血缘），再 generate_video_segments（step 7）",
        )
    return result
```

- [ ] **Step 2: 重启 + 回归测试**

```bash
docker restart omni-knowledge-engine
docker exec omni-knowledge-engine pytest tests/test_portrait_brief_tools.py tests/test_portrait_lineage.py -v
```

Expected: 全部 passed（brief not-found 用例现在走的是完整实现的同一条错误路径）。

- [ ] **Step 3: Commit**

```bash
git add services/knowledge-engine/app/mcp/tools/portrait_brief.py
git commit -m "feat(mcp): step 3.6 generate_director_brief（V7.2 备忘录+三向量+AI 映射+多方案并行）"
```

---

### Task 7: 注册 + doctor 78→80 + step 3 hint 分流

**Files:**
- Modify: `services/knowledge-engine/app/mcp/server.py`
- Modify: `services/knowledge-engine/app/mcp/doctor.py`
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`（generate_audience_match 的 next_step_hint）

- [ ] **Step 1: server.py 注册模块**

在 `app/mcp/server.py` 的 import 区（`yuntu_taxonomy` 那行之后）加：

```python
from app.mcp.tools import portrait_brief as _portrait_brief  # noqa: E402, F401  # 2026-06-11 step 3.5/3.6 人群画像 + 编导 brief
```

- [ ] **Step 2: doctor wanted 集 +2**

在 `app/mcp/doctor.py` 的 `_wanted_tools()` 集合尾部（`"query_yuntu_taxonomy",` 之后）加：

```python
            # 2026-06-11 sku-pipeline step 3.5/3.6：人群生活状态画像（KB 锚+可信度分级）+
            # 编导 brief（V7.2 备忘录+算法信号三向量+AI 出片映射，真人拍/AI 拍两用）
            "generate_audience_portrait", "generate_director_brief",
```

- [ ] **Step 3: step 3 的 next_step_hint 分流**

在 `app/mcp/tools/media.py` 的 `generate_audience_match` 尾部，把 `attach_next_step(...)` 调用里的 `human_text` 改为（其余参数不动）：

```python
        human_text="老板从 records 选 1 个人群后分流：投放圈包 → generate_audience_pack（step 4）；"
                   "内容 brief → generate_audience_portrait（step 3.5 画像）再 generate_director_brief（step 3.6）",
```

- [ ] **Step 4: 重启 + doctor 自检**

```bash
docker restart omni-knowledge-engine
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected: 输出含 `all 80 ok`。若 missing → 检查 server.py import 行；若 extra → 检查 doctor 名字拼写。

- [ ] **Step 5: Commit**

```bash
git add services/knowledge-engine/app/mcp/server.py services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/app/mcp/tools/media.py
git commit -m "feat(mcp): 注册 portrait_brief 模块，doctor 78→80，step 3 hint 分流圈包/内容链"
```

---

### Task 8: step 2 prompt 打磨（4 处定点编辑）

**Files:**
- Modify: `services/knowledge-engine/config/prompts/selling_points_matrix.system.md`

prompt 是 mtime 热加载，本任务**不需要重启容器**。用 Edit 工具按以下锚点做 4 处编辑（锚点原文已核对，2026-06-11 摘自该文件）：

- [ ] **Step 1: 编辑① 显性卖点加三层拆解+买点（1.1 节）**

找到 1.1 节字段清单中的这两行：

```
   - 核心关键词：[关键词1], [关键词2], [关键词3], [关键词4], [关键词5]
   - 匹配场景（**7 要素微剧本，不是一句话**）：
```

在两行**之间**插入：

```
   - 三层拆解：功能层（它是什么）→ 利益层（用户得到什么）→ 价值观层（用户成为什么样的人）——一行写完，如"天然米糀发酵 → 口感柔和/配料表干净 → 对家人健康负责"
   - 买点（用户买它的真实理由）：从"我有什么"翻成"他为什么掏钱"，一句口语（如"给娃拌饭不用再挑添加剂"）
```

- [ ] **Step 2: 编辑② 隐性卖点加同样两行（1.2 节）**

1.2 节字段清单里同样的两行之间（`   - 核心关键词：...` 与 `   - 匹配场景（**7 要素微剧本，不是一句话**）：` ——注意 1.2 的匹配场景行内容与 1.1 相同，Edit 时带上 1.2 节特有的上一行 `   - 与复购的关联性：强/中/弱` 一起锚定唯一性），插入与编辑①相同的两行（三层拆解 + 买点）。

- [ ] **Step 3: 编辑③ USP 三轴评分 + 竞品反证加狠（1.3 节）**

找到：

```
- **竞品反证检查**：罗列 2-3 个主要竞品是否也能讲同样的话。如果能，这条 USP 不成立，划掉。
- **最终结论**：成立 / 不成立 / 需要补证据
```

替换为：

```
- **竞品反证检查**：必须点名 ≥2 个具体竞品（如千禾/海天/欣和/李锦记）逐个判断"它能不能讲同样的话"。有竞品调研数据（competitor_search/competitor_decompose 产出）优先引用；没有就明写"搜证缺口：未做竞品实证，结论按品类常识判断"。竞品能讲 → 这条 USP 不成立，划掉。
- **三轴评分（各 1-5 分）**：排他性（只有你能说）/ 可感知（用户买前或一口就能感受到）/ 可演示（一个镜头能拍出来）
- **最终结论**：成立 / 不成立 / 需要补证据
```

再找到：

```
最后给出**推荐主打 USP（1 条，≤15 字）**，并说明为什么选它而不选另一条候选。打标签 `#USP #排他性_成立`。
```

替换为：

```
最后给出**推荐主打 USP（1 条，≤15 字）**——必须三轴均 ≥4 分才能当推荐主打；没有任何候选达标时，明写"本 SKU 暂无够格 USP，建议主打组合卖点：X + Y"（不许硬推）。说明为什么选它而不选另一条候选。打标签 `#USP #排他性_成立 #三轴_X/X/X`。
```

- [ ] **Step 4: 编辑④ 场景真需求 + 心智挂真需求（2.1/2.2 节）**

找到 2.1 节的：

```
**只做场景识别，不判断该场景适合什么人群或怎么做内容。**
```

替换为：

```
**每个场景必须附一行「该场景下的真需求」**：用户在这个场景到底要解决什么（如"给娃辅食"场景的真需求是"成分我能看懂、咸度我能控制"）——这是后面所有心智判断的地基。

**只做场景识别，不判断该场景适合什么人群或怎么做内容。**
```

找到 2.2 节的：

```
- 该场景想被占住，需要产品在哪一层卖点上发力（对应第 1 部分的哪条）
```

替换为：

```
- 该场景想被占住，需要产品在哪一层卖点上发力（对应第 1 部分的哪条）
- 该心智挂回哪条真需求（引用 2.1 的「真需求」行——心智判断不许悬空，挂不上真需求的心智砍掉）
```

- [ ] **Step 5: 自检清单同步（第七节 7.3）**

找到 7.3 节的：

```
- ✓ 显性卖点：每条 9 字段（含**新增的合规替代表述**——合规风险=高/中 时必填）
- ✓ 隐性卖点：每条 9 字段
```

替换为：

```
- ✓ 显性卖点：每条 11 字段（含合规替代表述 + **三层拆解 + 买点**）
- ✓ 隐性卖点：每条 11 字段（含证据类型 + **三层拆解 + 买点**）
- ✓ USP：每条有三轴评分；推荐主打 USP 三轴均 ≥4，否则明写"暂无够格 USP"
- ✓ 2.1 每个场景有「真需求」行；2.2 每个场景心智挂回了真需求
```

- [ ] **Step 6: 渲染验证 + Commit**

```bash
docker exec omni-knowledge-engine python -c "
from app.mcp import prompts
s = prompts.load('selling_points_matrix.system')
assert '三层拆解' in s and '买点' in s and '三轴评分' in s and '真需求' in s
print('ok', len(s))
"
git add services/knowledge-engine/config/prompts/selling_points_matrix.system.md
git commit -m "feat(prompts): step 2 卖点矩阵打磨——三层拆解/买点视角/USP 三轴/场景真需求"
```

---

### Task 9: 端到端验收（真 SKU 走全链）+ CLAUDE.md 话术表

**Files:**
- Modify: `C:\Users\Administrator\.claude\CLAUDE.md`（话术表 + tool 数）

- [ ] **Step 1: 跑 step 2（打磨后 prompt 回归）**

在 Claude Code 会话里调 MCP tool（或老板亲自跑）：

```
generate_selling_points_matrix(sku_id='SKU-375753-0001')
```

验收：输出 5 部分结构未破坏；显性/隐性卖点带「三层拆解」「买点」行；USP 带三轴评分；2.1 场景带「真需求」行。**给老板看，老板说 OK 再继续。**

- [ ] **Step 2: 跑 step 3 + 选人群**

```
generate_audience_match(sku_id='SKU-375753-0001', matrix_md=<step1 输出>, matrix_run_id=<step1 返回>)
```

验收：≥15 人群正常返回，records 落库。老板选一个 record（或测试时取 records[0].id）。

- [ ] **Step 3: 跑 step 3.5**

```
generate_audience_portrait(audience_record_id=<选中的 record id>)
```

验收：
- portrait_md 5 部分齐全；`validation_warnings` 为空（或仅料薄提示——若 [KB:] 占比警告频发，回头调 prompt 或检索配额）
- 生活细节具体到"能拍出来"；第 2 部分"对这群人说的那句话"是口语、主语是人
- trace.prompt 可看；`SELECT status, version FROM pipeline.audience_portraits WHERE sku_id='SKU-375753-0001'` 有 draft 行

- [ ] **Step 4: 跑 step 3.6（两种开关都试）**

```
generate_director_brief(portrait_id=<step3 返回>)                          # 带 AI 映射
generate_director_brief(portrait_id=<step3 返回>, include_ai_mapping=False, idea_seed='闺女给妈寄酱油')
```

验收：
- 第 0-4 部分齐全 + 12 项自检逐项打勾；带映射版有第 5 部分（image/last_frame/motion 三 prompt 齐全、英文、含真人感锚）
- validation_warnings 为空（禁用词/缺节都没有）
- 台词老板亲自读——像人话、≤15 字/句、产品信息 ≤2 句

- [ ] **Step 5: 血缘反查验证**

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "
SELECT s.id AS script_id, s.kind, p.id AS portrait_id, r.name AS audience_name,
       ar.id AS audience_run_id, m.id AS matrix_run_id, s.sku_id
FROM pipeline.scripts s
JOIN pipeline.audience_portraits p ON s.portrait_id = p.id
JOIN pipeline.audience_records r ON p.audience_record_id = r.id
JOIN pipeline.audience_runs ar ON r.audience_run_id = ar.id
JOIN pipeline.matrix_runs m ON r.matrix_run_id = m.id
WHERE s.kind = 'director_brief' ORDER BY s.created_at DESC LIMIT 3"
```

Expected: 至少 1 行，6 表 join 全通。

- [ ] **Step 6: pipeline_adopt 画像采纳**

```
pipeline_adopt(table='audience_portraits', run_id=<portrait_id>)
```

Expected: `{"ok": true, "status": "adopted"}`。

- [ ] **Step 7: 全量测试回归**

```bash
docker exec omni-knowledge-engine pytest tests/test_portrait_lineage.py tests/test_portrait_brief_tools.py -v
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected: 测试全过 + `all 80 ok`。

- [ ] **Step 8: 更新 CLAUDE.md**

编辑 `C:\Users\Administrator\.claude\CLAUDE.md`：

8a. 开头「omni 暴露 **78 个 tool**」改为「omni 暴露 **80 个 tool**」（`all 78 ok` 同步改 `all 80 ok`，调试常用命令一节里的也改）。

8b. tool 清单里 sku-pipeline LLM 行（`generate_creative_pack`（step 5 创意素材 6 类，phase C）之后）加：

```
`generate_audience_portrait`（step 3.5 人群生活状态画像：四路定向召回+可信度分级标注+卖点重构+情绪触点，落 pipeline.audience_portraits）, `generate_director_brief`（step 3.6 编导备忘录：V7.2 一件事/起伏≠反转/卖点种情绪+算法信号三向量+可选 AI 出片映射，落 pipeline.scripts kind='director_brief'）
```

8c. 在「sku-pipeline step 5 创意素材」节后面加新节：

```markdown
## sku-pipeline step 3.5/3.6 内容 brief 链（2026-06-11）

step 3 选中人群后**分流**：投放圈包走 step 4；**内容 brief 走 3.5→3.6**（每步停等老板反馈）：

| 老板说 | Claude 应做 |
|---|---|
| "给这个人群出画像 / 选第 N 个出生活状态 / 深挖这个人群" | `generate_audience_portrait(audience_record_id)` |
| "给 X 出编导 brief / 拍摄 brief / 给编导下个 brief" | 链路缺啥跑啥：没画像先 3.5，有了直接 `generate_director_brief(portrait_id)` |
| "想拍 X 那种（具体的事）" | `generate_director_brief(..., idea_seed='X')` |
| "不要 AI 那段" | `include_ai_mapping=False` |
| "再来一版 / 换个创意" | 重跑 3.6（新版本落库）或 `num_variants=2-3` |
| "把这版画像采纳" | `pipeline_adopt(table='audience_portraits', run_id=...)` |

防臆想：画像每句标 [KB:doc]/🧠推演/⚠️推测，validation_warnings 报配额超标 = KB 料薄，提示老板补圈层 KB 重跑（不硬编）。brief 自检 12 项 + 禁用词确定性扫描。
```

- [ ] **Step 9: 最终 commit + 汇报老板**

```bash
git add docs/superpowers/plans/2026-06-11-audience-portrait-director-brief.md
git commit -m "docs(plan): step 3.5/3.6 实施计划（已执行完毕）"
```

汇报内容：doctor 80 ok、端到端产物链接（portrait_md/brief_md）、血缘 join 截图、validation_warnings 状态、提示老板"prompt 在 config/prompts/{audience_portrait,director_brief}.*.md，改完即生效不用重启"。

---

## Self-Review 记录

- **Spec 覆盖**：spec §2 做的 8 项 ↔ Task 1（migration+047）/ Task 2（lineage+adopt）/ Task 3-4（3.5 prompt+tool）/ Task 5-6（3.6 prompt+tool）/ Task 7（注册+doctor+hint 分流）/ Task 8（step 2 打磨 4 处）/ Task 9（E2E+CLAUDE.md）。无缺口。
- **占位符扫描**：Task 4 的 generate_director_brief 占位实现是**计划内的 TDD 中间态**（Task 6 替换为本计划写明的完整代码），不是缺内容。CREATIVE_KINDS 定位用 grep（常量位置未知但改法明确）。
- **类型一致性**：save_audience_portrait 关键字参数 ↔ Task 4 调用处一致；_validate_brief(md, include_ai_mapping=) 签名 ↔ 测试一致；get_audience_portrait 返回字段（audience_record_id/audience_run_id/matrix_run_id/sku_id/portrait_md）↔ Task 6 使用处一致。
