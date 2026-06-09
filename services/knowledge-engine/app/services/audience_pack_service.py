"""人群包投前诊断 + 提纯 service（蓝图 §6 分析半 · 方法论沉淀）。

老板痛点（《和田宽人群包评估方法论》）：和田宽是高端日式发酵调味品，**出厂价已 ≥ 竞品
线上零售价，打不了价格战**。投放靠"做用户喜欢的内容 → 软植入 → 深度种草 → 收割"。所以做
内容/投放**之前**必须判断一个人群包适不适合——这群"会被内容打动"的人必须是**真需求**。

数据：两份同结构画像（`标签类型 / 标签 / 占比 / TGI`）：
- **行业 A4**：一个月内真实购买过酱油的人（基准）= **真需求标尺**（不是提纯工具、不是模仿对象）。
- **候选包**（如"地域寻味人"）：一个候选投放包。

本 service 实现《02 人群包对比诊断说明书》的确定性引擎（镜像 business_analysis_service 的
"确定性骨架 + 可选 LLM 叙事"套路，R-14 强制分层禁伪因果）：

1. diagnose_audience_pack(candidate, baseline)：逐维度算候选 vs A4 的相对指数 → 投前诊断卡。
   **方法论主线（确定性映射，不靠 LLM 编）**：
   - **比对看方向，不算总相似分**（一个总分会把"高端增益"和"价值流失"两件相反的事抹平）。
   - **价值维（付得起）** = 消费力/城市/手机价位 → 期望**正向偏离 A4**（高端尾部）；
     贴近 A4 均值是反的（A4 大多价格敏感，恰是和田宽最打不动的人）。
   - **购买行为维（软硬）** = 线上客单/购买频次 → 比 A4 软 = 种草信号（非扣分，定漏斗位）。
   - **需求维（真需求）** = 品类成交/品牌/兴趣/触点 → 期望**重叠 A4 真需求指纹**
     （品类锚 TGI 1300+ / 兴趣锚 220–280 / 触点锚 300–490）。重叠高 = 真需求强。
   - **身份维（谁）** = 八大消费群体/年龄/性别/职业/人生阶段 → **差异不计**（构成不同 ≠ 质量缺口）。
   - **噪音维** = 手机品牌/活跃用户等 → 忽略。
   → 输出**漏斗定位**（种草型/收割型/价值流失警告）+ **内容策略定调**（可 KB grounding）。

2. 可选《01 提纯施工单》（with_purify_plan=True）：**提纯优先级阶梯**（**A4 不参与**）：
   不限刀数，**按漏斗定位排序**（种草型先非电商需求/内容，收割型先高客单/品类成交），
   每刀落到画像里**真实可勾的巨量云图标签**（数据工厂维度+值）+ 标**是否电商成交数据**
   （⚠电商刀只能上品牌广告、不能上非品牌广告；✅非电商刀可上非品牌广告投放范围更大）。
   老板一刀一刀切、每刀去云图看覆盖人数，不满意把缩窄后画像重导出再跑做二次提纯。

反幻觉/口径铁律（写进每份诊断卡第四节）：**画像比对只是投前的冷启动代理**——能判断圈选合不
合理、生成"先测哪些细分"的假设，但**判断不了真实投放价值**；真实价值只有 CTR/CVR/ROI/GMV
说了算（方法论 §二.8）。observation 全是画像里的真数字；hypothesis 标"假设 + 要证实需对比 X"。
同 service 函数被 MCP tool 与（未来）REST 共用（禁漂移）。
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

from app.services.diagnose_service import _fmt_num

# LLM 叙事层 + 巨量云图 KB grounding 依赖（fail-open：缺任一不影响确定性骨架）
try:  # pragma: no cover - import 容错
    from app.mcp import prompts as _prompts
    from app.mcp.model_config import get_model_for_tool as _get_model
    from app.services.ai_hub_client import AIHubClient as _AIHubClient
except Exception:  # noqa: BLE001
    _prompts = None
    _get_model = None
    _AIHubClient = None

logger = logging.getLogger(__name__)

# 画像数据目录（bundled 静态标尺 + 老板导出的候选包都放这；bind-mount 进容器 /app/config/audience/）
_AUDIENCE_DIR: Path = Path(__file__).resolve().parents[2] / "config" / "audience"
# 老板可另配一个 dropbox 目录（导出 CSV 丢这），缺省回退 bundled 目录
_EXTRA_DIR = os.environ.get("OMNI_AUDIENCE_PACK_DIR", "").strip()

# ───────────────────────── 四维 + 五维分类（方法论主线）─────────────────────────

# 价值维（付得起）：每维"高端尾部"标签匹配器。候选在尾部的占比和 应 > A4 = 正向偏离高端。
_VALUE_DIMS: list[dict] = [
    {"type": "预测消费能力", "cn": "消费力", "tail": lambda l: l == "高消费"},
    {"type": "城市等级", "cn": "城市层级（高线）", "tail": lambda l: l.endswith("一线城市")},
    {"type": "手机价格", "cn": "手机价位（高端机）", "tail": lambda l: _lead_int(l) >= 5000},
]
# 购买行为维（线上实际购买软硬）：高端尾部 = 高客单 / 高频次。
# 候选 < A4 = 购买行为更软 = 种草信号（非扣分，定漏斗位，方法论"购买力高但线上实际购买更软"）。
_BEHAVIOR_DIMS: list[dict] = [
    {"type": "电商消费金额", "cn": "线上客单（高客单占比）", "tail": lambda l: "+∞" in l},
    {"type": "电商消费频次", "cn": "线上购买频次（高频占比）", "tail": lambda l: "+∞" in l},
]
# 需求维（真需求）：期望重叠 A4 真需求指纹（高 TGI 锚）。anchor_tgi=该维"算锚"的 TGI 下限。
_DEMAND_DIMS: list[dict] = [
    {"type": "电商品类成交偏好", "cn": "品类成交", "weight": 3, "band": "品类锚 TGI 1300+"},
    {"type": "电商品牌成交偏好", "cn": "品牌成交", "weight": 1, "band": "品牌锚"},
    {"type": "触点互动偏好", "cn": "广告触点", "weight": 2, "band": "触点锚 TGI 300–490"},
    {"type": "抖音视频观看兴趣分类v2", "cn": "抖音兴趣", "weight": 2, "band": "兴趣锚 TGI 220–280"},
    {"type": "抖音视频观看兴趣分类", "cn": "抖音兴趣（细分）", "weight": 1, "band": "兴趣锚"},
    {"type": "头条用户阅读兴趣分类", "cn": "头条兴趣", "weight": 1, "band": "兴趣锚"},
    {"type": "西瓜视频观看兴趣分类", "cn": "西瓜兴趣", "weight": 1, "band": "兴趣锚"},
]
# 身份维（谁）：差异不计，只客观描述。
_IDENTITY_DIMS: list[dict] = [
    {"type": "八大消费群体", "cn": "八大消费群体"},
    {"type": "预测人生阶段", "cn": "人生阶段"},
    {"type": "预测年龄段", "cn": "年龄段"},
    {"type": "预测性别", "cn": "性别"},
    {"type": "预测职业", "cn": "职业"},
    {"type": "地域分布", "cn": "地域分布"},
]

# 真需求指纹提取参数：A4 里 TGI ≥ floor、占比 ≥ 0.3% 的标签，按 TGI 降序取 top-K 当锚。
_DEMAND_FLOOR = 120.0       # 高于此 TGI 才算"明显偏好"
_DEMAND_TOPK = 12
_MIN_ANCHOR_SHARE = 0.003   # 0.3%，剔除微量噪声标签
_RETAIN_TGI = 100.0         # 候选在某锚的 TGI ≥ 100（高于大盘均值）= 留住该真需求信号
_STRONG_TGI = 150.0
# 方向阈值（占比差 > 5 个百分点才算"动了"）
_DIR_EPS = 0.05
# R-15 样本量（一个维度可用标签 < 此值 → 该维结论标"待验证"）
_SAMPLE_THRESHOLD = 5


# ───────────────────────── 解析 ─────────────────────────


def _lead_int(label: str) -> int:
    """抽标签里第一个整数（'10000及以上'→10000，'5000~5999'→5000，无→-1）。"""
    m = re.search(r"\d+", label or "")
    return int(m.group(0)) if m else -1


def _parse_share(s: str) -> float:
    """'35.22%' → 0.3522；'0' / '' / '-' → 0.0。"""
    s = (s or "").strip().rstrip("%").strip()
    if not s or s == "-":
        return 0.0
    try:
        return float(s) / 100.0
    except ValueError:
        return 0.0


def _parse_tgi(s: str) -> float | None:
    """'143.2' → 143.2；'-' / '' → None（缺失，不当 0）。"""
    s = (s or "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_profile_csv(text: str) -> dict:
    """解析画像 CSV 文本 → {display_name, by_type:{标签类型:{标签:{share,tgi}}}, n_rows}。

    Header 形如 `标签类型,标签,<包名>-占比,<包名>-tgi`；display_name = 第3列去掉 '-占比'。
    确定性、容错（缺列/'-' 安全）。
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return {"display_name": "(空)", "by_type": {}, "n_rows": 0}
    header = [h.strip() for h in lines[0].split(",")]
    display_name = "候选包"
    if len(header) >= 3:
        display_name = re.sub(r"[-_]?占比$", "", header[2]).strip() or "候选包"
    by_type: dict[str, dict[str, dict]] = {}
    n = 0
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) < 4:
            continue
        ttype = parts[0].strip()
        label = parts[1].strip()
        if not ttype or not label:
            continue
        by_type.setdefault(ttype, {})[label] = {
            "share": _parse_share(parts[2]),
            "tgi": _parse_tgi(parts[3]),
        }
        n += 1
    return {"display_name": display_name, "by_type": by_type, "n_rows": n}


