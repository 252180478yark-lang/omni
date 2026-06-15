"""编导 brief A/B 单变量迭代闭环 —— 实验台账 + 确定性状态机 + 市场数据→规则沉淀桥。

migration 052 / service app.services.experiment_lab。设计稿 docs/design-director-brief-ab-loop.md。

节拍=真实投放天/周，不跑 agent loop。6 个状态机 tool 全确定性 SQL（排名/判 winner/
汇总/建议下变量）；只有 experiment_distill 的 polish 路径调 LLM（默认不开）。R-14 不编因果、
R-15 n<5 标待验证。

老板话术 → tool：
- "给 SKU-X 这个人群建个种草 A/B 实验" → experiment_create(sku_id, intent='planting', portrait_id=...)
- "这一轮测开头钩子，登记这几条 brief" → experiment_register_round(experiment_id, swept_variable='opening_hook_3s', arms=[...])
- "看这轮哪个臂赢了 / 下一步测啥" → experiment_status(experiment_id)
- "锁定 B 臂 / 这个钩子定了" → experiment_lock_winner(experiment_id, round_no, winning_arm_id)
- "把这套获胜框架沉淀下来" → experiment_distill(experiment_id)（先 dry_run 看，再 dry_run=False 落规则草稿，老板 prompt_rule_set_enabled 点亮）
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import build_trace
from app.services import experiment_lab as lab
from app.services import prompt_rules as pr
from app.services.ai_hub_client import AIHubClient

# 沉淀桥 polish 护栏：出现这些"因果/比较级"词 → 判定编造，回退模板（R-14）
_POLISH_BLACKLIST = (
    "因为", "所以", "因此", "故而", "导致", "致使", "由于",
    "更", "优于", "有效", "明显", "抓住", "吸引", "打动", "提升", "增强", "胜过", "好于",
)


def _polish_ok(text: str, value: str) -> bool:
    """润色后规则只能表达'获胜设定'，不能编因果/加数值/丢取值。"""
    if not text or any(b in text for b in _POLISH_BLACKLIST):
        return False
    val_digits = {c for c in value if c.isdigit()}
    if any(c.isdigit() and c not in val_digits for c in text):  # 禁新增数值
        return False
    if value not in text:  # 必须保留获胜取值原文
        return False
    return True


@tool_with_audit(mcp, require_approval=False)
async def experiment_create(
    sku_id: str,
    intent: str,
    portrait_id: str | None = None,
    audience_record_id: str | None = None,
    north_star_metric: str | None = None,
    title: str | None = None,
) -> dict:
    """建一个编导 brief A/B 实验（SKU×人群×投放意图×北极星）。确定性。

    一个实验 = 围绕"这个 SKU × 这个人群 × 这个 intent"长期跑的单变量迭代台账。intent 定死后
    北极星自动选（种草→完播率 completion_rate / 收割→转化率 cvr / 软广→完播率 / 硬广→cvr）。
    **intent 不可中途改、不可当变量扫**（换 intent 北极星就变，没法比）；要比种草 vs 收割是
    两个独立实验。

    Args:
        sku_id: mvp_sku id
        intent: planting(种草) / harvest(收割) / soft_ad(软广) / hard_ad(硬广)
        portrait_id: step 3.5 人群画像 id（给了自动回填 record/run/matrix 血缘）
        audience_record_id: 没画像时用人群记录 id
        north_star_metric: 一般不填（按 intent 自动选）；要自定义必须是 ad_metrics 白名单里的
            rate/money/count 指标（roi/roas 是后端算的不可手填，收割北极星用 cvr）
        title: 可选实验名

    Returns:
        {ok, experiment:{id, intent, north_star_metric, ...}, north_star, next_step_hint}
    """
    return await lab.create_experiment(
        sku_id=sku_id, intent=intent, portrait_id=portrait_id,
        audience_record_id=audience_record_id, north_star_metric=north_star_metric, title=title,
    )


@tool_with_audit(mcp, require_approval=False)
async def experiment_register_round(
    experiment_id: str,
    swept_variable: str,
    arms: list[dict],
    round_no: int | None = None,
) -> dict:
    """登记一轮 flight：本轮只扫一个变量，给 ≥2 个臂（每臂一个取值 = 一条 director_brief）。

    单变量纪律：本轮只动 swept_variable，其余按 experiment.baseline 固定。生成各臂 brief 时
    通过 generate_director_brief 的 experiment_context={"baseline":{...},"sweep":{"variable","value"}}
    喂进去，让 brief 硬性"固定 baseline、只动这个变量"。本 tool **只登记结果**（已生成 brief 的
    script_id），自身不调 LLM。

    可扫变量（标准池，按对'视频↔人群匹配度'撬动排序）：
        内容核 idea_seed(拍什么事) / opening_hook_3s(开头钩子) / selling_point_set(卖点组合) / scene(场景)
        表达层 emotion(情绪) / story_pace(叙事节奏)
        呈现层 edit_pace(剪辑节奏) / visual_vector(画面向量) / bgm(音乐) / target_model(AI模型)

    Args:
        experiment_id: experiment_create 返的 id
        swept_variable: 本轮扫的变量 key（上面池里选；自定义也行但不进'建议下变量'轮转）
        arms: [{"variable_value": "悬念式", "script_id": "<director_brief 的 id>"}, ...]
            ≥2 个、variable_value 不重复；script_id 可空（先登记后补）
        round_no: 一般不填（自增）；显式传可指定轮号

    Returns:
        {ok, round:{round_id, round_no, arms:[{id, arm_label, variable_value, script_id}]}, warnings}
    """
    return await lab.register_round(
        experiment_id=experiment_id, swept_variable=swept_variable, arms=arms, round_no=round_no,
    )


@tool_with_audit(mcp, require_approval=False)
async def experiment_status(experiment_id: str, round_no: int | None = None) -> dict:
    """看某轮各臂的投后排名 + 当前基线 + 建议下个变量。确定性、R-14 分层、R-15 待验证。

    读 pipeline.v_experiment_round_results（按北极星 avg 排名，sum 只展示不排名——避免'投得多'
    误判成'取值好'）。严格分层：observations（客观真值不含因果）/ hypotheses（只给'当前领先'+
    待验证，禁'因为X所以Y'）/ next_variable_suggestion（确定性差集）。n<5 的臂标 preliminary，
    不许直接判 winner（lock 时拦，除非 force）。

    Args:
        experiment_id: 实验 id
        round_no: 看某轮（不填=最新未锁定轮）

    Returns:
        {ok, arms:[{arm_label, variable_value, n_videos, north_star_avg, sample_status,...}],
         ranking, leader_arm_id, can_lock, observations, hypotheses,
         next_variable_suggestion, metric_scale_warning}
    """
    return await lab.experiment_status(experiment_id, round_no=round_no)


@tool_with_audit(mcp, require_approval=False)
async def experiment_lock_winner(
    experiment_id: str,
    round_no: int,
    winning_arm_id: str,
    force: bool = False,
) -> dict:
    """锁定某轮 winner，把它的取值写进 baseline（下一轮自动继承）。确定性 + R-15 闸。

    n<5 的臂默认拦下（preliminary_winner_blocked）——补够视频/回传再锁；急的话 force=True
    硬锁（会标 forced 留痕，且这只是'当前领先'不是统计证明）。锁定后状态机建议下一个该扫的变量。

    Args:
        experiment_id: 实验 id
        round_no: 哪一轮
        winning_arm_id: 获胜臂 id（experiment_status 的 arms[].arm_id）
        force: True 强行锁 n<5 的臂（R-15 旁路，留痕）

    Returns:
        {ok, locked:{swept_variable, value, forced, reason}, baseline, overwrite_warning,
         next_variable_suggestion, next_step_hint}
    """
    return await lab.lock_winner(
        experiment_id=experiment_id, round_no=round_no, winning_arm_id=winning_arm_id, force=force,
    )


@tool_with_audit(mcp, require_approval=False)
async def experiment_list(
    sku_id: str | None = None,
    status: str | None = None,
    limit: int = 30,
) -> dict:
    """列实验台账（可按 sku_id / status=running/converged/archived 过滤）。确定性只读。"""
    return await lab.list_experiments(sku_id=sku_id, status=status, limit=limit)


@tool_with_audit(mcp, require_approval=False)
async def experiment_get(experiment_id: str) -> dict:
    """看一个实验的全貌：基线 + 每轮各臂 + 投后结果。确定性只读。"""
    return await lab.get_experiment(experiment_id)


@tool_with_audit(mcp, require_approval=False)
async def experiment_distill(
    experiment_id: str,
    dry_run: bool = True,
    polish: bool = False,
) -> dict:
    """把一个实验的获胜基线沉淀成回注 generate_director_brief 的 prompt_rule（市场数据→规则桥）。

    这是"越用越聪明"的关键——把真实投放跑出来的获胜设定，写成下条 brief 自动带上的规则。
    **铁律（R-14/R-15）**：规则只表达【确定的获胜设定】（"开头钩子固定用悬念式"），绝不写
    【为什么】（禁"因为悬念更抓人"这类编造因果）。样本门槛：n<3 不出规则（只入观察）；
    n∈[3,5) 标 [待验证]+"倾向用"；n≥5 才"固定用"。规则默认 enabled=FALSE，老板逐条
    prompt_rule_set_enabled 点亮才生效。

    Args:
        experiment_id: 收敛（或老板觉得可沉淀）的实验
        dry_run: 默认 True——零写库，返候选规则 + 人读获胜框架预览供审；False 才真落 prompt_rules 草稿
        polish: 默认 False=纯模板（事实 100% 来自 baseline）；True 在模板上跑 LLM 口语化润色，
            但过护栏（禁因果/比较级词、禁新增数值、必保留获胜取值原文），越界自动回退模板

    Returns:
        dry_run: {ok, dry_run:True, candidates:[{label, value, rule_text, tier, n, already_distilled,
                  value_changed}], blocked, winning_framework_preview, scope}
        落库:   {ok, dry_run:False, created:[{rule_id, swept_variable, rule_text, enabled:False}],
                 skipped, winning_framework_md, next_step_hint}
    """
    skel = await lab.collect_distill_skeleton(experiment_id)
    if not skel.get("ok"):
        return skel
    candidates = skel["candidates"]
    blocked = skel["blocked"]
    exp = skel["experiment"]
    scope = skel["scope"]

    if not candidates and not blocked:
        return {"ok": False, "error": "nothing_to_distill",
                "hint": "实验 baseline 还空——先 lock_winner 锁定至少一个变量再沉淀"}

    # 已沉淀判重（同实验同变量）
    already = await lab.already_distilled_map(experiment_id)
    for c in candidates:
        existing = already.get(c["swept_variable"])
        c["already_distilled"] = bool(existing)
        if existing:
            m = re.search(r"「(.+?)」", existing)
            c["value_changed"] = bool(m and m.group(1) != c["value"])
        else:
            c["value_changed"] = False

    # polish：模板 → LLM 润色 → 护栏，越界回退模板（dry_run 也跑，保证预览=落库）
    trace = None
    if polish and candidates:
        try:
            sys_msg = prompts.load("experiment_distill.system")
            lines = "\n".join(
                f"- 变量={c['label']}；获胜取值=「{c['value']}」；模板规则={c['rule_text']}"
                for c in candidates
            )
            user_msg = prompts.render("experiment_distill.user",
                                      intent_label=exp["intent_label"], candidates=lines)
            mcfg = get_model_for_tool("experiment_distill")
            client = AIHubClient(timeout=120.0)
            resp = await client.chat(
                messages=[{"role": "system", "content": sys_msg},
                          {"role": "user", "content": user_msg}],
                provider=mcfg.get("provider", "gemini"),
                model=mcfg.get("model", "gemini-3.1-pro-preview"),
                temperature=0.3, max_tokens=1200, enforce_human_voice=True,
            )
            txt = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
                   or resp.get("text") or "").strip()
            polished = {}
            for ln in txt.splitlines():
                mm = re.match(r"\s*[-*]?\s*([^：:]+)[：:]\s*(.+)", ln.strip())
                if mm:
                    polished[mm.group(1).strip()] = mm.group(2).strip()
            for c in candidates:
                cand = polished.get(c["label"])
                prefix = "[待验证] " if c["tier"] == "preliminary" else ""
                if cand and _polish_ok(cand, c["value"]):
                    c["rule_text"] = prefix + cand.lstrip("[待验证] ").strip()
                # 否则保留模板 rule_text（已是安全文本）
            trace = build_trace(
                provider=mcfg.get("provider", "gemini"), model=mcfg.get("model", "gemini-3.1-pro-preview"),
                prompt=sys_msg + "\n\n" + user_msg,
                params={"polish": True, "n_candidates": len(candidates)},
                cost_estimate="1 small quota call (~1-2k tokens)",
            )
        except Exception as exc:
            logger.warning("experiment_distill polish 失败，回退纯模板：%s", exc)

    # 人读获胜框架
    header = (f"# 获胜内容框架 · {exp['sku_id']} · {exp['intent_label']}\n"
              f"> 北极星：{exp['north_star_metric']}。下列为各变量当前实验领先的设定。\n"
              f"> ⚠️ 画像/投放数据只是冷启动代理，真实价值以持续 CTR/CVR/ROI 为准；"
              f"未排除平台分发量级/冷启动差异。\n")
    framework_md = header + "\n".join(skel["framework_lines"])

    if dry_run:
        return {
            "ok": True, "dry_run": True,
            "experiment": exp,
            "scope": scope,
            "candidates": candidates,
            "blocked": blocked,
            "winning_framework_preview": framework_md,
            "trace": trace,
            "next_step_hint": "确认无误后 experiment_distill(experiment_id, dry_run=False) 落规则草稿（默认 enabled=FALSE），再 prompt_rule_set_enabled 逐条点亮",
        }

    # 落库：每个未沉淀过的候选 → create_rule（enabled=False）
    created, skipped = [], []
    for c in candidates:
        if c["already_distilled"] and not c["value_changed"]:
            skipped.append({"swept_variable": c["swept_variable"], "reason": "already_distilled_same_value"})
            continue
        try:
            rule = await pr.create_rule(
                "pipeline.director_brief", c["rule_text"],
                scope=scope, enabled=False,
                source_experiment_id=experiment_id, source_round_var=c["swept_variable"],
            )
            item = {"rule_id": str(rule["id"]), "swept_variable": c["swept_variable"],
                    "rule_text": c["rule_text"], "enabled": False}
            if c["value_changed"]:
                item["note"] = "该变量旧规则取值已变，新规则已建——旧规则请手动 prompt_rule_set_enabled(False) 熄灭"
            created.append(item)
        except Exception as exc:
            logger.exception("experiment_distill create_rule failed: %s", exc)
            skipped.append({"swept_variable": c["swept_variable"], "reason": f"db_error:{exc}"})

    await lab.write_winning_framework(experiment_id, framework_md)

    return {
        "ok": True, "dry_run": False,
        "experiment": exp,
        "scope": scope,
        "created": created,
        "skipped": skipped,
        "blocked": blocked,
        "winning_framework_md": framework_md,
        "trace": trace,
        "next_step_hint": (
            "规则已落库但 enabled=FALSE 不生效。prompt_rule_list(node_id='pipeline.director_brief') 看草稿，"
            "prompt_rule_set_enabled(rule_id, True) 逐条点亮 → 以后这个 SKU 这个 intent 的 brief 自动带上"
        ),
    }
