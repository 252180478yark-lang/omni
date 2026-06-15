"""实验台账 + 确定性状态机 service（编导 brief A/B 单变量迭代闭环，migration 052）。

设计稿：docs/design-director-brief-ab-loop.md
节拍=真实投放天/周，不跑 agent loop。**排名/判 winner/汇总/建议下变量全是确定性 SQL**，
LLM 只在 distill 的 polish 路径（默认不开）。R-14 不编因果、R-15 n<5 标待验证。

北极星按 intent 分（INTENT_NORTH_STAR）；可扫变量池（SWEEP_VARIABLE_POOL）schema 无关，
加变量只改这里 + 提示词，零 migration。
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from app.database import get_pool
from app.services.ad_metrics_validation import _WHITELIST

logger = logging.getLogger(__name__)

# ── 北极星：intent → (主指标 key, 方向, 辅助展示 key) ────────────────────────
# 主指标必须可直接回传（rate/count），**不用 roi**——roi 是 computed 型，手填会被
# 标 suspect 不进聚合（R-4），且被预算量级干扰；收割用 cvr（转化率，跨臂公平），
# roi/gmv 作辅助展示。
INTENT_NORTH_STAR: dict[str, tuple[str, str, list[str]]] = {
    "planting": ("completion_rate", "higher_better", ["like_rate", "a3_ratio"]),
    "harvest":  ("cvr",             "higher_better", ["roi", "gmv"]),
    "soft_ad":  ("completion_rate", "higher_better", ["new_followers"]),
    "hard_ad":  ("cvr",             "higher_better", ["roi", "gmv"]),
}
INTENT_LABELS = {"planting": "种草", "harvest": "收割", "soft_ad": "软广", "hard_ad": "硬广"}

# 主指标允许的 kind（拒 computed 的 roi/roas、拒 meta 文本）
_ALLOWED_NS_KINDS = {"rate", "pct", "money", "count"}

# ── 可扫变量池（按对"视频↔人群匹配度"撬动大小排优先级：内容核→表达→呈现）──────
# (key, 中文 label, 层)；intent 不在池里（它是实验级属性，换 intent 北极星就变）。
SWEEP_VARIABLE_POOL: list[tuple[str, str, str]] = [
    ("idea_seed",         "拍什么事（母题/核心事件）", "内容核"),
    ("opening_hook_3s",   "开头钩子（前3秒留人）",     "内容核"),
    ("selling_point_set", "卖点组合（几个+哪几个）",   "内容核"),
    ("scene",             "匹配场景",                 "内容核"),
    ("emotion",           "情绪基调",                 "表达层"),
    ("story_pace",        "叙事节奏",                 "表达层"),
    ("edit_pace",         "剪辑节奏",                 "呈现层"),
    ("visual_vector",     "画面向量（构图/色调/质感）", "呈现层"),
    ("bgm",               "音乐",                     "呈现层"),
    ("target_model",      "AI 出片模型（仅 AI 拍）",   "呈现层"),
]
SWEEP_VARIABLE_LABELS: dict[str, str] = {k: lbl for k, lbl, _ in SWEEP_VARIABLE_POOL}
SWEEP_VARIABLE_ORDER: list[str] = [k for k, _, _ in SWEEP_VARIABLE_POOL]


# ── helpers ──────────────────────────────────────────────────────────────────
def _as_dict(v: Any) -> dict:
    """asyncpg JSONB 默认返字符串 → 转 dict。"""
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v) or {}
        except Exception:
            return {}
    return {}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    return None


def var_label(key: str) -> str:
    return SWEEP_VARIABLE_LABELS.get(key, key)


def default_north_star(intent: str) -> tuple[str, str, list[str]]:
    return INTENT_NORTH_STAR.get(intent, ("completion_rate", "higher_better", []))


# ── AI 出片链专属可扫变量（技术/保真类，投前视觉快环判；human_brief 链没有）──────
AI_EXTRA_VARIABLES: list[tuple[str, str, str]] = [
    ("prompt_structure", "提示词结构/拆块",   "AI技术"),
    ("realism_anchor",   "真人感锚措辞",      "AI技术"),
    ("character_ref",    "锁脸参考图",        "AI技术"),
    ("negative_words",   "负向词",           "AI技术"),
    ("motion_style",     "运镜/动作描述",     "AI技术"),
]
SWEEP_VARIABLE_LABELS.update({k: lbl for k, lbl, _ in AI_EXTRA_VARIABLES})

# ── intent → creative_pack kind（AI 链生成臂时用；硬广复用收割 kind）────────────
_INTENT_TO_KIND = {
    "planting": "video_planting", "harvest": "video_harvest",
    "soft_ad": "video_soft_ad", "hard_ad": "video_harvest",
}
# ── track → 沉淀写哪个 prompt 节点（mixed 出的是模式偏好、不沉淀成单节点规则）──────
TRACK_TO_PROMPT_NODE = {
    "human_brief": "pipeline.director_brief",
    "ai_video": "pipeline.creative_pack",
    "mixed": None,
}


def intent_to_creative_kind(intent: str) -> str:
    return _INTENT_TO_KIND.get(intent, "video_planting")


def sweep_order_for_track(track: str | None) -> list[str]:
    """该 track 的"建议下个变量"顺序：ai_video / mixed 多带 AI 技术变量。"""
    if track in ("ai_video", "mixed"):
        return SWEEP_VARIABLE_ORDER + [k for k, _, _ in AI_EXTRA_VARIABLES]
    return SWEEP_VARIABLE_ORDER


def build_experiment_constraint(ec: dict | None) -> str:
    """A/B 实验约束块：固定 baseline、只动本轮变量（单变量纪律写进生成提示词，不靠自律）。
    director_brief 与 creative_pack 共用（放这里避免 media ↔ portrait_brief 循环 import）。
    """
    if not ec:
        return ""
    baseline = ec.get("baseline") or {}
    sweep = ec.get("sweep") or {}
    lines = ["## ⓪⓪ A/B 实验约束（单变量纪律 · 必须严格遵守）", ""]
    if baseline:
        lines.append("**以下已验证设定保持不变**（前几轮跑赢锁定的，本条一个都不许改）：")
        for k, v in baseline.items():
            lines.append(f"- {var_label(k)}：{v}")
        lines.append("")
    var, val = sweep.get("variable"), sweep.get("value")
    if var and val:
        lines.append(f"**本条专门测试【{var_label(var)}】，在这一点上严格用：「{val}」。**")
        lines.append("其余创意自由发挥，但绝不能动上面 baseline 里的任何设定（动了就不是单变量测试了）。")
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# create
# ══════════════════════════════════════════════════════════════════════════════
async def create_experiment(
    *,
    sku_id: str,
    intent: str,
    portrait_id: str | None = None,
    audience_record_id: str | None = None,
    audience_run_id: str | None = None,
    matrix_run_id: str | None = None,
    north_star_metric: str | None = None,
    title: str | None = None,
    track: str = "human_brief",
) -> dict:
    """建一个实验（SKU×人群×intent×北极星×track）。确定性。

    track：human_brief（真人编导 brief→拍）/ ai_video（AI 提示词→出片）/
    mixed（同实验 A/B 真人 vs AI，swept_variable=production_mode）。决定沉淀写哪个 prompt 节点。
    """
    if track not in TRACK_TO_PROMPT_NODE:
        return {"ok": False, "error": "bad_track",
                "hint": f"track 只能是 {list(TRACK_TO_PROMPT_NODE)}（human_brief 真人 / ai_video AI / mixed 对比）"}
    if intent not in INTENT_NORTH_STAR:
        return {"ok": False, "error": "bad_intent",
                "hint": f"intent 只能是 {list(INTENT_NORTH_STAR)} 之一（intent 是实验级属性，不可当变量扫）"}
    if not sku_id:
        return {"ok": False, "error": "missing_sku_id"}
    # 铁律：内容永远是"给某个从 SKU 推出的人群"的 —— 实验必须绑人群，杜绝裸 SKU 实验
    if not (portrait_id or audience_record_id):
        return {"ok": False, "error": "missing_audience",
                "hint": "实验必须绑人群（铁律：出发点 SKU→卖点→人群→内容）——传 portrait_id（step3.5 画像）或 audience_record_id（step3 人群）"}

    ns_default, direction, _aux = default_north_star(intent)
    ns = (north_star_metric or ns_default).strip()
    spec = _WHITELIST.get(ns)
    if spec is None or spec[0] not in _ALLOWED_NS_KINDS:
        return {"ok": False, "error": "bad_north_star_metric",
                "hint": f"north_star_metric 必须是 ad_metrics 白名单里的 rate/money/count 指标（roi/roas 是后端算的不可手填，收割用 cvr）。给的：{ns}"}

    pool = get_pool()
    # denorm 回填：给了 portrait_id 就从画像反查 record/run/matrix
    if portrait_id and not (audience_record_id and audience_run_id and matrix_run_id):
        prow = await pool.fetchrow(
            "SELECT audience_record_id, audience_run_id, matrix_run_id, sku_id "
            "FROM pipeline.audience_portraits WHERE id = $1::uuid", portrait_id,
        )
        if prow:
            audience_record_id = audience_record_id or (str(prow["audience_record_id"]) if prow["audience_record_id"] else None)
            audience_run_id = audience_run_id or (str(prow["audience_run_id"]) if prow["audience_run_id"] else None)
            matrix_run_id = matrix_run_id or (str(prow["matrix_run_id"]) if prow["matrix_run_id"] else None)

    try:
        row = await pool.fetchrow(
            """
            INSERT INTO pipeline.experiments (
                sku_id, portrait_id, audience_record_id, audience_run_id, matrix_run_id,
                intent, north_star_metric, north_star_direction, title, track
            ) VALUES ($1, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6, $7, $8, $9, $10)
            RETURNING id::text AS id, sku_id, intent, track, north_star_metric,
                      north_star_direction, status, created_at
            """,
            sku_id, portrait_id, audience_record_id, audience_run_id, matrix_run_id,
            intent, ns, direction, title, track,
        )
    except Exception as exc:
        logger.exception("create_experiment failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}

    d = dict(row)
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    return {
        "ok": True,
        "experiment": d,
        "north_star": {"metric": ns, "direction": direction,
                       "auxiliary": _aux, "label": INTENT_LABELS.get(intent, intent)},
        "next_step_hint": "用 experiment_register_round 登记第 1 轮：选一个变量(swept_variable)，给 ≥2 个臂(每臂一个 director_brief script_id)",
    }


# ══════════════════════════════════════════════════════════════════════════════
# register round（只登记已生成 brief 的 script_id，tool 内零 LLM）
# ══════════════════════════════════════════════════════════════════════════════
async def register_round(
    *,
    experiment_id: str,
    swept_variable: str,
    arms: list[dict],
    round_no: int | None = None,
) -> dict:
    """登记一轮（flight）：扫一个变量，≥2 个臂。每臂 = {variable_value, script_id?}。

    单变量纪律：本轮只动 swept_variable，其余按 experiment.baseline 固定（baseline 通过
    generate_director_brief 的 experiment_context 喂进每个臂的 brief，本函数只登记结果）。
    """
    pool = get_pool()
    exp = await pool.fetchrow(
        "SELECT id::text AS id, sku_id, intent, track, baseline, status FROM pipeline.experiments WHERE id = $1::uuid",
        experiment_id,
    )
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    if not swept_variable:
        return {"ok": False, "error": "missing_swept_variable"}

    # 去重 variable_value（单变量下同取值重复无意义）
    seen: set[str] = set()
    clean_arms: list[dict] = []
    for a in arms or []:
        v = (a.get("variable_value") or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        clean_arms.append({"variable_value": v, "script_id": a.get("script_id")})
    if len(clean_arms) < 2:
        return {"ok": False, "error": "need_at_least_2_arms",
                "hint": "一轮 A/B 至少 2 个不同取值的臂（如 5 种开头钩子）"}
    if len(clean_arms) > 26:
        return {"ok": False, "error": "too_many_arms", "hint": "臂标签 A-Z，单轮 ≤26"}

    baseline = _as_dict(exp["baseline"])
    warnings: list[str] = []
    if swept_variable in baseline:
        warnings.append(f"⚠ 变量「{var_label(swept_variable)}」已在 baseline（值={baseline[swept_variable]}）——这是二次提纯/复测，确认要重测")
    if swept_variable not in SWEEP_VARIABLE_ORDER:
        warnings.append(f"⚠ 「{swept_variable}」不在标准变量池（自定义变量，可以，但不进'建议下个变量'轮转）")

    # round_no
    if round_no is None:
        r = await pool.fetchrow(
            "SELECT COALESCE(MAX(round_no), 0) AS m FROM pipeline.experiment_rounds WHERE experiment_id = $1::uuid",
            experiment_id,
        )
        round_no = int(r["m"]) + 1

    # 校验 script_id（给了就得真存在 + sku 对得上）
    for a in clean_arms:
        sid = a.get("script_id")
        if sid:
            srow = await pool.fetchrow(
                "SELECT sku_id, kind FROM pipeline.scripts WHERE id = $1::uuid", sid,
            )
            if not srow:
                return {"ok": False, "error": "script_not_found", "script_id": sid}
            if srow["sku_id"] != exp["sku_id"]:
                return {"ok": False, "error": "script_sku_mismatch", "script_id": sid,
                        "hint": f"该 script 属于 {srow['sku_id']}，实验是 {exp['sku_id']}"}

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                rnd = await conn.fetchrow(
                    """
                    INSERT INTO pipeline.experiment_rounds (experiment_id, sku_id, round_no, swept_variable)
                    VALUES ($1::uuid, $2, $3, $4)
                    RETURNING id::text AS id
                    """,
                    experiment_id, exp["sku_id"], round_no, swept_variable,
                )
                round_id = rnd["id"]
                out_arms = []
                _track = exp["track"]
                for i, a in enumerate(clean_arms):
                    label = chr(ord("A") + i)
                    # 该臂产出链：扫 production_mode 时逐臂取值=模式；否则继承 experiment.track
                    if swept_variable == "production_mode":
                        pmode = a["variable_value"] if a["variable_value"] in ("human_brief", "ai_video") else None
                    else:
                        pmode = _track if _track in ("human_brief", "ai_video") else None
                    arm = await conn.fetchrow(
                        """
                        INSERT INTO pipeline.experiment_arms (
                            round_id, experiment_id, sku_id, round_no,
                            swept_variable, variable_value, arm_label, script_id, production_mode
                        ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::uuid, $9)
                        RETURNING id::text AS id, arm_label, variable_value, script_id::text AS script_id
                        """,
                        round_id, experiment_id, exp["sku_id"], round_no,
                        swept_variable, a["variable_value"], label, a.get("script_id"), pmode,
                    )
                    out_arms.append(dict(arm))
    except Exception as exc:
        if "experiment_rounds_uq" in str(exc):
            return {"ok": False, "error": "round_exists",
                    "hint": f"实验已有第 {round_no} 轮；不传 round_no 让它自增，或换号"}
        logger.exception("register_round failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}

    return {
        "ok": True,
        "round": {"round_id": round_id, "round_no": round_no, "swept_variable": swept_variable,
                  "swept_variable_label": var_label(swept_variable), "arms": out_arms},
        "warnings": warnings,
        "next_step_hint": "拍片→投放→对每条视频 record_ad_metrics(asset_id, experiment_arm_id=对应臂)；攒够数据后 experiment_status 看排名",
    }


# ══════════════════════════════════════════════════════════════════════════════
# status（确定性排名 + R-14 分层 + R-15 待验证 + 建议下变量）
# ══════════════════════════════════════════════════════════════════════════════
async def experiment_status(experiment_id: str, round_no: int | None = None) -> dict:
    pool = get_pool()
    exp = await pool.fetchrow(
        """SELECT id::text AS id, sku_id, intent, track, north_star_metric, north_star_direction,
                  baseline, status, title FROM pipeline.experiments WHERE id = $1::uuid""",
        experiment_id,
    )
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    baseline = _as_dict(exp["baseline"])
    ns_metric = exp["north_star_metric"]
    direction = exp["north_star_direction"]
    higher_better = direction != "lower_better"

    # 目标轮：给了用给的；否则最新未锁定轮；都没有用最大轮
    if round_no is None:
        r = await pool.fetchrow(
            """SELECT round_no FROM pipeline.experiment_rounds WHERE experiment_id = $1::uuid
               ORDER BY (status='open') DESC, round_no DESC LIMIT 1""",
            experiment_id,
        )
        round_no = int(r["round_no"]) if r else None

    arms_out: list[dict] = []
    if round_no is not None:
        rows = await pool.fetch(
            """SELECT arm_id::text AS arm_id, arm_label, variable_value, swept_variable,
                      n_videos, north_star_avg, north_star_sum, sample_status,
                      is_winner, is_baseline_locked, forced, production_mode,
                      script_id::text AS script_id
               FROM pipeline.v_experiment_round_results
               WHERE experiment_id = $1::uuid AND round_no = $2
               ORDER BY arm_label""",
            experiment_id, round_no,
        )
        for row in rows:
            d = dict(row)
            d["n_videos"] = int(d["n_videos"] or 0)
            d["north_star_avg"] = _num(d["north_star_avg"])
            d["north_star_sum"] = _num(d["north_star_sum"])
            arms_out.append(d)

    # 排名（只在有北极星值的臂之间；sufficient 优先）
    ranked = [a for a in arms_out if a["north_star_avg"] is not None]
    ranked.sort(key=lambda a: a["north_star_avg"], reverse=higher_better)
    sufficient = [a for a in ranked if a["sample_status"] == "sufficient"]
    leader = sufficient[0] if sufficient else (ranked[0] if ranked else None)
    can_lock = bool(sufficient)  # 有 ≥1 个 n≥5 的臂才允许正常锁定（n<5 要 force）

    # 观察层（R-14：客观事实，不含因果）
    observations = [
        f"臂 {a['arm_label']}（{a['variable_value']}）：{ns_metric} 均值 {a['north_star_avg']}"
        f"，n={a['n_videos']}{'·待验证' if a['sample_status']=='preliminary' else ''}"
        for a in ranked
    ]
    # 假设层（R-15：只给"倾向"，标待验证，禁"因为X所以Y"）
    hypotheses: list[str] = []
    if leader is not None:
        tag = "（待验证·样本不足5条，可能是冷启动波动，不是结论）" if leader["sample_status"] == "preliminary" else ""
        hypotheses.append(
            f"当前领先：臂 {leader['arm_label']}「{leader['variable_value']}」{tag}。"
            f"注：领先=当前 {ns_metric} 均值高，未排除平台分发量级/冷启动差异，非统计证明更好。"
        )
    if not ranked:
        hypotheses.append("还没有任何臂回传北极星数据——先对每条视频 record_ad_metrics(experiment_arm_id=...)。")

    # 建议下个变量（确定性差集：标准池顺序 - 已测过的 - baseline 已锁的）
    tested = set(baseline.keys())
    trows = await pool.fetch(
        "SELECT DISTINCT swept_variable FROM pipeline.experiment_rounds WHERE experiment_id = $1::uuid",
        experiment_id,
    )
    tested |= {t["swept_variable"] for t in trows}
    next_var = next((k for k in sweep_order_for_track(exp["track"]) if k not in tested), None)

    # 口径提醒（老板选了"率类不强制 0..1"，跨回传保持同口径）
    metric_scale_warning = None
    sp = _WHITELIST.get(ns_metric)
    if sp and sp[0] in ("rate", "pct"):
        metric_scale_warning = f"率类指标「{ns_metric}」：跨视频/跨回传请保持同一单位（都填 0.45 或都填 45），混口径会让均值排名失真。"

    return {
        "ok": True,
        "experiment_id": experiment_id,
        "sku_id": exp["sku_id"],
        "intent": exp["intent"],
        "intent_label": INTENT_LABELS.get(exp["intent"], exp["intent"]),
        "track": exp["track"],
        "north_star_metric": ns_metric,
        "north_star_direction": direction,
        "status": exp["status"],
        "round_no": round_no,
        "baseline": baseline,
        "arms": arms_out,
        "ranking": [a["arm_label"] for a in ranked],
        "leader_arm_id": leader["arm_id"] if leader else None,
        "can_lock": can_lock,
        "observations": observations,
        "hypotheses": hypotheses,
        "next_variable_suggestion": (
            {"variable": next_var, "label": var_label(next_var)} if next_var else None
        ),
        "metric_scale_warning": metric_scale_warning,
        "next_step_hint": (
            "锁定 winner：experiment_lock_winner(experiment_id, round_no, winning_arm_id)"
            if can_lock else
            "样本还不够（每臂 n<5），先补够视频/回传；急的话 experiment_lock_winner(..., force=True) 但只是'当前领先'非统计证明"
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# lock winner（推进 baseline；R-15 闸 + force 留痕）
# ══════════════════════════════════════════════════════════════════════════════
async def lock_winner(
    *, experiment_id: str, round_no: int, winning_arm_id: str, force: bool = False,
) -> dict:
    pool = get_pool()
    arm = await pool.fetchrow(
        """SELECT arm_id::text AS arm_id, arm_label, variable_value, swept_variable,
                  n_videos, north_star_avg, sample_status, north_star_metric
           FROM pipeline.v_experiment_round_results
           WHERE experiment_id = $1::uuid AND round_no = $2 AND arm_id = $3::uuid""",
        experiment_id, round_no, winning_arm_id,
    )
    if not arm:
        return {"ok": False, "error": "arm_not_found",
                "hint": "winning_arm_id 不属于该实验该轮；用 experiment_status 看 arm_id"}
    n = int(arm["n_videos"] or 0)
    if arm["sample_status"] == "preliminary" and not force:
        return {"ok": False, "error": "preliminary_winner_blocked",
                "n_videos": n,
                "hint": f"该臂 n={n}<5（R-15 工程门槛），补够视频/回传再锁；确要硬锁传 force=True（会标 forced 留痕，且这只是'当前领先'非统计证明）"}

    swept = arm["swept_variable"]
    value = arm["variable_value"]
    reason = (f"轮{round_no} 臂{arm['arm_label']} 北极星 {arm['north_star_metric']} 均值 "
              f"{_num(arm['north_star_avg'])}（n={n}{'·FORCED·n<5·R-15 bypassed' if force else ''}）领先锁定")

    pool2 = get_pool()
    exp = await pool2.fetchrow(
        "SELECT baseline, track FROM pipeline.experiments WHERE id = $1::uuid", experiment_id,
    )
    baseline = _as_dict(exp["baseline"]) if exp else {}
    overwrite_warning = None
    if swept in baseline and baseline[swept] != value:
        overwrite_warning = f"⚠ baseline 里「{var_label(swept)}」原值={baseline[swept]}，本次覆盖为「{value}」"

    new_baseline = {**baseline, swept: value}
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 该轮其它臂的 winner 标记清零（保证一轮一个 winner）
                await conn.execute(
                    "UPDATE pipeline.experiment_arms SET is_winner=FALSE, is_baseline_locked=FALSE "
                    "WHERE experiment_id=$1::uuid AND round_no=$2", experiment_id, round_no,
                )
                await conn.execute(
                    """UPDATE pipeline.experiment_arms
                       SET is_winner=TRUE, is_baseline_locked=TRUE, forced=$2, decided_reason=$3
                       WHERE id=$1::uuid""",
                    winning_arm_id, force, reason,
                )
                await conn.execute(
                    """UPDATE pipeline.experiment_rounds
                       SET status='locked', winning_arm_id=$2::uuid, baseline_snapshot=$3::jsonb
                       WHERE experiment_id=$1::uuid AND round_no=$4""",
                    experiment_id, winning_arm_id, json.dumps(new_baseline, ensure_ascii=False), round_no,
                )
                await conn.execute(
                    "UPDATE pipeline.experiments SET baseline=$2::jsonb WHERE id=$1::uuid",
                    experiment_id, json.dumps(new_baseline, ensure_ascii=False),
                )
    except Exception as exc:
        logger.exception("lock_winner failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}

    # 建议下个变量
    tested = set(new_baseline.keys())
    trows = await pool.fetch(
        "SELECT DISTINCT swept_variable FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid",
        experiment_id,
    )
    tested |= {t["swept_variable"] for t in trows}
    next_var = next((k for k in sweep_order_for_track(exp["track"]) if k not in tested), None)

    return {
        "ok": True,
        "locked": {"swept_variable": swept, "label": var_label(swept), "value": value,
                   "arm_label": arm["arm_label"], "forced": force, "reason": reason},
        "baseline": new_baseline,
        "overwrite_warning": overwrite_warning,
        "next_variable_suggestion": ({"variable": next_var, "label": var_label(next_var)} if next_var else None),
        "next_step_hint": (
            f"开第 {round_no+1} 轮扫「{var_label(next_var)}」（baseline 自动固定已锁的设定）" if next_var
            else "标准变量都扫完了——可 experiment_distill 把获胜框架沉淀成 prompt_rule（先 dry_run 看）"
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# list / get
# ══════════════════════════════════════════════════════════════════════════════
async def list_experiments(sku_id: str | None = None, status: str | None = None, limit: int = 30) -> dict:
    pool = get_pool()
    where, params = [], []
    if sku_id:
        params.append(sku_id); where.append(f"sku_id = ${len(params)}")
    if status:
        params.append(status); where.append(f"status = ${len(params)}")
    params.append(limit)
    rows = await pool.fetch(
        f"""SELECT e.id::text AS id, e.sku_id, e.intent, e.north_star_metric, e.status,
                   e.title, e.baseline, e.created_at,
                   (SELECT COALESCE(MAX(round_no),0) FROM pipeline.experiment_rounds r WHERE r.experiment_id=e.id) AS rounds
            FROM pipeline.experiments e
            {('WHERE ' + ' AND '.join(where)) if where else ''}
            ORDER BY e.created_at DESC LIMIT ${len(params)}""",
        *params,
    )
    out = []
    for row in rows:
        d = dict(row)
        d["baseline"] = _as_dict(d["baseline"])
        d["rounds"] = int(d["rounds"] or 0)
        d["intent_label"] = INTENT_LABELS.get(d["intent"], d["intent"])
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
        out.append(d)
    return {"ok": True, "count": len(out), "experiments": out}


async def get_experiment(experiment_id: str) -> dict:
    pool = get_pool()
    exp = await pool.fetchrow(
        """SELECT id::text AS id, sku_id, portrait_id::text AS portrait_id,
                  audience_record_id::text AS audience_record_id, intent, track,
                  north_star_metric, north_star_direction, status, title, baseline,
                  winning_framework_md, framework_distilled_at, created_at
           FROM pipeline.experiments WHERE id = $1::uuid""",
        experiment_id,
    )
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    d = dict(exp)
    d["baseline"] = _as_dict(d["baseline"])
    d["intent_label"] = INTENT_LABELS.get(d["intent"], d["intent"])
    for k in ("framework_distilled_at", "created_at"):
        if d.get(k):
            d[k] = d[k].isoformat()

    rounds = await pool.fetch(
        """SELECT round_no, swept_variable, status, winning_arm_id::text AS winning_arm_id
           FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid ORDER BY round_no""",
        experiment_id,
    )
    results = await pool.fetch(
        """SELECT round_no, arm_id::text AS arm_id, arm_label, variable_value, swept_variable,
                  n_videos, north_star_avg, sample_status, is_winner, production_mode,
                  script_id::text AS script_id
           FROM pipeline.v_experiment_round_results WHERE experiment_id=$1::uuid
           ORDER BY round_no, arm_label""",
        experiment_id,
    )
    res_by_round: dict[int, list[dict]] = {}
    for r in results:
        rr = dict(r)
        rr["n_videos"] = int(rr["n_videos"] or 0)
        rr["north_star_avg"] = _num(rr["north_star_avg"])
        res_by_round.setdefault(int(rr["round_no"]), []).append(rr)
    round_list = []
    for r in rounds:
        rd = dict(r)
        rd["swept_variable_label"] = var_label(rd["swept_variable"])
        rd["arms"] = res_by_round.get(int(rd["round_no"]), [])
        round_list.append(rd)

    return {"ok": True, "experiment": d, "rounds": round_list}


# ══════════════════════════════════════════════════════════════════════════════
# distill helpers（确定性骨架；polish 由 tool 层调 LLM 加护栏）
# ══════════════════════════════════════════════════════════════════════════════
async def collect_distill_skeleton(experiment_id: str) -> dict:
    """读已锁定 baseline + 各变量获胜轮的真实数据 → 候选规则骨架（纯确定性，零 LLM）。

    返回 {ok, experiment, candidates:[{swept_variable, label, value, n, north_star_avg,
    sample_status, rule_text(模板), tier}], framework_lines, blocked:[低样本被挡]}。
    tier: 'formal'(n>=5) / 'preliminary'(3<=n<5) / 'dropped'(n<3 不出规则只入观察).
    """
    g = await get_experiment(experiment_id)
    if not g.get("ok"):
        return g
    exp = g["experiment"]
    intent = exp["intent"]
    intent_label = INTENT_LABELS.get(intent, intent)
    baseline = exp["baseline"]
    sku_id = exp["sku_id"]

    # 每个已锁变量 → 找它获胜轮那一臂的 n / avg
    win_rows = {}
    for rnd in g["rounds"]:
        for arm in rnd["arms"]:
            if arm.get("is_winner"):
                win_rows[rnd["swept_variable"]] = arm

    candidates, framework_lines, blocked = [], [], []
    for var, value in baseline.items():
        arm = win_rows.get(var)
        n = int(arm["n_videos"]) if arm else 0
        avg = arm.get("north_star_avg") if arm else None
        label = var_label(var)
        if n < 3:
            blocked.append({"swept_variable": var, "label": label, "value": value, "n": n,
                            "reason": "样本<3条，不沉淀成规则（只作观察）"})
            framework_lines.append(f"- 【观察·样本不足】{label} 倾向「{value}」（n={n}，证据太弱，未排除冷启动差异，仅记录）")
            continue
        tier = "preliminary" if n < 5 else "formal"
        prefix = "[待验证] " if tier == "preliminary" else ""
        verb = "倾向用" if tier == "preliminary" else "固定用"
        rule_text = f"{prefix}这个 SKU 的{intent_label}编导 brief，{label}{verb}「{value}」"
        candidates.append({
            "swept_variable": var, "label": label, "value": value,
            "n": n, "north_star_avg": avg, "sample_status": arm.get("sample_status"),
            "rule_text": rule_text, "tier": tier,
        })
        ns = exp["north_star_metric"]
        framework_lines.append(
            f"- {label}：「{value}」（{ns} 均值 {avg}，n={n}{'·待验证' if tier=='preliminary' else ''}；"
            f"未排除平台分发量级/冷启动差异，差距方向仅供参考）"
        )

    return {
        "ok": True,
        "experiment": {"id": experiment_id, "sku_id": sku_id, "intent": intent,
                       "intent_label": intent_label, "north_star_metric": exp["north_star_metric"],
                       "status": exp["status"], "track": exp.get("track"),
                       "prompt_node": TRACK_TO_PROMPT_NODE.get(exp.get("track") or "human_brief")},
        "candidates": candidates,
        "blocked": blocked,
        "framework_lines": framework_lines,
        "scope": {"sku_id": sku_id, "intent": intent},
    }


async def already_distilled_map(experiment_id: str) -> dict[str, str]:
    """该实验已沉淀过的变量 → 已写规则的取值（判重/标 value_changed 用）。"""
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT source_round_var, rule_text FROM knowledge.prompt_rules
           WHERE source_experiment_id = $1::uuid AND source_round_var IS NOT NULL""",
        experiment_id,
    )
    return {r["source_round_var"]: r["rule_text"] for r in rows}