def _candidate_dirs() -> list[Path]:
    dirs = [_AUDIENCE_DIR]
    if _EXTRA_DIR:
        p = Path(_EXTRA_DIR)
        if p != _AUDIENCE_DIR:
            dirs.insert(0, p)
    return dirs


def _list_bundled() -> list[str]:
    seen: list[str] = []
    for d in _candidate_dirs():
        if d.exists():
            for f in sorted(d.glob("*.csv")):
                if f.stem not in seen:
                    seen.append(f.stem)
    return seen


def _resolve_profile(spec: str) -> tuple[dict | None, str]:
    """把 candidate/baseline 参数解析成 parsed profile。

    spec 可以是：① 内置/dropbox 里的文件名（'baseline_a4' / 'diyu_xunwei' / 'x.csv'）；
    ② 容器可达的绝对路径；③ 原始 CSV 文本（含 '标签类型,'）。
    返 (parsed | None, source_note)。
    """
    spec = (spec or "").strip()
    if not spec:
        return None, "empty"
    # ③ 原始 CSV 文本
    if "标签类型" in spec and "\n" in spec:
        return _parse_profile_csv(spec), "inline_csv"
    # ② 绝对路径
    p = Path(spec)
    if p.suffix.lower() == ".csv" and p.exists():
        return _parse_profile_csv(p.read_text(encoding="utf-8", errors="ignore")), f"path:{p}"
    # ① 内置/dropbox 文件名
    stem = spec[:-4] if spec.lower().endswith(".csv") else spec
    for d in _candidate_dirs():
        f = d / f"{stem}.csv"
        if f.exists():
            return _parse_profile_csv(f.read_text(encoding="utf-8", errors="ignore")), f"bundled:{f.name}"
    return None, f"not_found:{spec}"


# ───────────────────────── 价值维 / 购买行为维 ─────────────────────────


