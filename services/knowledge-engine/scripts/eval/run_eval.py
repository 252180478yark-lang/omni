"""黄金集 + LLM-judge 输出质量回归 · runner。

用法（容器内）：
    docker exec omni-knowledge-engine python /app/scripts/eval/run_eval.py --tool generate_selling_points_matrix --no-judge
    docker exec omni-knowledge-engine python /app/scripts/eval/run_eval.py --tool generate_brief --case brief-xxxx
    docker exec omni-knowledge-engine python /app/scripts/eval/run_eval.py --tool generate_creative_pack --reps 2

流程（每 case）：
1. 读 config/eval/golden/<tool>/<case>/input.yaml（冻结输入）→ extra_context 追加 "[eval-run]" 标记
2. 真跑 tool（import 已注册的 @tool_with_audit 函数 → mcp.tool_calls 照常留痕）
3. 确定性层 checks.run_checks（fatal 直接判 0 跳过 judge 省 token）
4. LLM-judge（--no-judge 跳过）：rubric 维度打分 + vs_golden
5. **防污染血缘**：本次重跑落库的 draft 行 UPDATE status='archived', notes='eval-run'
6. baseline diff（对比上次 latest.json）→ 报告 md + latest.json 落 data/agent_state/eval/<tool>/

铁律：不写 mvp_daily_metric；只 archive 自己这次产生的 draft 行（按返回 id 精确点名）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_KE_ROOT = _HERE.parents[1]
for _p in (str(_KE_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402

import checks  # noqa: E402
import judge as judge_mod  # noqa: E402
from app.database import close_pool, get_pool, init_pool  # noqa: E402

GOLDEN_ROOT = _KE_ROOT / "config" / "eval" / "golden"
# 报告目录：容器内 /app/agent_state（bind-mount data/agent_state）；host 直跑落 repo data/agent_state
_REPORT_BASE = Path("/app/agent_state") if Path("/app/agent_state").exists() \
    else _KE_ROOT.parents[1] / "data" / "agent_state"
REPORT_ROOT = _REPORT_BASE / "eval"

EVAL_MARK = "[eval-run]"

# 防误伤白名单：archive 只允许动这三张 pipeline 表
_ARCHIVE_TABLES = {"pipeline.matrix_runs", "pipeline.audience_portraits", "pipeline.scripts"}


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _mark_args(args: dict) -> dict:
    out = dict(args)
    prev = (out.get("extra_context") or "").strip()
    out["extra_context"] = f"{prev}\n{EVAL_MARK}".strip() if prev else EVAL_MARK
    return out


# ---------- 各 tool 的执行适配：跑 tool → (output_md, draft_refs, result) ----------

async def _exec_generate_brief(args: dict):
    from app.mcp.tools import media
    res = await media.generate_brief(**args)
    md = ((res.get("result") or {}).get("brief_md")) or ""
    return md, [], res  # generate_brief 不落 pipeline 表，无 draft 要 archive


async def _exec_matrix(args: dict):
    from app.mcp.tools import media
    res = await media.generate_selling_points_matrix(**args)
    r = res.get("result") or {}
    refs = [("pipeline.matrix_runs", r["matrix_run_id"])] if r.get("matrix_run_id") else []
    return r.get("matrix_md") or "", refs, res


async def _exec_portrait(args: dict):
    from app.mcp.tools import portrait_brief
    res = await portrait_brief.generate_audience_portrait(**args)
    r = res.get("result") or {}
    refs = [("pipeline.audience_portraits", r["portrait_id"])] if r.get("portrait_id") else []
    return r.get("portrait_md") or "", refs, res


async def _exec_director(args: dict):
    from app.mcp.tools import portrait_brief
    res = await portrait_brief.generate_director_brief(**args)
    r = res.get("result") or {}
    variants = r.get("variants") or []
    md = (variants[0] or {}).get("brief_md") or "" if variants else ""
    refs = [("pipeline.scripts", v["script_id"]) for v in variants if v.get("script_id")]
    return md, refs, res


async def _exec_creative(args: dict):
    from app.mcp.tools import media
    res = await media.generate_creative_pack(**args)
    r = res.get("result") or {}
    refs = [("pipeline.scripts", v["script_id"])
            for v in (r.get("variants") or []) if v.get("script_id")]
    return r.get("script_md") or "", refs, res


EXECUTORS = {
    "generate_brief": _exec_generate_brief,
    "generate_selling_points_matrix": _exec_matrix,
    "generate_audience_portrait": _exec_portrait,
    "generate_director_brief": _exec_director,
    "generate_creative_pack": _exec_creative,
}


# ---------- 防污染：archive 本次产生的 draft ----------

async def archive_drafts(refs: list[tuple[str, str]]) -> list[str]:
    """把本次 eval 重跑落库的 draft 行标 archived + notes='eval-run'。返回动过的 id。"""
    pool = get_pool()
    done: list[str] = []
    for table, row_id in refs:
        if table not in _ARCHIVE_TABLES:
            print(f"  [archive-skip] 非白名单表 {table}，拒绝操作")
            continue
        try:
            tag = await pool.execute(
                f"UPDATE {table} SET status='archived', notes='eval-run' "
                f"WHERE id = $1 AND status = 'draft'",
                _uuid.UUID(str(row_id)),
            )
            if tag.endswith("1"):
                done.append(f"{table}:{row_id}")
            else:
                print(f"  [archive-warn] {table} id={row_id} 不是 draft（{tag}），未动")
        except Exception as exc:  # noqa: BLE001
            print(f"  [archive-error] {table} id={row_id}: {exc}")
    return done


# ---------- case 装载 ----------

def load_cases(tool: str, only_case: str | None = None) -> list[dict]:
    tool_dir = GOLDEN_ROOT / tool
    if not tool_dir.exists():
        raise SystemExit(f"黄金集目录不存在：{tool_dir}（先跑 seed_golden.py）")
    cases = []
    for case_dir in sorted(tool_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        if only_case and case_dir.name != only_case:
            continue
        input_p, golden_p = case_dir / "input.yaml", case_dir / "golden.md"
        if not input_p.exists() or not golden_p.exists():
            continue
        spec = yaml.safe_load(input_p.read_text(encoding="utf-8"))
        cases.append({
            "name": case_dir.name,
            "args": spec.get("args") or {},
            "source": spec.get("source") or "",
            "golden_md": golden_p.read_text(encoding="utf-8"),
        })
    if not cases:
        raise SystemExit(
            f"{tool} 无可跑 case"
            + (f"（--case {only_case} 未命中）" if only_case else
               "（黄金集为空——director_brief 等老板采纳后重 seed）")
        )
    return cases


def _input_summary(args: dict) -> str:
    """喂 judge 的输入摘要：超长值（kb_recall_override 等）截断。"""
    view = {}
    for k, v in args.items():
        s = str(v) if v is not None else None
        view[k] = (s[:400] + f"…（截断，共 {len(s)} 字）") if s and len(s) > 400 else v
    return yaml.safe_dump(view, allow_unicode=True, sort_keys=False)


async def _sku_snapshot(args: dict) -> str:
    """tool 运行时会从 DB 拉 SKU 真实字段——把快照补给 judge，防止把库内真值误判成编造。"""
    sku_id = args.get("sku_id")
    if not sku_id:
        return ""
    try:
        row = await get_pool().fetchrow(
            "SELECT id, name, category, price_min, price_max, specifications, "
            "owner_selling_points FROM mvp_sku WHERE id = $1", sku_id,
        )
        if not row:
            return ""
        return (
            "\n# SKU 库内真实字段快照（tool 运行时可见，产物里与此相符的数字不是编造）\n"
            f"- 品名：{row['name']}\n- 品类：{row['category']}\n"
            f"- 售价：{row['price_min']} - {row['price_max']}\n"
            f"- 规格：{row['specifications']}\n"
            f"- 老板手填卖点：{str(row['owner_selling_points'])[:600]}\n"
        )
    except Exception:  # noqa: BLE001
        return ""


# ---------- 单 case 执行 ----------

async def run_case(tool: str, case: dict, *, no_judge: bool, rep: int) -> dict:
    name = case["name"]
    print(f"\n--- case {name}（rep {rep}）---")
    args = _mark_args(case["args"])
    entry: dict = {"case": name, "rep": rep}

    try:
        output_md, refs, result = await EXECUTORS[tool](args)
    except Exception as exc:  # noqa: BLE001
        print(f"  [error] tool 执行异常：{type(exc).__name__}: {exc}")
        entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                      "fatal": True, "score": 0})
        return entry

    if not result.get("ok"):
        print(f"  [error] tool 返回 ok=False：{result.get('error')}")
        entry.update({"ok": False, "error": result.get("error"),
                      "fatal": True, "score": 0})
        return entry

    # 确定性层
    det = checks.run_checks(tool, output_md, result, args=case["args"])
    entry.update({
        "ok": True,
        "output_chars": len(output_md),
        "deterministic": det,
    })
    for w in det["warnings"] + det["harvested"]:
        print(f"  [det] {w}")
    if det["fatal"]:
        print(f"  [FATAL] {det['fatal_reasons']} → 判 0 跳过 judge")
        entry.update({"fatal": True, "score": 0})
    else:
        entry["fatal"] = False
        if no_judge:
            entry["judge"] = {"skipped": True}
            print("  [judge] --no-judge 跳过")
        else:
            j = await judge_mod.judge_output(
                tool,
                input_summary=_input_summary(case["args"]) + await _sku_snapshot(case["args"]),
                golden_md=case["golden_md"],
                candidate_md=output_md,
                det_warnings=det["warnings"] + det["harvested"],
            )
            entry["judge"] = j
            if j.get("ok"):
                print(f"  [judge] avg={j.get('avg_score')} vs_golden={j.get('vs_golden')} "
                      f"({j.get('model')})")
            else:
                print(f"  [judge-error] {j.get('error')}")

    # 防污染血缘：archive 本次 draft
    archived = await archive_drafts(refs)
    entry["archived_drafts"] = archived
    if archived:
        print(f"  [archived] {archived}")
    # 重跑产物存档进报告（人工复核用）
    entry["candidate_md"] = output_md
    return entry


# ---------- 报告 ----------

def _summarize(entry: dict) -> dict:
    j = entry.get("judge") or {}
    return {
        "rep": entry.get("rep"),
        "ok": entry.get("ok"),
        "fatal": entry.get("fatal"),
        "warnings_count": len((entry.get("deterministic") or {}).get("warnings", []))
        + len((entry.get("deterministic") or {}).get("harvested", [])),
        "judge_avg": j.get("avg_score"),
        "vs_golden": j.get("vs_golden"),
    }


def _diff_line(case: str, prev: dict | None, cur: dict) -> str | None:
    if not prev:
        return f"- `{case}`：新 case（无基线）"
    msgs = []
    pa, ca = prev.get("judge_avg"), cur.get("judge_avg")
    if pa is not None and ca is not None and ca != pa:
        arrow = "↑" if ca > pa else "↓ ⚠️"
        msgs.append(f"judge 均分 {pa} → {ca} {arrow}")
    pw, cw = prev.get("warnings_count"), cur.get("warnings_count")
    if pw is not None and cw is not None and cw != pw:
        arrow = "↓" if cw < pw else "↑ ⚠️"
        msgs.append(f"确定性警告 {pw} → {cw} {arrow}")
    if prev.get("vs_golden") != cur.get("vs_golden"):
        msgs.append(f"vs_golden {prev.get('vs_golden')} → {cur.get('vs_golden')}")
    if not prev.get("fatal") and cur.get("fatal"):
        msgs.append("**变 FATAL ⚠️⚠️**")
    return f"- `{case}`：{'；'.join(msgs)}" if msgs else None


def write_report(tool: str, entries: list[dict], *, no_judge: bool) -> None:
    ts = _now_ts()
    out_dir = REPORT_ROOT / tool
    out_dir.mkdir(parents=True, exist_ok=True)

    # baseline diff：读上次 latest.json
    latest_p = out_dir / "latest.json"
    prev_cases: dict = {}
    if latest_p.exists():
        try:
            prev_cases = (json.loads(latest_p.read_text(encoding="utf-8")) or {}).get("cases", {})
        except Exception:  # noqa: BLE001
            prev_cases = {}

    # 按 case 聚合（--reps > 1 时取末 rep 当代表 + 全部列出）
    by_case: dict[str, list[dict]] = {}
    for e in entries:
        by_case.setdefault(e["case"], []).append(e)
    cur_cases = {c: _summarize(reps[-1]) for c, reps in by_case.items()}

    diff_lines = [l for c, cur in cur_cases.items()
                  if (l := _diff_line(c, prev_cases.get(c), cur))]

    # markdown 报告
    lines = [
        f"# eval 回归报告 · {tool} · {ts}",
        "",
        f"- case 数：{len(by_case)}（reps 共 {len(entries)} 次）",
        f"- fatal：{sum(1 for e in entries if e.get('fatal'))}",
        f"- judge：{'跳过（--no-judge）' if no_judge else '启用'}",
        "",
        "## 对比上次（baseline diff）",
        "",
    ]
    lines += diff_lines or ["- 无变化（或无基线）"]
    for case_name, reps in by_case.items():
        lines += ["", f"## case `{case_name}`", ""]
        src = next((c.get("source") for c in reps if c.get("source")), "")
        for e in reps:
            lines.append(f"### rep {e.get('rep')}")
            if not e.get("ok"):
                lines += [f"- **执行失败**：{e.get('error')}", ""]
                continue
            det = e.get("deterministic") or {}
            lines.append(f"- 输出 {e.get('output_chars')} 字；fatal={e.get('fatal')}")
            if det.get("fatal_reasons"):
                lines.append(f"- fatal 原因：{det['fatal_reasons']}")
            for w in det.get("warnings", []):
                lines.append(f"- [自检] {w}")
            for w in det.get("harvested", []):
                lines.append(f"- [tool 自带] {w}")
            j = e.get("judge") or {}
            if j.get("ok"):
                lines.append(f"- judge（{j.get('model')}）：均分 **{j.get('avg_score')}** / "
                             f"vs_golden **{j.get('vs_golden')}** —— {j.get('reason')}")
                for dim, v in (j.get("dims") or {}).items():
                    if isinstance(v, dict):
                        lines.append(f"  - {dim}：{v.get('score')} 分 —— {v.get('reason')}")
            elif j.get("skipped"):
                lines.append("- judge：跳过")
            elif j:
                lines.append(f"- judge 失败：{j.get('error')}")
            if e.get("archived_drafts"):
                lines.append(f"- 已 archive 的 eval draft：{e['archived_drafts']}")
            lines.append("")
            lines.append("<details><summary>本次重跑产物全文</summary>")
            lines.append("")
            lines.append(e.get("candidate_md") or "（空）")
            lines.append("")
            lines.append("</details>")

    report_p = out_dir / f"report-{ts}.md"
    report_p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    latest_p.write_text(json.dumps(
        {"tool": tool, "ts": ts, "no_judge": no_judge, "cases": cur_cases},
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    print(f"\n报告：{report_p}\n基线：{latest_p}")


# ---------- main ----------

async def main() -> None:
    parser = argparse.ArgumentParser(description="黄金集 + LLM-judge 输出质量回归")
    parser.add_argument("--tool", required=True, choices=list(EXECUTORS), help="要回归的 tool")
    parser.add_argument("--case", help="只跑某个 case（目录名）")
    parser.add_argument("--no-judge", action="store_true", help="只跑确定性层，跳过 LLM-judge")
    parser.add_argument("--reps", type=int, default=1, help="每 case 重复次数（默认 1）")
    ns = parser.parse_args()

    cases = load_cases(ns.tool, ns.case)
    print(f"== eval {ns.tool}：{len(cases)} case × {ns.reps} reps "
          f"{'（no-judge）' if ns.no_judge else ''} ==")

    await init_pool()
    try:
        entries: list[dict] = []
        for case in cases:
            for rep in range(1, max(1, ns.reps) + 1):
                e = await run_case(ns.tool, case, no_judge=ns.no_judge, rep=rep)
                e["source"] = case.get("source")
                entries.append(e)
        write_report(ns.tool, entries, no_judge=ns.no_judge)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
