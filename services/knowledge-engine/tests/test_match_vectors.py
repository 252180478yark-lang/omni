"""内容↔人群向量匹配 + 北极星闭环（migration 066）测试：

- 纯函数：三路文本抽取（三向量段/whole_prompt降级/scenes字段）、人群文本抽取、皮尔逊
- 端到端（mock embed_texts 出确定性向量）：embed 落库 → predict 余弦写臂级预测分
- calibrate 样本不足路径
"""
from __future__ import annotations

import pytest
import pytest_asyncio

import app.mcp.server  # noqa: F401  # 先完整加载 server，避免循环导入
from app.database import init_pool, close_pool, get_pool
from app.services import match_vectors as mv
from app.services import experiment_lab as lab
from app.services import pipeline_lineage as pl

SKU = "SKU-TEST-MATCHVEC"

_BRIEF_MD = """### 第 3 部分 · 算法信号三向量
画面向量：温馨厨房、酱油瓶、主妇下厨、暖黄灯光
文案向量：好吃、下饭、家常味、零添加
音乐向量：舒缓钢琴、温暖治愈
"""

_AUDIENCE_MD = """### 第 1 部分：KB 匹配人群
#### 1.1 [测试人群]
**[KB来源：测试文档/测试章节]**
> 测试 chunk 原文
**匹配理由（≥5条）**：
1. 卖点 1.1.1 + 场景 2.1 → 测试
**圈层标签**：食饮
"""


async def _mk_portrait() -> str:
    """走真实落库链建一个画像，返回 portrait_id。"""
    mrid = await pl.save_matrix_run(sku_id=SKU, matrix_md="# 测试矩阵", extra_context="(test)",
                                    model_provider="(test)", model="(test)")
    rid, recs = await pl.save_audience_run(matrix_run_id=mrid, sku_id=SKU, audience_md=_AUDIENCE_MD,
                                           recall_meta={"mode": "test"}, model_provider="(test)", model="(test)")
    return await pl.save_audience_portrait(
        audience_record_id=str(recs[0]["id"]), audience_run_id=rid, matrix_run_id=mrid, sku_id=SKU,
        portrait_md="### 1.3 算法信号原料\n厨房 家常 下饭 零添加", recall_meta={"mode": "test"},
        validation_warnings=[])


# ── 纯函数（无 DB / 无 API）────────────────────────────────────────────────────
def test_extract_content_tracks_three_vectors():
    t = mv.extract_content_tracks(_BRIEF_MD, "director_brief", [])
    assert set(t) == {"visual", "text", "music"}
    assert "厨房" in t["visual"] and "下饭" in t["text"] and "钢琴" in t["music"]


def test_extract_content_tracks_creativepack_with_trivector_tail():
    # creative_pack video_* 新形态：提示词块 + 末尾追加三向量段（① 让 AI 链也三路分开）
    scenes = [{"scene_no": 1, "whole_prompt": True, "video_prompt": "一大段叙事"}]
    md = ("### 提示词块 1（0-15s）\n一大段连续叙事...\n\n"
          "## 算法信号三向量\n"
          "- 画面向量：厨房、酱油瓶、主妇\n"
          "- 文案向量：下饭、家常、零添加\n"
          "- 音乐向量：轻快电子、治愈\n")
    t = mv.extract_content_tracks(md, "video_planting", scenes)
    assert set(t) == {"visual", "text", "music"}  # 三向量段优先于 whole_prompt 降级
    assert "酱油瓶" in t["visual"] and "下饭" in t["text"] and "电子" in t["music"]


def test_extract_content_tracks_whole_prompt_degrades_to_text():
    scenes = [{"scene_no": 1, "whole_prompt": True, "video_prompt": "一大段连续叙事，主妇下厨倒酱油。"}]
    t = mv.extract_content_tracks("### 提示词块 1（0-10s）\n一大段", "video_planting", scenes)
    assert list(t) == ["text"]
    assert "主妇下厨" in t["text"]


