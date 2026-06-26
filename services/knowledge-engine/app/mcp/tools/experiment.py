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

import asyncio
import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

from app.database import get_pool
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
    track: str = "human_brief",
) -> dict:
    """建一个 A/B 实验（SKU×人群×投放意图×北极星×track）。确定性。

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
        track: 生产链 human_brief（真人编导 brief→拍，默认）/ ai_video（AI 提示词→出片，
            沉淀写 creative_pack 节点 + 可投前视觉快环）/ mixed（同实验 A/B 真人 vs AI，
            swept_variable=production_mode，只出模式偏好不写 prompt 规则）

    Returns:
        {ok, experiment:{id, intent, track, north_star_metric, ...}, north_star, next_step_hint}
    """
    return await lab.create_experiment(
        sku_id=sku_id, intent=intent, portrait_id=portrait_id,
        audience_record_id=audience_record_id, north_star_metric=north_star_metric, title=title,
        track=track,
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
async def experiment_attach_arm(
    experiment_id: str,
    script_id: str,
    variable_value: str,
    round_no: int | None = None,
    swept_variable: str | None = None,
    adopt_script: bool = True,
) -> dict:
    """采纳即挂臂：把老板采纳的一条 brief/AI 脚本挂成某轮某臂（单条追加，配合采纳动作）。

    register_round 是"一次登记整轮 ≥2 臂"；本 tool 是"老板一条条采纳、逐条标成臂"——采纳
    step3.6 编导 brief 或 step5 creative_pack(AI) 后，标"这是实验X第N轮、本轮扫变量Z、本臂取值Y"，
    自动挂成臂 + 把该脚本 draft→adopted。老板话术"把这条采纳为实验X的某臂 / 这条挂成钩子=悬念那个臂"。

    Args:
        experiment_id: experiment_create 返的 id
        script_id: 采纳的 pipeline.scripts.id（director_brief 或 creative_pack 脚本）
        variable_value: 本臂的变量取值（如"悬念式钩子"）
        round_no: 不填=挂到最新 open 轮（要已存在）；显式给则用该轮（不存在则新开，要 swept_variable）
        swept_variable: 新开一轮时必填——本轮扫的变量 key（opening_hook_3s/selling_point_set/...）
        adopt_script: True（默认）顺手把该 script draft→adopted

    Returns:
        {ok, arm:{arm_id, arm_label, round_no, swept_variable, variable_value, arm_code}, script_adopted,
         warnings, next_step_hint}；arm_code（如 R2B）写进巨量视频名，投后 record_ad_metrics_batch 按它回灌。
    """
    return await lab.attach_arm(
        experiment_id=experiment_id, script_id=script_id, variable_value=variable_value,
        round_no=round_no, swept_variable=swept_variable, adopt_script=adopt_script,
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
async def experiment_next_version_seed(
    experiment_id: str, override_variable: str | None = None,
) -> dict:
    """一键出下一版（块B）：把已锁的获胜 baseline + 建议扫的下个变量预填好，喂下一版生成。

    半自动——本 tool 不生成、不写库，只算清"下一版该带哪些获胜设定、测哪个变量"返回。主大脑据此
    调 generate_director_brief / generate_creative_pack（带返回的 experiment_context），给本轮 ≥2 个
    取值各生成一条 → 各自 experiment_attach_arm 挂臂。老板话术"出下一版 / 接着测下一个变量"。

    Args:
        experiment_id: 实验 id
        override_variable: 不想按建议、指定本轮扫某个变量（默认 None=确定性差集自动选撬动最大的）

    Returns:
        {ok, baseline, next_variable:{variable,label}, next_round_no,
         generation:{tool, suggested_args:{...experiment_context...}}, hint}
        都扫完了 → {ok, done:True, hint=可以 distill 沉淀}
    """
    return await lab.next_version_seed(experiment_id, override_variable=override_variable)


@tool_with_audit(mcp, require_approval=False)
async def experiment_changelog(experiment_id: str) -> dict:
    """版本变更日志（块C）：逐轮"改了哪个变量 / 取值从→到 / 这版赢面(avg/n/曝光)"，串成演化树。

    确定性只读（派生视图 v_content_version_changelog + tool 层按相邻轮快照算 X→Y diff）。
    老板话术"这实验改过哪些 / 看演化 / 每版动了啥"。

    Returns:
        {ok, status, current_baseline, entries:[{round_no, swept_variable_label, from_value,
         to_value, north_star_avg, n_videos, impressions, forced, status}], markdown}
    """
    return await lab.get_changelog(experiment_id)


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
    node_id = exp.get("prompt_node")  # human_brief→director_brief / ai_video→creative_pack / mixed→None

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

    # mixed 实验出的是"模式偏好"（真人 vs AI），不沉淀成单一节点 prompt 规则——只落人读框架
    if not node_id:
        await lab.write_winning_framework(experiment_id, framework_md)
        return {
            "ok": True, "dry_run": False, "experiment": exp, "scope": scope,
            "created": [], "skipped": [{"reason": "mixed_track_no_prompt_node"}], "blocked": blocked,
            "winning_framework_md": framework_md, "trace": trace,
            "next_step_hint": "mixed（真人 vs AI 对比）实验只出人读获胜框架——结论是'这个人群更吃哪种生产模式'，按它选后续主力链，不写 prompt 规则",
        }

    # 落库：每个未沉淀过的候选 → create_rule（enabled=False；按 track 路由到 director_brief / creative_pack 节点）
    created, skipped = [], []
    for c in candidates:
        if c["already_distilled"] and not c["value_changed"]:
            skipped.append({"swept_variable": c["swept_variable"], "reason": "already_distilled_same_value"})
            continue
        try:
            rule = await pr.create_rule(
                node_id, c["rule_text"],
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
            f"规则已落库但 enabled=FALSE 不生效。prompt_rule_list(node_id='{node_id}') 看草稿，"
            "prompt_rule_set_enabled(rule_id, True) 逐条点亮 → 以后这个 SKU 这个 intent 的生成自动带上"
        ),
    }


@tool_with_audit(mcp, require_approval=False)
async def experiment_prescreen_round(experiment_id: str, round_no: int | None = None) -> dict:
    """投前视觉快环：多模态 judge 给本轮 AI 视频打 5 维质量分（保真/真人感/锁脸/品牌/可用）+ gate。

    **代理指标、非投放真值**——只在投放前过滤崩片/假片/不锁脸，帮 AI 提示词的技术类变量在算力速度
    快速收敛；**判不了带货**（带货只有真实投放的完播/转化说了算）。仅对 ai_video/mixed track 的
    AI 视频有意义（真人拍的视频不走这关）。gate(pass/fail) 后端按分数确定性算，不靠模型自判。

    前置：该轮各臂要先 generate_video_segments(script_id=该臂brief, experiment_arm_id=臂id) 出片，
    视频会自动挂到臂。

    Args:
        experiment_id: 实验 id
        round_no: 哪一轮（不填=最新轮）

    Returns:
        {ok, round_no, judged:[{asset_id, arm_label, variable_value, scores, gate, error?}],
         per_arm:[{arm_label, n, pass_n, avg_usable}], trace, next_step_hint}
    """
    got = await lab.get_round_video_assets(experiment_id, round_no)
    assets = got.get("assets") or []
    if not assets:
        return {"ok": False, "error": "no_video_assets",
                "hint": "该轮还没挂 AI 视频——先 generate_video_segments(script_id=该臂brief, experiment_arm_id=臂id) 出片（视频自动挂臂）"}
    rno = got["round_no"]

    pool = get_pool()
    sku_id = await pool.fetchval("SELECT sku_id FROM pipeline.experiments WHERE id=$1::uuid", experiment_id)
    skurow = await pool.fetchrow("SELECT name, category FROM mvp_sku WHERE id=$1", sku_id) if sku_id else None
    sku_md = (f"- 品名：{skurow['name']}\n- 品类：{skurow['category'] or '调味品'}\n"
              if skurow else f"- sku_id：{sku_id}\n")

    try:
        from app.services.asset_storage import get_disk_path_for_public_url
        from app.services.gemini_video_client import GeminiVideoClient
    except ImportError as exc:
        return {"ok": False, "error": "gemini_sdk_missing", "hint": str(exc)}
    mcfg = get_model_for_tool("experiment_prescreen_round")
    used_model = (mcfg.get("model") or "gemini-2.5-flash").strip()
    _temp = float(mcfg.get("temperature", 0.2))
    _maxtok = int(mcfg.get("max_tokens", 2000))
    try:
        client = GeminiVideoClient(model=used_model)
    except RuntimeError as exc:
        return {"ok": False, "error": "gemini_not_configured", "hint": str(exc)}
    sys_msg = prompts.load("prescreen_video.system")

    sem = asyncio.Semaphore(3)

    async def _judge(a: dict) -> dict:
        base = {"asset_id": a["asset_id"], "arm_id": a["arm_id"], "arm_label": a["arm_label"],
                "variable_value": a["variable_value"]}
        disk = get_disk_path_for_public_url(a["file_url"]) if a["file_url"] else None
        if not disk or not disk.exists():
            return {**base, "error": "video_not_on_disk", "file_url": a["file_url"]}
        user_msg = prompts.render("prescreen_video.user", sku_md=sku_md,
                                  arm_label=a["arm_label"], variable_value=a["variable_value"])
        async with sem:
            try:
                scores, _usage = await client.analyze_video(
                    video_path=str(disk), system_prompt=sys_msg, user_prompt=user_msg,
                    temperature=_temp, max_tokens=_maxtok,
                )
            except Exception as exc:
                logger.warning("prescreen judge failed asset=%s: %s", a["asset_id"], exc)
                return {**base, "error": f"{type(exc).__name__}: {exc}"}
        gate = lab.prescreen_gate(scores)
        scores = {**scores, "gate": gate}
        await lab.save_visual_prescreen(a["asset_id"], scores)
        return {**base, "scores": scores, "gate": gate}

    judged = await asyncio.gather(*[_judge(a) for a in assets])

    by_arm: dict[str, list] = defaultdict(list)
    for j in judged:
        by_arm[j["arm_label"]].append(j)
    per_arm = []
    for label, js in sorted(by_arm.items()):
        ok_js = [j for j in js if j.get("scores")]
        pass_n = sum(1 for j in ok_js if j.get("gate") == "pass")
        avg_usable = (round(sum(float(j["scores"].get("usable", 0)) for j in ok_js) / len(ok_js), 1)
                      if ok_js else None)
        per_arm.append({"arm_label": label, "n": len(js), "judged_ok": len(ok_js),
                        "pass_n": pass_n, "avg_usable": avg_usable})

    return {
        "ok": True, "experiment_id": experiment_id, "round_no": rno,
        "judged": judged, "per_arm": per_arm,
        "trace": build_trace(
            provider="gemini", model=used_model, prompt=sys_msg,
            params={"n_videos": len(assets), "round_no": rno},
            cost_estimate=f"{len(assets)} gemini 视频判官调用",
        ),
        "next_step_hint": (
            "gate=fail 的别投（崩/假/不锁脸）——调 creative_pack 提示词重出该臂再预检；"
            "gate=pass 的才投放，投后 record_ad_metrics(experiment_arm_id) 回传真实完播/转化判匹配度。"
            "⚠️ 视觉分只是投前代理，过关≠带货。"
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 内容↔人群向量匹配（投前预测分）+ 北极星闭环（migration 066）
# ══════════════════════════════════════════════════════════════════════════════
@tool_with_audit(mcp, require_approval=False)
async def embed_content_and_audience(
    script_id: str | None = None,
    portrait_id: str | None = None,
) -> dict:
    """把内容脚本/人群画像的文本 embed 成向量落库（投前匹配分的前置步）。

    复用现成 embed_texts（gemini 1536 维，带缓存）。内容侧抽 文字/画面/音乐 三路文本
    （director_brief 三向量段最干净；creative_pack 节点 scenes 字段次之；whole_prompt 整段降级成
    text 单路）；人群侧抽画像「1.3 算法信号原料」段。script_id / portrait_id 给一个或都给。

    Args:
        script_id: pipeline.scripts.id（内容脚本，落 pipeline.content_vectors 三行）
        portrait_id: pipeline.audience_portraits.id（人群画像，落 pipeline.audience_vectors 一行）

    Returns:
        {ok, content?:{tracks, note}, audience?:{chars}}；二者按传入分别返回
    """
    from app.services import match_vectors as mv
    if not (script_id or portrait_id):
        return {"ok": False, "error": "missing_target", "hint": "script_id / portrait_id 至少给一个"}
    out: dict = {"ok": True}
    if portrait_id:
        out["audience"] = await mv.embed_and_store_audience(portrait_id)
    if script_id:
        out["content"] = await mv.embed_and_store_content(script_id)
    out["ok"] = all(v.get("ok") for k, v in out.items() if isinstance(v, dict))
    out["next_step_hint"] = "内容+人群都 embed 后 → predict_audience_match(experiment_id) 算投前预测分。"
    return out


@tool_with_audit(mcp, require_approval=False)
async def predict_audience_match(experiment_id: str, round_no: int | None = None) -> dict:
    """投前向量预测匹配分：本轮各臂内容向量 vs 人群向量 余弦相似度（三路分开看 + 简单平均），
    写进 experiment_arms.predicted_match_score。**排序候选臂、少烧广告费用，不判 winner。**

    前置：实验绑了 portrait_id；该画像 + 各臂脚本都先 embed_content_and_audience 过。
    没 embed 的臂会跳过并提示先 embed。

    Args:
        experiment_id: 实验 id（须绑 portrait_id 当人群锚）
        round_no: 哪一轮（不填=最新轮）

    Returns:
        {ok, round_no, arms:[{arm_label, predicted_match_score, tracks:{text,visual,music}} | {skipped}],
         ranking, disclaimer, next_step_hint}
    """
    from app.services import match_vectors as mv
    return await mv.predict_match(experiment_id, round_no=round_no)


@tool_with_audit(mcp, require_approval=False)
async def calibrate_match_predictor(
    sku_id: str | None = None,
    experiment_id: str | None = None,
    min_pairs: int = 8,
) -> dict:
    """闭环校准（"同时升级"的投后半）：拉 (投前预测分, 投后北极星) 配对 → 看相关性 + 四象限偏差
    → 建议三路权重。**确定性记账，不训练、不自动改权重**（建议仅供老板拍板）。

    配对天然成立（同锚 experiment_arm_id：预测分写在臂、北极星经 record_ad_metrics 聚到同臂）。
    样本不足（<min_pairs 个 n≥5 的臂）时返 insufficient_samples——校准要先攒够投放数据才有意义。

    Args:
        sku_id / experiment_id: 限定范围（都不给=全量已有配对）
        min_pairs: 起算门槛（默认 8 个 n≥5 的臂配对）

    Returns:
        样本不足 {ok, status:'insufficient_samples', n_pairs, hint}
        够了    {ok, status:'calibrated', n_pairs, overall_correlation, quadrants(tp/tn/fp/fn),
                 track_correlation, suggested_weights, reading, disclaimer}
    """
    from app.services import match_vectors as mv
    return await mv.calibrate(sku_id=sku_id, experiment_id=experiment_id, min_pairs=min_pairs)
