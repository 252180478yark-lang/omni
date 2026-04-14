# 技术实现文档 — 投放复盘系统（Ad Review System）

> 模块代号：SP8-AdReview  
> 版本：v1.0  
> 日期：2026-04-07

---

## 1. 系统架构

### 1.1 方案选型

**新增独立服务 `ad-review-service`（SP8）**，端口 `8008`。

理由：
- 有独立的数据模型（投放批次、人群包、素材指标等）
- 需要协调多个现有服务（SP4知识引擎、SP6视频分析、SP3 AI Hub）
- 逻辑复杂度高，独立服务便于维护和扩展

### 1.2 架构图

```
┌──────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                        │
│              /ad-review/*  页面 + BFF API                    │
└─────────────────────────┬────────────────────────────────────┘
                          │
                   Nginx Gateway :80
                   /api/v1/ad-review/* ──→ ad-review-service:8008
                          │
              ┌───────────┼───────────────┐
              │           │               │
     ┌────────▼───┐ ┌────▼──────┐  ┌─────▼──────────┐
     │ AI Provider │ │ Knowledge │  │ Video Analysis │
     │ Hub :8001   │ │ Engine    │  │ Service :8006  │
     │             │ │ :8002     │  │                │
     │ - LLM调用   │ │ - RAG检索  │  │ - 获取分析结果  │
     │ - 生成建议   │ │ - 日志入库  │  │ - 维度评分     │
     └─────────────┘ └───────────┘  └────────────────┘
              │
     ┌────────▼──────────┐
     │   PostgreSQL       │
     │   Schema: ad_review│
     └───────────────────┘
```

### 1.3 服务间通信

| 调用方 | 被调用方 | 方式 | 用途 |
|--------|---------|------|------|
| ad-review → AI Hub | HTTP | 调用LLM生成复盘建议（流式SSE） |
| ad-review → Knowledge Engine | HTTP | RAG检索历史经验 + 日志入库 |
| ad-review → Video Analysis | HTTP | 查询视频分析结果列表和详情 |
| Frontend BFF → ad-review | HTTP | 所有业务操作 |

---

## 2. 数据库设计

### 2.1 新增 Schema

