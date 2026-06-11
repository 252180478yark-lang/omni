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
    rec = dict(records[0])
    rec["audience_run_id"] = run_id
    rec["matrix_run_id"] = matrix_run_id
    return rec


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
