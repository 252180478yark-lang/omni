"""C1 新形态「一大段提示词块」：parse 层 + step 6/7 适配 + 后端反算（不调 LLM）。"""
from __future__ import annotations

import pytest
import pytest_asyncio

import app.mcp.server  # noqa: F401  # 先完整加载 server：media 当首入口会触发既有循环导入

from app.database import init_pool, close_pool
from app.services import pipeline_lineage
from app.services.video_prompt_compiler import compile_final_prompt_segment
from app.services.pipeline_lineage import (
    parse_scenes_from_script_md,
    _parse_whole_prompt_blocks,
    _time_range_to_seconds,
)
from app.mcp.tools.media import (
    _validate_creative_metrics,
    _validate_whole_prompt_scenes,
    generate_storyboard_images,
    generate_video_segments,
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    await close_pool()


_TWO_BLOCK_MD = """
# 视频脚本

### 第 4.5 部分：AI 出片提示词（一大段连续故事描述）

### 提示词块 1（0-15s）

本提示词配合产品白底图参考图使用。一位 45 岁的母亲站在老式厨房里，
(0:00-0:05) 她伸手从灶台边拿起酱油瓶，倒入锅中，(0:05-0:15) 转头对镜头外的女儿笑。
负向：电影感、影棚光

### 提示词块 2（15-30s）

本提示词配合产品白底图参考图使用。同一位 45 岁的母亲端起炒好的菜，
(0:15-0:22) 夹一筷子递给女儿，(0:22-0:30) 女儿明显点头，母亲把瓶子放回灶台。
负向：电影感、影棚光

## 自检结果

- [x] 全部通过

```json
{"duration_seconds": 30}
```
"""


def test_parse_two_blocks():
    scenes = parse_scenes_from_script_md(_TWO_BLOCK_MD, "video_planting")
    assert len(scenes) == 2
    s1, s2 = scenes
    assert s1["scene_no"] == 1 and s2["scene_no"] == 2
    assert s1["time_range"] == "0-15s" and s2["time_range"] == "15-30s"
    assert s1["duration_s"] == 15 and s2["duration_s"] == 15
    assert s1["whole_prompt"] is True
    assert "伸手从灶台边拿起酱油瓶" in s1["video_prompt"]
    # 块后的「## 自检结果」与 ```json 栅栏被截掉
    assert "自检结果" not in s2["video_prompt"]
    assert "duration_seconds" not in s2["video_prompt"]
    assert s2["video_prompt"].endswith("负向：电影感、影棚光")


@pytest.mark.parametrize("raw,expect", [
    ("0-22s", (0, 22)),
    ("0:00-0:22", (0, 22)),
    ("0-22秒", (0, 22)),
    ("0~22", (0, 22)),
    ("1:05-1:20", (65, 80)),
    ("", (None, None)),
    ("乱写", (None, None)),
])
def test_time_range_variants(raw, expect):
    assert _time_range_to_seconds(raw) == expect


def test_parse_fullwidth_paren_and_h4():
    md = "#### 提示词块 1（0-15s）\n\n正文内容超过十个字的叙事描述。\n"
    scenes = _parse_whole_prompt_blocks(md)
    assert len(scenes) == 1
    assert scenes[0]["duration_s"] == 15


def test_parse_block_without_time():
    md = "### 提示词块 1\n\n没有时间范围也不抛错的正文。\n"
    scenes = _parse_whole_prompt_blocks(md)
    assert len(scenes) == 1
    assert scenes[0]["time_range"] is None
    assert "duration_s" not in scenes[0]


def test_whole_blocks_win_over_legacy_nodes():
    md = (
        "#### 节点 1 · 开场（0-5s）\n- **画面**：旧形态残留\n\n"
        "### 提示词块 1（0-15s）\n\n新形态正文。\n"
    )
    scenes = parse_scenes_from_script_md(md, "video_soft_ad")
    assert len(scenes) == 1
    assert scenes[0].get("whole_prompt") is True


def test_director_brief_still_excluded():
    md = "### 提示词块 1（0-15s）\n\ndirector brief 里的整段提示词。\n"
    assert parse_scenes_from_script_md(md, "director_brief") == []


def test_legacy_video_scripts_unchanged():
    md = (
        "#### 节点 1 · 开场（0-5s）\n"
        "- **画面**：母亲在厨房\n"
        "- **镜头**：中景\n"
    )
    scenes = parse_scenes_from_script_md(md, "video_planting")
    assert len(scenes) == 1
    assert scenes[0].get("whole_prompt") is None
    assert scenes[0]["visual"] == "母亲在厨房"


# ============ 后端反算 ============


def _mk_scene(no, tr, n_chars=600):
    return {"scene_no": no, "time_range": tr, "whole_prompt": True,
            "video_prompt": "字" * n_chars}


def test_whole_prompt_validation_clean():
    scenes = [_mk_scene(1, "0-15s"), _mk_scene(2, "15-30s")]
    assert _validate_whole_prompt_scenes(scenes, {"duration_seconds": 30}) == []


def test_whole_prompt_validation_warnings():
    scenes = [
        _mk_scene(1, "0-22s"),            # 超 15s 上限
        _mk_scene(2, "25-30s", n_chars=10),  # 起点不连续 + 字数不足
    ]
    w = _validate_whole_prompt_scenes(scenes, {"duration_seconds": 60})
    assert any("超单段上限" in x for x in w)
    assert any("时间戳不连续" in x for x in w)
    assert any("细节密度不够" in x for x in w)
    assert any("覆盖到 30s ≠" in x for x in w)
    assert any("块数 2 < " in x for x in w)


def test_creative_metrics_whole_no_legacy_gap_warning():
    """whole 模式不被旧「单段超 8s 断完播」误报。"""
    scenes = [_mk_scene(1, "0-15s"), _mk_scene(2, "15-30s")]
    metrics = {"selected_framework": "slice_of_life", "duration_seconds": 30}
    w = _validate_creative_metrics(metrics, "video_soft_ad", scenes=scenes)
    assert not any("8s" in x and "断完播" in x for x in w)


# ============ step 6 / step 7 ============


_WHOLE_SCRIPT = {
    "id": "script-whole-1",
    "kind": "video_planting",
    "sku_id": "SKU-TEST",
    "scenes": [
        {"scene_no": 1, "time_range": "0-15s", "duration_s": 15,
         "whole_prompt": True, "video_prompt": "块一全文叙事。"},
        {"scene_no": 2, "time_range": "15-37s", "duration_s": 22,
         "whole_prompt": True, "video_prompt": "块二全文叙事。"},
    ],
}


@pytest.fixture
def legacy_whole_script():
    return {
        **_WHOLE_SCRIPT,
        "contract_version": "legacy",
        "scenes": [dict(scene) for scene in _WHOLE_SCRIPT["scenes"]],
    }


@pytest.mark.asyncio
async def test_step6_whole_prompt_gate(monkeypatch):
    async def fake_get(script_id):
        return dict(_WHOLE_SCRIPT)
    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", fake_get)
    out = await generate_storyboard_images(script_id="script-whole-1")
    assert out["ok"] is False
    assert out["error"] == "whole_prompt_script_no_storyboard"
    assert "step 7" in out["hint"]


@pytest.mark.asyncio
async def test_step7_dry_run_legacy_whole_mode(monkeypatch, legacy_whole_script):
    async def fake_get(script_id):
        return legacy_whole_script

    async def fake_assets(**kwargs):
        return []

    async def fake_sheets(script_id):
        return [{"character_role": "mother", "file_url": "http://x/mother.png"}]

    async def fake_lineage_ctx(script):
        return {}

    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", fake_get)
    monkeypatch.setattr(pipeline_lineage, "list_assets", fake_assets)
    monkeypatch.setattr(pipeline_lineage, "list_character_sheets_for_script", fake_sheets)
    monkeypatch.setattr(pipeline_lineage, "gather_lineage_context", fake_lineage_ctx)

    out = await generate_video_segments(
        script_id="script-whole-1", dry_run=True,
        extra_prompt_suffix="slow handheld",
    )
    assert out["ok"] is True
    rows = {r["scene_no"]: r for r in out["result"]["results"]}
    r1, r2 = rows[1], rows[2]
    # 块全文原样直出（仅显式 suffix 追加），无一致性锁/D 框架/lineage 二次加工
    assert r1["prompt"] == "块一全文叙事。\nslow handheld"
    assert r1["first_frame_used"] is None and r1["last_frame_used"] is None
    assert r1["t2v_mode"] is True
    assert r1["whole_prompt"] is True
    assert r1["duration_s"] == 15 and r1["duration_clamped"] is False
    # 显式 legacy 数据保留旧 clamp 兼容；formal 段走下面的编译硬闸。
    assert r2["duration_s"] == 15 and r2["duration_clamped"] is True


def test_formal_22_second_segment_returns_duration_invalid():
    out = compile_final_prompt_segment(
        {},
        duration_seconds=22,
        intent="planting",
    )

    assert out["ok"] is False
    assert out["error"] == "video_segment_duration_invalid"
    assert out["failed_checks"] == ["duration"]
