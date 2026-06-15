"""黄金集 seeding：从 live DB 捞老板采纳/好评过的产物 → 生成 case 目录。

用法（容器内）：
    docker exec omni-knowledge-engine python /app/scripts/eval/seed_golden.py
    docker exec omni-knowledge-engine python /app/scripts/eval/seed_golden.py --tool generate_brief
    # --no-freeze-recall：portrait case 不做四路召回冻结（省时间，eval 时走 live 召回）

数据源（只读业务表；写入仅 config/eval/golden/ 下的 case 文件）：
- generate_brief                  ← content_studio.briefs（有 sku_id 的行）
- generate_selling_points_matrix  ← pipeline.matrix_runs status='adopted'
                                  + mcp.tool_calls user_rating='good'（result jsonb 全文在库）
- generate_audience_portrait      ← pipeline.audience_portraits status='adopted'
                                    （kb_recall 在 seed 时实跑四路召回冻结进 input.yaml 回放）
- generate_creative_pack          ← pipeline.scripts status='adopted'（video_soft_ad / video_planting）
- generate_director_brief         ← 目前 0 条 adopted → 留 README 占位，等老板采纳后重跑本脚本

case 目录结构：config/eval/golden/<tool>/<case>/{input.yaml, golden.md}
input.yaml = 真实 args + 来源备注；golden.md = 产物全文。重跑 seed = 同名 case 覆盖刷新。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_KE_ROOT = _HERE.parents[1]
for _p in (str(_KE_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402

from app.database import close_pool, get_pool, init_pool  # noqa: E402

GOLDEN_ROOT = _KE_ROOT / "config" / "eval" / "golden"

TOOLS = [
    "generate_brief",
    "generate_selling_points_matrix",
    "generate_audience_portrait",
    "generate_director_brief",
    "generate_creative_pack",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_case(tool: str, case: str, args: dict, golden_md: str, source: str) -> Path:
    case_dir = GOLDEN_ROOT / tool / case
    case_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": tool,
        "case": case,
        "source": source,
        "seeded_at": _now(),
        "args": args,
    }
    (case_dir / "input.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    (case_dir / "golden.md").write_text((golden_md or "").strip() + "\n", encoding="utf-8")
    print(f"  [seeded] {tool}/{case}  (golden {len(golden_md or '')} 字)")
    return case_dir


def _jsonb(v):
    """asyncpg jsonb 可能返 str 或已解码对象，统一成 python 对象。"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # noqa: BLE001
            return v
    return v


# ---------- generate_brief ← content_studio.briefs ----------

def _render_brief_golden(row: dict) -> str:
    """briefs 表是结构化字段（无 brief_md 原文）→ 渲染成 markdown 当 golden。"""
    def _as(v, typ):
        v = _jsonb(v)
        return v if isinstance(v, typ) else typ()

    scenarios = _as(row.get("scenarios"), list)
    audience = _as(row.get("audience_profile"), dict)
    tone = _as(row.get("tone_style"), dict)
    extra = _as(row.get("extra"), dict)
    usp_structured = extra.get("usp_structured") or []

    lines = [f"# {row.get('title') or '（无标题）'}", ""]
    lines += ["## 核心卖点", "", (row.get("usp") or "").strip(), ""]
    if usp_structured:
        lines.append("### 结构化卖点")
        for it in usp_structured:
            if isinstance(it, dict):
                lines.append(f"- {it.get('point')}（依据：{it.get('evidence')}；优先级 {it.get('priority')}）")
        lines.append("")
    if scenarios:
        lines.append("## 主场景")
        for s in scenarios:
            lines.append(f"- {s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)}")
        lines.append("")
    if audience:
        lines += ["## 目标人群", "", "```json",
                  json.dumps(audience, ensure_ascii=False, indent=2), "```", ""]
    if tone:
        lines += ["## 语气风格", "", "```json",
                  json.dumps(tone, ensure_ascii=False, indent=2), "```", ""]
    if row.get("source_notes"):
        lines += ["## 来源备注", "", str(row["source_notes"]).strip(), ""]
    return "\n".join(lines)


async def seed_generate_brief() -> int:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, sku_id, title, usp, scenarios, audience_profile, tone_style, "
        "source_notes, extra, created_at FROM content_studio.briefs "
        "WHERE sku_id IS NOT NULL AND sku_id <> '' ORDER BY created_at"
    )
    n = 0
    for r in rows:
        row = dict(r)
        case = f"brief-{str(row['id'])[:8]}"
        args = {
            "sku_id": row["sku_id"],
            "channel": "douyin",  # briefs 表未存渠道；这批历史 brief 全是抖音链路 → 钉 douyin
            "kb_context": "",     # 冻结输入：来源备注「命中知识库：无」→ 空 KB 上下文回放
            "extra_context": None,
        }
        source = (
            f"content_studio.briefs id={row['id']} created_at={row['created_at']} "
            f"title={row.get('title')!r}（golden 由结构化字段渲染——briefs 表不存 brief_md 原文）"
        )
        _write_case("generate_brief", case, args, _render_brief_golden(row), source)
        n += 1
    skipped = await pool.fetchval(
        "SELECT count(*) FROM content_studio.briefs WHERE sku_id IS NULL OR sku_id = ''"
    )
    if skipped:
        print(f"  [skip] content_studio.briefs 无 sku_id 的 {skipped} 行（无法回放输入）")
    return n