def _tail_share(prof: dict, ttype: str, match: Callable[[str], bool]) -> tuple[float, int]:
    """某维度"匹配尾部"的占比和 + 该维有效标签数。"""
    labels = prof.get("by_type", {}).get(ttype, {})
    total = sum(v["share"] for lab, v in labels.items() if match(lab))
    return round(total, 6), len(labels)


def _value_axis(cand: dict, base: dict) -> list[dict]:
    """价值维：候选高端尾部占比 vs A4，正向偏离 = 好（高端）。"""
    out: list[dict] = []
    for d in _VALUE_DIMS:
        c, cn_ = _tail_share(cand, d["type"], d["tail"])
        b, _bn = _tail_share(base, d["type"], d["tail"])
        delta = c - b
        verdict = "正向偏离" if delta > _DIR_EPS else ("流失" if delta < -_DIR_EPS else "持平")
        out.append({
            "type": d["type"], "cn": d["cn"], "cand": c, "base": b,
            "delta": round(delta, 6), "verdict": verdict, "n_labels": cn_,
        })
    return out


def _behavior_axis(cand: dict, base: dict) -> list[dict]:
    """购买行为维：候选高客单/高频尾部 vs A4。候选更低 = 购买更软（种草信号，非扣分）。"""
    out: list[dict] = []
    for d in _BEHAVIOR_DIMS:
        c, cn_ = _tail_share(cand, d["type"], d["tail"])
        b, _bn = _tail_share(base, d["type"], d["tail"])
        delta = c - b
        verdict = "更软" if delta < -_DIR_EPS else ("更硬" if delta > _DIR_EPS else "相当")
        out.append({
            "type": d["type"], "cn": d["cn"], "cand": c, "base": b,
            "delta": round(delta, 6), "verdict": verdict, "n_labels": cn_,
        })
    return out


def _value_verdict(value_rows: list[dict]) -> str:
    pos = sum(1 for r in value_rows if r["verdict"] == "正向偏离")
    neg = sum(1 for r in value_rows if r["verdict"] == "流失")
    if neg >= 2 or (neg >= 1 and pos == 0):
        return "偏离低端(价值流失)"
    if pos >= 2:
        return "正向偏离高端"
    if pos >= 1 and neg == 0:
        return "略偏高端"
    return "持平"


def _behavior_verdict(beh_rows: list[dict]) -> str:
    soft = sum(1 for r in beh_rows if r["verdict"] == "更软")
    hard = sum(1 for r in beh_rows if r["verdict"] == "更硬")
    if soft >= 1 and hard == 0:
        return "更软(潜在)"
    if hard >= 1 and soft == 0:
        return "更硬(即时)"
    return "相当"


# ───────────────────────── 需求维：真需求指纹重叠 ─────────────────────────


def _fingerprint(base: dict, ttype: str) -> list[dict]:
    """从 A4 提该维真需求指纹锚：TGI ≥ floor、占比 ≥ 0.3%，按 TGI 降序取 top-K。"""
    labels = base.get("by_type", {}).get(ttype, {})
    cands = [
        {"label": lab, "tgi": v["tgi"], "share": v["share"]}
        for lab, v in labels.items()
        if v["tgi"] is not None and v["tgi"] >= _DEMAND_FLOOR and v["share"] >= _MIN_ANCHOR_SHARE
    ]
    cands.sort(key=lambda x: x["tgi"], reverse=True)
    return cands[:_DEMAND_TOPK]


def _demand_axis(cand: dict, base: dict) -> list[dict]:
    """需求维：逐维度算候选对 A4 真需求指纹的重叠（留住率 + 锚均 TGI）。"""
    out: list[dict] = []
    for d in _DEMAND_DIMS:
        anchors = _fingerprint(base, d["type"])
        cand_labels = cand.get("by_type", {}).get(d["type"], {})
        retained = 0
        strong = 0
        cand_tgis: list[float] = []
        anchor_detail: list[dict] = []
        for a in anchors:
            cv = cand_labels.get(a["label"], {})
            ctgi = cv.get("tgi")
            kept = ctgi is not None and ctgi >= _RETAIN_TGI
            if kept:
                retained += 1
            if ctgi is not None and ctgi >= _STRONG_TGI:
                strong += 1
            if ctgi is not None:
                cand_tgis.append(ctgi)
            anchor_detail.append({
                "label": a["label"], "a4_tgi": round(a["tgi"], 1),
                "cand_tgi": round(ctgi, 1) if ctgi is not None else None, "kept": kept,
            })
        n_anchor = len(anchors)
        overlap = (retained / n_anchor) if n_anchor else 0.0
        mean_cand = round(sum(cand_tgis) / len(cand_tgis), 1) if cand_tgis else None
        if n_anchor == 0:
            verdict = "无锚(缺数据)"
        elif overlap >= 0.6 or (mean_cand is not None and mean_cand >= _STRONG_TGI):
            verdict = "重叠强"
        elif overlap >= 0.35 or (mean_cand is not None and mean_cand >= _RETAIN_TGI):
            verdict = "重叠中"
        else:
            verdict = "重叠软"
        out.append({
            "type": d["type"], "cn": d["cn"], "band": d["band"], "weight": d["weight"],
            "n_anchor": n_anchor, "retained": retained, "strong": strong,
            "overlap": round(overlap, 3), "mean_cand_tgi": mean_cand, "verdict": verdict,
            "anchors": anchor_detail,
        })
    return out


def _demand_verdict(demand_rows: list[dict]) -> str:
    """加权重叠（品类权重最高）→ 强/中/软。"""
    num = 0.0
    den = 0.0
    for r in demand_rows:
        if r["n_anchor"] == 0:
            continue
        num += r["overlap"] * r["weight"]
        den += r["weight"]
    if den == 0:
        return "缺数据"
    w = num / den
    if w >= 0.6:
        return "强"
    if w >= 0.35:
        return "中"
    return "软"