```sql
-- ═══ Ad Review Schema ═══
CREATE SCHEMA IF NOT EXISTS ad_review;
COMMENT ON SCHEMA ad_review IS 'Ad campaign review & optimization logs';

-- ── 产品表 ──
CREATE TABLE IF NOT EXISTS ad_review.products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),          -- 产品类别：护肤/食品/服装...
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_products_name ON ad_review.products (name);

-- ── 投放批次表 ──
CREATE TABLE IF NOT EXISTS ad_review.campaigns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID NOT NULL REFERENCES ad_review.products(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,       -- 批次名称
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_budget DECIMAL(12,2),       -- 预算
    total_cost DECIMAL(12,2),         -- 实际总消耗（CSV数据汇总）
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
        -- draft | data_uploaded | reviewed | archived
    review_log_id UUID,               -- 关联的复盘日志
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_campaigns_product ON ad_review.campaigns (product_id);
CREATE INDEX idx_campaigns_status ON ad_review.campaigns (status);
CREATE INDEX idx_campaigns_date ON ad_review.campaigns (start_date DESC);

-- ── 人群包表 ──
CREATE TABLE IF NOT EXISTS ad_review.audience_packs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,        -- 人群包名称
    description TEXT DEFAULT '',        -- 人群特征描述
    tags JSONB DEFAULT '[]',           -- 结构化标签 ["25-35岁", "女性", "护肤兴趣"]
    targeting_method_text TEXT,         -- 圈包手法-LLM建议文本
    targeting_method_file TEXT,         -- 圈包手法-上传的Excel文件路径
    audience_profile_text TEXT,         -- 人群画像-文本描述
    audience_profile_file TEXT,         -- 人群画像-上传的Excel文件路径
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audience_campaign ON ad_review.audience_packs (campaign_id);

-- ── 素材表 ──
CREATE TABLE IF NOT EXISTS ad_review.materials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_pack_id UUID NOT NULL REFERENCES ad_review.audience_packs(id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,         -- 素材名称（CSV中的素材名）
    
    -- 迭代追踪
    parent_material_id UUID REFERENCES ad_review.materials(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1,
    iteration_note TEXT,                -- 优化说明："优化了前3秒钩子"
    
    -- 千川投放指标（CSV导入）
    cost DECIMAL(12,2),                 -- 消耗
    impressions INTEGER,                -- 展示次数
    clicks INTEGER,                     -- 点击次数
    front_impressions INTEGER,          -- 前展
    ctr DECIMAL(8,4),                   -- 点击率
    shares_7d INTEGER,                  -- 7日分享次数
    comments INTEGER,                   -- 评论次数
    plays INTEGER,                      -- 播放数
    play_3s INTEGER,                    -- 3秒播放数
    play_25pct INTEGER,                 -- 25%进度播放数
    play_50pct INTEGER,                 -- 50%进度播放数
    play_75pct INTEGER,                 -- 75%进度播放数
    completion_rate DECIMAL(8,4),       -- 完播率
    new_a3 INTEGER,                     -- 新增A3
    cost_per_result DECIMAL(12,4),      -- 消耗成本
    a3_ratio DECIMAL(8,4),             -- 新增A3占比
    
    -- 衍生指标（系统计算）
    play_3s_rate DECIMAL(8,4),         -- 3秒完播率 = play_3s / plays
    interaction_rate DECIMAL(8,4),      -- 互动率 = (shares_7d + comments) / plays
    cpm DECIMAL(12,4),                  -- CPM = cost / impressions * 1000
    cpc DECIMAL(12,4),                  -- CPC = cost / clicks
    
    -- 视频分析关联
    video_analysis_id TEXT,             -- SP6 视频分析的 video_id
    video_analysis_scores JSONB,        -- 缓存的分析评分快照
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_materials_audience ON ad_review.materials (audience_pack_id);
CREATE INDEX idx_materials_campaign ON ad_review.materials (campaign_id);
CREATE INDEX idx_materials_parent ON ad_review.materials (parent_material_id);

-- ── 复盘日志表 ──
CREATE TABLE IF NOT EXISTS ad_review.review_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    
    -- 日志内容
    content_md TEXT NOT NULL,           -- Markdown格式的完整复盘日志
    ai_suggestions JSONB,              -- 结构化的AI优化建议
    experience_tags JSONB DEFAULT '[]', -- 经验标签 ["#护肤", "#痛点钩子有效"]
    
    -- 知识库关联
    kb_id UUID,                         -- 写入的知识库ID
    kb_document_id UUID,                -- 写入的文档ID
    kb_synced_at TIMESTAMPTZ,           -- 最后同步时间
    
    -- 元数据
    is_edited BOOLEAN DEFAULT FALSE,    -- 用户是否编辑过
    generation_model VARCHAR(100),      -- 生成使用的模型
    generation_tokens INTEGER,          -- 生成消耗的token数
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_review_logs_campaign ON ad_review.review_logs (campaign_id);
CREATE INDEX idx_review_logs_tags ON ad_review.review_logs USING gin (experience_tags);

-- ── CSV导入记录表 ──
CREATE TABLE IF NOT EXISTS ad_review.csv_imports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    audience_pack_id UUID NOT NULL REFERENCES ad_review.audience_packs(id) ON DELETE CASCADE,
    original_filename VARCHAR(500),
    row_count INTEGER,
    column_mapping JSONB,               -- CSV列名到系统字段的映射关系
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 2.2 数据库迁移策略

将上述 SQL 追加到 `services/infra-core/postgres/init.sql` 的末尾。对于已有数据库的环境，提供独立的迁移脚本 `migrations/001_ad_review_schema.sql`。

---

## 3. 后端服务设计

### 3.1 目录结构

```
services/ad-review-service/
├── Dockerfile
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理
│   ├── database.py                # PostgreSQL 连接池
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── campaigns.py           # 批次 CRUD + 列表
│   │   ├── audiences.py           # 人群包 CRUD
│   │   ├── materials.py           # 素材管理 + CSV导入
│   │   ├── review.py              # 复盘生成 + 编辑 + 知识库同步
│   │   └── analytics.py           # 趋势分析 API
│   ├── services/
│   │   ├── __init__.py
│   │   ├── csv_parser.py          # CSV解析器（UTF-8/GBK自适应）
│   │   ├── metrics_calculator.py  # 衍生指标计算
│   │   ├── review_engine.py       # 复盘生成引擎（核心）
│   │   ├── kb_sync.py             # 知识库同步服务
│   │   ├── video_analysis_client.py # SP6视频分析客户端
│   │   └── ai_client.py           # SP3 AI Hub客户端
│   └── schemas.py                 # Pydantic 模型
```

### 3.2 核心服务实现

#### 3.2.1 CSV 解析器 — `csv_parser.py`

```python
"""千川CSV数据解析器，支持UTF-8/GBK编码自适应和中文列名模糊匹配。"""

