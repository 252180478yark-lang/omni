"""综合经营分析 + 临时问数 service（蓝图 §6 分析半 · §6.1 老板/操盘手两面）。

两个能力（均确定性为主，复用诊断官 diagnose_service 的 R-14 分层 + R-15 样本量套路）：

1. generate_business_analysis(face, days)：读 mvp_daily_metric(近 N 天序列) +
   mvp_industry_benchmark(同行) + mvp_anomaly(异动)，产出一份《综合经营分析》。
   **R-14 强制分层**：
     ① 观察到的（带数据：哪些指标涨跌多少、vs 同行什么位置、哪些异动）——客观、不含因果。
     ② 可能的原因（明确标"假设" + 列未排除混杂因子 + "要证实需对比 X"）——禁"主因是 X"断言。
   R-15 样本不足（序列点 < 5）标"待验证"。
   按两面分别出：face='owner'=经营诊断（北极星 + 同行分位 + 异动）；
                face='operator'=投放选品建议（5A 分层 + 货品结构）。
   确定性模板化映射数据→叙事；polish=True 时可选 LLM 润色，但**必须过 R-14 约束**
   （把确定性骨架当 ground truth 喂给 LLM，只许改写不许新增结论/数值/因果）。

2. query_metric_nl(question)：临时问数。把口语问句解析成 metric_name + 时间窗 + 维度（全店/SKU），
   查 mvp_daily_metric 返回序列 + 一句话简述（确定性，不调 LLM，不归因）。先支持已落库的 29 指标。

反幻觉铁律：observation 全是库内真实数字；hypothesis 走 diagnose_service 同一套模板化映射
（_match_analysis_hypothesis，禁伪因果）。同 service 函数被 MCP tool 与 REST 共用（禁漂移）。
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Any

from app.database import get_pool
from app.services import metric_registry as reg
from app.services.diagnose_service import (
    _fmt_num,
    _fmt_ts,
    _match_analysis_hypothesis,
)

# LLM 叙事层依赖（fail-open：缺任一不影响确定性骨架）
try:  # pragma: no cover - import 容错
    from app.mcp import prompts as _prompts
    from app.mcp.model_config import get_model_for_tool as _get_model
    from app.services.ai_hub_client import AIHubClient as _AIHubClient
except Exception:  # noqa: BLE001
    _prompts = None
    _get_model = None
    _AIHubClient = None

logger = logging.getLogger(__name__)

SHOP_SENTINEL = "_SHOP_"
PLATFORM_DEFAULT = "douyin"
# R-15：序列点 < 此值的指标只能"初步观察 / 待验证"
_SAMPLE_THRESHOLD = 5
# 同比基线对比窗口（"环比" = 最近一段 vs 紧邻的前一段；窗口长度取分析窗口的一半，<3 不算）
_MIN_COMPARE_HALF = 3


def _confidence(n: int) -> str:
    return "observed" if n >= _SAMPLE_THRESHOLD else "preliminary"


def _conf_tag(n: int) -> str:
    return "" if n >= _SAMPLE_THRESHOLD else "（初步观察·样本 n<%d 待验证）" % _SAMPLE_THRESHOLD


def _pct(a: float | None, b: float | None) -> float | None:
    """(a-b)/b，b 为 0/None 返 None（避免除零 + 不编造）。"""
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b


def _fmt_delta(p: float | None) -> str:
    return f"{p:+.1%}" if p is not None else "—"


# ───────────────────────── 读库：某指标近 N 天序列 + 环比 + 同行 ─────────────────────────


async def _metric_block(
    pool, metric_name: str, days: int, platform: str,
) -> dict:
    """读全店某指标近 days 天序列（mvp_daily_metric, sku_id='_SHOP_'）+ 环比 + 同行标杆。

    返 {metric, cn, unit, direction, n, latest, latest_date, first, first_value,
        change_window_pct, period_avg, prev_avg, benchmark:{...}|None, series:[...]}.
    确定性、纯库内数字，不归因。
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    since = (now - _dt.timedelta(days=days)).date()
    rows = await pool.fetch(
        """
        SELECT date, value
        FROM mvp_daily_metric
        WHERE metric_name = $1 AND platform = $2 AND sku_id = $3 AND date >= $4
        ORDER BY date ASC
        """,
        metric_name, platform, SHOP_SENTINEL, since,
    )
    series = [
        {"date": r["date"].isoformat() if r["date"] else None,
         "value": float(r["value"]) if r["value"] is not None else None}
        for r in rows
    ]
    vals = [(s["date"], s["value"]) for s in series if s["value"] is not None]
    n = len(vals)
    block: dict[str, Any] = {
        "metric": metric_name,
        "cn": reg.cn(metric_name),
        "unit": reg.unit(metric_name),
        "direction": reg.direction(metric_name),
        "n": n,
        "latest": None, "latest_date": None,
        "first": None, "first_value": None,
        "change_window_pct": None,
        "period_avg": None, "prev_avg": None, "mom_pct": None,
        "benchmark": None,
        "series": series,
    }
    if not vals:
        return block

    block["first_value"], block["first"] = vals[0][1], vals[0][0]
    block["latest"], block["latest_date"] = vals[-1][1], vals[-1][0]
    block["change_window_pct"] = _pct(vals[-1][1], vals[0][1])
    block["period_avg"] = round(sum(v for _, v in vals) / n, 6)

    # 环比：后半段均值 vs 前半段均值（窗口够长才算，否则不编）
    half = n // 2
    if half >= _MIN_COMPARE_HALF:
        prev_vals = [v for _, v in vals[:half]]
        cur_vals = [v for _, v in vals[half:]]
        prev_avg = sum(prev_vals) / len(prev_vals)
        cur_avg = sum(cur_vals) / len(cur_vals)
        block["prev_avg"] = round(prev_avg, 6)
        block["period_avg"] = round(cur_avg, 6)
        block["mom_pct"] = _pct(cur_avg, prev_avg)

    # 同行标杆（mvp_industry_benchmark 最新一天）
    if metric_name in reg.BENCHMARK_METRICS:
        try:
            br = await pool.fetchrow(
                """
                SELECT date, industry_avg, industry_top, shop_value, percentile, industry_rank
                FROM mvp_industry_benchmark
                WHERE metric_name = $1 AND date >= $2
                ORDER BY date DESC LIMIT 1
                """,
                metric_name, since,
            )
            if br:
                block["benchmark"] = {
                    "date": br["date"].isoformat() if br["date"] else None,
                    "industry_avg": float(br["industry_avg"]) if br["industry_avg"] is not None else None,
                    "industry_top": float(br["industry_top"]) if br["industry_top"] is not None else None,
                    "shop_value": float(br["shop_value"]) if br["shop_value"] is not None else None,
                    "percentile": float(br["percentile"]) if br["percentile"] is not None else None,
                    "industry_rank": br["industry_rank"],
                }
        except Exception as exc:  # 标杆缺表/缺列容忍
            logger.warning("benchmark 读失败 metric=%s: %s", metric_name, exc)

    return block