# ───────────────────────── 身份维（差异不计·只描述）─────────────────────────


def _top_labels(prof: dict, ttype: str, k: int = 3) -> list[tuple[str, float]]:
    labels = prof.get("by_type", {}).get(ttype, {})
    rows = sorted(labels.items(), key=lambda kv: kv[1]["share"], reverse=True)
    return [(lab, v["share"]) for lab, v in rows[:k] if v["share"] > 0]


def _identity_rows(cand: dict, base: dict) -> list[dict]:
    out: list[dict] = []
    for d in _IDENTITY_DIMS:
        out.append({
            "type": d["type"], "cn": d["cn"],
            "cand_top": _top_labels(cand, d["type"]),
            "base_top": _top_labels(base, d["type"]),
        })
    return out


# ───────────────────────── 漏斗定位 + 内容策略 ─────────────────────────


def _position(value_v: str, behavior_v: str, demand_v: str) -> dict:
    """三维 verdict → 漏斗定位 + 一句话定调（确定性规则，方法论 §三 判读）。"""
    if value_v == "偏离低端(价值流失)":
        return {
            "label": "价值流失·慎投",
            "why": ("候选包比 A4 更价格敏感——A4 本就是价格敏感大盘，而和田宽出厂价已 ≥ 竞品零售价、"
                    "打不了价格战，这类人正是你最打不动的。除非有极强内容能撬动，否则不建议作主力包。"),
            "funnel": "不建议（或先极小预算验证内容能否撬动）",
        }
    if demand_v == "强" and behavior_v in ("更硬(即时)", "相当"):
        return {
            "label": "即投/收割型",
            "why": ("付得起 + 真需求强 + 线上购买行为不软——重叠 A4 验证过的真需求指纹高，"
                    "可较快进收割，内容唤醒担子轻。"),
            "funnel": "A4 行动收割为主，A3 共鸣兜底",
        }
    if demand_v == "软" or behavior_v == "更软(潜在)":
        return {
            "label": "种草型",
            "why": ("付得起、打得动，但线上实际购买比验证过的品类买家更软 / 需求偏潜在——"
                    "内容从唤醒做起，收割别急，转化担子在内容上，别指望它像 A4 一投就收割。"),
            "funnel": "A2 触动 → A3 共鸣种草为主，A4 收割压后",
        }
    return {
        "label": "种草偏收割（中间型）",
        "why": "付得起 + 需求中等——以种草养意愿为主、择机收割。",
        "funnel": "A3 共鸣为主，择机 A4 收割",
    }


# ───────────────────────── 提纯施工单（优先级阶梯，A4 不参与）─────────────────────────

# 内容兴趣类（非电商交易数据：抖音/头条/西瓜观看兴趣分类）
_INTEREST_TYPES = (
    "抖音视频观看兴趣分类v2", "抖音视频观看兴趣分类",
    "头条用户阅读兴趣分类", "西瓜视频观看兴趣分类",
)

# 每把"刀"的定义：name / rule / ecommerce（是否引入电商成交数据 → 破坏非品牌广告资格）。
_CUT_DEFS: dict[str, dict] = {
    "value": {
        "name": "价值/付得起（切到死）", "ecommerce": False,
        "rule": "付得起内容补不了，价格敏感的切到死，只留高端尾部。消费力/城市/手机价位都是用户属性，非电商数据。",
        "placeholder": "（价值维高端尾部标签缺失，先确认画像导出是否完整）",
    },
    "interest": {
        "name": "需求相邻·内容兴趣（非电商）", "ecommerce": False,
        "rule": "用抖音/头条/西瓜观看兴趣分类交集到\"会下厨/讲究吃\"，非电商交易数据，不影响非品牌广告资格。",
        "placeholder": "（兴趣锚留存偏弱，建议靠内容偏好 + 关键词包收紧）",
    },
    "touch": {
        "name": "内容亲和·广告触点（非电商）", "ecommerce": False,
        "rule": "按高 TGI 广告触点收紧，留平时就爱看做饭/家庭内容的人。目的地是云图数据工厂 / 自定义人群。",
        "placeholder": "（触点锚留存偏弱，建议靠内容偏好收紧）",
    },
    "category": {
        "name": "需求相邻·品类成交（⚠电商）", "ecommerce": True,
        "rule": "交集买过相邻品类（食用油调味油 / 调味品果酱沙拉等）——最准但属电商成交数据。切到\"会下厨\"，不切到\"已买酱油\"（那是收割层 filter）。",
        "placeholder": "（品类成交锚留存偏弱，提纯空间有限，建议保量靠内容唤醒）",
    },
    "brand": {
        "name": "需求相邻·品牌成交（⚠电商）", "ecommerce": True,
        "rule": "交集买过同类 / 高端调味品牌——电商成交数据。",
        "placeholder": "（品牌成交锚留存偏弱，跳过）",
    },
    "behavior": {
        "name": "购买行为·高客单高频（⚠电商）", "ecommerce": True,
        "rule": "保留高客单 / 高频次档——强买意图，属电商交易数据，慎用于种草包。",
        "placeholder": "（线上客单/频次高端尾部标签缺失，确认画像导出是否完整）",
    },
}

# 优先级随漏斗定位重排（同一刀对不同功能的包优先级不同——老板明确要求）。
# 原则：提质高 + 不伤包性质的刀排前面；电商刀（污染非品牌广告资格）默认压后，收割型例外。
_PURIFY_ORDER: dict[str, list[str]] = {
    "价值流失·慎投": ["value", "interest", "touch", "category", "brand", "behavior"],
    "即投/收割型": ["behavior", "category", "value", "brand", "interest", "touch"],
    "种草型": ["interest", "touch", "value", "category", "brand", "behavior"],
    "种草偏收割（中间型）": ["interest", "value", "touch", "category", "brand", "behavior"],
}
_DEFAULT_ORDER = "种草偏收割（中间型）"
_PURIFY_RATIONALE: dict[str, str] = {
    "价值流失·慎投": "这包本就偏价格敏感，先把买不起的切到死（价值刀），其余靠内容唤醒。",
    "即投/收割型": "核心价值是强买意图，先保高客单/品类成交（即便含电商数据），内容兴趣最后才动。",
    "种草型": "怕误杀\"潜在真需求但还没买\"的人，先用非电商需求/内容信号收，电商刀压最后（且会破坏非品牌广告资格）。",
    "种草偏收割（中间型）": "以非电商需求 + 价值为主收窄，电商刀压后当兜底。",
}


