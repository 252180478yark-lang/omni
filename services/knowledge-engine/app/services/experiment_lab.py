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
import math
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.database import get_pool
from app.services.ad_metrics_validation import _WHITELIST
from app.services.video_intent_profiles import get_video_intent_profile

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _reuse_or_acquire_connection(executor: Any, connection: Any | None):
    """Reuse a caller transaction connection; otherwise borrow one from the pool."""
    if connection is not None:
        yield connection
        return
    async with executor.acquire() as acquired:
        yield acquired


# ── 北极星：intent → (主指标 key, 方向, 辅助展示 key) ────────────────────────
# 主指标必须可直接回传（rate/count），**不用 roi**——roi 是 computed 型，手填会被
# 标 suspect 不进聚合（R-4），且被预算量级干扰；收割用 cvr（转化率，跨臂公平），
# roi/gmv 作辅助展示。
INTENT_NORTH_STAR: dict[str, tuple[str, str, list[str]]] = {
    "planting": ("a3_ratio",        "higher_better", ["cpm", "completion_rate", "play_3s_rate"]),
    "harvest":  ("cvr",             "higher_better", ["roi", "gmv"]),
    "soft_ad":  ("completion_rate", "higher_better", ["play_3s_rate"]),
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
SWEEP_VARIABLE_LABELS.update({
    "pain_scene_bridge": "痛点场景桥",
    "presentation_motif": "呈现母题",
    "justification_density": "理由密度",
    "justification_module": "理由模块",
})


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


_EVALUATION_POLICY_OVERRIDE_FIELDS = frozenset({
    "play_3s_floor",
    "completion_floor",
    "a3_floor",
    "cpm_ceiling",
    "min_impressions",
    "min_a3_eligible_users",
})
_RATE_POLICY_FIELDS = frozenset({"play_3s_floor", "completion_floor", "a3_floor"})
_NONNEGATIVE_POLICY_FIELDS = _EVALUATION_POLICY_OVERRIDE_FIELDS - _RATE_POLICY_FIELDS


def _invalid_policy_override(field: str) -> dict:
    return {
        "ok": False,
        "error": "invalid_evaluation_policy_overrides",
        "field": field,
    }


def _snapshot_evaluation_policy(
    intent: str,
    overrides: dict[str, Any] | None,
) -> tuple[dict | None, dict | None]:
    """Snapshot the versioned intent policy; only six business thresholds are mutable."""
    if overrides is not None and not isinstance(overrides, dict):
        return None, _invalid_policy_override("evaluation_policy_overrides")

    try:
        profile = get_video_intent_profile(intent)
    except ValueError as exc:
        # Only the two intentionally unconfigured legacy intents may use an empty policy.
        is_legacy_missing = (
            intent in {"harvest", "hard_ad"}
            and str(exc) == f"video_intent_profile_not_found:{intent}"
        )
        if is_legacy_missing:
            if overrides:
                field = next(iter(overrides), "evaluation_policy_overrides")
                return None, _invalid_policy_override(field)
            return {}, None
        return None, {
            "ok": False,
            "error": "evaluation_policy_unavailable",
            "intent": intent,
        }

    policy = dict(profile.evaluation_policy)
    policy.update({
        "profile_version": profile.version,
        "intent": profile.intent,
        "north_star": profile.north_star,
        "diagnostic_metrics": list(profile.diagnostic_metrics),
    })

    for field, value in (overrides or {}).items():
        if field not in _EVALUATION_POLICY_OVERRIDE_FIELDS:
            return None, _invalid_policy_override(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            return None, _invalid_policy_override(field)
        if field in _RATE_POLICY_FIELDS and not 0 <= value <= 1:
            return None, _invalid_policy_override(field)
        if field in _NONNEGATIVE_POLICY_FIELDS and value < 0:
            return None, _invalid_policy_override(field)
        policy[field] = value

    return policy, None


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
    evaluation_policy_overrides: dict[str, Any] | None = None,
    _connection: Any | None = None,
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
    if intent == "planting" and track == "ai_video" and ns != "a3_ratio":
        return {
            "ok": False,
            "error": "bad_north_star_metric",
            "field": "north_star_metric",
            "hint": "正式种草 AI 视频实验固定以 a3_ratio 为北极星；完播、3 秒和 CPM 仅作诊断。",
        }
    spec = _WHITELIST.get(ns)
    if spec is None or spec[0] not in _ALLOWED_NS_KINDS:
        return {"ok": False, "error": "bad_north_star_metric",
                "hint": f"north_star_metric 必须是 ad_metrics 白名单里的 rate/money/count 指标（roi/roas 是后端算的不可手填，收割用 cvr）。给的：{ns}"}

    evaluation_policy, policy_error = _snapshot_evaluation_policy(
        intent,
        evaluation_policy_overrides,
    )
    if policy_error:
        return policy_error

    db = _connection or get_pool()
    # denorm 回填：给了 portrait_id 就从画像反查 record/run/matrix
    if portrait_id and not (audience_record_id and audience_run_id and matrix_run_id):
        prow = await db.fetchrow(
            "SELECT audience_record_id, audience_run_id, matrix_run_id, sku_id "
            "FROM pipeline.audience_portraits WHERE id = $1::uuid", portrait_id,
        )
        if prow:
            audience_record_id = audience_record_id or (str(prow["audience_record_id"]) if prow["audience_record_id"] else None)
            audience_run_id = audience_run_id or (str(prow["audience_run_id"]) if prow["audience_run_id"] else None)
            matrix_run_id = matrix_run_id or (str(prow["matrix_run_id"]) if prow["matrix_run_id"] else None)

    try:
        row = await db.fetchrow(
            """
            INSERT INTO pipeline.experiments (
                sku_id, portrait_id, audience_record_id, audience_run_id, matrix_run_id,
                intent, north_star_metric, north_star_direction, title, track, evaluation_policy
            ) VALUES ($1, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6, $7, $8, $9, $10,
                      $11::jsonb)
            RETURNING id::text AS id, sku_id, intent, track, north_star_metric,
                      north_star_direction, evaluation_policy, status, created_at
            """,
            sku_id, portrait_id, audience_record_id, audience_run_id, matrix_run_id,
            intent, ns, direction, title, track, json.dumps(evaluation_policy, ensure_ascii=False),
        )
    except Exception as exc:
        logger.exception("create_experiment failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}

    d = dict(row)
    d["evaluation_policy"] = _as_dict(d.get("evaluation_policy"))
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
# attach arm（采纳即挂臂：老板一条条采纳 brief/AI，逐条标成某轮某臂；单条追加）
# ══════════════════════════════════════════════════════════════════════════════
def arm_code(round_no: int, arm_label: str) -> str:
    """实验内唯一臂码（派生，不落库）：R{轮号}{臂标}，如 R2B。
    老板把它写进巨量视频名/备注，CSV 回灌(record_ad_metrics_batch)按它精确匹配到臂。"""
    return f"R{round_no}{arm_label}"


def _arm_mismatch(field: str) -> dict:
    return {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": field,
    }


async def attach_arm(
    *,
    experiment_id: str,
    script_id: str,
    variable_value: str,
    round_no: int | None = None,
    swept_variable: str | None = None,
    adopt_script: bool = True,
    _connection: Any | None = None,
) -> dict:
    """把一条已生成、老板采纳的 brief/AI 脚本挂成某轮某臂（采纳即挂臂，单条追加）。

    register_round 是"一次登记整轮 ≥2 臂"；本函数是"老板一条条采纳、逐条标成臂"。
    - round_no 不给 + swept_variable 不给 → 挂到最新 open 轮（必须已存在）
    - swept_variable 给了且无可用 open 轮 → 自动新开一轮
    - round_no 显式给：存在则追加（必须 open），不存在则用该号新开（要 swept_variable）
    臂标 A/B/C... 按轮内已有臂数派生；同取值不重复挂。adopt_script=True 顺手把 draft→adopted。
    """
    db = _connection or get_pool()
    lineage = await db.fetchrow(
        """SELECT e.id::text AS id,
                  e.sku_id AS experiment_sku_id,
                  e.intent AS experiment_intent,
                  e.track AS experiment_track,
                  e.north_star_metric,
                  e.status AS experiment_status,
                  s.id::text AS script_id,
                  s.sku_id AS script_sku_id,
                  s.kind AS script_kind,
                  s.intent AS script_intent,
                  s.status AS script_status
           FROM pipeline.experiments e
           LEFT JOIN pipeline.scripts s ON s.id=$2::uuid
           WHERE e.id=$1::uuid""",
        experiment_id,
        script_id,
    )
    if not lineage:
        return {"ok": False, "error": "experiment_not_found"}
    if not lineage["script_id"]:
        return {"ok": False, "error": "script_not_found", "script_id": script_id}

    exp = {
        "id": lineage["id"],
        "sku_id": lineage["experiment_sku_id"],
        "intent": lineage["experiment_intent"],
        "track": lineage["experiment_track"],
        "north_star_metric": lineage["north_star_metric"],
        "status": lineage["experiment_status"],
    }
    srow = {
        "sku_id": lineage["script_sku_id"],
        "kind": lineage["script_kind"],
        "intent": lineage["script_intent"],
        "status": lineage["script_status"],
    }

    value = (variable_value or "").strip()
    if not value:
        return {"ok": False, "error": "missing_variable_value",
                "hint": "本臂的变量取值（如『悬念式钩子』）"}

    script_track = _track_for_kind(srow["kind"])
    formal_planting = (
        (exp["intent"] == "planting" and exp["track"] == "ai_video")
        or (srow["intent"] == "planting" and script_track == "ai_video")
    )
    if formal_planting:
        if srow["sku_id"] != exp["sku_id"]:
            return _arm_mismatch("sku_id")
        if exp["intent"] != "planting" or srow["intent"] != "planting":
            return _arm_mismatch("intent")
        if exp["track"] != "ai_video" or script_track != "ai_video":
            return _arm_mismatch("track")
        if exp["north_star_metric"] != "a3_ratio":
            return _arm_mismatch("north_star_metric")
    elif srow["sku_id"] != exp["sku_id"]:
        return {"ok": False, "error": "script_sku_mismatch", "script_id": script_id,
                "hint": f"该 script 属于 {srow['sku_id']}，实验是 {exp['sku_id']}"}

    if formal_planting:
        open_round = await db.fetchrow(
            """SELECT r.id::text AS id, r.round_no, r.swept_variable, r.status,
                      count(a.id)::int AS arm_count
               FROM pipeline.experiment_rounds r
               LEFT JOIN pipeline.experiment_arms a ON a.round_id=r.id
               WHERE r.experiment_id=$1::uuid AND r.status='open'
               GROUP BY r.id, r.round_no, r.swept_variable, r.status
               ORDER BY r.round_no DESC LIMIT 1""",
            experiment_id,
        )
        if open_round and int(open_round["arm_count"] or 0) >= 1:
            if round_no is None or int(round_no) != int(open_round["round_no"]):
                return _arm_mismatch("round_no")
            if not swept_variable or swept_variable.strip() != open_round["swept_variable"]:
                return _arm_mismatch("swept_variable")

    warnings: list[str] = []
    try:
        async with _reuse_or_acquire_connection(db, _connection) as conn:
            async with conn.transaction():
                # ── 定位/新建轮 ──
                if round_no is not None:
                    rnd = await conn.fetchrow(
                        "SELECT id::text AS id, round_no, swept_variable, status "
                        "FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid AND round_no=$2",
                        experiment_id, round_no,
                    )
                else:
                    rnd = await conn.fetchrow(
                        "SELECT id::text AS id, round_no, swept_variable, status "
                        "FROM pipeline.experiment_rounds "
                        "WHERE experiment_id=$1::uuid AND status='open' "
                        "ORDER BY round_no DESC LIMIT 1",
                        experiment_id,
                    )

                if rnd is None:
                    # 要新开一轮，必须有 swept_variable
                    sv = (swept_variable or "").strip()
                    if not sv:
                        return {"ok": False, "error": "missing_swept_variable",
                                "hint": "这是本实验/本轮第一条臂，要新开一轮——传 swept_variable（本轮扫的变量，如 opening_hook_3s）"}
                    exp2 = await conn.fetchrow(
                        "SELECT baseline FROM pipeline.experiments WHERE id=$1::uuid", experiment_id)
                    baseline = _as_dict(exp2["baseline"]) if exp2 else {}
                    if sv in baseline:
                        warnings.append(f"⚠ 变量「{var_label(sv)}」已在 baseline（值={baseline[sv]}）——这是二次提纯/复测")
                    if sv not in SWEEP_VARIABLE_ORDER:
                        warnings.append(f"⚠ 「{sv}」不在标准变量池（自定义变量，不进'建议下个变量'轮转）")
                    rno = round_no
                    if rno is None:
                        rr = await conn.fetchrow(
                            "SELECT COALESCE(MAX(round_no),0) AS m FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid",
                            experiment_id)
                        rno = int(rr["m"]) + 1
                    rnd = await conn.fetchrow(
                        "INSERT INTO pipeline.experiment_rounds (experiment_id, sku_id, round_no, swept_variable) "
                        "VALUES ($1::uuid,$2,$3,$4) RETURNING id::text AS id, round_no, swept_variable, status",
                        experiment_id, exp["sku_id"], rno, sv,
                    )
                else:
                    if rnd["status"] != "open":
                        if formal_planting:
                            return _arm_mismatch("round_no")
                        return {"ok": False, "error": "round_locked",
                                "hint": f"第 {rnd['round_no']} 轮已锁定，不能再加臂；新开一轮（传新 round_no + swept_variable）"}
                    if swept_variable and swept_variable.strip() and swept_variable.strip() != rnd["swept_variable"]:
                        if formal_planting:
                            return _arm_mismatch("swept_variable")
                        warnings.append(f"⚠ 第 {rnd['round_no']} 轮扫的是「{var_label(rnd['swept_variable'])}」，忽略本次传的「{var_label(swept_variable.strip())}」（一轮只扫一个变量）")

                round_id = rnd["id"]
                round_no_eff = int(rnd["round_no"])
                sv_eff = rnd["swept_variable"]

                # ── 同轮取值去重 ──
                dup = await conn.fetchrow(
                    "SELECT arm_label FROM pipeline.experiment_arms "
                    "WHERE round_id=$1::uuid AND variable_value=$2", round_id, value,
                )
                if dup:
                    return {"ok": False, "error": "variable_value_exists",
                            "hint": f"第 {round_no_eff} 轮已有臂 {dup['arm_label']} 用「{value}」——同取值不重复挂"}

                # ── 派生臂标 A/B/C...（轮内已有臂数）──
                cnt = await conn.fetchval(
                    "SELECT count(*) FROM pipeline.experiment_arms WHERE round_id=$1::uuid", round_id)
                if int(cnt) >= 26:
                    return {"ok": False, "error": "too_many_arms", "hint": "单轮臂标 A-Z，已满 26"}
                label = chr(ord("A") + int(cnt))

                # production_mode：扫 production_mode 时取值=模式；否则继承 experiment.track
                if sv_eff == "production_mode":
                    pmode = value if value in ("human_brief", "ai_video") else None
                else:
                    pmode = exp["track"] if exp["track"] in ("human_brief", "ai_video") else None

                arm = await conn.fetchrow(
                    "INSERT INTO pipeline.experiment_arms "
                    "(round_id, experiment_id, sku_id, round_no, swept_variable, variable_value, arm_label, script_id, production_mode) "
                    "VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8::uuid,$9) "
                    "RETURNING id::text AS id, arm_label, variable_value, script_id::text AS script_id",
                    round_id, experiment_id, exp["sku_id"], round_no_eff,
                    sv_eff, value, label, script_id, pmode,
                )

                adopted = False
                if adopt_script:
                    ad = await conn.fetchrow(
                        "UPDATE pipeline.scripts SET status='adopted' "
                        "WHERE id=$1::uuid AND status<>'archived' RETURNING id", script_id)
                    adopted = bool(ad)
    except Exception as exc:
        if "experiment_arms_uq" in str(exc):
            return {"ok": False, "error": "arm_label_collision", "hint": "并发挂臂撞臂标，重试一次"}
        logger.exception("attach_arm failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}

    code = arm_code(round_no_eff, arm["arm_label"])
    return {
        "ok": True,
        "arm": {"arm_id": arm["id"], "arm_label": arm["arm_label"],
                "round_no": round_no_eff, "swept_variable": sv_eff,
                "swept_variable_label": var_label(sv_eff),
                "variable_value": arm["variable_value"], "script_id": arm["script_id"],
                "arm_code": code},
        "script_adopted": adopted,
        "warnings": warnings,
        "next_step_hint": (
            f"挂成 第{round_no_eff}轮·臂{arm['arm_label']}（扫{var_label(sv_eff)}=「{value}」）。"
            f"投放时把臂码「{code}」写进巨量视频名/备注；投后用 "
            f"record_ad_metrics_batch(experiment_id, csv) 导出报表整轮回灌（按臂码匹配），"
            f"或单条 record_ad_metrics(experiment_arm_id='{arm['id']}', metrics=...)。"
            f"⚠️ metrics 务必带 impressions（曝光量），否则没法判 winner 可不可信。"
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# adopt script as arm（采纳即自动 A/B：采纳一条脚本→找/建实验+挂臂，一步成）
# ══════════════════════════════════════════════════════════════════════════════
# kind → intent 反推（脚本没显式 intent 时兜底）；kind → 生产链 track
_KIND_TO_INTENT = {
    "video_planting": "planting", "video_harvest": "harvest", "video_soft_ad": "soft_ad",
}


def _track_for_kind(kind: str | None) -> str:
    """脚本生产链：director_brief=真人编导(human_brief)；creative_pack/其它=AI 出片链(ai_video)。"""
    return "human_brief" if kind == "director_brief" else "ai_video"


async def adopt_script_as_arm(
    *,
    script_id: str,
    variable_value: str,
    swept_variable: str | None = None,
    round_no: int | None = None,
    experiment_id: str | None = None,
    intent: str | None = None,
    north_star_metric: str | None = None,
    title: str | None = None,
    _connection: Any | None = None,
) -> dict:
    """采纳即自动 A/B：采纳一条脚本时自动找到（或新建）它的 SKU×intent×track 实验，再把这条
    脚本挂成某轮某臂（draft→adopted）。一步打通"认可脚本 → 起有记录的 A/B 测试"。

    实验从脚本血缘自动推（sku_id/intent/portrait_id/audience_record_id 都在 scripts 行里）：
    同 SKU×intent×track 已有 running 实验 → 复用；没有 → 自动 create_experiment。然后 attach_arm。
    新实验/新轮要 swept_variable（本轮测哪个变量）。单臂不构成对比——采纳第 2 条同轮换取值的脚本
    才凑成真 A/B（status/changelog 会提示）。
    """
    explicit_experiment_id = experiment_id is not None
    if explicit_experiment_id:
        if not isinstance(experiment_id, str) or not experiment_id.strip():
            return _arm_mismatch("experiment_id")
        try:
            experiment_id = str(UUID(experiment_id.strip()))
        except ValueError:
            return _arm_mismatch("experiment_id")
    explicit_round_no = round_no is not None
    db = _connection or get_pool()
    srow = await db.fetchrow(
        "SELECT sku_id, kind, intent, status, "
        "portrait_id::text AS portrait_id, audience_record_id::text AS audience_record_id "
        "FROM pipeline.scripts WHERE id=$1::uuid", script_id,
    )
    if not srow:
        return {"ok": False, "error": "script_not_found", "script_id": script_id}

    value = (variable_value or "").strip()
    if not value:
        return {"ok": False, "error": "missing_variable_value",
                "hint": "本臂的变量取值（如『悬念式钩子』）——采纳挂臂要标这条脚本在本轮变量上取了啥值"}

    sku_id = srow["sku_id"]
    kind = srow["kind"]
    track = _track_for_kind(kind)
    eff_intent = intent or srow["intent"] or _KIND_TO_INTENT.get(kind or "")
    if not eff_intent:
        return {"ok": False, "error": "missing_intent",
                "hint": f"脚本没带 intent（kind={kind}）且没法从 kind 反推——传 intent"
                        f"（planting/harvest/soft_ad/hard_ad）说明投放意图，北极星才能定"}
    if eff_intent not in INTENT_NORTH_STAR:
        return {"ok": False, "error": "bad_intent",
                "hint": f"intent 只能是 {list(INTENT_NORTH_STAR)} 之一；给的/推的：{eff_intent}"}
    formal_planting = eff_intent == "planting" and track == "ai_video"
    if formal_planting and srow["intent"] != "planting":
        return _arm_mismatch("intent")

    if formal_planting and not explicit_experiment_id and _connection is None:
        lock_key = f"pipeline.adopt_script_as_arm:{sku_id}:{eff_intent}:{track}"
        async with db.acquire() as conn:
            async with conn.transaction():
                # Transaction-scoped: commit/rollback releases the lock automatically.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0::bigint))",
                    lock_key,
                )
                # Re-read every decision input while holding the same cross-process lock.
                return await adopt_script_as_arm(
                    script_id=script_id,
                    variable_value=variable_value,
                    swept_variable=swept_variable,
                    round_no=round_no,
                    experiment_id=experiment_id,
                    intent=intent,
                    north_star_metric=north_star_metric,
                    title=title,
                    _connection=conn,
                )

    # ── 定位实验：显式 experiment_id 优先；否则找同 SKU×intent×track 的 running 实验 ──
    if explicit_experiment_id:
        erow = await db.fetchrow(
            "SELECT id::text AS id, sku_id, intent, track, north_star_metric "
            "FROM pipeline.experiments WHERE id=$1::uuid", experiment_id)
        if not erow:
            return {"ok": False, "error": "experiment_not_found", "experiment_id": experiment_id}
        if formal_planting and erow["sku_id"] != sku_id:
            return _arm_mismatch("sku_id")
        if formal_planting and erow["intent"] != "planting":
            return _arm_mismatch("intent")
        if formal_planting and erow["track"] != "ai_video":
            return _arm_mismatch("track")
        if formal_planting and erow["north_star_metric"] != "a3_ratio":
            return _arm_mismatch("north_star_metric")
        if not formal_planting and erow["sku_id"] != sku_id:
            return {"ok": False, "error": "experiment_sku_mismatch",
                    "hint": f"实验属于 {erow['sku_id']}，脚本是 {sku_id}"}
        eid = experiment_id
    else:
        erow = await db.fetchrow(
            "SELECT id::text AS id, sku_id, intent, track, north_star_metric FROM pipeline.experiments "
            "WHERE sku_id=$1 AND intent=$2 AND track=$3 AND status='running' "
            "ORDER BY created_at DESC LIMIT 1", sku_id, eff_intent, track)
        eid = erow["id"] if erow else None
        if formal_planting and erow and erow["north_star_metric"] != "a3_ratio":
            return _arm_mismatch("north_star_metric")

    # ── 提前拦：要新开一轮却没 swept_variable（建空实验前就拦，避免留垃圾实验）──
    open_round = await db.fetchrow(
        """SELECT r.id::text AS id, r.round_no, r.swept_variable, r.status,
                  count(a.id)::int AS arm_count
           FROM pipeline.experiment_rounds r
           LEFT JOIN pipeline.experiment_arms a ON a.round_id=r.id
           WHERE r.experiment_id=$1::uuid AND r.status='open'
           GROUP BY r.id, r.round_no, r.swept_variable, r.status
           ORDER BY r.round_no DESC LIMIT 1""",
        eid,
    ) if eid else None
    has_open_round = bool(open_round)
    if formal_planting and open_round and int(open_round["arm_count"] or 0) >= 1:
        if not (explicit_experiment_id and explicit_round_no):
            return {
                "ok": False,
                "error": "planting_second_arm_requires_explicit_round",
            }
        if int(round_no) != int(open_round["round_no"]):
            return _arm_mismatch("round_no")
        if not swept_variable or swept_variable.strip() != open_round["swept_variable"]:
            return _arm_mismatch("swept_variable")
    will_open_new_round = (eid is None) or (round_no is None and not has_open_round)
    if will_open_new_round and not (swept_variable or "").strip():
        return {"ok": False, "error": "missing_swept_variable",
                "hint": "这是该实验/该轮第一条臂，要新开一轮——传 swept_variable（本轮测哪个变量，"
                        "如 opening_hook_3s/selling_point_set/idea_seed），这样 changelog 才一眼看出是单变量测试"}

    # ── 没现成实验 → 从脚本血缘自动建 ──
    created_experiment = False
    north_star_meta = None
    if eid is None:
        if not (srow["portrait_id"] or srow["audience_record_id"]):
            return {"ok": False, "error": "script_missing_audience",
                    "hint": "脚本没挂人群（portrait_id/audience_record_id 都空），建不了实验——"
                            "这条脚本不是从 SKU→人群链出来的？补人群再采纳"}
        cr = await create_experiment(
            sku_id=sku_id, intent=eff_intent, portrait_id=srow["portrait_id"],
            audience_record_id=srow["audience_record_id"], north_star_metric=north_star_metric,
            title=title or f"{sku_id} {INTENT_LABELS.get(eff_intent, eff_intent)}（采纳自动建）", track=track,
            _connection=_connection)
        if not cr.get("ok"):
            return cr
        eid = cr["experiment"]["id"]
        created_experiment = True
        north_star_meta = cr.get("north_star")

    # ── 挂臂（采纳：draft→adopted）──
    res = await attach_arm(
        experiment_id=eid, script_id=script_id, variable_value=value,
        round_no=round_no, swept_variable=swept_variable, adopt_script=True,
        _connection=_connection)
    res["experiment_id"] = eid
    res["created_experiment"] = created_experiment
    if not res.get("ok"):
        return res  # 自动建的空实验无害，不回滚，带 experiment_id 回去方便排查

    res["intent"] = eff_intent
    res["track"] = track
    if north_star_meta:
        res["north_star"] = north_star_meta
    arm = res["arm"]
    res["round_no"] = arm["round_no"]
    res["adopt_hint"] = (
        f"已采纳并挂成{'【新建实验】' if created_experiment else ''}第{arm['round_no']}轮·臂{arm['arm_label']}"
        f"（测{arm['swept_variable_label']}=「{value}」）。单臂还不是对比——再采纳一条同轮、"
        f"{arm['swept_variable_label']}换个取值的脚本凑成 A/B；投放把臂码「{arm['arm_code']}」写进巨量视频名，"
        f"投后 record_ad_metrics_batch 整轮回灌。看演化：experiment_changelog。"
    )
    return res


# ══════════════════════════════════════════════════════════════════════════════
# status（确定性排名 + R-14 分层 + R-15 待验证 + 建议下变量）
# ══════════════════════════════════════════════════════════════════════════════
async def experiment_status(experiment_id: str, round_no: int | None = None) -> dict:
    pool = get_pool()
    exp = await pool.fetchrow(
        """SELECT id::text AS id, sku_id, intent, track, north_star_metric, north_star_direction,
                  baseline, evaluation_policy, status, title
           FROM pipeline.experiments WHERE id = $1::uuid""",
        experiment_id,
    )
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    baseline = _as_dict(exp["baseline"])
    evaluation_policy = _as_dict(exp["evaluation_policy"])
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
                      impressions_sum, predicted_match_score, script_id::text AS script_id
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
            d["impressions"] = _num(d.pop("impressions_sum", None))  # 064：曝光量旁证
            d["predicted_match_score"] = _num(d.get("predicted_match_score"))  # 066：投前向量预测分旁证
            d["arm_code"] = arm_code(round_no, d["arm_label"])       # 巨量命名/CSV 回灌匹配码
            arms_out.append(d)

    # 排名（只在有北极星值的臂之间；sufficient 优先）
    ranked = [a for a in arms_out if a["north_star_avg"] is not None]
    ranked.sort(key=lambda a: a["north_star_avg"], reverse=higher_better)
    sufficient = [a for a in ranked if a["sample_status"] == "sufficient"]
    leader = sufficient[0] if sufficient else (ranked[0] if ranked else None)
    can_lock = bool(sufficient)  # 有 ≥1 个 n≥5 的臂才允许正常锁定（n<5 要 force）

    # 曝光量旁证（064/块0b）：北极星是比率、对曝光量脱敏。臂间曝光差太大时 winner 可能是
    # "被多灌量灌出来的"——给确定性存疑提示，不改排名（系统强制不了等量投放，留给老板眼判）。
    exposure_skew_warning = None
    _imps = [a["impressions"] for a in ranked if a.get("impressions") and a["impressions"] > 0]
    if len(_imps) >= 2:
        _ratio = max(_imps) / min(_imps)
        if _ratio >= 3:
            exposure_skew_warning = (
                f"⚠ 臂间曝光量差 {_ratio:.1f} 倍（{int(min(_imps))}~{int(max(_imps))}）——北极星是比率、对曝光量脱敏，"
                f"曝光差这么大时 winner 可能是被多灌量灌出来的，别直接按均值定输赢；尽量等量投放后再判。"
            )
    _missing_imp = [a["arm_label"] for a in ranked if a.get("impressions") is None]
    exposure_note = (
        f"臂 {','.join(_missing_imp)} 没回传曝光量(impressions)——补上才能判这个比率可不可信。"
        if (_missing_imp and ranked) else None
    )

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
        "evaluation_policy": evaluation_policy,
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
        "exposure_skew_warning": exposure_skew_warning,
        "exposure_note": exposure_note,
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
# next version seed（块B：一键出下一版——组上版获胜 baseline + 建议扫的下个变量，预填生成）
# ══════════════════════════════════════════════════════════════════════════════
async def next_version_seed(experiment_id: str, override_variable: str | None = None) -> dict:
    """组下一版生成的"种子"：把已锁的获胜 baseline + 建议扫的下个变量预填好，喂 generate_*。

    半自动（符合"每步停等反馈"）：本函数不生成、不写库，只把"下一版该带啥设定、测哪个变量"
    算清楚返回；主大脑据此调 generate_director_brief / generate_creative_pack（带 experiment_context），
    给本轮 ≥2 个取值各生成一条 → 各自 experiment_attach_arm 挂臂。
    """
    pool = get_pool()
    exp = await pool.fetchrow(
        "SELECT id::text AS id, sku_id, portrait_id::text AS portrait_id, "
        "audience_record_id::text AS audience_record_id, intent, track, "
        "north_star_metric, baseline, status FROM pipeline.experiments WHERE id=$1::uuid",
        experiment_id)
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    baseline = _as_dict(exp["baseline"])

    # 建议下个变量：override 优先；否则确定性差集（标准池 - 已测 - baseline 已锁）
    tested = set(baseline.keys())
    trows = await pool.fetch(
        "SELECT DISTINCT swept_variable FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid",
        experiment_id)
    tested |= {t["swept_variable"] for t in trows}
    next_var = (override_variable.strip() if override_variable
                else next((k for k in sweep_order_for_track(exp["track"]) if k not in tested), None))

    next_round_no = int(await pool.fetchval(
        "SELECT COALESCE(MAX(round_no),0)+1 FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid",
        experiment_id))

    if not next_var:
        return {"ok": True, "experiment_id": experiment_id, "baseline": baseline,
                "next_variable": None, "next_round_no": next_round_no, "done": True,
                "hint": "标准变量都扫完了——可 experiment_distill 把获胜框架沉淀成 prompt_rule（先 dry_run）。"}

    # experiment_context：固定 baseline、本轮只动 next_var（value 留空，老板/生成时填每臂取值）
    experiment_context = {"baseline": baseline, "sweep": {"variable": next_var, "value": None}}
    target_model = baseline.get("target_model")
    if exp["track"] == "ai_video":
        gen_tool = "generate_creative_pack"
        gen_args = {"kind": intent_to_creative_kind(exp["intent"]),
                    "audience_record_id": exp["audience_record_id"],
                    "intent": exp["intent"], "experiment_context": experiment_context}
    else:  # human_brief / mixed → 真人编导 brief
        gen_tool = "generate_director_brief"
        gen_args = {"portrait_id": exp["portrait_id"],
                    "audience_record_id": exp["audience_record_id"],
                    "intent": exp["intent"], "experiment_context": experiment_context}
    if target_model:
        gen_args["target_model"] = target_model

    return {
        "ok": True,
        "experiment_id": experiment_id,
        "sku_id": exp["sku_id"], "intent": exp["intent"], "track": exp["track"],
        "north_star_metric": exp["north_star_metric"],
        "baseline": baseline,
        "next_variable": {"variable": next_var, "label": var_label(next_var)},
        "next_round_no": next_round_no,
        "generation": {"tool": gen_tool, "suggested_args": gen_args},
        "hint": (
            f"下一版（第{next_round_no}轮）建议扫【{var_label(next_var)}】。调 {gen_tool}(...) 带上 "
            f"experiment_context（已固定 {len(baseline)} 项获胜 baseline），给本轮 ≥2 个取值各生成一条 → "
            f"各自 experiment_attach_arm(round_no={next_round_no}, swept_variable='{next_var}', variable_value=该取值) 挂臂。"
            + ("⚠️ 真人链单变量是近似（演员/光线/剪辑噪声消不掉），结论是粗信号。" if exp["track"] != "ai_video" else "")
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# changelog（块C：版本变更日志——逐轮"改了哪个变量 / 取值从→到 / 这版赢面"，派生只读）
# ══════════════════════════════════════════════════════════════════════════════
async def get_changelog(experiment_id: str) -> dict:
    pool = get_pool()
    exp = await pool.fetchrow(
        "SELECT id::text AS id, sku_id, intent, track, north_star_metric, baseline, status "
        "FROM pipeline.experiments WHERE id=$1::uuid", experiment_id)
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    rows = await pool.fetch(
        "SELECT round_no, swept_variable, status, winner_label, winner_value, winner_forced, "
        "       winner_north_star_avg, winner_n_videos, winner_impressions, n_arms, baseline_snapshot "
        "FROM pipeline.v_content_version_changelog WHERE experiment_id=$1::uuid ORDER BY round_no",
        experiment_id)

    entries = []
    prev_baseline: dict = {}
    for r in rows:
        sv = r["swept_variable"]
        to_val = r["winner_value"]
        entries.append({
            "round_no": int(r["round_no"]),
            "swept_variable": sv, "swept_variable_label": var_label(sv),
            "status": r["status"],
            "from_value": prev_baseline.get(sv),   # 上一版该变量取值（None=首次确定）
            "to_value": to_val,
            "winner_label": r["winner_label"], "forced": bool(r["winner_forced"]) if r["winner_forced"] is not None else False,
            "north_star_avg": _num(r["winner_north_star_avg"]),
            "n_videos": int(r["winner_n_videos"]) if r["winner_n_videos"] is not None else 0,
            "impressions": _num(r["winner_impressions"]),
            "n_arms": int(r["n_arms"] or 0),
        })
        snap = _as_dict(r["baseline_snapshot"]) if r["baseline_snapshot"] else {}
        if snap:
            prev_baseline = snap
        elif to_val is not None and r["status"] == "locked":
            prev_baseline = {**prev_baseline, sv: to_val}

    cur_baseline = _as_dict(exp["baseline"])
    lines = [f"# 内容版本变更日志 · {exp['sku_id']} · {INTENT_LABELS.get(exp['intent'], exp['intent'])}",
             f"> 北极星：{exp['north_star_metric']}；当前 baseline 已锁 {len(cur_baseline)} 项。", ""]
    for e in entries:
        if e["status"] == "locked" and e["to_value"] is not None:
            chg = (f"【{e['swept_variable_label']}】定为「{e['to_value']}」"
                   + (f"（上版「{e['from_value']}」→改）" if e["from_value"] else "（首次确定）"))
            nsa = e["north_star_avg"]
            mp = ""
            if nsa is not None:
                mp = (f"，赢面 {nsa}（n={e['n_videos']}"
                      + (f"·曝光{int(e['impressions'])}" if e["impressions"] else "")
                      + ("·FORCED·n<5" if e["forced"] else "") + "）")
            lines.append(f"- **第{e['round_no']}轮** {chg}{mp}")
        else:
            lines.append(f"- **第{e['round_no']}轮** 扫【{e['swept_variable_label']}】（{e['n_arms']}臂，进行中·未锁）")
    if not entries:
        lines.append("- （还没有任何轮次——experiment_attach_arm 挂第一轮的臂开始）")

    return {"ok": True, "experiment_id": experiment_id, "sku_id": exp["sku_id"],
            "intent": exp["intent"], "north_star_metric": exp["north_star_metric"],
            "status": exp["status"], "current_baseline": cur_baseline,
            "entries": entries, "markdown": "\n".join(lines)}


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
        f"""SELECT e.id::text AS id, e.sku_id, e.intent, e.track, e.north_star_metric, e.status,
                   e.title, e.baseline, e.evaluation_policy, e.created_at,
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
        d["evaluation_policy"] = _as_dict(d["evaluation_policy"])
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
                   evaluation_policy, winning_framework_md, framework_distilled_at, created_at
           FROM pipeline.experiments WHERE id = $1::uuid""",
        experiment_id,
    )
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    d = dict(exp)
    d["baseline"] = _as_dict(d["baseline"])
    d["evaluation_policy"] = _as_dict(d["evaluation_policy"])
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
