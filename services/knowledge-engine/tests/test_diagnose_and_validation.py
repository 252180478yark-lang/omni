"""阶段0 新增能力的纯函数单测（2026-06-02）：
- ad_metrics 入库校验（§1.4 白名单/上下界/R-4 拒手填 roi）
- 诊断官提议确定性生成（§6.2 + R-14 分层 + R-15 样本量 + R-20 dedupe_key）

纯函数、无 DB / 无 LLM，跑得快，纳入 L0-7 回归网。
"""
from __future__ import annotations

from app.services.ad_metrics_validation import validate_ad_metrics
from app.services.diagnose_service import (
    _build_analysis_proposals,
    _build_proposals,
    _confidence,
    _match_analysis_hypothesis,
)


# ───────────────────────── ad_metrics 校验 ─────────────────────────

def test_valid_metrics_all_ok():
    rep = validate_ad_metrics({"ctr": 0.05, "gmv": 1000, "plays": 5000})
    assert set(rep["ok_keys"]) == {"ctr", "gmv", "plays"}
    assert rep["suspect"] == {}
    assert rep["unknown_keys"] == []


def test_rate_above_max_is_suspect():
    # 比率上界放宽到 0..100（单位约定未钉死，避免 5% 写成 5 被误判）；150 是明确垃圾
    rep = validate_ad_metrics({"ctr": 150.0})
    assert "ctr" in rep["suspect"]
    assert "above_max" in rep["suspect"]["ctr"]["reason"]


def test_rate_5_percent_not_flagged():
    # ctr=5（按 0-100 当 5%）不该被误判存疑
    rep = validate_ad_metrics({"ctr": 5})
    assert "ctr" not in rep["suspect"]
    assert "ctr" in rep["ok_keys"]


def test_string_nan_is_suspect():
    # 字符串 'NaN' 也要拦（float('NaN') 不抛异常）
    rep = validate_ad_metrics({"plays": "NaN"})
    assert "plays" in rep["suspect"]
    assert "not_a_number" in rep["suspect"]["plays"]["reason"]


def test_aligned_ad_review_fields_recognized():
    # 对齐 ad-review csv_parser 的字段不再被当 unknown
    rep = validate_ad_metrics({"cpm": 30, "cpc": 0.5, "cost_per_result": 12, "direct_orders": 8})
    assert rep["unknown_keys"] == []
    assert "direct_pay_roi" not in rep["ok_keys"]  # ROI 类仍 R-4 拒手填
    rep2 = validate_ad_metrics({"direct_pay_roi": 3.0})
    assert "direct_pay_roi" in rep2["suspect"]


def test_negative_money_is_suspect():
    rep = validate_ad_metrics({"spend": -5})
    assert "spend" in rep["suspect"]
    assert "below_min" in rep["suspect"]["spend"]["reason"]


def test_hand_filled_roi_rejected_R4():
    # R-4：roi 应后端算，手填标 suspect 不进聚合
    rep = validate_ad_metrics({"roi": 3.2})
    assert "roi" in rep["suspect"]
    assert "hand_filled" in rep["suspect"]["roi"]["reason"]


def test_unknown_key_flagged_not_dropped():
    rep = validate_ad_metrics({"weird_metric": 1, "gmv": 100})
    assert "weird_metric" in rep["unknown_keys"]
    assert "gmv" in rep["ok_keys"]


def test_nan_is_suspect():
    rep = validate_ad_metrics({"plays": float("nan")})
    assert "plays" in rep["suspect"]
    assert "not_a_number" in rep["suspect"]["plays"]["reason"]


def test_internal_validation_key_skipped():
    rep = validate_ad_metrics({"_validation": {"x": 1}, "gmv": 1})
    assert "_validation" not in rep["unknown_keys"]
    assert "_validation" not in rep["suspect"]


# ───────────────────────── 诊断官提议生成 ─────────────────────────

def test_confidence_threshold():
    assert _confidence(1) == "preliminary"
    assert _confidence(4) == "preliminary"
    assert _confidence(5) == "observed"
    assert _confidence(99) == "observed"


def test_msg_feedback_proposal_shape_R14_R15():
    data = {"msg_by_cat": [{"category": "factual_error", "n": 2, "samples": ["错了"]}],
            "tool_by_cat": [], "asset_perf": []}
    props = _build_proposals(data, lookback_days=7)
    assert len(props) == 1
    p = props[0]
    assert p["dedupe_key"] == "content:msg_feedback:factual_error"
    assert p["sample_size"] == 2
    assert p["confidence"] == "preliminary"          # R-15: n<5
    # R-14：observation 客观、hypothesis 标"假设"且不下断言
    assert "假设" in p["hypothesis"]
    assert "主因是" not in p["hypothesis"]
    assert "要证实需对比" in p["hypothesis"]
    assert p["priority"] == 2.0                       # R-20: 按频次


def test_observed_when_enough_samples():
    data = {"msg_by_cat": [{"category": "prompt_bad", "n": 8, "samples": []}],
            "tool_by_cat": [], "asset_perf": []}
    p = _build_proposals(data, 7)[0]
    assert p["confidence"] == "observed"             # n>=5
    assert "初步观察" not in p["title"]                # 无 preliminary 前缀