def _benchmark_phrase(b: dict | None, metric_name: str) -> str | None:
    """同行标杆 → 一句"你 vs 同行"客观陈述（无因果）。"""
    if not b:
        return None
    parts: list[str] = []
    sv = b.get("shop_value")
    avg = b.get("industry_avg")
    top = b.get("industry_top")
    pct = b.get("percentile")
    rk = b.get("industry_rank")
    if sv is not None and avg is not None:
        rel = "高于" if sv > avg else ("低于" if sv < avg else "持平")
        d = _pct(sv, avg)
        parts.append(f"你 {_fmt_num(sv)} vs 同行均值 {_fmt_num(avg)}（{rel}{_fmt_delta(d) if d is not None else ''}）")
    if top is not None:
        parts.append(f"行业TOP参考 {_fmt_num(top)}")
    if pct is not None:
        parts.append(f"同行分位 {pct:.0%}" if 0 <= pct <= 1 else f"同行分位 {_fmt_num(pct)}")
    if rk is not None:
        parts.append(f"行业排名第 {rk}")
    return "；".join(parts) if parts else None


# ───────────────────────── 异动读取（复用 diagnose 同口径）─────────────────────────


async def _recent_anomalies(pool, days: int, platform: str, limit: int = 30) -> list[dict]:
    """近 N 天未处理、非预期异动（与 diagnose_service._collect_anomalies 同口径）。"""
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        rows = await pool.fetch(
            """
            SELECT id, sku_id, metric_name, rule_id, severity, description,
                   delta_pct, baseline_value, today_value, baseline_days, as_of, platform
            FROM mvp_anomaly
            WHERE handled = FALSE
              AND COALESCE(expected, FALSE) = FALSE
              AND platform = $1
              AND detected_at > $2
            ORDER BY detected_at DESC
            LIMIT $3
            """,
            platform, now - _dt.timedelta(days=days), limit,
        )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("异动读失败: %s", exc)
        return []


