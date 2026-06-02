"""W4-A T1: pattern_lib helper 单元测试。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.mcp import pattern_lib


@pytest.fixture
def tmp_state_dir(monkeypatch, tmp_path):
    """临时 agent_state 目录 + 占位 patterns.md。"""
    success = tmp_path / "successful_patterns.md"
    failed = tmp_path / "failed_patterns.md"
    success.write_text("# Successful Patterns\n\n", encoding="utf-8")
    failed.write_text("# Failed Patterns\n\n", encoding="utf-8")
    monkeypatch.setattr(pattern_lib, "AGENT_STATE_DIR", tmp_path)
    return tmp_path


def test_append_successful_pattern(tmp_state_dir):
    pattern_lib.append_successful_pattern(
        tool_call_id="abc-123",
        tool_name="generate_brief",
        note="出片很顺",
    )
    text = (tmp_state_dir / "successful_patterns.md").read_text(encoding="utf-8")
    assert "abc-123" in text
    assert "generate_brief" in text
    assert "出片很顺" in text


def test_append_failed_pattern(tmp_state_dir):
    pattern_lib.append_failed_pattern(
        tool_call_id="def-456",
        tool_name="compute_margin",
        note="算错了",
    )
    text = (tmp_state_dir / "failed_patterns.md").read_text(encoding="utf-8")
    assert "def-456" in text
    assert "compute_margin" in text
    assert "算错了" in text


def test_read_recent_patterns_returns_last_n(tmp_state_dir):
    for i in range(5):
        pattern_lib.append_successful_pattern(
            tool_call_id=f"call-{i}",
            tool_name="generate_brief",
            note=f"note-{i}",
        )
    recent = pattern_lib.read_recent_patterns(kind="successful", limit=3)
    assert len(recent) == 3
    # 最后写的最先返
    assert recent[0]["tool_call_id"] == "call-4"