def test_tool_feedback_proposal():
    data = {"msg_by_cat": [], "asset_perf": [],
            "tool_by_cat": [{"tool_name": "generate_brief", "rating_category": "tone_off", "n": 3}]}
    p = _build_proposals(data, 7)[0]
    assert p["source"] == "tool_feedback"
    assert p["dedupe_key"] == "content:tool_feedback:generate_brief:tone_off"
    assert "generate_brief" in p["hypothesis"]


def test_asset_perf_summary_priority_and_R17_caveat():
    data = {"msg_by_cat": [], "tool_by_cat": [],
            "asset_perf": [{"asset_id": "a1", "sku_id": "SKU-X", "ad_metrics": {"roi": 2.0, "_validation": {}}}]}
    p = _build_proposals(data, 7)[0]
    assert p["source"] == "asset_perf"
    assert p["dedupe_key"] == "content:asset_perf:summary"
    assert p["priority"] > p["sample_size"]          # 投后给高于纯频次的权重
    assert "自然流量" in p["hypothesis"]               # R-17 口径混杂提示


def test_empty_data_no_proposals():
    assert _build_proposals({"msg_by_cat": [], "tool_by_cat": [], "asset_perf": []}, 7) == []


# ──────────────── 诊断官·分析面趋势归因（R-14 模板化 + R-15 + R-20）────────────────

def test_analysis_hypothesis_templated_by_metric():
    # 命中 gmv 模板：三段式 + 拆 UV×转化×客单 + 禁断言
    h = _match_analysis_hypothesis("gmv_paid", "drop_30d")
    assert h.startswith("假设")
    assert "未排除混杂" in h
    assert "要证实需对比" in h
    assert "主因是" not in h          # R-14：禁伪因果断言
    assert "UV" in h and "转化" in h  # gmv 拆因子


def test_analysis_hypothesis_ctr_fatigue_template():
    h = _match_analysis_hypothesis("点击率", "ctr_decline")
    assert "素材疲劳" in h or "定向漂移" in h
    assert "主因是" not in h


def test_analysis_hypothesis_generic_fallback():
    # 没命中任何关键词 → 通用兜底（仍三段式、仍禁断言）
    h = _match_analysis_hypothesis("zzz_unknown_metric", "zzz_rule")
    assert h.startswith("假设")
    assert "未排除混杂" in h
    assert "要证实需对比" in h
    assert "主因是" not in h


def _mk_anomaly(aid, sku, metric="gmv_paid", rule="drop_30d", delta=-0.3):
    return {"id": aid, "sku_id": sku, "metric_name": metric, "rule_id": rule,
            "severity": "high", "description": "d", "delta_pct": delta,
            "baseline_value": 1000, "today_value": 700, "baseline_days": 7, "as_of": None}


def test_analysis_proposal_shape_R14_R15_R20():
    data = {"anomalies": [_mk_anomaly(1, "SKU-1"), _mk_anomaly(2, "SKU-2")]}
    props = _build_analysis_proposals(data, lookback_days=7, platform="douyin")
    assert len(props) == 1                                    # 同 metric 聚合成 1 条
    p = props[0]
    assert p["mode"] == "analysis"
    assert p["source"] == "anomaly"
    assert p["dedupe_key"] == "analysis:anomaly:gmv_paid:drop_30d"  # R-20 去重键
    assert p["sample_size"] == 2
    assert p["confidence"] == "preliminary"                  # R-15: n<5
    assert "初步观察" in p["title"]                            # preliminary 前缀
    # R-14 分层：observation 客观、hypothesis 标假设且禁断言
    assert "假设" in p["hypothesis"]
    assert "主因是" not in p["hypothesis"]
    assert p["evidence"]["anomaly_ids"] == [1, 2]
    assert p["evidence"]["platform"] == "douyin"


def test_analysis_proposal_groups_by_metric():
    # 两个不同 metric → 两条提议（各自聚合）
    data = {"anomalies": [
        _mk_anomaly(1, "SKU-1", metric="gmv_paid"),
        _mk_anomaly(2, "SKU-2", metric="ctr", rule="ctr_decline"),
    ]}
    props = _build_analysis_proposals(data, 7, "douyin")
    assert len(props) == 2
    keys = {p["dedupe_key"] for p in props}
    assert "analysis:anomaly:gmv_paid:drop_30d" in keys
    assert "analysis:anomaly:ctr:ctr_decline" in keys


def test_analysis_observed_when_enough_anomalies():
    data = {"anomalies": [_mk_anomaly(i, f"SKU-{i}") for i in range(1, 7)]}  # n=6
    p = _build_analysis_proposals(data, 7, "douyin")[0]
    assert p["sample_size"] == 6
    assert p["confidence"] == "observed"                     # n>=5
    assert "初步观察" not in p["title"]


def test_analysis_empty_no_proposals():
    assert _build_analysis_proposals({"anomalies": []}, 7, "douyin") == []