import csv
import io
import chardet
from typing import Any

# 千川CSV列名 → 系统字段的映射（支持多种可能的列名写法）
COLUMN_MAPPING = {
    "消耗": "cost",
    "花费": "cost",
    "展示次数": "impressions",
    "展示数": "impressions",
    "点击次数": "clicks",
    "点击数": "clicks",
    "前展": "front_impressions",
    "点击率": "ctr",
    "7日分享次数": "shares_7d",
    "分享次数": "shares_7d",
    "评论次数": "comments",
    "评论数": "comments",
    "播放数": "plays",
    "播放次数": "plays",
    "3秒播放数": "play_3s",
    "3秒播放次数": "play_3s",
    "25%进度播放数": "play_25pct",
    "50%进度播放数": "play_50pct",
    "75%进度播放数": "play_75pct",
    "完播率": "completion_rate",
    "新增A3": "new_a3",
    "消耗成本": "cost_per_result",
    "新增A3占比": "a3_ratio",
    "素材名称": "name",
    "素材ID": "name",
    "素材名": "name",
}


def detect_encoding(raw_bytes: bytes) -> str:
    """检测CSV文件编码。"""
    result = chardet.detect(raw_bytes)
    encoding = result.get("encoding", "utf-8")
    # chardet 对 GBK 的检测结果可能是 GB2312 或 GB18030
    if encoding and encoding.upper() in ("GB2312", "GB18030", "GBK"):
        return "gbk"
    return encoding or "utf-8"


def parse_csv(raw_bytes: bytes) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """解析千川CSV文件。

    Returns:
        (rows, column_mapping) — rows 是解析后的字典列表，
        column_mapping 是实际CSV列名到系统字段名的映射。
    """
    encoding = detect_encoding(raw_bytes)
    text = raw_bytes.decode(encoding)

    reader = csv.DictReader(io.StringIO(text))
    csv_columns = reader.fieldnames or []

    # 构建实际映射
    actual_mapping: dict[str, str] = {}
    for csv_col in csv_columns:
        cleaned = csv_col.strip()
        if cleaned in COLUMN_MAPPING:
            actual_mapping[cleaned] = COLUMN_MAPPING[cleaned]

    rows: list[dict[str, Any]] = []
    for row in reader:
        parsed: dict[str, Any] = {}
        for csv_col, sys_field in actual_mapping.items():
            raw_value = row.get(csv_col, "").strip()
            parsed[sys_field] = _parse_value(sys_field, raw_value)
        rows.append(parsed)

    return rows, actual_mapping


def _parse_value(field: str, raw: str) -> int | float | str | None:
    """根据字段类型解析值。"""
    if not raw or raw == "--":
        return None
    # 去除百分号
    if raw.endswith("%"):
        raw = raw[:-1]
    # 去除逗号（千分位分隔符）
    raw = raw.replace(",", "")
    
    int_fields = {
        "impressions", "clicks", "front_impressions", "shares_7d",
        "comments", "plays", "play_3s", "play_25pct",
        "play_50pct", "play_75pct", "new_a3",
    }
    decimal_fields = {
        "cost", "ctr", "completion_rate", "cost_per_result", "a3_ratio",
    }
    
    if field in int_fields:
        return int(float(raw))
    if field in decimal_fields:
        return float(raw)
    return raw