async def write_winning_framework(experiment_id: str, framework_md: str) -> None:
    """落人读获胜框架（不覆盖：已有就保留旧的、不动）。"""
    pool = get_pool()
    await pool.execute(
        """UPDATE pipeline.experiments
           SET winning_framework_md = COALESCE(winning_framework_md, $2),
               framework_distilled_at = COALESCE(framework_distilled_at, NOW()),
               status = CASE WHEN status='running' THEN 'converged' ELSE status END
           WHERE id = $1::uuid""",
        experiment_id, framework_md,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 投前视觉快环（AI 链：多模态 judge 打质量分，投放前过滤崩/假/不锁脸 + 收敛技术变量）
# ══════════════════════════════════════════════════════════════════════════════
def prescreen_gate(scores: dict) -> str:
    """确定性 gate（不让 LLM 自判）：usable<6 或 fidelity<5 或 face_consistency<5 → fail。"""
    try:
        u = float(scores.get("usable", 0))
        f = float(scores.get("fidelity", 0))
        fc = float(scores.get("face_consistency", 0))
    except (TypeError, ValueError):
        return "fail"
    return "pass" if (u >= 6 and f >= 5 and fc >= 5) else "fail"


async def get_round_video_assets(experiment_id: str, round_no: int | None = None) -> dict:
    """该轮各臂挂的 video 资产（file_url + 现有 visual_prescreen）。供投前视觉快环判。"""
    pool = get_pool()
    if round_no is None:
        r = await pool.fetchval(
            "SELECT MAX(round_no) FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid",
            experiment_id,
        )
        round_no = int(r) if r else None
    if round_no is None:
        return {"ok": True, "round_no": None, "assets": []}
    rows = await pool.fetch(
        """SELECT a.id::text AS asset_id, a.file_url, a.visual_prescreen,
                  arm.id::text AS arm_id, arm.arm_label, arm.variable_value, arm.swept_variable
           FROM pipeline.experiment_arms arm
           JOIN pipeline.assets a ON a.experiment_arm_id = arm.id AND a.asset_type = 'video'
           WHERE arm.experiment_id = $1::uuid AND arm.round_no = $2
           ORDER BY arm.arm_label, a.created_at""",
        experiment_id, round_no,
    )
    assets = [{"asset_id": r["asset_id"], "file_url": r["file_url"],
               "visual_prescreen": _as_dict(r["visual_prescreen"]),
               "arm_id": r["arm_id"], "arm_label": r["arm_label"],
               "variable_value": r["variable_value"], "swept_variable": r["swept_variable"]}
              for r in rows]
    return {"ok": True, "round_no": round_no, "assets": assets}


async def save_visual_prescreen(asset_id: str, scores: dict) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE pipeline.assets SET visual_prescreen = $2::jsonb WHERE id = $1::uuid",
        asset_id, json.dumps(scores, ensure_ascii=False),
    )