def test_extract_content_tracks_node_scenes():
    scenes = [{"scene_no": 1, "visual": "厨房空镜", "dialog": "这酱油真香", "sound": "环境音+轻快BGM"}]
    t = mv.extract_content_tracks("（节点脚本无三向量段）", "video_planting", scenes)
    assert t["visual"] == "厨房空镜" and "真香" in t["text"] and "BGM" in t["music"]


def test_extract_audience_text():
    md = "## 第1部分\n### 1.3 算法信号原料\n高频元素：厨房、家常\n标签云：好吃 下饭\n### 1.4 下一节\n别的"
    s = mv.extract_audience_text(md)
    assert "算法信号原料" in s and "下饭" in s and "下一节" not in s


def test_pearson():
    assert round(mv._pearson([1, 2, 3], [1, 2, 3]), 3) == 1.0
    assert round(mv._pearson([1, 2, 3], [3, 2, 1]), 3) == -1.0
    assert mv._pearson([1, 1, 1], [1, 2, 3]) == 0.0  # 零方差 → 0


# ── 端到端（mock embedding）───────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    pool = get_pool()
    await pool.execute("DELETE FROM pipeline.content_vectors WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.audience_vectors WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.assets WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.experiments WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.scripts WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.audience_portraits WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.audience_records WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.audience_runs WHERE sku_id=$1", SKU)
    await pool.execute("DELETE FROM pipeline.matrix_runs WHERE sku_id=$1", SKU)
    await close_pool()


@pytest.mark.asyncio
async def test_embed_predict_end_to_end(monkeypatch):
    pool = get_pool()
    # 固定向量 e1（1536维）→ 任意两段文本余弦=1 → 预测分=1.0（验通路：抽取→embed→落库→余弦→写臂）
    e1 = [1.0] + [0.0] * 1535

    async def fake_embed(texts, model=None, provider=None):
        return [list(e1) for _ in texts]
    monkeypatch.setattr(mv, "embed_texts", fake_embed)

    pid = await _mk_portrait()
    sids = []
    for _ in range(2):
        sids.append(await pl.save_creative_pack(sku_id=SKU, kind="director_brief", script_md=_BRIEF_MD))

    # embed 人群 + 两条内容
    ra = await mv.embed_and_store_audience(pid)
    assert ra["ok"], ra
    for sid in sids:
        rc = await mv.embed_and_store_content(sid)
        assert rc["ok"] and set(rc["tracks"]) == {"visual", "text", "music"}, rc

    # 建实验 + 挂两臂
    exp = await lab.create_experiment(sku_id=SKU, intent="planting", portrait_id=pid)
    eid = exp["experiment"]["id"]
    await lab.attach_arm(experiment_id=eid, script_id=sids[0],
                         variable_value="悬念钩子", swept_variable="opening_hook_3s")
    await lab.attach_arm(experiment_id=eid, script_id=sids[1], variable_value="痛点钩子")

    # 投前预测
    pm = await mv.predict_match(eid)
    assert pm["ok"], pm
    assert len(pm["ranking"]) == 2
    assert "disclaimer" in pm
    for arm in pm["arms"]:
        assert arm["predicted_match_score"] == 1.0       # e1 余弦=1
        assert set(arm["tracks"]) == {"visual", "text", "music"}

    # 写进了臂级列 + experiment_status 并排带出来
    sc = await pool.fetchval(
        "SELECT predicted_match_score FROM pipeline.experiment_arms "
        "WHERE experiment_id=$1::uuid AND arm_label='A'", eid)
    assert float(sc) == 1.0
    st = await lab.experiment_status(eid)
    assert all(a.get("predicted_match_score") == 1.0 for a in st["arms"])

    # 还没投放数据 → 校准样本不足
    cal = await mv.calibrate(experiment_id=eid)
    assert cal["ok"] and cal["status"] == "insufficient_samples"


@pytest.mark.asyncio
async def test_predict_guards():
    # 没绑画像 → no_portrait
    exp = await lab.create_experiment(sku_id=SKU, intent="planting",
                                      audience_record_id="00000000-0000-0000-0000-000000000000")
    r = await mv.predict_match(exp["experiment"]["id"])
    assert not r["ok"] and r["error"] == "no_portrait"