```

#### 3.2.2 复盘生成引擎 — `review_engine.py`

```python
"""投放复盘生成引擎 — 核心模块。

整合投放数据 + 视频分析 + 知识库RAG + LLM，生成复盘日志。
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

AI_HUB_BASE = settings.ai_hub_url          # http://ai-provider-hub:8001
KE_BASE = settings.knowledge_engine_url    # http://knowledge-engine:8002
VA_BASE = settings.video_analysis_url      # http://video-analysis:8006


async def generate_review(campaign: dict, audiences: list, materials: list) -> AsyncIterator[str]:
    """生成复盘日志（流式输出）。

    Steps:
        1. 汇总投放数据，计算衍生指标
        2. 拉取关联的视频分析结果
        3. 查找素材迭代链，计算前后变化
        4. 从知识库 RAG 检索历史经验
        5. 构造 Prompt，调用 LLM 流式生成
    """
    # Step 1: 汇总数据
    data_summary = _build_data_summary(campaign, audiences, materials)

    # Step 2: 拉取视频分析
    video_insights = await _fetch_video_analyses(materials)

    # Step 3: 迭代对比
    iteration_diffs = _build_iteration_diffs(materials)

    # Step 4: RAG 检索历史经验
    rag_context = await _rag_search_experience(campaign, audiences)

    # Step 5: 构造 Prompt 并调用 LLM
    prompt = _build_review_prompt(
        data_summary=data_summary,
        video_insights=video_insights,
        iteration_diffs=iteration_diffs,
        rag_context=rag_context,
        audiences=audiences,
    )

    async for chunk in _stream_llm(prompt):
        yield chunk


def _build_data_summary(campaign: dict, audiences: list, materials: list) -> str:
    """将投放数据汇总为文本摘要。"""
    lines = [
        f"产品: {campaign['product_name']}",
        f"投放周期: {campaign['start_date']} ~ {campaign['end_date']}",
        f"总消耗: ￥{sum(m.get('cost', 0) or 0 for m in materials):.2f}",
        "",
    ]

    for aud in audiences:
        aud_materials = [m for m in materials if m["audience_pack_id"] == aud["id"]]
        lines.append(f"## 人群包: {aud['name']}")
        lines.append(f"描述: {aud.get('description', '')}")
        lines.append(f"素材数: {len(aud_materials)}")
        lines.append("")

        # 按消耗排序展示素材
        sorted_mats = sorted(aud_materials, key=lambda m: m.get("cost", 0) or 0, reverse=True)
        for m in sorted_mats:
            lines.append(
                f"- {m['name']}: 消耗￥{m.get('cost', 0)}, "
                f"展示{m.get('impressions', 0)}, "
                f"点击率{m.get('ctr', 0):.2%}, "
                f"完播率{m.get('completion_rate', 0):.2%}, "
                f"3秒播放率{m.get('play_3s_rate', 0):.2%}, "
                f"新增A3={m.get('new_a3', 0)}, "
                f"A3占比{m.get('a3_ratio', 0):.2%}, "
                f"互动率{m.get('interaction_rate', 0):.2%}"
            )
        lines.append("")

    return "\n".join(lines)


async def _fetch_video_analyses(materials: list) -> str:
    """从SP6拉取关联的视频分析报告。"""
    insights = []
    async with httpx.AsyncClient(timeout=30) as client:
        for m in materials:
            vid = m.get("video_analysis_id")
            if not vid:
                continue
            try:
                resp = await client.get(f"{VA_BASE}/api/v1/video-analysis/videos/{vid}")
                if resp.status_code == 200:
                    data = resp.json()
                    report = data.get("report_json") or {}
                    scores = report.get("scores", {})
                    dims = scores.get("dimensions", {})
                    
                    insight_lines = [f"### 素材「{m['name']}」视频分析"]
                    insight_lines.append(f"总分: {scores.get('overall', 0)}/10")
                    for dim_key, dim_val in dims.items():
                        insight_lines.append(
                            f"- {dim_key}: {dim_val.get('score', 0)}/10 — {dim_val.get('brief', '')}"
                        )
                    # 改进建议
                    suggestions = report.get("improvement_suggestions", {})
                    if suggestions.get("priority_actions"):
                        insight_lines.append("优先改进:")
                        for action in suggestions["priority_actions"][:3]:
                            insight_lines.append(f"  - {action}")
                    
                    insights.append("\n".join(insight_lines))
            except Exception as e:
                logger.warning("Failed to fetch video analysis %s: %s", vid, e)

    return "\n\n".join(insights) if insights else "（无关联视频分析数据）"


def _build_iteration_diffs(materials: list) -> str:
    """计算素材迭代前后的指标变化。"""
    # 建立 id → material 映射
    by_id = {m["id"]: m for m in materials}
    diffs = []
    
    for m in materials:
        parent_id = m.get("parent_material_id")
        if not parent_id or parent_id not in by_id:
            continue
        parent = by_id[parent_id]
        
        lines = [f"### {m['name']}（v{m.get('version', '?')}） vs {parent['name']}（v{parent.get('version', '?')}）"]
        if m.get("iteration_note"):
            lines.append(f"优化说明: {m['iteration_note']}")
        
        # 计算关键指标变化
        for metric, label in [
            ("ctr", "点击率"), ("completion_rate", "完播率"),
            ("play_3s_rate", "3秒播放率"), ("interaction_rate", "互动率"),
            ("a3_ratio", "A3占比"),
        ]:
            old_val = parent.get(metric, 0) or 0
            new_val = m.get(metric, 0) or 0
            if old_val > 0:
                change_pct = (new_val - old_val) / old_val * 100
                arrow = "+" if change_pct > 0 else ""
                lines.append(f"- {label}: {old_val:.2%} → {new_val:.2%} ({arrow}{change_pct:.1f}%)")
        
        diffs.append("\n".join(lines))
    
    return "\n\n".join(diffs) if diffs else "（本批次无迭代素材）"


async def _rag_search_experience(campaign: dict, audiences: list) -> str:
    """从知识库中 RAG 检索相关历史投放经验。"""
    # 构造检索 query：结合产品和人群信息
    product_name = campaign.get("product_name", "")
    audience_tags = []
    for aud in audiences:
        audience_tags.extend(aud.get("tags", []))

    query = (
        f"投放复盘经验：产品类型={product_name}，"
        f"人群={', '.join(audience_tags)}，"
        f"关于点击率和转化率的优化经验、有效的钩子策略、"
        f"素材类型和人群匹配的历史结论"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 查找"投放复盘经验库"知识库
            kb_resp = await client.get(f"{KE_BASE}/api/v1/knowledge/bases")
            kbs = kb_resp.json() if kb_resp.status_code == 200 else []
            review_kb = next((kb for kb in kbs if "复盘" in kb.get("name", "")), None)

            if not review_kb:
                return "（投放复盘经验库尚无历史数据）"

            # RAG 检索
            rag_resp = await client.post(
                f"{KE_BASE}/api/v1/knowledge/rag",
                json={
                    "kb_id": review_kb["id"],
                    "query": query,
                    "top_k": 5,
                    "stream": False,
                },
                timeout=60,
            )
            if rag_resp.status_code == 200:
                result = rag_resp.json()
                return result.get("answer", "（无相关历史经验）")
    except Exception as e:
        logger.warning("RAG search failed: %s", e)

    return "（RAG检索失败，跳过历史经验）"


def _build_review_prompt(
    data_summary: str,
    video_insights: str,
    iteration_diffs: str,
    rag_context: str,
    audiences: list,
) -> str:
    """构建发送给LLM的复盘Prompt。"""
    audience_profiles = "\n".join(
        f"- {a['name']}: {a.get('description', '')}; 圈包手法: {a.get('targeting_method_text', '未提供')}"
        for a in audiences
    )

    return f"""你是一位资深的巨量千川投放优化师，同时精通短视频内容分析。
