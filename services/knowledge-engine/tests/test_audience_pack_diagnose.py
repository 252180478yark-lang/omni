"""人群包投前诊断引擎纯函数单测（2026-06-08）。

只测确定性逻辑（无 DB / 无 LLM）：画像解析、四/五维分类、价值正向偏离 / 购买软硬 /
需求真需求指纹重叠、漏斗定位规则、提纯优先级阶梯施工单。纳入 L0-7 回归网（跑得快、不打外部）。

worked-example 集成测（bundled diyu_xunwei vs baseline_a4）放最后，缺文件自动 skip。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import audience_pack_service as aps


# ───────────────────────── 解析原语 ─────────────────────────

def test_parse_share():
    assert aps._parse_share("35.22%") == pytest.approx(0.3522)
    assert aps._parse_share("0") == 0.0
    assert aps._parse_share("-") == 0.0
    assert aps._parse_share("") == 0.0
    assert aps._parse_share("69.08%") == pytest.approx(0.6908)


def test_parse_tgi():
    assert aps._parse_tgi("143.2") == pytest.approx(143.2)
    assert aps._parse_tgi("-") is None   # 缺失当 None，不当 0
    assert aps._parse_tgi("") is None
    assert aps._parse_tgi("0") == 0.0


def test_lead_int():
    assert aps._lead_int("5000~5999") == 5000
    assert aps._lead_int("10000及以上") == 10000
    assert aps._lead_int("高消费") == -1


def test_parse_profile_csv_basic():
    text = (
        "标签类型,标签,候选包X-占比,候选包X-tgi\n"
        "预测消费能力,高消费,69.08%,577.8\n"
        "预测消费能力,低消费,0.008%,0.01\n"
        "城市等级,一线城市,31.84%,510.4\n"
    )
    prof = aps._parse_profile_csv(text)
    assert prof["display_name"] == "候选包X"
    assert prof["n_rows"] == 3
    assert prof["by_type"]["预测消费能力"]["高消费"]["share"] == pytest.approx(0.6908)
    assert prof["by_type"]["城市等级"]["一线城市"]["tgi"] == pytest.approx(510.4)


# ───────────────────────── 价值维 / 购买行为维 ─────────────────────────

def _prof(by_type: dict) -> dict:
    return {"display_name": "t", "by_type": by_type, "n_rows": 0}


def test_value_axis_positive_deviation():
    """候选高端尾部占比 > A4 → 正向偏离。"""
    cand = _prof({"预测消费能力": {"高消费": {"share": 0.69, "tgi": 500}}})
    base = _prof({"预测消费能力": {"高消费": {"share": 0.47, "tgi": 400}}})
    rows = aps._value_axis(cand, base)
    row = next(r for r in rows if r["type"] == "预测消费能力")
    assert row["verdict"] == "正向偏离"
    assert row["delta"] == pytest.approx(0.22, abs=1e-6)


def test_value_axis_city_tail_matcher():
    """城市层级高端尾部 = 一线 + 新一线（endswith 一线城市）。"""
    cand = _prof({"城市等级": {
        "一线城市": {"share": 0.32, "tgi": 510},
        "新一线城市": {"share": 0.62, "tgi": 240},
        "二线城市": {"share": 0.04, "tgi": 30},
    }})
    base = _prof({"城市等级": {
        "一线城市": {"share": 0.09, "tgi": 123},
        "新一线城市": {"share": 0.21, "tgi": 122},
        "二线城市": {"share": 0.20, "tgi": 120},
    }})
    row = next(r for r in aps._value_axis(cand, base) if r["type"] == "城市等级")
    assert row["cand"] == pytest.approx(0.94)   # 一线+新一线
    assert row["base"] == pytest.approx(0.30)
    assert row["verdict"] == "正向偏离"


def test_behavior_axis_softer_is_seeding_signal():
    """候选高客单/高频占比 < A4 → 更软（种草信号，非扣分）。"""
    cand = _prof({"电商消费金额": {"(2000，+∞)": {"share": 0.54, "tgi": 300}}})
    base = _prof({"电商消费金额": {"(2000，+∞)": {"share": 0.75, "tgi": 569}}})
    row = next(r for r in aps._behavior_axis(cand, base) if r["type"] == "电商消费金额")
    assert row["verdict"] == "更软"


# ───────────────────────── 需求维：真需求指纹重叠 ─────────────────────────

def test_fingerprint_thresholds():
    """A4 锚 = TGI≥floor、占比≥0.3%，按 TGI 降序。低 TGI / 微量标签不入锚。"""
    base = _prof({"电商品类成交偏好": {
        "锚A": {"share": 0.18, "tgi": 1666},
        "锚B": {"share": 0.05, "tgi": 1200},
        "微量高TGI": {"share": 0.001, "tgi": 2000},   # 占比 < 0.3% 剔除
        "低TGI": {"share": 0.30, "tgi": 60},          # TGI < floor 剔除
    }})
    anchors = aps._fingerprint(base, "电商品类成交偏好")
    labels = [a["label"] for a in anchors]
    assert labels == ["锚A", "锚B"]   # 按 TGI 降序、阈值过滤


def test_demand_overlap_retained():
    """候选在 A4 锚上 TGI≥100 = 留住该真需求信号。"""
    cand = _prof({"电商品类成交偏好": {
        "锚A": {"share": 0.30, "tgi": 482},   # 留住
        "锚B": {"share": 0.10, "tgi": 80},    # 没留住（<100）
    }})
    base = _prof({"电商品类成交偏好": {
        "锚A": {"share": 0.18, "tgi": 1666},
        "锚B": {"share": 0.05, "tgi": 1300},
    }})
    row = next(r for r in aps._demand_axis(cand, base) if r["type"] == "电商品类成交偏好")
    assert row["n_anchor"] == 2
    assert row["retained"] == 1
    assert row["overlap"] == pytest.approx(0.5)


# ───────────────────────── 漏斗定位规则 ─────────────────────────

def test_position_value_loss_warns():
    p = aps._position("偏离低端(价值流失)", "相当", "强")
    assert p["label"] == "价值流失·慎投"


def test_position_seeding_when_behavior_soft():
    """付得起 + 购买行为更软 → 种草型（即便需求强）——和田宽核心场景。"""
    p = aps._position("正向偏离高端", "更软(潜在)", "强")
    assert p["label"] == "种草型"


def test_position_harvest_when_demand_strong_behavior_hard():
    p = aps._position("正向偏离高端", "更硬(即时)", "强")
    assert p["label"] == "即投/收割型"


def test_value_verdict_aggregation():
    rows = [{"verdict": "正向偏离"}, {"verdict": "正向偏离"}, {"verdict": "持平"}]
    assert aps._value_verdict(rows) == "正向偏离高端"
    rows2 = [{"verdict": "流失"}, {"verdict": "流失"}, {"verdict": "持平"}]
    assert aps._value_verdict(rows2) == "偏离低端(价值流失)"


# ───────────────────────── worked-example 集成（bundled，缺文件 skip）─────────────────────────

_BUNDLED = Path(aps._AUDIENCE_DIR) / "diyu_xunwei.csv"


@pytest.mark.skipif(not _BUNDLED.exists(), reason="bundled diyu_xunwei.csv 不在（仅容器内/已 bundle 时跑）")
def test_worked_example_diyu_xunwei():
    """范例：地域寻味人 vs A4 → 价值正向偏离高端 + 购买更软 + 种草型（方法论结论）。"""
    r = asyncio.run(aps.diagnose_audience_pack(candidate="diyu_xunwei", polish=False))
    assert r["ok"] is True
    assert r["value_verdict"] == "正向偏离高端"
    assert r["behavior_verdict"] == "更软(潜在)"
    assert r["position"]["label"] == "种草型"
    # 价值维三轴都应正向偏离（消费力/城市/手机）
    assert all(x["verdict"] == "正向偏离" for x in r["value_axis"])
    # 提纯施工单优先级阶梯：按漏斗定位「种草型」排序，非电商刀（兴趣/内容/价值）排在电商刀前
    p = r["purify_plan"]
    assert p["funnel"] == "种草型"
    levers = [c["lever"] for c in p["cuts"]]
    assert levers == ["interest", "touch", "value", "category", "brand", "behavior"]
    # 每刀都带电商资格标记；价值/兴趣/触点是非电商，品类/品牌/行为是电商
    assert all("ecommerce" in c for c in p["cuts"])
    ecom = {c["lever"]: c["ecommerce"] for c in p["cuts"]}
    assert ecom["interest"] is False and ecom["value"] is False and ecom["touch"] is False
    assert ecom["category"] is True and ecom["brand"] is True and ecom["behavior"] is True
    # markdown 含关键段
    md = r["markdown"]
    assert "投前诊断卡" in md and "漏斗定位" in md and "提纯施工单" in md
    # 口径警示：画像是投前冷启动代理
    assert "冷启动代理" in md


@pytest.mark.skipif(not _BUNDLED.exists(), reason="bundled CSV 不在")
def test_candidate_not_found_returns_available():
    r = asyncio.run(aps.diagnose_audience_pack(candidate="不存在的包xyz", polish=False))
    assert r["ok"] is False
    assert r["error"] == "candidate_not_found"
    assert "baseline_a4" in r["available"]
