"""工具目录 + 通用执行端点测试（真服务 http）。"""
from __future__ import annotations

import httpx
import pytest

BASE = "http://localhost:8002/api/v1/mcp/catalog"


def test_catalog_lists_all_tools():
    r = httpx.get(f"{BASE}/tools", timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["count"] >= 80
    by_name = {t["name"]: t for t in j["tools"]}
    # 新工具在目录里且带 schema
    p = by_name["generate_audience_portrait"]
    assert "audience_record_id" in (p["input_schema"].get("properties") or {})
    assert p["require_approval"] is False
    # Gate 工具标记正确
    assert by_name["record_cost"]["require_approval"] is True


def test_exec_dispatches_cheap_tool():
    r = httpx.post(f"{BASE}/exec", json={"tool_name": "list_channel_fees", "args": {}}, timeout=30)
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_exec_unknown_tool_404():
    r = httpx.post(f"{BASE}/exec", json={"tool_name": "no_such_tool_xyz", "args": {}}, timeout=15)
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_exec_bad_args_422():
    r = httpx.post(f"{BASE}/exec", json={"tool_name": "get_sku", "args": {"nonexistent_param": 1}}, timeout=15)
    assert r.status_code == 422
    assert "bad_args" in r.json()["error"]