请基于以下全部数据，生成一份完整的投放复盘日志，包含深度分析和可执行的优化建议。

## 一、投放数据
{data_summary}

## 二、视频分析结果
{video_insights}

## 三、素材迭代对比
{iteration_diffs}

## 四、人群画像与圈包手法
{audience_profiles}

## 五、历史投放经验（来自知识库）
{rag_context}

---

请按照以下结构输出复盘日志（Markdown格式）：

### 一、数据亮点与问题诊断
- 识别表现最好和最差的素材，分析具体原因
- 关注关键指标异常：高点击低转化？低完播高分享？找出数据背后的逻辑

### 二、视频内容与投放数据关联分析
- 将视频分析的评分维度（钩子力、内容价值、画面质量等）与实际投放数据交叉分析
- 找出"什么样的内容特征 → 带来什么样的数据表现"的因果关系
- 特别分析前3秒钩子策略对点击率和3秒完播率的影响

### 三、人群匹配度评估
- 评估当前人群包与素材内容的匹配程度
- 分析该人群对不同内容类型的偏好（基于数据表现差异）
- 提出人群定向的调整建议

### 四、迭代效果评估（如有）
- 对比优化前后的素材数据变化
- 评估优化方向是否正确，量化改善幅度

### 五、具体优化建议
1. **下一轮素材制作方向**：具体到钩子策略、画面风格、脚本结构
2. **人群调整建议**：基于数据表现建议缩窄/放宽/更换人群
3. **投放策略建议**：预算分配、出价策略、投放时段
4. **A/B测试建议**：下一轮应该测试哪些变量