def _value_cut_actions(cand: dict) -> list[str]:
    out: list[str] = []
    for d in _VALUE_DIMS:
        labels = cand.get("by_type", {}).get(d["type"], {})
        kept = [lab for lab in labels if d["tail"](lab)]
        if kept:
            out.append(f"{d['cn']}（数据工厂 → {d['type']}）：保留 {('、'.join(kept))}")
    return out


def _behavior_cut_actions(cand: dict) -> list[str]:
    out: list[str] = []
    for d in _BEHAVIOR_DIMS:
        labels = cand.get("by_type", {}).get(d["type"], {})
        kept = [lab for lab in labels if d["tail"](lab)]
        if kept:
            out.append(f"{d['cn']}（数据工厂 → {d['type']}）：保留 {('、'.join(kept))}")
    return out


def _demand_cut_actions(demand_rows: list[dict], types: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for r in demand_rows:
        if r["type"] not in types:
            continue
        kept = [a["label"] for a in r["anchors"] if a["kept"]][:6]
        if kept:
            out.append(f"{r['cn']}（数据工厂 → {r['type']}）：交集 {('、'.join(kept))}")
    return out


def _purify_plan(
    cand: dict, value_rows: list[dict], beh_rows: list[dict],
    demand_rows: list[dict], position: dict,
) -> dict:
    """《01 提纯施工单》优先级阶梯：按漏斗定位排序的 N 刀（不限刀数），每刀落到画像里
    **真实可勾的巨量云图标签**（数据工厂维度 + 值），并标**是否引入电商成交数据**。

    核心（老板要求）：
    - **不限三刀** —— 把所有可切的杠杆都列出来，老板能不断测、一刀一刀往下切。
    - **优先级随包功能（漏斗定位）重排** —— 同一刀对种草型 / 收割型 / 价值流失型的先后不同。
    - **每刀标电商资格** —— 含电商成交数据的刀（品类/品牌成交、高客单高频）只能上品牌广告，
      不能上传非品牌广告；要走非品牌广告（投放范围更大）就只用非电商刀。
    - **A4 不参与提纯**（它是真需求标尺，不是提纯工具）。
    """
    label = position.get("label", _DEFAULT_ORDER)
    order = _PURIFY_ORDER.get(label, _PURIFY_ORDER[_DEFAULT_ORDER])
    builders: dict[str, Callable[[], list[str]]] = {
        "value": lambda: _value_cut_actions(cand),
        "interest": lambda: _demand_cut_actions(demand_rows, _INTEREST_TYPES),
        "touch": lambda: _demand_cut_actions(demand_rows, ("触点互动偏好",)),
        "category": lambda: _demand_cut_actions(demand_rows, ("电商品类成交偏好",)),
        "brand": lambda: _demand_cut_actions(demand_rows, ("电商品牌成交偏好",)),
        "behavior": lambda: _behavior_cut_actions(cand),
    }
    cuts: list[dict] = []
    for rank, lever in enumerate(order, start=1):
        d = _CUT_DEFS[lever]
        actions = builders[lever]() or [d["placeholder"]]
        cuts.append({
            "rank": rank, "lever": lever, "name": f"第 {rank} 刀 · {d['name']}",
            "rule": d["rule"], "ecommerce": d["ecommerce"], "actions": actions,
        })
    return {
        "funnel": label,
        "order_rationale": _PURIFY_RATIONALE.get(label, _PURIFY_RATIONALE[_DEFAULT_ORDER]),
        "ecommerce_note": ("标 ⚠电商 的刀会让人群包含电商成交数据 → **只能上品牌广告，不能上传非品牌广告**。"
                           "要走非品牌广告（可投范围更大）就只用 ✅非电商 的刀，电商刀跳过。"),
        "cuts": cuts,
        "note": ("不限刀数，按优先级从上往下切；**每切完去云图看实际覆盖人数**，量级不满意就把缩窄后的"
                 "画像重新导出再跑一次本工具做**二次提纯**。A4 不参与提纯（它是真需求标尺）。"),
    }


# ───────────────────────── 巨量云图 KB grounding（叙事层用）─────────────────────────


async def _gather_yuntu_kb(position_label: str, cand_name: str) -> list[dict]:
    """召回巨量云图/人群方法论 KB（methodology + authoritative），给内容策略叙事当料。

    复用 search_kb 同一检索路径（禁漂移）：按 kb_role 解析 kb_ids → retrieve_multi_kb。
    fail-open：缺依赖 / 召回失败 → 返 []（叙事层降级，不影响确定性骨架）。
    """
    try:
        from app.services import ingestion as _ingestion
        from app.services.rag_chain import retrieve_multi_kb
    except Exception as exc:  # noqa: BLE001
        logger.debug("KB grounding import failed: %s", exc)
        return []
    try:
        all_kbs = await _ingestion.list_kbs()
        wanted_roles = {"methodology", "authoritative"}
        kb_ids = [k["id"] for k in all_kbs if k.get("kb_role") in wanted_roles]
        if not kb_ids:
            return []
        query = (
            f"巨量云图 {position_label} 人群打法 5A 漏斗 种草 软广 内容唤醒 "
            f"高端发酵调味品 真需求 提纯 标签 数据工厂"
        )
        snippets = await retrieve_multi_kb(
            query, kb_ids,
            top_k_per_kb=4, min_per_kb=0, score_threshold=0.25, total_limit=8,
        )
        for s in snippets:
            c = s.get("content") or ""
            if len(c) > 500:
                s["content"] = c[:500] + "..."
        return snippets
    except Exception as exc:  # noqa: BLE001
        logger.warning("巨量云图 KB grounding 召回失败（叙事降级）: %s", exc)
        return []


def _kb_block(snippets: list[dict]) -> str:
    """KB 片段 → 注入块（按 kb-prompt-guide 格式，带来源 + score）。"""
    if not snippets:
        return "（无 KB 召回——内容策略只给方法论通用骨架，标 [行业推理]，不编 KB 没有的打法）"
    lines = ["## 可用知识库材料（巨量云图/方法论，只能用这里的，没有的不许编）"]
    for s in snippets:
        src = s.get("kb_name") or s.get("source") or "KB"
        sc = s.get("score")
        sc_s = f"（score {sc:.2f}）" if isinstance(sc, (int, float)) else ""
        lines.append(f"- [来源:{src}] {(s.get('content') or '').strip()}{sc_s}")
    return "\n".join(lines)


# ───────────────────────── R-14 分层骨架 + sections ─────────────────────────


def _fmt_pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "—"


def _fmt_ppt(x: float | None) -> str:
    """占比差（百分点）。"""
    return f"{x * 100:+.1f}pp" if x is not None else "—"


def _build_diagnosis(
    cand: dict, base: dict, value_rows: list[dict], beh_rows: list[dict],
    demand_rows: list[dict], identity_rows: list[dict],
    value_v: str, behavior_v: str, demand_v: str, position: dict,
    purify: dict | None,
) -> dict:
    """确定性映射成《投前诊断卡》结构（R-14 强制分层，不调 LLM）。"""
    cand_name = cand.get("display_name", "候选包")
    base_name = base.get("display_name", "行业A4")

    lines: list[str] = [
        f"# 投前诊断卡 · {cand_name}",
        f"> 标尺 = {base_name}（真需求基准，不是提纯工具/模仿对象）· "
        f"方法论：比对看方向，不算总相似分",
        "",
        "## 一、观察到的（客观，带数据，不含因果）",
        "",
        "**价值维（付得起 → 期望正向偏离 A4 高端）**",
    ]
    for r in value_rows:
        lines.append(
            f"- {r['cn']}：候选 {_fmt_pct(r['cand'])} vs A4 {_fmt_pct(r['base'])}"
            f"（{_fmt_ppt(r['delta'])}，{r['verdict']}）"
        )
    lines.append(f"  → 价值维小结：**{value_v}**")
    lines += ["", "**购买行为维（线上实际购买软硬 → 比 A4 软 = 种草信号，非扣分）**"]
    for r in beh_rows:
        lines.append(
            f"- {r['cn']}：候选 {_fmt_pct(r['cand'])} vs A4 {_fmt_pct(r['base'])}"
            f"（{_fmt_ppt(r['delta'])}，{r['verdict']}）"
        )
    lines.append(f"  → 购买行为小结：**{behavior_v}**")
    lines += ["", "**需求维（真需求 → 期望重叠 A4 真需求指纹）**"]
    for r in demand_rows:
        if r["n_anchor"] == 0:
            lines.append(f"- {r['cn']}（{r['band']}）：A4 无可用锚（该维缺数据），跳过")
            continue
        mean_s = f"，锚均 TGI {r['mean_cand_tgi']}" if r["mean_cand_tgi"] is not None else ""
        lines.append(
            f"- {r['cn']}（{r['band']}）：留住 A4 真需求锚 {r['retained']}/{r['n_anchor']}"
            f"（重叠 {r['overlap']:.0%}{mean_s}）→ **{r['verdict']}**"
        )
    lines.append(f"  → 需求维小结：**重叠{demand_v}**" if demand_v in ("强", "中", "软") else f"  → 需求维小结：**{demand_v}**")
    lines += ["", "**身份维（谁 → 差异不计，构成不同 ≠ 质量缺口，仅描述）**"]
    for r in identity_rows:
        ct = "、".join(f"{lab} {_fmt_pct(sh)}" for lab, sh in r["cand_top"][:2]) or "—"
        bt = "、".join(f"{lab} {_fmt_pct(sh)}" for lab, sh in r["base_top"][:2]) or "—"
        lines.append(f"- {r['cn']}：候选[{ct}] · A4[{bt}]")

    # —— 二、漏斗定位（数据形态 → 定位，规则透明）——
    lines += [
        "", "## 二、漏斗定位（价值维方向 + 购买软硬 + 需求重叠 → 定位规则）",
        f"- **定位：{position['label']}**",
        f"- 依据：价值={value_v}｜购买行为={behavior_v}｜需求重叠={demand_v}",
        f"- 读法：{position['why']}",
        f"- 建议漏斗位：{position['funnel']}",
    ]

    # —— 三、内容策略定调 + 可能的原因（假设·非断言）——
    lines += [
        "", "## 三、内容策略定调（假设·非断言；要证实需对比真实转化）",
        f"- 定调跟着「{position['label']}」走：{position['funnel']}。",
        "- 这是**画像形态推出的内容方向假设**，不是结论；混杂因子（季节/竞品/创意本身好坏/出价）未排除。",
        "- **要证实需对比**：按这个定调做 2–3 条内容小预算测，看 A3 转化 / CTR / CVR，转化了再放量。",
    ]

    # —— 四、提纯施工单（优先级阶梯 · 可选）——
    if purify:
        lines += [
            "", "## 四、提纯施工单（优先级阶梯 · A4 不参与）",
            f"> 排序按漏斗定位「{purify['funnel']}」：{purify['order_rationale']}",
            f"> {purify['ecommerce_note']}",
        ]
        for c in purify["cuts"]:
            tag = "⚠电商（仅品牌广告）" if c["ecommerce"] else "✅非电商（可上非品牌广告）"
            lines.append(f"### {c['name']}　｜　{tag}")
            lines.append(f"> {c['rule']}")
            for act in c["actions"]:
                lines.append(f"- {act}")
            lines.append("")
        lines.append(f"> {purify['note']}")
        caveat_idx = "五"
    else:
        caveat_idx = "四"

    # —— 口径与样本量警示（R-15 / R-17 / 方法论 §二.8）——
    missing_dims = [r["cn"] for r in demand_rows if r["n_anchor"] == 0]
    thin_dims = [r["cn"] for r in value_rows + beh_rows if r["n_labels"] < _SAMPLE_THRESHOLD]
    lines += ["", f"## {caveat_idx}、口径与样本量警示（必读）"]
    lines += [
        "- **画像比对只是投前的冷启动代理**：能判断圈选合不合理、生成\"先测哪些细分\"的假设，"
        "但**判断不了真实投放价值**——真实价值只有 CTR/CVR/ROI/GMV 说了算；有了转化数据，"
        "转化永远压过画像相似度（方法论 §二.8）。",
        "- A4 = 真需求标尺，**不是提纯工具、不是模仿对象**；身份维差异不扣分（构成不同 ≠ 质量缺口）。",
        "- 价值维贴近 A4 均值是**反的**（A4 大多价格敏感，恰是和田宽最打不动的人）；要主动往高端尾部偏。",
    ]
    if missing_dims:
        lines.append("- 缺数据维度（A4 无可用锚，已跳过）：" + "、".join(missing_dims))
    if thin_dims:
        lines.append("- 样本偏薄维度（标签数 < %d，结论待验证）：" % _SAMPLE_THRESHOLD + "、".join(set(thin_dims)))

    return {
        "candidate": cand_name,
        "baseline": base_name,
        "value_axis": value_rows,
        "behavior_axis": beh_rows,
        "demand_axis": demand_rows,
        "identity_axis": identity_rows,
        "value_verdict": value_v,
        "behavior_verdict": behavior_v,
        "demand_verdict": demand_v,
        "position": position,
        "purify_plan": purify,
        "markdown": "\n".join(lines),
    }


def _build_sections(result: dict, narrative_md: str, narrated: bool) -> list[dict]:
    """桌面可分层展开 sections（observation / hypothesis / recommendation / other）。"""
    sections: list[dict] = [{
        "layer": "other",
        "title": "投前诊断卡" + ("" if narrated else "（确定性骨架·AI 叙事不可用）"),
        "body": narrative_md,
    }]
    # 观察层：三维 verdict + 关键数据
    obs_lines = [
        f"- 价值维：**{result['value_verdict']}**",
        f"- 购买行为维：**{result['behavior_verdict']}**",
        f"- 需求重叠：**{result['demand_verdict']}**",
    ]
    ev = []
    for r in result["value_axis"]:
        ev.append(f"{r['cn']}：候选 {_fmt_pct(r['cand'])} vs A4 {_fmt_pct(r['base'])}（{r['verdict']}）")
    for r in result["demand_axis"]:
        if r["n_anchor"]:
            ev.append(f"{r['cn']} 真需求锚留住 {r['retained']}/{r['n_anchor']}（{r['verdict']}）")
    sections.append({
        "layer": "observation",
        "title": "三维方向（客观·画像真值，不含因果）",
        "body": "\n".join(obs_lines),
        "evidence": ev,
    })
    pos = result["position"]
    sections.append({
        "layer": "recommendation",
        "title": f"漏斗定位：{pos['label']}",
        "body": f"{pos['why']}\n\n建议漏斗位：{pos['funnel']}",
        "evidence": [
            "画像是投前冷启动代理，判断不了真实投放价值——按定调小预算测，看 CTR/CVR/ROI 再放量（方法论 §二.8）",
        ],
    })
    if result.get("purify_plan"):
        p = result["purify_plan"]
        body = "\n\n".join(
            f"**{c['name']}｜{'⚠电商' if c['ecommerce'] else '✅非电商'}**\n{c['rule']}\n"
            + "\n".join(f"- {a}" for a in c["actions"])
            for c in p["cuts"]
        )
        sections.append({
            "layer": "recommendation",
            "title": f"提纯施工单（优先级阶梯·{p['funnel']}）",
            "body": body,
            "evidence": [p["ecommerce_note"], p["note"]],
        })
    return sections


# ───────────────────────── LLM 叙事层（KB grounded，fail-open）─────────────────────────


async def _narrate(
    skeleton_md: str, kb_block: str, position_label: str, focus: str | None,
) -> tuple[str, bool]:
    """把确定性《诊断卡骨架》当 ground truth + 巨量云图 KB 料 → 写成给老板看的诊断叙事。

    外置提示词 `audience_pack_diagnose.{system,user}.md`（铁律 C 热加载）。模型走
    tool_models.yaml 的 diagnose_audience_pack 条目（缺省 gemini-3.1-pro-preview）。
    **失败/依赖缺失 → 原样返骨架 + narrated=False（fail-open，绝不丢确定性真值）。**
    """
    if _prompts is None or _AIHubClient is None or _get_model is None:
        return skeleton_md, False
    try:
        cfg = {}
        try:
            cfg = _get_model("diagnose_audience_pack") or {}
        except Exception:  # noqa: BLE001
            cfg = {}
        provider = cfg.get("provider", "gemini")
        model = cfg.get("model", "gemini-3.1-pro-preview")
        temperature = float(cfg.get("temperature", 0.3))
        max_tokens = int(cfg.get("max_tokens", 9000))
        focus_block = (
            f"老板这次特别关注：{focus.strip()}\n（请在定调里优先回应这一点。）\n"
            if focus and focus.strip() else ""
        )
        system = _prompts.load("audience_pack_diagnose.system")
        user = _prompts.render(
            "audience_pack_diagnose.user",
            position_label=position_label,
            focus_block=focus_block,
            kb_block=kb_block,
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
        logger.warning("人群包诊断 AI 叙事返回过短（回退骨架）len=%d", len(text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("人群包诊断 AI 叙事失败（回退确定性骨架）: %s", exc)
    return skeleton_md, False


# ───────────────────────── 主入口 ─────────────────────────


async def diagnose_audience_pack(
    candidate: str,
    baseline: str = "baseline_a4",
    with_purify_plan: bool = True,
    polish: bool = False,
    focus: str | None = None,
) -> dict:
    """《02 人群包对比诊断》+《01 提纯施工单》——投前诊断一个候选人群包。

    candidate / baseline：内置/dropbox 文件名（'baseline_a4'、'diyu_xunwei'、'x.csv'）/
        容器可达绝对路径 / 原始 CSV 文本。baseline 默认 'baseline_a4'（行业 A4 真需求标尺）。
    with_purify_plan：True 附《提纯施工单》（三刀法，落到真实可勾标签）。
    polish：True 在确定性骨架上跑 **LLM 叙事层**（巨量云图 KB grounding；骨架为 ground truth，
        禁新增数值/伪因果；失败 fail-open 回退骨架）。默认 False（纯确定性、零 token）。
    focus：老板临时关注点，注入叙事（仅 polish 生效）。

    返 {ok, candidate, baseline, value_verdict, behavior_verdict, demand_verdict, position,
        value_axis, behavior_axis, demand_axis, identity_axis, purify_plan, markdown,
        sections, narrated, source, note} 或 {ok:false, error, available}。
    """
    cand, c_src = _resolve_profile(candidate)
    if cand is None:
        return {
            "ok": False, "error": "candidate_not_found",
            "hint": f"找不到候选包 {candidate!r}（{c_src}）。可传内置名 / dropbox 文件名 / 绝对路径 / 原始CSV。",
            "available": _list_bundled(),
            "dropbox": _EXTRA_DIR or str(_AUDIENCE_DIR),
        }
    base, b_src = _resolve_profile(baseline)
    if base is None:
        return {
            "ok": False, "error": "baseline_not_found",
            "hint": f"找不到基准包 {baseline!r}（{b_src}）。默认应为 'baseline_a4'。",
            "available": _list_bundled(),
        }
    if not cand.get("by_type"):
        return {"ok": False, "error": "candidate_empty", "hint": "候选画像解析为空，检查 CSV 格式（标签类型,标签,占比,tgi）。"}

    value_rows = _value_axis(cand, base)
    beh_rows = _behavior_axis(cand, base)
    demand_rows = _demand_axis(cand, base)
    identity_rows = _identity_rows(cand, base)

    value_v = _value_verdict(value_rows)
    behavior_v = _behavior_verdict(beh_rows)
    demand_v = _demand_verdict(demand_rows)
    position = _position(value_v, behavior_v, demand_v)

    purify = _purify_plan(cand, value_rows, beh_rows, demand_rows, position) if with_purify_plan else None

    result = _build_diagnosis(
        cand, base, value_rows, beh_rows, demand_rows, identity_rows,
        value_v, behavior_v, demand_v, position, purify,
    )
    skeleton_md = result["markdown"]

    narrated = False
    narrative_md = skeleton_md
    if polish:
        snippets = await _gather_yuntu_kb(position["label"], cand.get("display_name", ""))
        narrative_md, narrated = await _narrate(
            skeleton_md, _kb_block(snippets), position["label"], focus,
        )
        result["markdown"] = narrative_md
        result["kb_grounded"] = bool(snippets)

    sections = _build_sections(result, narrative_md, narrated)

    # 执行过程透出（蓝图 §1.8 可观测 / 客户端"执行过程展开"）——确定性内部步骤，
    # 桌面时间线按步渲染，让老板看见"这张诊断卡是怎么一步步推出来的"（黑盒→透明）。
    steps = [
        {"i": 1, "label": "读取候选画像",
         "detail": f"{cand.get('display_name', candidate)} · {cand.get('n_rows', 0)} 标签", "status": "ok"},
        {"i": 2, "label": "加载行业标尺（真需求标尺）",
         "detail": f"{base.get('display_name', baseline)} · {base.get('n_rows', 0)} 标签", "status": "ok"},
        {"i": 3, "label": "价值维比对（付得起）", "detail": value_v, "status": "ok"},
        {"i": 4, "label": "购买行为维比对（软硬）", "detail": behavior_v, "status": "ok"},
        {"i": 5, "label": "需求维·真需求指纹重叠", "detail": f"重叠{demand_v}", "status": "ok"},
        {"i": 6, "label": "漏斗定位（规则映射）", "detail": position["label"], "status": "ok"},
    ]
    if purify:
        steps.append({"i": len(steps) + 1, "label": "生成提纯优先级阶梯",
                      "detail": f"按「{position['label']}」排序 · {len(purify['cuts'])} 刀（标电商资格）",
                      "status": "ok"})
    if polish:
        steps.append({"i": len(steps) + 1, "label": "LLM 叙事层（巨量云图 KB grounding）",
                      "detail": "已生成" if narrated else "hub 不可用 → 回退确定性骨架",
                      "status": "ok" if narrated else "warn"})

    return {
        "ok": True,
        **result,
        "sections": sections,
        "steps": steps,
        "narrated": narrated,
        "source": {"candidate": c_src, "baseline": b_src},
        "note": ("投前诊断卡：观察层=画像真值（不含因果），定位/定调=确定性规则映射 + 假设（R-14 非断言）。"
                 "画像是投前冷启动代理，判断不了真实投放价值——按定调小预算测，看 CTR/CVR/ROI 再放量。"
                 + ("AI 叙事层已生成（巨量云图 KB grounding；确定性骨架为 ground truth，禁新增数值/因果）。"
                    if narrated else "AI 叙事层未生成（hub 不可用/被禁/polish=False），返回确定性骨架。")),
    }
