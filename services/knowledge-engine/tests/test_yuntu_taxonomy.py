"""巨量云图标签体系确定性查询 纯函数单测（2026-06-08）。

修 "agent 硬读 30k 大文件答不全" 的根因工具。只测确定性逻辑（读 bundled CSV，无 DB/LLM）。
纳入 L0-7 回归网。bundled CSV 缺则 skip。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import yuntu_taxonomy_service as t

_BUNDLED = Path(t._AUDIENCE_DIR) / "baseline_a4.csv"
pytestmark = pytest.mark.skipif(not _BUNDLED.exists(), reason="bundled 画像 CSV 不在")


def test_split_tree():
    tree = t._split_tree(["A-x", "A-y", "B", "A-x"], "-")
    assert list(tree.keys()) == ["A", "B"]
    assert tree["A"] == ["x", "y"]   # 去重保序
    assert tree["B"] == []


def test_overview_shape():
    o = t.overview()
    assert o["ok"] is True
    assert set(o["entrances"]) == {"A_自定义人群", "B_数据工厂标签工厂"}
    assert len(o["dimensions"]) >= 20
    assert "提纯三刀法" in o["const_sections"]


def test_dimension_category_is_full_tree():
    d = t.get_dimension("电商品类成交偏好")
    assert d["ok"] and d["is_tree"]
    assert d["l1_count"] == 140 and d["l2_count"] == 975   # 全量、确定性
    assert d["entrance"] == "factory"
    assert "食用油调味油" in d["tree"]["粮油米面南北干货调味品"]


def test_dimension_flat_and_substring_match():
    d = t.get_dimension("消费能力")   # 子串容错 → 预测消费能力
    assert d["ok"] and not d["is_tree"]
    assert set(d["values"]) == {"低消费", "中消费", "高消费"}


def test_search_returns_full_path_and_menu():
    s = t.search_tag("食用油")
    assert s["ok"] and s["count"] >= 1
    h = s["hits"][0]
    assert h["dimension"] == "电商品类成交偏好"
    assert h["hierarchy"] == "粮油米面南北干货调味品 > 食用油调味油"
    assert "数据工厂" in h["ui_path"]


def test_dimension_not_found():
    d = t.get_dimension("不存在的维度xyz")
    assert d["ok"] is False and d["error"] in ("dimension_not_found", "ambiguous")


def test_section_purify():
    s = t.get_section("提纯三刀法")
    assert s["ok"] and "第一刀_付得起" in s["content"]