# ---------- generate_selling_points_matrix ----------

async def seed_matrix() -> int:
    pool = get_pool()
    n = 0
    # 来源 1：adopted matrix_runs（输入字段全在行内 → 完整冻结）
    rows = await pool.fetch(
        "SELECT id, sku_id, matrix_md, user_initial_points, user_reviews, kb_context, "
        "extra_context, version, created_at FROM pipeline.matrix_runs "
        "WHERE status='adopted' ORDER BY created_at"
    )
    for r in rows:
        row = dict(r)
        case = f"matrix-adopted-{str(row['id'])[:8]}"
        args = {
            "sku_id": row["sku_id"],
            "user_initial_points": row.get("user_initial_points") or "",
            "user_reviews": row.get("user_reviews") or "",
            "kb_context": row.get("kb_context") or None,
            "extra_context": row.get("extra_context") or None,
        }
        source = (
            f"pipeline.matrix_runs id={row['id']} status=adopted version={row['version']} "
            f"created_at={row['created_at']}"
        )
        _write_case("generate_selling_points_matrix", case, args, row["matrix_md"], source)
        n += 1
    # 来源 2：mcp.tool_calls 老板点过 👍 的（args + result 全文在库）
    rows = await pool.fetch(
        "SELECT id, args, result, created_at FROM mcp.tool_calls "
        "WHERE tool_name='generate_selling_points_matrix' AND user_rating='good' "
        "AND status='completed' ORDER BY created_at"
    )
    for r in rows:
        row = dict(r)
        args_db = _jsonb(row["args"]) or {}
        result = _jsonb(row["result"]) or {}
        matrix_md = ((result.get("result") or {}).get("matrix_md")) or ""
        if not matrix_md.strip():
            print(f"  [skip] tool_call {row['id']} result 里无 matrix_md")
            continue
        if "anthropic-mock" in matrix_md:
            # hub 旧 build 坏模型名静默回退 anthropic-mock 的假响应（只是 prompt 回显）——
            # 老板当时误点了 👍，不能进黄金集
            print(f"  [skip] tool_call {row['id']} 是 anthropic-mock 假响应，不进黄金集")
            continue
        case = f"matrix-good-{str(row['id'])[:8]}"
        args = {
            "sku_id": args_db.get("sku_id"),
            "user_initial_points": args_db.get("user_initial_points") or "",
            "user_reviews": args_db.get("user_reviews") or "",
            "kb_context": args_db.get("kb_context"),
            "extra_context": args_db.get("extra_context"),
        }
        source = (
            f"mcp.tool_calls id={row['id']} user_rating=good created_at={row['created_at']}"
        )
        _write_case("generate_selling_points_matrix", case, args, matrix_md, source)
        n += 1
    return n


# ---------- generate_audience_portrait ----------

async def seed_portrait(freeze_recall: bool = True) -> int:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, audience_record_id, sku_id, portrait_md, recall_meta, extra_context, "
        "version, created_at FROM pipeline.audience_portraits "
        "WHERE status='adopted' ORDER BY created_at"
    )
    n = 0
    for r in rows:
        row = dict(r)
        case = f"portrait-adopted-{str(row['id'])[:8]}"
        override = None
        freeze_note = "未冻结（eval 时走 live 四路召回；KB 基本静态，可接受）"
        if freeze_recall:
            # 库里只存 prompt_hash 不存 final_prompt，原始召回文本不可恢复 →
            # seed 时实跑一次四路召回，把结果冻结进 input.yaml 当 kb_recall_override 回放
            try:
                from app.mcp.tools.portrait_brief import _portrait_recall
                from app.services import pipeline_lineage
                record = await pipeline_lineage.get_audience_record(str(row["audience_record_id"]))
                matrix_run = await pipeline_lineage.get_matrix_run(record.get("matrix_run_id")) if record else None
                matrix_md = (matrix_run or {}).get("matrix_md") or ""
                if record:
                    override, meta = await _portrait_recall(record, matrix_md)
                    freeze_note = (
                        f"seed 时实跑四路召回冻结（chunks={meta.get('chunk_count')}，"
                        f"{_now()}）——回放时 KB 上下文恒定"
                    )
            except Exception as exc:  # noqa: BLE001
                freeze_note = f"召回冻结失败（{type(exc).__name__}: {exc}）→ eval 时走 live 召回"
                print(f"  [warn] {case} {freeze_note}")
        args = {
            "audience_record_id": str(row["audience_record_id"]),
            "extra_context": row.get("extra_context") or None,
            "kb_recall_override": override,
        }
        source = (
            f"pipeline.audience_portraits id={row['id']} status=adopted version={row['version']} "
            f"sku={row['sku_id']} created_at={row['created_at']}；"
            f"原跑 recall_meta={json.dumps(_jsonb(row.get('recall_meta')) or {}, ensure_ascii=False)[:400]}；"
            f"kb_recall_override: {freeze_note}"
        )
        _write_case("generate_audience_portrait", case, args, row["portrait_md"], source)
        n += 1
    return n