# ───────────────────────── 综合经营分析 ─────────────────────────


def _observed_line(b: dict) -> str:
    """R-14 第①层：单指标客观陈述（带数据，无因果）。"""
    tag = _conf_tag(b["n"])
    if b["n"] == 0:
        return f"- {b['cn']}（{b['metric']}）：{tag}本窗口无数据（待落库 / 该指标未抓）。"
    bits = [f"最新 {_fmt_num(b['latest'])}{b['unit']}（{b['latest_date']}）"]
    if b["change_window_pct"] is not None:
        bits.append(f"窗口首尾 {_fmt_delta(b['change_window_pct'])}")
    if b.get("mom_pct") is not None:
        bits.append(f"后半段 vs 前半段 {_fmt_delta(b['mom_pct'])}")
    bench = _benchmark_phrase(b.get("benchmark"), b["metric"])
    if bench:
        bits.append(bench)
    return f"- {b['cn']}（{b['metric']}）：{tag}" + "；".join(bits) + f"（{b['n']} 天序列）"


def _direction_note(b: dict) -> str | None:
    """给"该往好/坏看"的一句客观判断（仅当方向明确 + 有变化），不归因。"""
    p = b.get("mom_pct") if b.get("mom_pct") is not None else b.get("change_window_pct")
    if p is None or abs(p) < 0.05:  # <5% 视为基本平稳，不喊话
        return None
    d = b["direction"]
    if d == "neutral":
        return None
    rising = p > 0
    good = (rising and d == "up_good") or ((not rising) and d == "down_good")
    arrow = "↑" if rising else "↓"
    judge = "向好" if good else "需关注"
    return f"{b['cn']} {arrow}{_fmt_delta(p)}（{judge}）"


