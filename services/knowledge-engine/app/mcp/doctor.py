"""omni MCP 健康检查（design doc §6.3 调试三件套之一）。

用法：
    # CLI（容器内）
    docker exec omni-knowledge-engine python -m app.mcp.doctor
    # 退出码 0 = 全绿；1 = 有红

    # 启动期（main.py lifespan 内）
    from app.mcp.doctor import run_at_startup
    await run_at_startup()  # 仅日志，不抛
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import settings
from app.database import init_pool, close_pool, get_pool

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    # warn=True：非阻塞提示（[WARN]）。ok 仍为 True 才不算 FAIL；
    # 用于"文档体检数字漂移""预算配置缺位"这类"提示但别拦着启动"的项。
    # 纯加法：现有 6 项检查都不传 warn，默认 False，输出/退出码语义不变。
    warn: bool = False


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_green(self) -> bool:
        # warn 项不算 FAIL（退出码语义不变：只有 ok=False 才让退出码为 1）。
        return all(c.ok for c in self.checks)

    def render(self) -> str:
        lines = ["omni MCP doctor 报告"]
        for c in self.checks:
            if not c.ok:
                mark = "FAIL"
            elif c.warn:
                mark = "WARN"
            else:
                mark = "OK  "
            lines.append(f"  [{mark}] {c.name}{(': ' + c.detail) if c.detail else ''}")
        lines.append("")
        lines.append("结论：全绿 ✓" if self.all_green else "结论：存在 FAIL ✗")
        return "\n".join(lines)


async def _check_db_pool(report: DoctorReport) -> None:
    try:
        pool = get_pool()
        v = await pool.fetchval("SELECT 1")
        report.checks.append(CheckResult("DB pool", v == 1))
    except Exception as exc:
        report.checks.append(CheckResult("DB pool", False, str(exc)))


async def _check_mcp_schema(report: DoctorReport) -> None:
    try:
        pool = get_pool()
        n = await pool.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables"
            " WHERE table_schema='mcp' AND table_name IN ('tool_calls','human_gates')"
        )
        ok = n == 2
        report.checks.append(CheckResult("mcp schema tables", ok, f"found {n}/2"))
    except Exception as exc:
        report.checks.append(CheckResult("mcp schema tables", False, str(exc)))


def _check_yaml(report: DoctorReport) -> None:
    try:
        from app.mcp.model_config import _load_yaml
        raw = _load_yaml()
        ok = "__default__" in raw
        report.checks.append(CheckResult("tool_models.yaml", ok, f"keys={list(raw.keys())[:5]}"))
    except Exception as exc:
        report.checks.append(CheckResult("tool_models.yaml", False, str(exc)))


def _wanted_tools() -> set[str]:
    """工具注册契约（唯一权威）—— 蓝图 §5【R-22】"工具数以 doctor wanted 为准"。

    单独抽成函数，让 R-22 文档体检（`_check_doc_consistency`）也能引用同一个
    集合做 len() 比对，避免"两处各写一份契约"再漂移。纯加法：原
    `_check_tools_registered` 改为调它，逻辑不变。
    """
    return {
            # W1
            "list_skus", "get_sku", "search_kb", "list_kbs", "list_briefs",
            # W2
            "query_costs", "compute_margin",
            "generate_brief", "generate_image", "generate_video",
            # W3a
            "record_cost", "disable_cost_item", "gather_brief_context",
            # W3b
            "fetch_compass_store_daily", "fetch_compass_sku_detail",
            "fetch_compass_search_traffic",
            "fetch_yuntu_5a", "fetch_yuntu_brand_mind",
            "kb_upload_doc", "kb_set_role",
            # W3c
            "summarize_text", "parse_long_doc_with_gemini",
            "query_template_chunks",
            # W4-A
            "rate_tool_call", "agent_self_review",
            "codify_pattern_to_skill", "refresh_project_context",
            # W4-B 切片 5（W4 加分 5 tool）
            "save_decision", "schedule_observation",
            "generate_image_compare", "send_wecom_message",
            "dy_publish_creative",
            # W4-B 切片 8（工厂出厂价字典）
            "list_product_prices",
            # W4-B 切片 9（渠道扣点表）
            "list_channel_fees",
            # W4-B 切片 14.1（sku-pipeline step 2 卖点矩阵）
            "generate_selling_points_matrix",
            # W4-B 切片 14.2（sku-pipeline step 3 人群匹配）
            "generate_audience_match",
            # W4-B 切片 14.3 phase A（pipeline lineage 查询/采纳）
            "pipeline_list_matrix_runs", "pipeline_get_matrix_run",
            "pipeline_list_audience_runs", "pipeline_get_audience_run",
            "pipeline_list_audience_records", "pipeline_get_audience_record",
            "pipeline_adopt",
            # W4-B 切片 14.4 phase D：投后 ad_metrics 回传闭环
            "record_ad_metrics", "pipeline_get_asset_lineage",
            "pipeline_list_asset_performance",
            # W4-B 切片 14.3 phase B（sku-pipeline step 4 圈包 SOP）
            "generate_audience_pack",
            # W4-B 切片 14.3 phase B+（关键词扩展 500 词）
            "generate_keyword_pack",
            # W4-B 切片 14.4 phase C（6 类素材脚本：视频软广/种草/收割 + 图文收割 + 主图 + 详情页）
            "generate_creative_pack",
            # W4-B 切片 14.4 phase D（分镜图生成挂血缘）
            "generate_storyboard_images",
            # W4-B 切片 14.4 phase D step 6.5（角色定妆白底像锁脸）
            "generate_character_sheets",
            # W4-B 切片 14.4 phase D step 7（视频段生成：分镜图当 first_frame + character_sheet 锁脸）
            "generate_video_segments",
            # realman 真实人物视频（绕过 Seedance content_sensitive）
            "realman_create_avatar", "realman_generate_portrait_video",
            # t2v 模式角色锚点生成
            "generate_video_anchor",
            # 2026-05-28 反推视频→故事板提示词(直调 Gemini Files API)
            "reverse_storyboard_video",
            # 2026-05-28 反馈飞轮地基（migration 031）：消息级反馈
            "rate_message",
            # 2026-05-28 Phase A+/A++（migration 032）：bug 记忆库 + 客户端日志
            "log_client_event", "report_bug", "list_bugs", "update_bug",
            # 2026-06-01 竞品调研：淘宝搜词抓榜（competitor_search）+ 主图/详情页视觉拆解（competitor_decompose）
            "competitor_search", "competitor_decompose",
            # 2026-06-02 阶段0 L0-2：月度成本总账查询（omni 自身月成本进 BI 当一等指标）
            "query_monthly_spend",
            # 2026-06-02 §6.2 诊断官：可调用的《改进提议》能力 + R-20 生命周期三态
            "diagnose", "list_proposals", "resolve_proposal",
            # 2026-06-02 §6.2 分析面趋势归因问数（R-14 模板化归因不调 LLM）
            "explain_anomaly", "query_metric_trend",
            # 2026-06-03 三平台实时取数底座（Mac 开发→集成）：4 个 platform_* tool
            "platform_fetch", "platform_batch_fetch",
            "platform_list_endpoints", "platform_auth_status",
            # 2026-06-03 落库桥：手动触发全量 ingest → mvp_daily_metric + mvp_industry_benchmark
            "ingest_platform_metrics",
            # 2026-06-03 综合经营分析 + 临时问数（§6 分析半）：读库 → R-14 分层分析 / NL → 指标序列
            "generate_business_analysis", "query_metric_nl",
            # 2026-06-08 人群包投前诊断 + 提纯（《和田宽人群包评估方法论》沉淀）：
            # 候选包画像 vs 行业 A4 真需求标尺 → 投前诊断卡（漏斗定位 + 内容策略）+ 提纯优先级阶梯施工单
            "diagnose_audience_pack",
            # 2026-06-08 巨量云图标签体系确定性查询（修 "agent 硬读 30k 大文件答不全" 根因）：
            # 总览/按维度/搜标签/常量段，圈包/提纯/答疑的标签 ground truth，完整不截断
            "query_yuntu_taxonomy",
            # 2026-06-12 sku-pipeline step 3.5/3.6：人群生活状态画像（KB 锚+可信度分级标注）+
            # 编导 brief（V7.2 备忘录+算法信号三向量+一大段 AI 出片提示词，真人拍/AI 拍两用）
            "generate_audience_portrait", "generate_director_brief",
            # 2026-06-12 画像血缘查询入 MCP——桌面智能下拉/chat 经 catalog/exec 可达
            "pipeline_list_audience_portraits", "pipeline_get_audience_portrait",
            # 2026-06-12 竞品人群逆向分析：竞品视频 → 8 项人群信号 + 人群假设（🧠/⚠️ 标注）
            # + 可选自家画像对照（对照表/人群空白四区/可借鉴打法），段二 fail-open
            "reverse_audience_analysis",
            # 2026-06-12 自建 SOP 存储（migration 050）：桌面拟稿→确认→入库→菜单「我的 SOP」复用
            "sop_save_custom", "sop_list_custom", "sop_archive_custom",
            # 2026-06-15 prompt 反馈飞轮搭桥（migration 051）：sku-pipeline 差评→提炼→规则→注入
            # 新世界 mcp.tool_calls 差评 → 旧世界 knowledge.prompt_rules 规则的单向桥 + 逐条点亮
            "list_unprocessed_complaints", "prompt_rule_save",
            "prompt_rule_list", "prompt_rule_set_enabled",
            # 2026-06-15 编导 brief A/B 单变量迭代闭环（migration 052）：实验台账 + 确定性状态机
            # + 市场数据→prompt_rule 沉淀桥（experiment_distill）
            "experiment_create", "experiment_register_round", "experiment_status",
            "experiment_lock_winner", "experiment_list", "experiment_get",
            "experiment_distill",
            # 2026-06-15 AI 链 Y-尾移植（migration 053）：投前视觉快环
            "experiment_prescreen_round",
            # 2026-06-26 内容版本迭代闭环 块0+块A（migration 064）：
            # 采纳即挂臂（单条追加）+ 巨量素材报表 CSV 整轮回灌（按臂码匹配 + 曝光量旁证）
            "experiment_attach_arm", "record_ad_metrics_batch",
            # 2026-06-26 内容版本迭代闭环 块B+块C（migration 065）：
            # 一键出下一版（组获胜 baseline + 建议变量预填生成）+ 版本变更日志（逐轮 X→Y 演化树）
            "experiment_next_version_seed", "experiment_changelog",
            # 2026-06-26 内容↔人群向量匹配 + 北极星闭环（migration 066）：投前向量预测分(排序少烧钱)
            # + 投后北极星并排 + 闭环校准(确定性记账建议三路权重，不训练)
            "embed_content_and_audience", "predict_audience_match", "calibrate_match_predictor",
    }


async def _check_tools_registered(report: DoctorReport) -> None:
    """FastMCP 3.x: mcp.list_tools() 是 async coroutine，必须 await。"""
    try:
        from app.mcp.server import mcp
        tools = await mcp.list_tools()
        # 契约（唯一权威）抽到 _wanted_tools()，R-22 文档体检共用同一份避免漂移。
        wanted = _wanted_tools()
        names = {getattr(t, "name", str(t)) for t in tools}
        missing = wanted - names
        # extra = 已注册但不在 wanted 契约里的 tool。
        # 加新 tool 忘了同步 wanted 时，这里会列出来提醒"该把它加进契约"——
        # 不算 FAIL（不影响功能），只是把漂移暴露出来，免得自检越用越名不副实。
        extra = names - wanted
        n = len(wanted)
        live = len(names)
        if missing:
            detail = f"missing={sorted(missing)}"
        elif extra:
            detail = f"contract {n} ok; live {live}; 新增未入契约 extra={sorted(extra)}（建议补进 wanted）"
        else:
            detail = f"all {n} ok (live {live})"
        report.checks.append(CheckResult(
            f"{n} tools registered", not missing, detail,
        ))
    except Exception as exc:
        report.checks.append(CheckResult("tools registered", False, str(exc)))


def _check_prompts(report: DoctorReport) -> None:
    """W3a：检 config/prompts/ 关键模板都在。"""
    try:
        from app.mcp import prompts as _p
        existing = set(_p.list_templates())
        wanted = {
            "anti_ai_voice",
            "generate_brief.system", "generate_brief.user",
            "compute_margin.system", "compute_margin.user",
            "channel_profiles/douyin",
            "channel_profiles/tmall",
            "channel_profiles/jd",
            # W4-B 切片 14.1：sku-pipeline step 2
            "selling_points_matrix.system", "selling_points_matrix.user",
            # W4-B 切片 14.2：sku-pipeline step 3
            "audience_match.system", "audience_match.user",
            # W4-B 切片 14.3 phase B：sku-pipeline step 4
            "audience_pack.system", "audience_pack.user",
            # W4-B 切片 14.3 phase B+：keyword 扩展
            "keyword_pack.system", "keyword_pack.user",
            # W4-B 切片 14.4 phase C：6 类素材 system + 1 共用 user
            "creative_pack.video_soft_ad.system",
            "creative_pack.video_planting.system",
            "creative_pack.video_harvest.system",
            "creative_pack.graphic_harvest.system",
            "creative_pack.product_main_image.system",
            "creative_pack.product_detail_page.system",
            "creative_pack.user",
            # t2v 模式角色锚点
            "video_anchor.system", "video_anchor.user",
            # 2026-05-28 反推视频
            "reverse_storyboard.system", "reverse_storyboard.user",
            # 2026-06-01 竞品调研：相关性过滤 + 主图/详情页视觉拆解
            "competitor_relevance.system", "competitor_relevance.user",
            "competitor_decompose.system", "competitor_decompose.user",
            # 2026-06-08 人群包投前诊断 AI 叙事层（巨量云图 KB grounding）
            "audience_pack_diagnose.system", "audience_pack_diagnose.user",
            # 2026-06-12 竞品人群逆向分析（段一视频信号提取 + 段二画像对照）
            "reverse_audience.system", "reverse_audience.user",
            "reverse_audience_compare.system", "reverse_audience_compare.user",
            # 2026-06-15 编导 brief A/B 沉淀桥 polish prompt（intent profiles 走热加载不入此集，同 video_model_profiles）
            "experiment_distill.system", "experiment_distill.user",
            # 2026-06-15 AI 链投前视觉快环 judge prompt
            "prescreen_video.system", "prescreen_video.user",
        }
        missing = wanted - existing
        report.checks.append(CheckResult(
            "prompt templates",
            not missing,
            f"missing={sorted(missing)}" if missing else f"all {len(wanted)} ok",
        ))
    except Exception as exc:
        report.checks.append(CheckResult("prompt templates", False, str(exc)))


def _check_smoke(report: DoctorReport) -> None:
    """L0-4（蓝图 §4）：从"注册检查"升级到"冒烟跑通检查"。

    不只验"tool 注册了没"，而是真跑一遍核心无副作用路径，证明引擎能转：
      ① prompt 引擎：真 load + render 一个现有模板（验证 prompts.render 跑通）。
         选 anti_ai_voice（全局通用、无占位符）→ render 等价 no-op format，
         不会因缺 ctx 抛 KeyError；既验文件读取/mtime cache，又验 str.format 引擎。
      ② tool 内部：真调一个无副作用纯函数（build_trace，每个 LLM tool 必经）。
    任一失败 → 显式 FAIL（不静默吞）。
    """
    try:
        from app.mcp import prompts as _p

        raw = _p.load("anti_ai_voice")
        if not raw or not raw.strip():
            report.checks.append(CheckResult(
                "smoke: prompt render", False, "anti_ai_voice 模板为空",
            ))
            return
        rendered = _p.render("anti_ai_voice")  # 无占位符 → 安全 no-op format
        if not rendered or not rendered.strip():
            report.checks.append(CheckResult(
                "smoke: prompt render", False, "render 结果为空",
            ))
            return

        # tool 内部无副作用冒烟：build_trace 是每个 LLM tool 返 trace 的必经纯函数
        from app.mcp.trace import build_trace
        trace = build_trace(
            provider="doctor_smoke",
            model="n/a",
            prompt="smoke",
            params={"smoke": True},
            cost_estimate="0（冒烟，不真调）",
        )
        if not isinstance(trace, dict) or "final_prompt" not in trace:
            report.checks.append(CheckResult(
                "smoke: tool internal", False,
                f"build_trace 返回异常（keys={list(trace) if isinstance(trace, dict) else type(trace)}）",
            ))
            return

        report.checks.append(CheckResult(
            "smoke run-through", True,
            f"render ok({len(rendered)}字) + build_trace ok",
        ))
    except Exception as exc:
        # 冒烟失败 = 引擎层真坏了，显式 FAIL 不静默
        report.checks.append(CheckResult("smoke run-through", False, str(exc)))


# CLAUDE.md 头部 "omni 暴露 N 个 tool" 的声明行，体检用正则抓 N。
# 路径优先 env OMNI_CLAUDE_MD_PATH（容器内可挂 CLAUDE.md 后指过去激活体检），
# 缺省回退 Windows 宿主路径（本机直接跑 doctor 时能读到）。容器内读不到 → 优雅 WARN-skip。
_CLAUDE_MD_PATH = Path(os.environ.get("OMNI_CLAUDE_MD_PATH") or r"E:\agent\omni\CLAUDE.md")
# 容忍 markdown 粗体/空格：'omni 暴露 **77 个 tool**' 里 暴露 与数字间有 `**`。
_TOOL_COUNT_RE = re.compile(r"omni\s*暴露[\s*]*(\d+)\s*个\s*tool")


def _check_doc_consistency(report: DoctorReport) -> None:
    """R-22 文档体检（蓝图 §4/§5）：CLAUDE.md 头部声明的工具数 vs len(wanted)。

    "本文档与代码同生共死"靠手工必腐烂（§5 工具数四处漂移就是实证）。
    把可机器核对的事实做成断言：读 CLAUDE.md 头部 "omni 暴露 N 个 tool"，
    与契约 len(_wanted_tools()) 比对。

    不一致 → [WARN]（非阻塞，给提示即可，不拦启动/不改退出码）。
    权威以 doctor wanted 为准（蓝图 §5 已钉）；CLAUDE.md 数字落后只是提醒该补。
    """
    try:
        n_wanted = len(_wanted_tools())
        if not _CLAUDE_MD_PATH.exists():
            report.checks.append(CheckResult(
                "doc consistency", True,
                f"CLAUDE.md 未找到（{_CLAUDE_MD_PATH}），跳过比对；wanted={n_wanted}",
                warn=True,
            ))
            return
        head = _CLAUDE_MD_PATH.read_text(encoding="utf-8", errors="ignore")[:4000]
        m = _TOOL_COUNT_RE.search(head)
        if not m:
            report.checks.append(CheckResult(
                "doc consistency", True,
                f"CLAUDE.md 头部未匹配到 'omni 暴露 N 个 tool' 声明；wanted={n_wanted}",
                warn=True,
            ))
            return
        declared = int(m.group(1))
        if declared != n_wanted:
            report.checks.append(CheckResult(
                "doc consistency", True,
                f"CLAUDE.md 头声明 {declared} 个 tool ≠ wanted {n_wanted}（权威以 wanted 为准，建议同步 CLAUDE.md）",
                warn=True,
            ))
        else:
            report.checks.append(CheckResult(
                "doc consistency", True, f"CLAUDE.md 头 {declared} == wanted {n_wanted}",
            ))
    except Exception as exc:
        # 体检本身别把 doctor 拖红：异常也只 WARN
        report.checks.append(CheckResult("doc consistency", True, str(exc), warn=True))


def _check_l0_gate(report: DoctorReport) -> None:
    """R-10 L0 gate（蓝图 §4）：静态验证 L0 关键不变量。

    把"加工具前先还地基债"的闸门做成机械检查，输出 "L0 gate: N/项通过"：
      ① realman 冒烟前提：realman.py 两处 build_trace 都含 cost_estimate
         （L0-3 已施工的回归网——曾因漏传 cost_estimate 抛 TypeError 静默崩）。
         扫源码而非真调（真调要打火山引擎，有副作用/要密钥）。
      ② 成本预算配置位（L0-2）：检测月度预算 env key 是否存在。
         L0-2 预算上限本身尚未施工（本切片只负责 doctor gate），缺则提示。

    现阶段 L0-2 未落地 → 预算项预期为"提示缺位"，不让它把 gate 判红。
    realman cost_estimate 项是真硬断言：缺了 = L0-3 回归，应显式 FAIL。
    """
    passed = 0
    total = 0
    notes: list[str] = []
    hard_fail = False

    # —— 项①：realman 两处 build_trace 含 cost_estimate（硬断言）——
    total += 1
    try:
        realman_path = (
            Path(__file__).resolve().parent / "tools" / "realman.py"
        )
        if not realman_path.exists():
            notes.append("realman.py 未找到（跳过 cost_estimate 扫描）")
        else:
            src = realman_path.read_text(encoding="utf-8", errors="ignore")
            n_build = src.count("build_trace(")
            n_cost = src.count("cost_estimate=")
            # 两处 build_trace 调用都应各带一个 cost_estimate
            if n_build >= 2 and n_cost >= n_build:
                passed += 1
                notes.append(f"realman cost_estimate ok（build_trace×{n_build}/cost_estimate×{n_cost}）")
            else:
                hard_fail = True
                notes.append(
                    f"realman cost_estimate 缺失（build_trace×{n_build} 但 cost_estimate×{n_cost}）"
                )
    except Exception as exc:
        hard_fail = True
        notes.append(f"realman 扫描异常：{exc}")

    # —— 项②：成本预算配置位存在（L0-2，软提示）——
    total += 1
    # L0-2 月度总账已施工（migration 033 + cost_ledger_service + /spend 端点 + query_monthly_spend
    # tool + 前端 task_done 归集）。软上限值由老板在 KE .env 配 OMNI_MONTHLY_SPEND_CAP_USD
    # （cost_ledger_service 实际读这个 key；缺失回退默认 500 美元，软上限即未启用）。
    # 早期命名漂移过：保留 OMNI_MONTHLY_BUDGET_USD/MONTHLY_BUDGET_USD 兼容。
    budget_env_keys = (
        "OMNI_MONTHLY_SPEND_CAP_USD",  # ← cost_ledger_service 真正读的 key（权威）
        "OMNI_MONTHLY_BUDGET_USD",
        "MONTHLY_BUDGET_USD",
    )
    found_key = next((k for k in budget_env_keys if os.environ.get(k)), None)
    if found_key:
        passed += 1
        notes.append(f"预算配置位 ok（{found_key}={os.environ.get(found_key)}）")
    else:
        # 总账已接线，只是软上限阈值未配：不判红，提示老板设 cap 启用超额检测。
        notes.append(
            "月度总账已接线（migration 033 + cost_ledger）；"
            f"软上限未启用——配 {budget_env_keys[0]} 即开（缺省回退 500）"
        )

    detail = f"{passed}/{total} 项通过；" + "；".join(notes)
    # gate 是否判红只看硬断言（realman）；预算软提示缺位不拦。
    report.checks.append(CheckResult("L0 gate", not hard_fail, detail))


async def _check_stage0_schema(report: DoctorReport) -> None:
    """阶段0 wiring 依赖的 schema 地基存在性（2026-06-02）：

    新工具（query_monthly_spend / diagnose / record_ad_metrics 校验 / tool_use 焊链）依赖
    migration 033/035/038 的表/列。缺了 = 这些工具运行时炸。机器核对，缺则显式 FAIL
    （对齐 _check_mcp_schema 的 precedent；live 已 apply 故应绿）。
    """
    try:
        pool = get_pool()
        n_tables = await pool.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='mcp' AND table_name IN ('monthly_spend','improvement_proposals')"
        )
        n_cols = await pool.fetchval(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE (table_name='mvp_daily_metric' AND column_name='platform') "
            "   OR (table_schema='mcp' AND table_name='tool_calls' AND column_name='tool_use_id')"
        )
        ok = (n_tables == 2) and (n_cols == 2)
        detail = (f"tables {n_tables}/2 (monthly_spend/improvement_proposals); "
                  f"cols {n_cols}/2 (metric.platform/toolcalls.tool_use_id)")
        report.checks.append(CheckResult("stage0 schema", ok, detail))
    except Exception as exc:
        report.checks.append(CheckResult("stage0 schema", False, str(exc)))


async def _check_mcp_http(report: DoctorReport) -> None:
    url = f"http://localhost:{settings.service_port}/mcp/"
    try:
        async with httpx.AsyncClient(timeout=5.0) as cli:
            # 用 initialize JSON-RPC 探活；MCP 协议要求 Accept SSE
            r = await cli.post(
                url,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "doctor", "version": "0.0"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            ok = r.status_code in (200, 202)
            report.checks.append(CheckResult("/mcp HTTP", ok, f"status={r.status_code}"))
    except Exception as exc:
        report.checks.append(CheckResult("/mcp HTTP", False, str(exc)))


async def run(*, skip_http: bool = False) -> DoctorReport:
    report = DoctorReport()
    await _check_db_pool(report)
    await _check_mcp_schema(report)
    _check_yaml(report)
    _check_prompts(report)
    await _check_tools_registered(report)
    # L0-4 冒烟 / R-22 文档体检 / R-10 L0 gate（蓝图 §4）——纯加法，排在现有 6 项之后
    _check_smoke(report)
    _check_doc_consistency(report)
    _check_l0_gate(report)
    await _check_stage0_schema(report)
    if not skip_http:
        await _check_mcp_http(report)
    return report


async def _deferred_http_check(delay: float = 2.0) -> None:
    """等 uvicorn 完成端口绑定后再探 /mcp HTTP。"""
    await asyncio.sleep(delay)
    report = DoctorReport()
    await _check_mcp_http(report)
    c = report.checks[0]
    if c.ok:
        logger.info("[doctor] %s OK %s", c.name, c.detail)
    else:
        logger.warning("[doctor] %s FAIL %s", c.name, c.detail)


async def run_at_startup() -> None:
    """启动期非阻塞自检：只 logger.warning 不抛。

    前 4 项（DB / schema / yaml / tools）在 lifespan 内同步检查；
    /mcp HTTP 探针通过后台任务延迟 2 s 执行（uvicorn 端口绑定完成后）。
    """
    try:
        report = await run(skip_http=True)
        for c in report.checks:
            if not c.ok:
                logger.warning("[doctor] %s FAIL %s", c.name, c.detail)
            elif c.warn:
                logger.warning("[doctor] %s WARN %s", c.name, c.detail)
            else:
                logger.info("[doctor] %s OK %s", c.name, c.detail)
        # HTTP 探针延迟触发，不阻塞 lifespan
        asyncio.create_task(_deferred_http_check(delay=2.0))
    except Exception:
        logger.warning("doctor self-check failed", exc_info=True)


async def _cli() -> int:
    await init_pool()
    try:
        report = await run()
    finally:
        await close_pool()
    print(report.render())
    return 0 if report.all_green else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli()))
