"""W3a T1：prompts loader/render/reload 单测。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.mcp import prompts as P


def test_load_existing_template():
    """anti_ai_voice.md 应该能加载。"""
    text = P.load("anti_ai_voice")
    assert "说人话" in text
    assert "反幻觉" in text
    assert "去 AI 化" in text


def test_load_unknown_raises():
    with pytest.raises(FileNotFoundError):
        P.load("__not_exist__")


def test_render_substitutes_placeholders(tmp_path, monkeypatch):
    """render 用 str.format 替换占位。"""
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    (p_dir / "_smoke.md").write_text("Hello {name}, channel={channel}", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    out = P.render("_smoke", name="Bob", channel="douyin")
    assert out == "Hello Bob, channel=douyin"


def test_render_missing_key_raises_keyerror(tmp_path, monkeypatch):
    """模板里有 {x} 但 ctx 没给 → KeyError（暴露 bug，不静默）。"""
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    (p_dir / "_smoke2.md").write_text("a={a} b={b}", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    with pytest.raises(KeyError):
        P.render("_smoke2", a=1)


def test_load_subdirectory(tmp_path, monkeypatch):
    """支持子目录形式名（channel_profiles/douyin）。"""
    p_dir = tmp_path / "prompts"
    sub = p_dir / "channel_profiles"
    sub.mkdir(parents=True)
    (sub / "douyin.md").write_text("抖音电商画像", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    out = P.load("channel_profiles/douyin")
    assert out == "抖音电商画像"


def test_mtime_invalidates_cache(tmp_path, monkeypatch):
    """改 .md 后 load 自动重读（mtime 检测）。"""
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    f = p_dir / "_smoke3.md"
    f.write_text("v1", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    assert P.load("_smoke3") == "v1"
    # 改文件 + 推 mtime（确保跨时钟分辨率）
    time.sleep(0.05)
    f.write_text("v2", encoding="utf-8")
    # 显式推 mtime（部分 FS 分辨率秒级）
    import os as _os
    _os.utime(f, None)

    assert P.load("_smoke3") == "v2"


def test_invalidate_clears_cache(tmp_path, monkeypatch):
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    f = p_dir / "_smoke4.md"
    f.write_text("a", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    assert P.load("_smoke4") == "a"
    f.write_text("b", encoding="utf-8")
    P.invalidate()
    assert P.load("_smoke4") == "b"


def test_anti_ai_voice_loaded_from_md():
    """prompt_constraints.ANTI_AI_HUMAN_VOICE 应从 .md 文件加载（不是字面量）。"""
    from app.mcp import prompt_constraints

    # 内容应该完整含三段标题
    assert "说人话" in prompt_constraints.ANTI_AI_HUMAN_VOICE
    assert "反幻觉" in prompt_constraints.ANTI_AI_HUMAN_VOICE
    assert "去 AI 化" in prompt_constraints.ANTI_AI_HUMAN_VOICE
    # 与直接 prompts.load 加载结果一致
    assert prompt_constraints.ANTI_AI_HUMAN_VOICE == P.load("anti_ai_voice")