def _build_analysis(
    face: str, blocks: list[dict], anomalies: list[dict], days: int, platform: str,
) -> dict:
    """把读到的数据确定性映射成《综合经营分析》结构（R-14 分层，不调 LLM）。

    返 {face, window_days, observed:{...}, hypotheses:[...], markdown, sample_caveats}。
    """
    have = [b for b in blocks if b["n"] > 0]
    missing = [b for b in blocks if b["n"] == 0]
    low_sample = [b for b in have if b["n"] < _SAMPLE_THRESHOLD]

    # —— R-14 第①层 observation ——
    observed_lines = [_observed_line(b) for b in blocks]
    movers = [m for b in have if (m := _direction_note(b))]

    # —— 异动段（客观）——
    anomaly_lines: list[str] = []
    for a in anomalies[:8]:
        delta = a.get("delta_pct")
        ds = f"{float(delta):+.2%}" if delta is not None else "缺delta"
        anomaly_lines.append(
            f"- [{a.get('severity') or '?'}] {reg.cn(a.get('metric_name') or '')}"
            f"（{a.get('metric_name')}）sku={a.get('sku_id')} {ds}"
            f"（今值 {_fmt_num(a.get('today_value'))} vs 基线 {_fmt_num(a.get('baseline_value'))}"
            f"，数据截至 {_fmt_ts(a.get('as_of')) or '未标'}）"
        )

    # —— R-14 第②层 hypothesis（模板化，按动得最大的指标 + 异动指标给方向，禁断言）——
    hyp_metrics: list[str] = []
    # 选"绝对变化最大"的前 3 个有方向指标
    scored = sorted(
        [b for b in have if b.get("mom_pct") is not None or b.get("change_window_pct") is not None],
        key=lambda b: abs(b.get("mom_pct") or b.get("change_window_pct") or 0),
        reverse=True,
    )
    for b in scored[:3]:
        hyp_metrics.append(b["metric"])
    for a in anomalies[:3]:
        m = a.get("metric_name")
        if m and m not in hyp_metrics:
            hyp_metrics.append(m)

    hypotheses: list[dict] = []
    seen: set[str] = set()
    for m in hyp_metrics:
        if m in seen:
            continue
        seen.add(m)
        hypotheses.append({
            "metric": m,
            "cn": reg.cn(m),
            "hypothesis": _match_analysis_hypothesis(m, None),
        })

    # —— 组 markdown（两面措辞不同）——
    face_title = "经营诊断（老板面）" if face == "owner" else "投放选品建议（操盘手面）"
    lines: list[str] = [
        f"# 综合经营分析 · {face_title}",
        f"> 平台 {platform} · 近 {days} 天 · 数据源 mvp_daily_metric + mvp_industry_benchmark + mvp_anomaly",
        "",
        "## 一、观察到的（客观事实，带数据，不含因果）",
    ]
    lines += observed_lines or ["- （本窗口无可用指标数据）"]
    if movers:
        lines += ["", "**动得明显的：** " + "；".join(movers)]
    lines += ["", "## 二、异动（异动引擎检出，未处理/非预期）"]
    lines += anomaly_lines or ["- （本窗口无未处理异动——引擎尚未 fire 或已全处理）"]
    lines += ["", "## 三、可能的原因（假设·非断言；R-14 强制分层）"]
    if hypotheses:
        for h in hypotheses:
            lines.append(f"### {h['cn']}（{h['metric']}）")
            lines.append(h["hypothesis"])
            lines.append("")
    else:
        lines += ["- （指标基本平稳，无显著待归因方向）", ""]
    # 样本量/口径警示（R-15 / R-17）
    caveats: list[str] = []
    if low_sample:
        caveats.append(
            "样本量不足（序列点 < %d）的指标只作初步观察、待验证：%s"
            % (_SAMPLE_THRESHOLD, "、".join(f"{b['cn']}({b['n']}天)" for b in low_sample))
        )
    if missing:
        caveats.append("本窗口缺数据的指标：" + "、".join(b["cn"] for b in missing))
    caveats.append(
        "口径（R-17）：单平台抖音（§8.5，京东/淘天数据未接入）；金额已 ÷100 为元；"
        "rate/占比为 0-1 原始值；rank 越小越靠前。同行标杆来自 mvp_industry_benchmark。"
    )
    caveats.append(
        "归因严格分层（R-14）：第一部分是相关不是因果；第三部分是模板化假设，"
        "需老板按每条的「要证实需对比 X」自行验证，禁当成结论。"
    )
    _bench_have = [b["cn"] for b in blocks if b["metric"] in reg.BENCHMARK_METRICS and b.get("benchmark")]
    _bench_miss = [b["cn"] for b in blocks if not (b["metric"] in reg.BENCHMARK_METRICS and b.get("benchmark"))]
    if _bench_have or _bench_miss:
        _msg = "同行对比："
        _msg += ("有同行基准的指标：" + "、".join(_bench_have) + "。") if _bench_have else "本面指标暂无同行基准数据。"
        if _bench_miss:
            _shown = "、".join(_bench_miss[:8]) + ("…" if len(_bench_miss) > 8 else "")
            _msg += f"其余指标（{_shown}）暂无同行参照——是数据未接，非缺失/bug。"
        caveats.append(_msg)
    lines += ["## 四、口径与样本量警示"]
    lines += [f"- {c}" for c in caveats]

    markdown = "\n".join(lines)
    return {
        "face": face,
        "window_days": days,
        "platform": platform,
        "observed": {
            "metrics": [
                {k: b[k] for k in ("metric", "cn", "unit", "direction", "n", "latest",
                                   "latest_date", "change_window_pct", "mom_pct",
                                   "period_avg", "prev_avg", "benchmark")}
                for b in blocks
            ],
            "movers": movers,
            "anomalies": [
                {"id": int(a["id"]) if a.get("id") is not None else None,
                 "sku_id": a.get("sku_id"), "metric_name": a.get("metric_name"),
                 "delta_pct": float(a["delta_pct"]) if a.get("delta_pct") is not None else None,
                 "severity": a.get("severity"), "as_of": _fmt_ts(a.get("as_of"))}
                for a in anomalies[:8]
            ],
        },
        "hypotheses": hypotheses,
        "sample_caveats": caveats,
        "confidence": _confidence(max((b["n"] for b in have), default=0)),
        "markdown": markdown,
    }


_FACE_TITLE = {
    "owner": "经营诊断（老板面）",
    "operator": "投放选品建议（操盘手面）",
}


