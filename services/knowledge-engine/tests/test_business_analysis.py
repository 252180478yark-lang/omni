"""综合经营分析 + 临时问数的纯函数单测（2026-06-03）。

只测确定性逻辑（无 DB / 无 LLM）：metric NL 解析、时间窗解析、R-14 分层组装、同行对比措辞。
纳入 L0-7 回归网（跑得快、不打外部）。
"""
from __future__ import annotations

from app.services import metric_registry as reg
from app.services.business_analysis_service import (
    _benchmark_phrase,
    _build_analysis,
    _parse_window,
    _pct,
    _summarize_series,
)


# ───────────────────────── metric NL 解析 ─────────────────────────

def test_resolve_exact_metric_name():
    assert reg.resolve_metric("看下 gmv_paid 最近") == "gmv_paid"


def test_resolve_chinese_fullname():
    assert reg.resolve_metric("成交金额这个月咋样") == "gmv_paid"


def test_resolve_alias_substring():
    assert reg.resolve_metric("最近转化率走势") == "pay_conversion"
    assert reg.resolve_metric("5A 总资产这周") == "asset_5a_total"


def test_resolve_long_alias_wins_over_short():
    # '商品卡成交额' 应命中 gmv_paid_card_7d 而不是裸 'gmv'/'成交额' → gmv_paid
    assert reg.resolve_metric("近7天商品卡成交额多少") == "gmv_paid_card_7d"


def test_resolve_none_when_no_metric():
    assert reg.resolve_metric("今天天气真好") is None
    assert reg.resolve_metric("") is None


def test_registry_directions_and_cn():
    assert reg.cn("gmv_paid") == "成交金额(支付)"
    assert reg.direction("industry_rank") == "down_good"   # 排名越小越好
    assert reg.direction("gmv_paid") == "up_good"
    # owner / operator 两面互不为空且都在 registry 里
    for m in reg.OWNER_FACE_METRICS + reg.OPERATOR_FACE_METRICS:
        assert m in reg.METRIC_REGISTRY


# ───────────────────────── 时间窗解析 ─────────────────────────

def test_parse_window_n_days():
    d, note = _parse_window("最近7天 gmv")
    assert d == 7


def test_parse_window_n_weeks():
    d, _ = _parse_window("近3周转化率")
    assert d == 21


def test_parse_window_time_word():
    d, _ = _parse_window("本月成交额")
    assert d == 30
    d2, _ = _parse_window("今天 gmv")
    assert d2 == 1


def test_parse_window_default():
    d, note = _parse_window("gmv 多少", default_days=28)
    assert d == 28
    assert "默认" in note


def test_parse_window_clamped():
    d, _ = _parse_window("近 9999 天")
    assert d == 365   # 上限封顶


# ───────────────────────── 工具函数 ─────────────────────────

def test_pct_basic_and_zero_div():
    assert _pct(110, 100) == 0.1
    assert _pct(100, 0) is None
    assert _pct(None, 100) is None


def test_benchmark_phrase_shop_vs_industry():
    b = {"shop_value": 500.0, "industry_avg": 800.0, "industry_top": 1200.0,
         "percentile": 0.4, "industry_rank": 7}
    phrase = _benchmark_phrase(b, "gmv_paid")
    assert "低于" in phrase
    assert "同行均值" in phrase
    assert "行业排名第 7" in phrase


def test_benchmark_phrase_none():
    assert _benchmark_phrase(None, "gmv_paid") is None


# ───────────────────────── 临时问数简述 ─────────────────────────

def test_summarize_empty_series():
    block = {"cn": "成交金额(支付)", "metric": "gmv_paid", "n": 0, "unit": "元",
             "latest": None, "latest_date": None, "change_window_pct": None,
             "mom_pct": None, "period_avg": None}
    s = _summarize_series(block, "近 7 天")
    assert "无数据" in s


def test_summarize_with_data():
    block = {"cn": "成交金额(支付)", "metric": "gmv_paid", "n": 10, "unit": "元",
             "latest": 600.0, "latest_date": "2026-06-02", "change_window_pct": 0.2,
             "mom_pct": 0.15, "period_avg": 550.0}
    s = _summarize_series(block, "近 10 天")
    assert "成交金额" in s
    assert "600" in s
    assert "+20.0%" in s  # change_window_pct


# ───────────────────────── R-14 分层组装 ─────────────────────────

def _mk_block(metric, n, latest, mom, bench=None):
    return {
        "metric": metric, "cn": reg.cn(metric), "unit": reg.unit(metric),
        "direction": reg.direction(metric), "n": n, "latest": latest,
        "latest_date": "2026-06-02", "first": "2026-05-20", "first_value": latest * 0.8 if latest else None,
        "change_window_pct": 0.25, "period_avg": latest, "prev_avg": (latest / (1 + mom)) if (latest and mom is not None) else None,
        "mom_pct": mom, "benchmark": bench, "series": [{"date": "2026-06-02", "value": latest}] * n,
    }


def test_build_analysis_r14_layers_present():
    blocks = [
        _mk_block("gmv_paid", 10, 600.0, 0.3,
                  bench={"shop_value": 600.0, "industry_avg": 800.0, "industry_top": None,
                         "percentile": None, "industry_rank": 5}),
        _mk_block("pay_conversion", 10, 0.04, -0.2),
    ]
    anomalies = [{"id": 1, "sku_id": "_SHOP_", "metric_name": "gmv_paid", "rule_id": "z",
                  "severity": "high", "delta_pct": -0.3, "today_value": 600.0,
                  "baseline_value": 850.0, "as_of": None}]
    out = _build_analysis("owner", blocks, anomalies, days=28, platform="douyin")
    md = out["markdown"]
    # 四段分层都在
    assert "观察到的" in md
    assert "异动" in md
    assert "可能的原因" in md
    assert "口径与样本量警示" in md
    # R-14：第三部分是假设不是断言
    assert "假设" in md
    assert "主因是" not in md
    # hypotheses 结构化返回
    assert any(h["metric"] == "gmv_paid" for h in out["hypotheses"])
    # observed 客观带数据
    assert any(m["metric"] == "gmv_paid" for m in out["observed"]["metrics"])


def test_build_analysis_low_sample_flagged_R15():
    blocks = [_mk_block("gmv_paid", 2, 600.0, None)]  # n<5
    out = _build_analysis("owner", blocks, [], days=28, platform="douyin")
    # R-15 样本不足标待验证
    assert any("待验证" in c or "样本量不足" in c for c in out["sample_caveats"])
    assert out["confidence"] == "preliminary"


def test_build_analysis_missing_metric_noted():
    blocks = [_mk_block("gmv_paid", 0, None, None)]  # 无数据
    out = _build_analysis("operator", blocks, [], days=28, platform="douyin")
    assert "缺数据" in out["markdown"]
