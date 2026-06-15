"""reverse_audience_analysis 测试：确定性校验函数 + 输入校验 + 段二 fail-open（mock LLM 不真调）。"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool
from app.mcp.tools.reverse_audience import (
    reverse_audience_analysis,
    _validate_reverse_persona,
    _format_signals_md,
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    await close_pool()


# ============ _validate_reverse_persona 各分支（纯函数，不调 LLM） ============


def test_validate_persona_empty():
    warnings = _validate_reverse_persona("")
    assert len(warnings) == 1
    assert "为空" in warnings[0]


def test_validate_persona_no_markers():
    md = "#### 假设 1：忙碌上班族\n- 他们下班晚，做饭求快。\n- 视频演员是上班族打扮。"
    warnings = _validate_reverse_persona(md)
    assert any("可信度标记" in w for w in warnings)


def test_validate_persona_fake_kb_anchor():
    """竞品反推只看视频，出现 [KB:] = 伪锚必须报。"""
    md = (
        "#### 假设 1：健康焦虑宝妈\n"
        "- 她们关注零添加 [KB:八大人群画像]。\n"
        "- 演员是宝妈人设 🧠 依据：演员人设信号。\n"
    )
    warnings = _validate_reverse_persona(md)
    assert any("伪" in w and "KB" in w for w in warnings)


def test_validate_persona_unmarked_number():
    """含量纲数字（岁/%/元/万）的行必须带 ⚠️。"""
    md = (
        "#### 假设 1：都市青年\n"
        "- 年龄段约 25-35 岁，一二线城市为主。\n"
        "- 视频 BGM 是动感电音 🧠 依据：BGM 信号。\n"
    )
    warnings = _validate_reverse_persona(md)
    assert any("数字" in w for w in warnings)


def test_validate_persona_marked_number_ok():
    md = (
        "#### 假设 1：都市青年\n"
        "- 年龄段约 25-35 岁 ⚠️ 推测（视频推不出精确年龄）。\n"
        "- 视频 BGM 是动感电音 🧠 依据：BGM 信号。\n"
    )
    assert _validate_reverse_persona(md) == []


def test_validate_persona_clean():
    md = (
        "#### 假设 1：忙碌上班族\n"
        "- 下班晚做饭求快 🧠 依据：话术反复强调「十分钟出锅」。\n"
        "### 核心沟通主张\n"
        "- 忙也能好好吃饭 🧠 依据：字幕放大「忙」字。\n"
        "### 它没在打谁\n"
        "- 极致比价党：全片无价格信号 🧠。\n"
    )
    assert _validate_reverse_persona(md) == []


def test_format_signals_md_missing_keys():
    """缺项标（无）；列表值合并；额外 key 也列出。"""
    md = _format_signals_md({"claims": ["零添加", "提鲜"], "extra_signal": "x"})
    assert "| 话术诉求 | 零添加；提鲜 |" in md
    assert "| 演员人设 | （无） |" in md
    assert "extra_signal" in md


# ============ 输入校验（不进 LLM） ============


@pytest.mark.asyncio
async def test_missing_input():
    out = await reverse_audience_analysis()
    assert out["ok"] is False
    assert out["error"] == "missing_input"


@pytest.mark.asyncio
async def test_file_not_found():
    out = await reverse_audience_analysis(video_path="/nonexistent/x.mp4")
    assert out["ok"] is False
    assert out["error"] == "file_not_found"


@pytest.mark.asyncio
async def test_is_directory(tmp_path):
    out = await reverse_audience_analysis(video_path=str(tmp_path))
    assert out["ok"] is False
    assert out["error"] == "is_directory"


# ============ 段二 fail-open（mock GeminiVideoClient，不真调） ============

_FAKE_LLM_RESULT = {
    "signals": {
        "actor_persona": "中年女性宝妈人设",
        "scene_class": "普通家庭厨房",
        "claims": ["零添加"],
        "bgm": "治愈系钢琴",
        "subtitles": "放大「零添加」",
        "hook": "孩子不吃饭冲突",
        "price_signals": "",
        "cta": "点小黄车",
    },
    "persona_md": (
        "#### 假设 1：健康焦虑宝妈\n"
        "- 关注零添加 🧠 依据：话术诉求信号。\n"
        "### 核心沟通主张\n- 孩子能吃 🧠 依据：字幕。\n"
        "### 它没在打谁\n- 比价党 🧠 无价格信号。\n"
    ),
    "funnel_guess": "A4 行动收割 🧠 依据：强 CTA",
    "confidence_notes": ["演员人设清晰"],
    "meta": {"video_duration_sec": 30.0, "warnings": []},
}


class _FakeGeminiVideoClient:
    def __init__(self, model, api_key=None):
        self.model_id = model

    async def analyze_video(self, **kwargs):
        usage = {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
                 "upload_seconds": 0.1, "generate_seconds": 0.2}
        return dict(_FAKE_LLM_RESULT), usage


@pytest.fixture
def fake_video(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.gemini_video_client.GeminiVideoClient", _FakeGeminiVideoClient
    )
    f = tmp_path / "fake.mp4"
    f.write_bytes(b"\x00" * 1024)
    return str(f)


@pytest.mark.asyncio
async def test_fail_open_no_portrait_no_sku(fake_video):
    """无 portrait/sku 也允许跑：只出段一 + warning 提示补对照。"""
    out = await reverse_audience_analysis(video_path=fake_video)
    assert out["ok"] is True
    res = out["result"]
    assert res["comparison_md"] is None
    assert res["compared_portrait_id"] is None
    assert "假设 1" in res["competitor_persona_md"]
    assert any("portrait_id" in w for w in res["validation_warnings"])
    assert "竞品人群假设全部为视频推演" in res["markdown"]
    # 没对照 → next step 指向先出自家画像
    assert out["next_step_hint"]["suggested_tool"] == "generate_audience_portrait"


@pytest.mark.asyncio
async def test_fail_open_portrait_not_found(fake_video):
    """portrait_id 查无：fail-open 只返段一 + warning，不报错。"""
    out = await reverse_audience_analysis(
        video_path=fake_video,
        portrait_id="00000000-0000-0000-0000-000000000000",
    )
    assert out["ok"] is True
    res = out["result"]
    assert res["comparison_md"] is None
    assert any("未找到" in w for w in res["validation_warnings"])


@pytest.mark.asyncio
async def test_fail_open_sku_without_portraits(fake_video):
    """sku_id 没有任何画像：fail-open + 提示先跑 step 3.5。"""
    out = await reverse_audience_analysis(
        video_path=fake_video, sku_id="SKU-TEST-REVAUD-NONE"
    )
    assert out["ok"] is True
    res = out["result"]
    assert res["comparison_md"] is None
    assert res["sku_id"] == "SKU-TEST-REVAUD-NONE"
    assert any("generate_audience_portrait" in w for w in res["validation_warnings"])


@pytest.mark.asyncio
async def test_persona_missing_schema_failed(tmp_path, monkeypatch):
    """LLM 没返 persona_md → schema_validation_failed 带 raw_result。"""
    class _EmptyClient(_FakeGeminiVideoClient):
        async def analyze_video(self, **kwargs):
            return {"signals": {}, "meta": {}}, {"input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(
        "app.services.gemini_video_client.GeminiVideoClient", _EmptyClient
    )
    f = tmp_path / "fake2.mp4"
    f.write_bytes(b"\x00" * 16)
    out = await reverse_audience_analysis(video_path=str(f))
    assert out["ok"] is False
    assert out["error"] == "schema_validation_failed"
    assert "raw_result" in out