async def _narrate(
    skeleton_md: str, face: str, days: int, platform: str, focus: str | None,
) -> tuple[str, bool]:
    """LLM 叙事层：把确定性《事实骨架》当 ground truth，按外置提示词写成给老板看的经营分析。

    提示词外置 `config/prompts/business_analysis.{system,user}.md`（铁律 C，热加载可调）。
    模型走 tool_models.yaml 的 generate_business_analysis 条目（缺省 gemini-3.5-flash）。
    **失败/依赖缺失 → 原样返回骨架 + narrated=False（fail-open，绝不丢确定性真值）。**
    """
    if _prompts is None or _AIHubClient is None or _get_model is None:
        return skeleton_md, False
    try:
        cfg = {}
        try:
            cfg = _get_model("generate_business_analysis") or {}
        except Exception:  # noqa: BLE001
            cfg = {}
        provider = cfg.get("provider", "gemini")
        model = cfg.get("model", "gemini-3.5-flash")
        temperature = float(cfg.get("temperature", 0.3))
        max_tokens = int(cfg.get("max_tokens", 8000))

        focus_block = (
            f"老板这次特别关注：{focus.strip()}\n（请在总览里优先回应这一点。）\n"
            if focus and focus.strip() else ""
        )
        system = _prompts.load("business_analysis.system")
        user = _prompts.render(
            "business_analysis.user",
            face_title=_FACE_TITLE.get(face, face),
            window_days=days,
            platform=platform,
            focus_block=focus_block,
            skeleton=skeleton_md,
        )
        cli = _AIHubClient()
        resp = await cli.chat(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            provider=provider, model=model, temperature=temperature,
            max_tokens=max_tokens, enforce_human_voice=True,
        )
        text = ((resp or {}).get("content") or (resp or {}).get("text") or "").strip() if isinstance(resp, dict) else ""
        if text and len(text) > 80:
            return text, True
        logger.warning("AI 叙事返回过短（回退骨架）len=%d", len(text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI 叙事失败（回退确定性骨架）: %s", exc)
    return skeleton_md, False


def _build_sections(result: dict, narrative_md: str, narrated: bool) -> list[dict]:
    """把确定性结构 + LLM 叙事拼成桌面可分层展开的 sections（AiAnalysisSection[]）。

    layer ∈ observation / hypothesis / recommendation / other。
    - 'other'「AI 综述」：放可读叙事（narrated 时是 LLM 写的；否则是确定性骨架）。
    - 'observation'：客观指标 + 异动，evidence 挂逐指标真值供下钻。
    - 'hypothesis'：模板化假设（R-14 非断言），evidence 挂证伪条件/口径警示。
    确定性段全部来自库内真值，绝不幻觉；叙事段已过 R-14 提示词约束。
    """
    observed = result.get("observed") or {}
    metrics = observed.get("metrics") or []
    anomalies = observed.get("anomalies") or []
    hyps = result.get("hypotheses") or []
    caveats = result.get("sample_caveats") or []

    sections: list[dict] = [{
        "layer": "other",
        "title": "AI 综述" + ("" if narrated else "（确定性骨架·AI 叙事不可用）"),
        "body": narrative_md,
    }]

    # 观察层：每个有数据的指标一条 bullet，evidence 挂逐指标真值
    have = [m for m in metrics if (m.get("n") or 0) > 0]
    if have:
        obs_lines, ev = [], []
        for m in have:
            obs_lines.append(_observed_line(m))
            ev.append(
                f"{m.get('cn')}({m.get('metric')})：最新 {_fmt_num(m.get('latest'))}{m.get('unit') or ''}"
                f"，{m.get('n')} 天序列，窗口首尾 {_fmt_delta(m.get('change_window_pct'))}"
                + (f"，后半vs前半 {_fmt_delta(m.get('mom_pct'))}" if m.get("mom_pct") is not None else "")
            )
        movers = observed.get("movers") or []
        body = "\n".join(obs_lines)
        if movers:
            body += "\n\n**动得明显的：** " + "；".join(movers)
        sections.append({
            "layer": "observation",
            "title": "观察到的（客观事实·库内真值，不含因果）",
            "body": body,
            "evidence": ev,
        })

    if anomalies:
        an_lines = [
            f"- [{a.get('severity') or '?'}] {reg.cn(a.get('metric_name') or '')}"
            f"（{a.get('metric_name')}）sku={a.get('sku_id')} {_fmt_delta(a.get('delta_pct'))}"
            f"（数据截至 {a.get('as_of') or '未标'}）"
            for a in anomalies
        ]
        sections.append({
            "layer": "observation",
            "title": "异动（异动引擎检出·未处理/非预期）",
            "body": "\n".join(an_lines),
            "evidence": [f"anomaly_id={a.get('id')}" for a in anomalies if a.get("id") is not None],
        })

    if hyps:
        hyp_body = "\n\n".join(
            f"**{h.get('cn')}（{h.get('metric')}）**\n{h.get('hypothesis')}" for h in hyps
        )
        sections.append({
            "layer": "hypothesis",
            "title": "可能的原因（假设·非断言，需按证伪条件自行验证）",
            "body": hyp_body,
            "evidence": caveats,
        })

    return sections


async def generate_business_analysis(
    face: str = "owner",
    days: int = 28,
    platform: str = PLATFORM_DEFAULT,
    polish: bool = False,
    focus: str | None = None,
) -> dict:
    """产出一份《综合经营分析》（确定性为主，R-14 强制分层 / R-15 样本量 / R-17 口径）。

    face：
      - 'owner'（老板面/经营诊断）：北极星（gmv/buyer/转化/uv/体验/排名/sov）+ 同行分位 + 异动。
      - 'operator'（操盘手面/投放选品建议）：5A 分层 + 货品结构 + 商品卡 + 搜索排名。
    days：分析窗口（默认 28 天）。platform：暂只 douyin 有数据（§8.5）。
    polish：True 时在确定性骨架之上再跑 **LLM 叙事层**（外置提示词
      `business_analysis.{system,user}.md`，把骨架当 ground truth；失败 fail-open 回退骨架）。
    focus：老板临时关注点，注入叙事提示词让总览优先回应（仅 polish 时生效）。

    返 {ok, face, window_days, platform, observed, hypotheses, sample_caveats,
        confidence, markdown, sections, as_of, narrated, polished, note}。
    - markdown：叙事文（narrated 时是 LLM 写的；否则确定性骨架）。
    - sections：桌面可分层展开视图（AiAnalysisSection[]，evidence 挂逐指标真值下钻）。
    """
    if face not in ("owner", "operator"):
        return {"ok": False, "error": "invalid_face", "hint": "face 需 ∈ {owner, operator}"}
    if days < 1 or days > 365:
        return {"ok": False, "error": "invalid_days", "hint": "days 需 ∈ [1, 365]"}

    metrics = reg.OWNER_FACE_METRICS if face == "owner" else reg.OPERATOR_FACE_METRICS
    pool = get_pool()
    try:
        blocks = [await _metric_block(pool, m, days, platform) for m in metrics]
        anomalies = await _recent_anomalies(pool, days, platform)
    except Exception as exc:
        logger.exception("generate_business_analysis 读库失败 face=%s", face)
        return {"ok": False, "error": f"read_failed: {exc}"}

    result = _build_analysis(face, blocks, anomalies, days, platform)
    skeleton_md = result["markdown"]

    narrated = False
    narrative_md = skeleton_md
    if polish:
        narrative_md, narrated = await _narrate(skeleton_md, face, days, platform, focus)
        result["markdown"] = narrative_md

    # 最新数据日期（as_of）：取所有指标里最大的 latest_date
    as_of = None
    for b in blocks:
        d = b.get("latest_date")
        if d and (as_of is None or d > as_of):
            as_of = d

    sections = _build_sections(result, narrative_md, narrated)

    # 执行过程透出（蓝图 §1.8 可观测 / 客户端"执行过程展开"）——确定性内部步骤，桌面时间线按步渲染。
    _face_cn = "经营诊断（老板面）" if face == "owner" else "投放选品（操盘手面）"
    _obs = result.get("observed") or {}
    _metrics_n = len(_obs.get("metrics") or []) if isinstance(_obs, dict) else 0
    _hyps = result.get("hypotheses") or []
    steps = [
        {"i": 1, "label": f"读取指标序列 · {_face_cn}",
         "detail": f"{len(metrics)} 指标 · 近 {days} 天 · {platform}", "status": "ok"},
        {"i": 2, "label": "对齐同行标杆",
         "detail": "mvp_industry_benchmark 同行均值/分位/排名", "status": "ok"},
        {"i": 3, "label": "拉取未处理异动",
         "detail": f"{len(anomalies)} 条", "status": "ok" if anomalies else "skip"},
        {"i": 4, "label": "R-14 强制分层骨架",
         "detail": f"观察 {_metrics_n} 指标 · 假设 {len(_hyps)} · 样本警示已附", "status": "ok"},
    ]
    if polish:
        steps.append({"i": 5, "label": "LLM 叙事层（骨架为 ground truth）",
                      "detail": "已生成" if narrated else "hub 不可用 → 回退确定性骨架",
                      "status": "ok" if narrated else "warn"})

    return {
        "ok": True,
        **result,
        "sections": sections,
        "steps": steps,
        "as_of": as_of,
        "narrated": narrated,
        "polished": narrated,  # 向后兼容旧字段名
        "focus": (focus or None),
        "note": ("综合经营分析：观察层=库内真值（不含因果），假设层=模板化（R-14 禁伪因果、非断言）。"
                 "单平台抖音口径（§8.5）。样本不足标 preliminary（R-15）。"
                 + ("AI 叙事层已生成（确定性骨架为 ground truth，禁新增数值/因果）。"
                    if narrated else "AI 叙事层未生成（hub 不可用/被禁），返回确定性骨架。")),
    }


# ───────────────────────── 临时问数（NL → metric 序列）─────────────────────────

# 时间窗解析：抓"近/最近 N 天/周/月" + "本周/本月/上周/上月/今天/昨天"等口语。
_NUM_DAYS_RE = re.compile(r"(?:近|最近|过去|前)\s*(\d+)\s*(天|日|周|星期|月|个月)")
_TIME_WORD = {
    "今天": 1, "昨天": 2, "本周": 7, "这周": 7, "上周": 14, "近一周": 7, "一周": 7,
    "本月": 30, "这个月": 30, "上月": 60, "近一月": 30, "一个月": 30, "近一个月": 30,
    "近三月": 90, "一季度": 90, "近半年": 180,
}


def _parse_window(question: str, default_days: int = 28) -> tuple[int, str]:
    """从问句解析时间窗（天）。返 (days, 解析说明)。"""
    m = _NUM_DAYS_RE.search(question)
    if m:
        n = int(m.group(1))
        unit_ = m.group(2)
        mult = {"天": 1, "日": 1, "周": 7, "星期": 7, "月": 30, "个月": 30}.get(unit_, 1)
        days = max(1, min(n * mult, 365))
        return days, f"近 {n}{unit_} → {days} 天"
    for word, d in _TIME_WORD.items():
        if word in question:
            return d, f"{word} → {d} 天"
    return default_days, f"未指定时间窗 → 默认 {default_days} 天"


# SKU 维度解析：抓 'SKU-xxxx' 形式；否则全店。
_SKU_RE = re.compile(r"(SKU-[0-9A-Za-z\-]+)", re.IGNORECASE)


def _summarize_series(block: dict, window_note: str) -> str:
    """一句话简述（确定性，不归因）。"""
    if block["n"] == 0:
        return (f"{block['cn']}（{block['metric']}）在该窗口无数据"
                f"（{window_note}）——可能未落库或该指标未抓。")
    bits = [f"{block['cn']} 最新 {_fmt_num(block['latest'])}{block['unit']}（{block['latest_date']}）"]
    if block["change_window_pct"] is not None:
        bits.append(f"窗口首尾 {_fmt_delta(block['change_window_pct'])}")
    if block.get("mom_pct") is not None:
        bits.append(f"后半段 vs 前半段 {_fmt_delta(block['mom_pct'])}")
    bits.append(f"{block['n']} 天序列、均值 {_fmt_num(block['period_avg'])}")
    tag = _conf_tag(block["n"])
    return tag + "；".join(bits) + f"（{window_note}）。"


async def query_metric_nl(
    question: str,
    default_days: int = 28,
    platform: str = PLATFORM_DEFAULT,
) -> dict:
    """临时问数：口语问句 → metric_name + 时间窗 + 维度 → 查 mvp_daily_metric 返序列 + 简述。

    确定性（不调 LLM、不归因）：
    - 解析 metric：metric_registry.resolve_metric（精确名 / 中文全名 / alias 子串）。
    - 解析时间窗：'近 N 天/周/月' + '本周/本月/今天…'，默认 default_days。
    - 解析维度：问句含 'SKU-xxxx' → 该 SKU；否则全店 '_SHOP_'。
    - 解析不出 metric → 返 ok=False + 候选清单（前端可让老板再说清）。

    返 {ok, question, metric_name, metric_cn, sku_id, platform, days, parse, series, summary, baseline, note}。
    """
    if not question or not question.strip():
        return {"ok": False, "error": "empty_question"}

    metric_name = reg.resolve_metric(question)
    if not metric_name:
        return {
            "ok": False, "error": "metric_not_resolved",
            "hint": "没听出要查哪个指标。已支持的指标（说中文名或 metric_name 都行）。",
            "supported": [{"metric": k, "cn": v["cn"]} for k, v in reg.METRIC_REGISTRY.items()],
        }
    # jd_ 指标只在 platform='jd' 有数据——自动切平台（问句含京东标记才会解析到 jd_）
    if metric_name.startswith("jd_"):
        platform = "jd"
    days, window_note = _parse_window(question, default_days)
    sku_m = _SKU_RE.search(question)
    sku_id = sku_m.group(1).upper() if sku_m else SHOP_SENTINEL

    pool = get_pool()
    try:
        if sku_id == SHOP_SENTINEL:
            block = await _metric_block(pool, metric_name, days, platform)
        else:
            block = await _metric_block_for_sku(pool, metric_name, sku_id, days, platform)
    except Exception as exc:
        logger.exception("query_metric_nl 读库失败 metric=%s", metric_name)
        return {"ok": False, "error": f"read_failed: {exc}"}

    return {
        "ok": True,
        "question": question,
        "metric_name": metric_name,
        "metric_cn": reg.cn(metric_name),
        "sku_id": sku_id,
        "platform": platform,
        "days": days,
        "parse": {
            "resolved_metric": metric_name,
            "window": window_note,
            "dimension": ("全店(_SHOP_)" if sku_id == SHOP_SENTINEL else sku_id),
        },
        "series": block["series"],
        "summary": _summarize_series(block, window_note),
        "baseline": {
            "n": block["n"], "latest": block["latest"], "first_value": block["first_value"],
            "period_avg": block["period_avg"], "prev_avg": block.get("prev_avg"),
            "change_window_pct": block["change_window_pct"], "mom_pct": block.get("mom_pct"),
        },
        "benchmark": block.get("benchmark"),
        "has_benchmark": bool(metric_name in reg.BENCHMARK_METRICS and block.get("benchmark")),
        "note": ("库内真实序列原样返回（mvp_daily_metric），不归因、不编造。"
                 "单平台抖音口径（§8.5）；覆盖已落库的 95 指标。"
                 + ("" if (metric_name in reg.BENCHMARK_METRICS and block.get("benchmark"))
                    else "（此指标暂无同行对比数据——没接同行基准、不是 bug；只返本店序列。）")),
    }


async def _metric_block_for_sku(
    pool, metric_name: str, sku_id: str, days: int, platform: str,
) -> dict:
    """同 _metric_block 但指定 SKU（非全店哨兵）。复用前者只是换 sku_id。"""
    now = _dt.datetime.now(_dt.timezone.utc)
    since = (now - _dt.timedelta(days=days)).date()
    rows = await pool.fetch(
        """
        SELECT date, value
        FROM mvp_daily_metric
        WHERE metric_name = $1 AND platform = $2 AND sku_id = $3 AND date >= $4
        ORDER BY date ASC
        """,
        metric_name, platform, sku_id, since,
    )
    series = [
        {"date": r["date"].isoformat() if r["date"] else None,
         "value": float(r["value"]) if r["value"] is not None else None}
        for r in rows
    ]
    vals = [(s["date"], s["value"]) for s in series if s["value"] is not None]
    n = len(vals)
    block: dict[str, Any] = {
        "metric": metric_name, "cn": reg.cn(metric_name), "unit": reg.unit(metric_name),
        "direction": reg.direction(metric_name), "n": n,
        "latest": None, "latest_date": None, "first": None, "first_value": None,
        "change_window_pct": None, "period_avg": None, "prev_avg": None, "mom_pct": None,
        "benchmark": None, "series": series,
    }
    if not vals:
        return block
    block["first_value"], block["first"] = vals[0][1], vals[0][0]
    block["latest"], block["latest_date"] = vals[-1][1], vals[-1][0]
    block["change_window_pct"] = _pct(vals[-1][1], vals[0][1])
    block["period_avg"] = round(sum(v for _, v in vals) / n, 6)
    half = n // 2
    if half >= _MIN_COMPARE_HALF:
        prev_avg = sum(v for _, v in vals[:half]) / half
        cur_avg = sum(v for _, v in vals[half:]) / (n - half)
        block["prev_avg"] = round(prev_avg, 6)
        block["period_avg"] = round(cur_avg, 6)
        block["mom_pct"] = _pct(cur_avg, prev_avg)
    return block