# ---------- generate_creative_pack ----------

async def seed_creative_pack() -> int:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, sku_id, kind, script_md, audience_record_id, audience_pack_id, "
        "extra_context, version, created_at FROM pipeline.scripts "
        "WHERE status='adopted' AND kind LIKE 'video_%' ORDER BY kind, created_at"
    )
    n = 0
    for r in rows:
        row = dict(r)
        case = f"{row['kind']}-v{row['version']}-{str(row['id'])[:8]}"
        args = {
            "kind": row["kind"],
            "sku_id": row["sku_id"],
            "audience_record_id": str(row["audience_record_id"]) if row.get("audience_record_id") else None,
            "audience_pack_id": str(row["audience_pack_id"]) if row.get("audience_pack_id") else None,
            "extra_context": row.get("extra_context") or None,
        }
        source = (
            f"pipeline.scripts id={row['id']} status=adopted kind={row['kind']} "
            f"version={row['version']} created_at={row['created_at']}"
        )
        _write_case("generate_creative_pack", case, args, row["script_md"], source)
        n += 1
    return n


# ---------- generate_director_brief（占位） ----------

async def seed_director_brief() -> int:
    pool = get_pool()
    cnt = await pool.fetchval(
        "SELECT count(*) FROM pipeline.scripts WHERE kind='director_brief' AND status='adopted'"
    )
    tool_dir = GOLDEN_ROOT / "generate_director_brief"
    tool_dir.mkdir(parents=True, exist_ok=True)
    if cnt:
        # 老板采纳后：按 creative_pack 同款方式 seed（portrait_id 在行内）
        rows = await pool.fetch(
            "SELECT id, sku_id, script_md, portrait_id, extra_context, version, created_at "
            "FROM pipeline.scripts WHERE kind='director_brief' AND status='adopted' ORDER BY created_at"
        )
        n = 0
        for r in rows:
            row = dict(r)
            if not row.get("portrait_id"):
                print(f"  [skip] director_brief {row['id']} 无 portrait_id（无法回放输入）")
                continue
            case = f"director-adopted-{str(row['id'])[:8]}"
            args = {
                "portrait_id": str(row["portrait_id"]),
                "extra_context": row.get("extra_context") or None,
                "num_variants": 1,
            }
            source = (
                f"pipeline.scripts id={row['id']} status=adopted kind=director_brief "
                f"version={row['version']} created_at={row['created_at']}"
            )
            _write_case("generate_director_brief", case, args, row["script_md"], source)
            n += 1
        return n
    (tool_dir / "README.md").write_text(
        "# generate_director_brief 黄金集（占位）\n\n"
        "截至 seed 时 `pipeline.scripts kind='director_brief'` **0 条 adopted**（只有 draft）——\n"
        "黄金集只收老板真实采纳过的产物，不拿 draft 凑数。\n\n"
        "**等老板在 /sku-pipeline step 3.6 采纳一版 brief 后**（`pipeline_adopt(table='scripts', run_id=...)`），\n"
        "重跑 `python /app/scripts/eval/seed_golden.py --tool generate_director_brief` 自动出 case。\n",
        encoding="utf-8",
    )
    print("  [placeholder] generate_director_brief：0 条 adopted → 写 README 占位")
    return 0


# ---------- main ----------

async def main() -> None:
    parser = argparse.ArgumentParser(description="黄金集 seeding（从 live DB 捞采纳产物）")
    parser.add_argument("--tool", choices=TOOLS, help="只 seed 某个 tool（默认全部）")
    parser.add_argument("--no-freeze-recall", action="store_true",
                        help="portrait case 不冻结四路召回（省时间）")
    ns = parser.parse_args()

    await init_pool()
    try:
        GOLDEN_ROOT.mkdir(parents=True, exist_ok=True)
        total = 0
        if not ns.tool or ns.tool == "generate_brief":
            print("== seed generate_brief ==")
            total += await seed_generate_brief()
        if not ns.tool or ns.tool == "generate_selling_points_matrix":
            print("== seed generate_selling_points_matrix ==")
            total += await seed_matrix()
        if not ns.tool or ns.tool == "generate_audience_portrait":
            print("== seed generate_audience_portrait ==")
            total += await seed_portrait(freeze_recall=not ns.no_freeze_recall)
        if not ns.tool or ns.tool == "generate_creative_pack":
            print("== seed generate_creative_pack ==")
            total += await seed_creative_pack()
        if not ns.tool or ns.tool == "generate_director_brief":
            print("== seed generate_director_brief ==")
            total += await seed_director_brief()
        print(f"\nseed 完成：共 {total} 个 case → {GOLDEN_ROOT}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
