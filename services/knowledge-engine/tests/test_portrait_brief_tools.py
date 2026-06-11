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
        assert "单次生成时长" in s, m
