"""C1 新形态「一大段提示词块」：parse 层 + step 6/7 适配 + 后端反算（不调 LLM）。"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

import app.mcp.server  # noqa: F401  # 先完整加载 server：media 当首入口会触发既有循环导入

from app.database import init_pool, close_pool
from app.services import pipeline_lineage, video_content_gate
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
        "content_contract": {},
        "scenes": [dict(scene) for scene in _WHOLE_SCRIPT["scenes"]],
    }


def _formal_prompt_source_3s() -> dict:
    return {
        "identity_product_anchor": (
            "主角小林保持同一张脸和米色针织衫。"
            "和田宽寿喜烧汁保持方瓶、红盖和米白标签一致。"
        ),
        "reference_instruction": "角色参考图锁定小林，产品参考图锁定寿喜烧汁包装。",
        "product_solution_action": "小林把寿喜烧汁倒入锅中，一次完成晚饭调味。",
        "timeline": (
            "0-1秒小林拿起寿喜烧汁；"
            "1-2秒把汁连续倒入锅中；"
            "2-3秒热饭完成并端上桌。"
        ),
        "scene_detail": "晚归厨房有通勤包、灶台蒸汽和自然暖光，竖屏近景保持生活感。" * 2,
        "sound_detail": "瓶盖轻响、锅中咕嘟声和瓷碗落桌声清楚连续。",
        "decorative_detail": "轻微手持感，真实皮肤和厨房使用痕迹可见。",
        "negative": "禁止换脸、包装变形、手部畸形、乱码、动作跳变。",
        "required_anchors": {
            "character": "主角小林",
            "product": "和田宽寿喜烧汁",
            "action": "倒入锅中",
            "result": "热饭完成并端上桌",
        },
    }


def _formal_whole_script(
    *, duration_s: int, prompt_source: dict | None = None
) -> dict:
    scene = {
        "scene_no": 1,
        "time_range": f"0-{duration_s}s",
        "duration_s": duration_s,
        "whole_prompt": True,
        "video_prompt": "未经正式编译的原始提示词。",
    }
    if prompt_source is not None:
        scene["prompt_source"] = prompt_source
    return {
        "id": "script-formal-1",
        "kind": "video_planting",
        "intent": "planting",
        "sku_id": "SKU-TEST",
        "content_contract": {
            "version": "2026-07-15.v1",
            "intent": "planting",
        },
        "scenes": [scene],
    }


def _install_step7_fakes(
    monkeypatch, script: dict, product_path: Path | None = None
) -> list[dict]:
    asset_calls: list[dict] = []

    async def fake_get(script_id):
        return script

    async def fake_assets(**kwargs):
        asset_calls.append(kwargs)
        return []

    async def fake_sheets(script_id, experiment_arm_id=None):
        return []

    async def fake_products(asset_ids):
        if product_path is None:
            return []
        return [{
            "id": "product-1",
            "sku_id": script["sku_id"],
            "asset_type": "product_reference",
            "file_url": str(product_path),
            "status": "adopted",
            "script_id": None,
            "experiment_arm_id": None,
            "generation_set_id": None,
        }]

    async def fake_admission(script_row, experiment_arm_id):
        return {"ok": True, "experiment_arm_id": experiment_arm_id}

    async def fake_lineage_ctx(script_row):
        return {}

    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", fake_get)
    monkeypatch.setattr(pipeline_lineage, "list_assets", fake_assets)
    monkeypatch.setattr(
        pipeline_lineage, "list_character_sheets_for_script", fake_sheets
    )
    monkeypatch.setattr(
        pipeline_lineage, "get_product_reference_assets", fake_products
    )
    monkeypatch.setattr(pipeline_lineage, "gather_lineage_context", fake_lineage_ctx)
    monkeypatch.setattr(
        video_content_gate, "assert_script_ready_for_media", fake_admission
    )
    return asset_calls


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
        legacy_mode=True,
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


@pytest.mark.asyncio
async def test_step7_formal_22_second_segment_fails_before_asset_reads(monkeypatch, tmp_path):
    script = _formal_whole_script(duration_s=22)
    product_path = tmp_path / "product.png"
    product_path.write_bytes(b"product")
    asset_calls = _install_step7_fakes(monkeypatch, script, product_path)

    out = await generate_video_segments(
        script_id=script["id"],
        dry_run=True,
        product_ref_asset_ids=["product-1"],
        experiment_arm_id="arm-1",
    )

    assert out["ok"] is False
    assert out["error"] == "video_segment_duration_invalid"
    assert out["failed_checks"] == ["duration"]
    assert out["scene_no"] == 1
    assert asset_calls == []


@pytest.mark.asyncio
async def test_step7_formal_whole_prompt_without_source_fails_closed(monkeypatch, tmp_path):
    script = _formal_whole_script(duration_s=15)
    product_path = tmp_path / "product.png"
    product_path.write_bytes(b"product")
    asset_calls = _install_step7_fakes(monkeypatch, script, product_path)

    out = await generate_video_segments(
        script_id=script["id"],
        dry_run=True,
        product_ref_asset_ids=["product-1"],
        experiment_arm_id="arm-1",
    )

    assert out["ok"] is False
    assert out["error"] == "prompt_detail_insufficient"
    assert out["failed_checks"] == ["prompt_source"]
    assert out["scene_no"] == 1
    assert asset_calls == []


@pytest.mark.asyncio
async def test_step7_formal_three_second_prompt_is_compiled_without_clamp(monkeypatch, tmp_path):
    source = _formal_prompt_source_3s()
    expected = compile_final_prompt_segment(
        source,
        duration_seconds=3,
        intent="planting",
    )
    assert expected["ok"] is True
    script = _formal_whole_script(duration_s=3, prompt_source=source)
    product_path = tmp_path / "product.png"
    product_path.write_bytes(b"product")
    _install_step7_fakes(monkeypatch, script, product_path)

    out = await generate_video_segments(
        script_id=script["id"],
        dry_run=True,
        product_ref_asset_ids=["product-1"],
        experiment_arm_id="arm-1",
    )

    assert out["ok"] is True
    row = out["result"]["results"][0]
    assert row["duration_s"] == 3
    assert row["duration_clamped"] is False
    assert row["prompt"] == expected["final_prompt"]
