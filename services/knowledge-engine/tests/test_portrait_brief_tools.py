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
        "他中午吃面 🧠 由 KB《测试文档》「面食偏好」推演。\n"
        + "他可能喜欢爬山 ⚠️推测。\n" * 6
        + "## 第 2 部分\n"
    )
    warnings = _validate_portrait_markers(md)
    assert any("推测" in w for w in warnings)
    assert any("50%" in w for w in warnings)


def test_validate_portrait_markers_clean():
    md = (
        "## 第 1 部分\n"
        "他早上喝粥 [KB:测试文档]。\n"
        "他中午吃面 [KB:测试文档]。\n"
        "他晚上散步 🧠 由 KB《测试文档》「夜间活跃」推演。\n"
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


def test_validate_brief_zhiyu_whitelist():
    """'治愈系' 是合法内容风格词不报警；裸 '治愈'（医疗宣称）要报。"""
    base = (
        "## 第 0 部分 · 这条视频拍给谁\nx\n"
        "## 第 1 部分 · 今天拍什么\nx\n"
        "## 第 2 部分 · 分段拍摄备忘\nx\n"
        "## 第 3 部分 · 算法信号三向量\n音乐向量：温暖治愈系轻音乐\n"
        "## 第 4 部分 · 发的时候\nx\n"
        "## 自检结果\nx\n"
    )
    assert _validate_brief(base, include_ai_mapping=False) == []
    bad = base.replace("温暖治愈系轻音乐", "这个酱油能治愈胃病")
    assert any("禁用词" in w for w in _validate_brief(bad, include_ai_mapping=False))


def test_director_brief_scene_kinds_reverted():
    """director_brief 走一大段提示词形态，不进视频分镜解析集合。"""
    from app.services import pipeline_lineage
    md = (
        "### 分镜 1 · 映射\n"
        "- **image_prompt**（首帧）：x\n"
    )
    assert pipeline_lineage.parse_scenes_from_script_md(md, "director_brief") == []


# ============ 批量模式（C5，2026-06-12） ============


@pytest.mark.asyncio
async def test_portrait_batch_param_exclusive():
    out = await generate_audience_portrait(
        audience_record_id="a", audience_record_ids=["b"]
    )
    assert out["ok"] is False
    assert "只能传一个" in out["error"]


@pytest.mark.asyncio
async def test_portrait_missing_params():
    out = await generate_audience_portrait()
    assert out["ok"] is False
    assert "缺参数" in out["error"]


@pytest.mark.asyncio
async def test_portrait_batch_dedupe_cap_isolation(monkeypatch):
    """去重 + 上限 6 + 单个失败（异常/软错误）不连坐 + next_step 只带成功 id。"""
    from app.mcp.tools import portrait_brief as pb

    async def fake_one(rid, extra_context=None, kb_recall_override=None):
        if rid == "bad":
            raise RuntimeError("boom")
        if rid == "soft":
            return {"ok": False, "error": "audience_record 未找到", "hint": "x"}
        return {"ok": True,
                "result": {"portrait_id": f"p-{rid}", "audience_record_id": rid}}

    monkeypatch.setattr(pb, "_portrait_one", fake_one)
    # 去重后 7 个 → 截 6（丢 r5）；bad 异常 + soft 软错误 → 4 成功
    ids = ["r1", "r1", "bad", "soft", "r2", "r3", "r4", "r5"]
    out = await pb.generate_audience_portrait(audience_record_ids=ids)
    assert out["ok"] is True
    res = out["result"]
    assert res["batch"] is True
    assert res["total"] == 6
    assert res["dropped_over_cap"] == 1
    assert res["succeeded"] == 4
    assert res["failed"] == 2
    fail_items = [it for it in res["items"] if not it["ok"]]
    assert {it["audience_record_id"] for it in fail_items} == {"bad", "soft"}
    hint_ids = out["next_step_hint"]["suggested_args"]["portrait_ids"]
    assert sorted(hint_ids) == ["p-r1", "p-r2", "p-r3", "p-r4"]


@pytest.mark.asyncio
async def test_brief_batch_forces_single_variant(monkeypatch):
    """批量 brief 每画像强制 num_variants=1；全失败时 ok=False。"""
    from app.mcp.tools import portrait_brief as pb

    seen_variants: list[int] = []

    async def fake_brief(pid, *, idea_seed=None, include_ai_mapping=True,
                         ai_prompt_count=None, target_model="seedance",
                         extra_context=None, num_variants=1):
        seen_variants.append(num_variants)
        return {"ok": True, "result": {"portrait_id": pid, "variants": [{"script_id": f"s-{pid}"}]}}

    monkeypatch.setattr(pb, "_brief_one", fake_brief)
    out = await pb.generate_director_brief(
        portrait_ids=["p1", "p2"], num_variants=3  # 显式 3 也被强制成 1
    )
    assert out["ok"] is True
    assert out["result"]["succeeded"] == 2
    assert seen_variants == [1, 1]

    async def all_fail(pid, **kwargs):
        raise TimeoutError("hub down")

    monkeypatch.setattr(pb, "_brief_one", all_fail)
    out2 = await pb.generate_director_brief(portrait_ids=["p1"])
    assert out2["ok"] is False
    assert out2["result"]["failed"] == 1


def test_validate_brief_new_part5_title():
    """include_ai_mapping=True 时，新标题「第 5 部分 · AI 出片提示词」满足裸串检查，零警告。"""
    md = (
        "## 第 0 部分 · 这条视频拍给谁\nx\n"
        "## 第 1 部分 · 今天拍什么\nx\n"
        "## 第 2 部分 · 分段拍摄备忘\nx\n"
        "## 第 3 部分 · 算法信号三向量\nx\n"
        "## 第 4 部分 · 发的时候\nx\n"
        "## 第 5 部分 · AI 出片提示词\nx\n"
        "## 自检结果\nx\n"
    )
    assert _validate_brief(md, include_ai_mapping=True) == []


def test_video_model_profiles_loadable():
    """4 个模型档案可加载；未知名由 tool 内部回退 generic（这里仅验证档案文件齐全）。"""
    from app.mcp import prompts
    for m in ("generic", "veo", "seedance", "jimeng"):
        s = prompts.load(f"video_model_profiles/{m}")
        assert s.strip(), f"{m} 档案为空"
    # seedance 2.0 重写后不再用「单次生成时长」字段，改为不分块整段叙事
    sd = prompts.load("video_model_profiles/seedance")
    assert "不分块" in sd, "seedance 档案缺「不分块」关键字"
    assert "语言：中文" in sd, "seedance 档案缺「语言：中文」声明"
    # 其余三档仍有单次生成时长字段
    for m in ("generic", "veo", "jimeng"):
        s = prompts.load(f"video_model_profiles/{m}")
        assert "单次生成时长" in s, f"{m} 档案缺「单次生成时长」字段"