### 六、避坑清单
- 本次验证的无效做法，明确标注"不要再做"
- 本次发现的有效做法，明确标注"继续使用"

### 七、经验标签
以 #标签 格式输出本次复盘的关键经验标签，用于知识库检索。
包含：产品类型、人群特征、有效策略、无效策略、素材类型等维度。
"""


async def _stream_llm(prompt: str) -> AsyncIterator[str]:
    """调用 AI Hub 流式生成。"""
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{AI_HUB_BASE}/v1/chat/completions",
            json={
                "model": settings.review_model or "gemini-2.0-flash",
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "temperature": 0.7,
                "max_tokens": 4096,
            },
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
```

#### 3.2.3 知识库同步 — `kb_sync.py`

```python
"""复盘日志同步到知识引擎服务（SP4），使其可被 RAG 检索。"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KE_BASE = settings.knowledge_engine_url
REVIEW_KB_NAME = "投放复盘经验库"


async def ensure_review_kb() -> str:
    """确保"投放复盘经验库"存在，返回 kb_id。"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{KE_BASE}/api/v1/knowledge/bases")
        kbs = resp.json() if resp.status_code == 200 else []
        existing = next((kb for kb in kbs if kb["name"] == REVIEW_KB_NAME), None)
        if existing:
            return existing["id"]

        # 创建知识库
        create_resp = await client.post(
            f"{KE_BASE}/api/v1/knowledge/bases",
            json={
                "name": REVIEW_KB_NAME,
                "description": "投放复盘日志自动沉淀，包含历史投放数据分析、优化经验、素材效果对比等",
            },
        )
        return create_resp.json()["id"]


async def sync_review_to_kb(
    review_log: dict,
    campaign: dict,
    experience_tags: list[str],
) -> tuple[str, str]:
    """将复盘日志写入知识库。

    Returns:
        (kb_id, document_id)
    """
    kb_id = await ensure_review_kb()
    
    title = f"投放复盘-{campaign['product_name']}-{campaign['start_date']}~{campaign['end_date']}"
    
    # 在日志前添加结构化 metadata 头，增强 RAG 检索
    metadata_header = (
        f"---\n"
        f"type: 投放复盘\n"
        f"product: {campaign['product_name']}\n"
        f"period: {campaign['start_date']}~{campaign['end_date']}\n"
        f"total_cost: {campaign.get('total_cost', 0)}\n"
        f"tags: {', '.join(experience_tags)}\n"
        f"---\n\n"
    )
    
    content = metadata_header + review_log["content_md"]

    async with httpx.AsyncClient(timeout=60) as client:
        # 如果已有文档，先删除旧的
        if review_log.get("kb_document_id"):
            try:
                await client.delete(
                    f"{KE_BASE}/api/v1/knowledge/documents/{review_log['kb_document_id']}"
                )
            except Exception:
                pass

        # 写入新文档（触发 ingestion pipeline）
        resp = await client.post(
            f"{KE_BASE}/api/v1/knowledge/ingest",
            json={
                "kb_id": kb_id,
                "title": title,
                "content": content,
                "source_type": "ad_review",
            },
        )
        result = resp.json()
        document_id = result.get("document_id") or result.get("task_id", "")
    
    return kb_id, document_id
```

### 3.3 API 设计

#### 3.3.1 产品 API

```
GET    /api/v1/ad-review/products              # 产品列表
POST   /api/v1/ad-review/products              # 创建产品
PUT    /api/v1/ad-review/products/{id}          # 更新产品
DELETE /api/v1/ad-review/products/{id}          # 删除产品
```

#### 3.3.2 投放批次 API

```
GET    /api/v1/ad-review/campaigns              # 批次列表（支持筛选）
POST   /api/v1/ad-review/campaigns              # 创建批次
GET    /api/v1/ad-review/campaigns/{id}         # 批次详情（含人群包+素材+日志）
PUT    /api/v1/ad-review/campaigns/{id}         # 更新批次
DELETE /api/v1/ad-review/campaigns/{id}         # 删除批次
```

#### 3.3.3 人群包 API

```
GET    /api/v1/ad-review/campaigns/{cid}/audiences          # 人群包列表
POST   /api/v1/ad-review/campaigns/{cid}/audiences          # 添加人群包
PUT    /api/v1/ad-review/audiences/{id}                      # 更新人群包
DELETE /api/v1/ad-review/audiences/{id}                      # 删除人群包
POST   /api/v1/ad-review/audiences/{id}/upload-profile       # 上传人群画像文件
POST   /api/v1/ad-review/audiences/{id}/upload-targeting     # 上传圈包手法文件
```

#### 3.3.4 素材 API

```
POST   /api/v1/ad-review/audiences/{aid}/import-csv          # CSV导入素材
GET    /api/v1/ad-review/campaigns/{cid}/materials            # 素材列表
PUT    /api/v1/ad-review/materials/{id}                       # 更新素材（关联视频/标记迭代）
PUT    /api/v1/ad-review/materials/{id}/link-video            # 关联视频分析
PUT    /api/v1/ad-review/materials/{id}/link-parent           # 标记迭代关系
GET    /api/v1/ad-review/materials/{id}/iteration-chain       # 获取迭代链路
```

#### 3.3.5 复盘 API

```
POST   /api/v1/ad-review/campaigns/{cid}/generate-review     # 生成复盘（SSE流式）
GET    /api/v1/ad-review/campaigns/{cid}/review               # 获取复盘日志
PUT    /api/v1/ad-review/campaigns/{cid}/review               # 编辑复盘日志
POST   /api/v1/ad-review/campaigns/{cid}/review/sync-kb       # 同步到知识库
```

#### 3.3.6 分析 API

```
GET    /api/v1/ad-review/analytics/product-trend?product_id=X  # 产品投放趋势
GET    /api/v1/ad-review/analytics/audience-compare?cid=X      # 人群包对比
GET    /api/v1/ad-review/analytics/iteration-chain?material_id=X # 迭代效果链路
```

### 3.4 请求/响应模型示例

```python
# schemas.py

from pydantic import BaseModel
from datetime import date
from typing import Optional

class CampaignCreate(BaseModel):
    product_id: Optional[str] = None
    product_name: str                    # 可直接传名称，自动创建或匹配
    name: str                            # 批次名称
    start_date: date
    end_date: date
    total_budget: Optional[float] = None

class AudiencePackCreate(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    targeting_method_text: str = ""
    audience_profile_text: str = ""

class MaterialLinkVideo(BaseModel):
    video_analysis_id: str               # SP6的video_id

class MaterialLinkParent(BaseModel):
    parent_material_id: str
    iteration_note: str = ""             # 优化说明

class ReviewLogUpdate(BaseModel):
    content_md: str
    experience_tags: list[str] = []

class GenerateReviewResponse(BaseModel):
    """SSE 事件流中每个 chunk 的格式"""
    type: str                            # "chunk" | "done" | "error"
    content: str = ""
    review_log_id: str = ""              # done 时返回
```

---

## 4. 前端实现

### 4.1 新增页面

```
frontend/src/app/ad-review/
├── page.tsx                           # 投放批次列表页
├── [id]/
│   ├── page.tsx                       # 批次详情页（Tab式）
│   └── review/
│       └── page.tsx                   # 复盘日志查看/编辑页
└── analytics/
    └── page.tsx                       # 趋势分析页
```

### 4.2 BFF API Routes

```
frontend/src/app/api/omni/ad-review/
├── campaigns/
│   └── route.ts                       # 代理到 ad-review-service
├── audiences/
│   └── route.ts
├── materials/
│   ├── route.ts
│   └── import-csv/route.ts
├── review/
│   ├── route.ts
│   └── generate/route.ts             # SSE 流式代理
└── analytics/
    └── route.ts
```

### 4.3 关键交互流程

**CSV导入流程**：
1. 用户选择CSV文件 → 前端调用 `/import-csv`
2. 后端解析CSV → 返回解析结果预览（列名映射 + 前3行预览）
3. 用户确认映射无误 → 确认导入
4. 后端批量写入素材记录 → 计算衍生指标 → 返回素材列表

**复盘生成流程**：
1. 用户点击"生成复盘" → 前端建立 SSE 连接到 `/generate`
2. 后端执行 `review_engine.generate_review()` → 流式返回 Markdown
3. 前端实时渲染 Markdown（复用现有 chat 页面的流式渲染组件）
4. 生成完毕 → 用户可编辑 → 点击"保存" → 写入 DB
5. 点击"入知识库" → 调用 `kb_sync` → 同步到知识引擎

**视频分析关联流程**：
1. 用户点击素材的"关联视频" → 前端调用 SP6 获取已分析视频列表
2. 展示视频列表（缩略图 + 名称 + 分析日期）
3. 用户点选 → 前端调用 `/link-video` → 后端写入关联 + 缓存评分快照

---

## 5. Docker 集成

### 5.1 docker-compose.yml 新增

```yaml
  ad-review-service:
    build:
      context: ./services/ad-review-service
      dockerfile: Dockerfile
    container_name: omni-ad-review
    ports:
      - "8008:8008"
    environment:
      - DATABASE_URL=postgresql://omni:${POSTGRES_PASSWORD}@postgres:5432/omni
      - AI_HUB_URL=http://ai-provider-hub:8001
      - KNOWLEDGE_ENGINE_URL=http://knowledge-engine:8002
      - VIDEO_ANALYSIS_URL=http://video-analysis:8006
      - REVIEW_MODEL=${REVIEW_MODEL:-gemini-2.0-flash}
      - LOG_LEVEL=${LOG_LEVEL:-info}
    volumes:
      - ad_review_data:/app/data
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - omni-network
    restart: unless-stopped
```

### 5.2 Nginx 路由新增

```nginx
location /api/v1/ad-review/ {
    proxy_pass http://ad-review-service:8008;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # SSE 支持
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
    proxy_buffering off;
    proxy_cache off;
}
```

---

## 6. 关键技术决策

| 决策 | 方案 | 理由 |
|------|------|------|
| CSV编码检测 | chardet 库 | 千川默认导出GBK，需自适应 |
| 复盘生成 | SSE流式 | 生成时间较长(30-60s)，流式体验好 |
| 知识库同步 | 调用SP4 HTTP API | 复用现有 ingestion pipeline，不重复造轮子 |
| 视频分析关联 | 手动选择 + 评分快照缓存 | 用户确认关联，避免错误；缓存防止SP6数据变更影响历史 |
| 衍生指标 | 导入时计算 + 存储 | 避免每次查询都计算，提升性能 |
| 迭代追踪 | 自引用外键 + version | 简单有效，支持多级迭代链路 |

---

## 7. 依赖清单

### 7.1 Python 依赖 (`requirements.txt`)

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
asyncpg==0.30.0
pydantic==2.9.0
httpx==0.27.0
chardet==5.2.0
python-multipart==0.0.9
openpyxl==3.1.5
sse-starlette==2.0.0
```

### 7.2 前端依赖（已有，无需新增）

- react-markdown（已有，用于渲染复盘日志）
- recharts（已有，用于趋势图表）
- shadcn/ui（已有，用于表格、Tab、表单等）
