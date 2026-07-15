"""SKU 出片链路血缘落库（W4-B 切片 14.3 phase A）。

提供 step 2 / step 3 LLM tool 跑完后的持久化函数，以及 step 3 audience_md
→ audience_records 的 regex 拆分。

设计原则：
- 跑完即落库（status='draft'），老板手动采纳改 'adopted'
- 多版本（version 自增 + parent_run_id 串前后），不覆盖
- denorm sku_id 到每张表，最终复盘 SQL 不用多层 join
- 解析失败不阻塞主流程，记 warning 入 audience_runs.notes，但 audience_records 拆 0 条也不报错

字段对齐 migrations/021_pipeline_lineage.sql
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import logging
import re
from typing import Any

from app.database import get_pool

logger = logging.getLogger(__name__)


def _prompt_hash(prompt: str) -> str:
    """SHA256 前 12 字符，用于追溯同一份 prompt 的多次调用。"""
    return hashlib.sha256(prompt.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _coerce_jsonb_list(v) -> list:
    """asyncpg 默认返 JSONB 为字符串，转回 Python list（briefs.py 同款 helper）。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _coerce_jsonb_dict(v) -> dict:
    if isinstance(v, Mapping):
        return dict(v)
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


# ════════════════════════════════════════════════════════════════
# step 2 落库
# ════════════════════════════════════════════════════════════════

async def save_matrix_run(
    *,
    sku_id: str,
    matrix_md: str,
    user_initial_points: str | None = None,
    user_reviews: str | None = None,
    kb_context: str | None = None,
    extra_context: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    parent_run_id: str | None = None,
) -> str | None:
    """落 1 行 pipeline.matrix_runs，返回 id（UUID 字符串）。失败返 None 不抛。"""
    if not matrix_md or not matrix_md.strip():
        logger.warning("save_matrix_run: matrix_md 空，跳过落库")
        return None

    pool = get_pool()

    # 同 sku 当前 version 自增
    next_version = 1
    if parent_run_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.matrix_runs WHERE id = $1::uuid",
            parent_run_id,
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        row = await pool.fetchrow(
            "SELECT MAX(version) AS v FROM pipeline.matrix_runs WHERE sku_id = $1",
            sku_id,
        )
        if row and row["v"]:
            next_version = int(row["v"]) + 1

    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.matrix_runs (
                sku_id, matrix_md,
                user_initial_points, user_reviews, kb_context, extra_context,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_run_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                'draft', $11, $12
            ) RETURNING id::text AS id
            """,
            sku_id,
            matrix_md.strip(),
            user_initial_points,
            user_reviews,
            kb_context,
            extra_context,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_run_id,
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_matrix_run failed: %s", exc)
        return None


# ════════════════════════════════════════════════════════════════
# step 3 拆 audience_records（regex 解析）
# ════════════════════════════════════════════════════════════════

# 人群段头：`#### 1.X [人群名]` 或 `#### 1.X 人群名`（兼容方括号缺失）
_RECORD_HEADER_RE = re.compile(
    r"^#{3,4}\s+(?P<num>\d+(?:\.\d+)*)\s+\[?(?P<name>[^\]\n]+?)\]?\s*$",
    re.M,
)
# KB 来源标签：**[KB 来源：文档名 / 章节路径]** 或 [KB 来源：xxx]
_KB_SOURCE_RE = re.compile(
    r"\[\s*KB\s*来源\s*[:：]\s*(?P<doc>[^/\n\]]+?)(?:\s*/\s*(?P<section>[^\]\n]+?))?\s*\]",
)
# 引用块 KB chunk：连续 > 开头的行
_QUOTE_BLOCK_RE = re.compile(r"((?:^>.*(?:\n|$))+)", re.M)
# 匹配理由列表：1. xxx 2. xxx ...（取 1.~9. 的连续条目）
_REASON_ITEM_RE = re.compile(r"^\s*\d+\.\s+(.+?)$", re.M)
# 圈层标签：**圈层标签**：a / b / c 或 a, b, c
_LAYER_TAGS_RE = re.compile(
    r"\*\*\s*圈层标签\s*\*\*\s*[:：]\s*(?P<tags>[^\n]+)$",
    re.M,
)


def _parse_one_record(segment: str, ordinal: int) -> dict[str, Any] | None:
    """解析单段 #### 1.X [人群名] ... 段为字段字典。"""
    head_match = _RECORD_HEADER_RE.search(segment)
    if not head_match:
        return None

    name = head_match.group("name").strip().strip("[]").strip()
    if not name:
        return None

    # KB 来源
    kb_doc = None
    kb_section = None
    kb_match = _KB_SOURCE_RE.search(segment)
    if kb_match:
        kb_doc = (kb_match.group("doc") or "").strip() or None
        kb_section = (kb_match.group("section") or "").strip() or None

    # KB chunk 原文（取最长的引用块）
    kb_chunk_text = None
    quotes = _QUOTE_BLOCK_RE.findall(segment)
    if quotes:
        # 取字符数最多的引用块（避免误抓"匹配理由"前的小引用）
        kb_chunk_text = max(quotes, key=len).rstrip()

    # 匹配理由（在 "**匹配理由" 之后到 "**圈层标签" 之前的区域里抓 1./2./3.）
    reasons: list[str] = []
    reason_zone_match = re.search(
        r"\*\*\s*匹配理由[^\n]*\*\*\s*[:：]?\s*(.+?)(?=\*\*\s*圈层标签|\Z)",
        segment,
        re.S,
    )
    if reason_zone_match:
        reason_zone = reason_zone_match.group(1)
        for m in _REASON_ITEM_RE.finditer(reason_zone):
            text = m.group(1).strip()
            if text:
                reasons.append(text)

    # 圈层标签
    layer_tags: list[str] = []
    tags_match = _LAYER_TAGS_RE.search(segment)
    if tags_match:
        raw = tags_match.group("tags")
        # 切分支持 / 、 / 中文逗号 / 顿号
        parts = re.split(r"[/、，,]", raw)
        layer_tags = [p.strip() for p in parts if p.strip()]

    return {
        "ordinal": ordinal,
        "name": name,
        "kb_doc": kb_doc,
        "kb_section": kb_section,
        "kb_chunk_text": kb_chunk_text,
        "match_reasons": reasons,
        "layer_tags": layer_tags,
        "raw_md_segment": segment.strip(),
    }


def parse_audience_records(audience_md: str) -> list[dict[str, Any]]:
    """从 audience_md 拆出 N 个人群 record。

    策略：
    1. 找所有 `#### 1.X [人群名]` 头位置
    2. 每个头到下一个头之间为一段
    3. 第二部分（结构化标签汇总）开始之前停止（标志：`### 第 2 部分` 或 `## 第 2 部分`）
    4. 每段调 _parse_one_record 解析

    解析失败的段不入库；返回成功的列表。
    """
    if not audience_md or not audience_md.strip():
        return []

    text = audience_md
    # 截掉第二部分（标签汇总）—— 多种可能写法
    cutoffs = [
        re.search(r"^#{2,4}\s*第\s*[二2]\s*部分", text, re.M),
        re.search(r"^#{2,4}\s*结构化标签汇总", text, re.M),
        re.search(r"^#{2,4}\s*标签汇总", text, re.M),
    ]
    cutoff_pos = None
    for c in cutoffs:
        if c:
            cutoff_pos = c.start() if cutoff_pos is None else min(cutoff_pos, c.start())
    if cutoff_pos is not None:
        text = text[:cutoff_pos]

    # 找所有人群段头位置
    headers = list(_RECORD_HEADER_RE.finditer(text))
    if not headers:
        return []

    records: list[dict[str, Any]] = []
    for i, h in enumerate(headers):
        start = h.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        segment = text[start:end]
        parsed = _parse_one_record(segment, ordinal=i + 1)
        if parsed:
            records.append(parsed)
    return records


# ════════════════════════════════════════════════════════════════
# step 3 落库
# ════════════════════════════════════════════════════════════════

async def save_audience_run(
    *,
    matrix_run_id: str,
    sku_id: str,
    audience_md: str,
    recall_meta: dict | None = None,
    extra_context: str | None = None,
    kb_recall_override: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    parent_run_id: str | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """落 1 行 pipeline.audience_runs + N 行 pipeline.audience_records。

    返回 (audience_run_id, parsed_records_with_ids)。失败返 (None, []) 不抛。
    parsed_records_with_ids 每条加了 'id'（DB 生成的 UUID）。
    """
    if not audience_md or not audience_md.strip():
        logger.warning("save_audience_run: audience_md 空，跳过落库")
        return None, []

    pool = get_pool()

    # 版本号
    next_version = 1
    if parent_run_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.audience_runs WHERE id = $1::uuid",
            parent_run_id,
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        row = await pool.fetchrow(
            "SELECT MAX(version) AS v FROM pipeline.audience_runs WHERE matrix_run_id = $1::uuid",
            matrix_run_id,
        )
        if row and row["v"]:
            next_version = int(row["v"]) + 1

    # 先拆 records（先解析，后入库；解析失败也不阻塞 audience_run 落库）
    parsed = parse_audience_records(audience_md)

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                run_rec = await conn.fetchrow(
                    """
                    INSERT INTO pipeline.audience_runs (
                        matrix_run_id, sku_id, audience_md, recall_meta, record_count,
                        extra_context, kb_recall_override,
                        model_provider, model, prompt_hash, cost_estimate,
                        status, version, parent_run_id
                    ) VALUES (
                        $1::uuid, $2, $3, $4::jsonb, $5,
                        $6, $7,
                        $8, $9, $10, $11,
                        'draft', $12, $13
                    ) RETURNING id::text AS id
                    """,
                    matrix_run_id,
                    sku_id,
                    audience_md.strip(),
                    json.dumps(recall_meta or {}, ensure_ascii=False),
                    len(parsed),
                    extra_context,
                    kb_recall_override,
                    model_provider,
                    model,
                    _prompt_hash(final_prompt) if final_prompt else None,
                    cost_estimate,
                    next_version,
                    parent_run_id,
                )
                audience_run_id = run_rec["id"]

                # 批量插 records
                records_with_ids: list[dict[str, Any]] = []
                for r in parsed:
                    rec = await conn.fetchrow(
                        """
                        INSERT INTO pipeline.audience_records (
                            audience_run_id, matrix_run_id, sku_id,
                            ordinal, name, kb_doc, kb_section,
                            kb_chunk_text, match_reasons, layer_tags, raw_md_segment,
                            status
                        ) VALUES (
                            $1::uuid, $2::uuid, $3,
                            $4, $5, $6, $7,
                            $8, $9::jsonb, $10::jsonb, $11,
                            'draft'
                        ) RETURNING id::text AS id
                        """,
                        audience_run_id,
                        matrix_run_id,
                        sku_id,
                        r["ordinal"],
                        r["name"],
                        r["kb_doc"],
                        r["kb_section"],
                        r["kb_chunk_text"],
                        json.dumps(r["match_reasons"], ensure_ascii=False),
                        json.dumps(r["layer_tags"], ensure_ascii=False),
                        r["raw_md_segment"],
                    )
                    out = dict(r)
                    out["id"] = rec["id"]
                    records_with_ids.append(out)

                return audience_run_id, records_with_ids
    except Exception as exc:
        logger.exception("save_audience_run failed: %s", exc)
        return None, []


# ════════════════════════════════════════════════════════════════
# step 3 分批落库（generate_audience_match batch 模式：建空 run → 逐批 append → 收尾 update）
# ════════════════════════════════════════════════════════════════

async def create_audience_run(
    *,
    matrix_run_id: str,
    sku_id: str,
    recall_meta: dict | None = None,
    extra_context: str | None = None,
    kb_recall_override: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    parent_run_id: str | None = None,
) -> str | None:
    """建一行空 audience_run（record_count=0、audience_md=''），供分批模式逐批 append。

    版本号逻辑同 save_audience_run。失败返 None（调用方退化为内存累积 + 末尾一次性 save）。
    """
    pool = get_pool()
    next_version = 1
    if parent_run_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.audience_runs WHERE id = $1::uuid", parent_run_id
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        row = await pool.fetchrow(
            "SELECT MAX(version) AS v FROM pipeline.audience_runs WHERE matrix_run_id = $1::uuid",
            matrix_run_id,
        )
        if row and row["v"]:
            next_version = int(row["v"]) + 1
    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.audience_runs (
                matrix_run_id, sku_id, audience_md, recall_meta, record_count,
                extra_context, kb_recall_override,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_run_id
            ) VALUES (
                $1::uuid, $2, '', $3::jsonb, 0,
                $4, $5,
                $6, $7, $8, $9,
                'draft', $10, $11
            ) RETURNING id::text AS id
            """,
            matrix_run_id,
            sku_id,
            json.dumps(recall_meta or {}, ensure_ascii=False),
            extra_context,
            kb_recall_override,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_run_id,
        )
        return rec["id"]
    except Exception as exc:
        logger.warning("create_audience_run failed: %s", exc)
        return None


async def append_audience_records(
    *,
    audience_run_id: str,
    matrix_run_id: str,
    sku_id: str,
    records: list[dict[str, Any]],
    start_ordinal: int = 1,
) -> list[dict[str, Any]]:
    """把一批已 parse 的 records 追加进现有 run；ordinal 从 start_ordinal 续号。

    返回带 DB id + 续号 ordinal 的列表；失败返 []（调用方保留内存态）。
    """
    if not records:
        return []
    pool = get_pool()
    out: list[dict[str, Any]] = []
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for offset, r in enumerate(records):
                    ordinal = start_ordinal + offset
                    rec = await conn.fetchrow(
                        """
                        INSERT INTO pipeline.audience_records (
                            audience_run_id, matrix_run_id, sku_id,
                            ordinal, name, kb_doc, kb_section,
                            kb_chunk_text, match_reasons, layer_tags, raw_md_segment,
                            status
                        ) VALUES (
                            $1::uuid, $2::uuid, $3,
                            $4, $5, $6, $7,
                            $8, $9::jsonb, $10::jsonb, $11,
                            'draft'
                        ) RETURNING id::text AS id
                        """,
                        audience_run_id,
                        matrix_run_id,
                        sku_id,
                        ordinal,
                        r["name"],
                        r["kb_doc"],
                        r["kb_section"],
                        r["kb_chunk_text"],
                        json.dumps(r["match_reasons"], ensure_ascii=False),
                        json.dumps(r["layer_tags"], ensure_ascii=False),
                        r["raw_md_segment"],
                    )
                    o = dict(r)
                    o["id"] = rec["id"]
                    o["ordinal"] = ordinal
                    out.append(o)
        return out
    except Exception as exc:
        logger.warning("append_audience_records failed: %s", exc)
        return []


async def update_audience_run_md(
    *,
    audience_run_id: str,
    audience_md: str,
    record_count: int,
    notes: str | None = None,
) -> None:
    """分批收尾：把组装好的整段 audience_md + 最终人群数 + notes 写回 run。"""
    pool = get_pool()
    try:
        await pool.execute(
            "UPDATE pipeline.audience_runs "
            "SET audience_md = $1, record_count = $2, notes = $3, updated_at = NOW() "
            "WHERE id = $4::uuid",
            audience_md,
            record_count,
            notes,
            audience_run_id,
        )
    except Exception as exc:
        logger.warning("update_audience_run_md failed: %s", exc)


# ════════════════════════════════════════════════════════════════
# 查询 helpers（A4 阶段 tool 用）
# ════════════════════════════════════════════════════════════════

async def list_audience_runs(sku_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    """列某 SKU 的所有 step 3 跑次（最近 N 条；不传 sku_id = 全表）。"""
    pool = get_pool()
    if sku_id:
        rows = await pool.fetch(
            """
            SELECT id::text, matrix_run_id::text, sku_id, version, status,
                   record_count, model_provider, model, created_at, parent_run_id::text
            FROM pipeline.audience_runs
            WHERE sku_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            sku_id, limit,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id::text, matrix_run_id::text, sku_id, version, status,
                   record_count, model_provider, model, created_at, parent_run_id::text
            FROM pipeline.audience_runs
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def get_audience_run(audience_run_id: str) -> dict[str, Any] | None:
    """拉单条 audience_run 全字段 + 关联的所有 audience_records 列表（按 ordinal）。"""
    pool = get_pool()
    run = await pool.fetchrow(
        """
        SELECT id::text, matrix_run_id::text, sku_id, audience_md,
               recall_meta, record_count, extra_context, kb_recall_override,
               model_provider, model, version, status, parent_run_id::text,
               created_at, updated_at
        FROM pipeline.audience_runs
        WHERE id = $1::uuid
        """,
        audience_run_id,
    )
    if not run:
        return None
    run_d = dict(run)
    run_d["recall_meta"] = _coerce_jsonb_dict(run_d.get("recall_meta"))

    rec_rows = await pool.fetch(
        """
        SELECT id::text, ordinal, name, kb_doc, kb_section,
               layer_tags, match_reasons, status, selected_for_pack
        FROM pipeline.audience_records
        WHERE audience_run_id = $1::uuid
        ORDER BY ordinal
        """,
        audience_run_id,
    )
    records = []
    for r in rec_rows:
        d = dict(r)
        d["layer_tags"] = _coerce_jsonb_list(d.get("layer_tags"))
        d["match_reasons"] = _coerce_jsonb_list(d.get("match_reasons"))
        records.append(d)

    return {"run": run_d, "records": records}


# ════════════════════════════════════════════════════════════════
# step 4 圈包落库（phase B）
# ════════════════════════════════════════════════════════════════

async def save_audience_pack(
    *,
    audience_record_id: str,
    audience_run_id: str,
    matrix_run_id: str,
    sku_id: str,
    pack_md: str,
    dmp_tags: list | None = None,
    budget_suggestion: dict | None = None,
    extra_context: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    parent_pack_id: str | None = None,
) -> str | None:
    """落 1 行 pipeline.audience_packs，返回 id。失败返 None 不抛。"""
    if not pack_md or not pack_md.strip():
        logger.warning("save_audience_pack: pack_md 空，跳过落库")
        return None

    pool = get_pool()

    # 同 audience_record 的 version 自增
    next_version = 1
    if parent_pack_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.audience_packs WHERE id = $1::uuid",
            parent_pack_id,
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        row = await pool.fetchrow(
            "SELECT MAX(version) AS v FROM pipeline.audience_packs WHERE audience_record_id = $1::uuid",
            audience_record_id,
        )
        if row and row["v"]:
            next_version = int(row["v"]) + 1

    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.audience_packs (
                audience_record_id, audience_run_id, matrix_run_id, sku_id,
                pack_md, dmp_tags, budget_suggestion,
                extra_context,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_pack_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4,
                $5, $6::jsonb, $7::jsonb,
                $8,
                $9, $10, $11, $12,
                'draft', $13, $14
            ) RETURNING id::text AS id
            """,
            audience_record_id,
            audience_run_id,
            matrix_run_id,
            sku_id,
            pack_md.strip(),
            json.dumps(dmp_tags or [], ensure_ascii=False),
            json.dumps(budget_suggestion or {}, ensure_ascii=False),
            extra_context,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_pack_id,
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_audience_pack failed: %s", exc)
        return None


# ════════════════════════════════════════════════════════════════
# 关键词包落库（phase B+）
# ════════════════════════════════════════════════════════════════

async def save_keyword_pack(
    *,
    sku_id: str,
    seed_keywords: str,
    keyword_text: str,
    keyword_count: int,
    target_count: int = 500,
    audience_record_id: str | None = None,
    audience_pack_id: str | None = None,
    extra_context: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    parent_pack_id: str | None = None,
) -> str | None:
    """落 1 行 pipeline.keyword_packs。失败返 None 不抛。"""
    if not keyword_text or not keyword_text.strip():
        logger.warning("save_keyword_pack: keyword_text 空，跳过落库")
        return None

    pool = get_pool()

    # 同上下文 version 自增（按 sku_id+audience_record_id 唯一锚）
    next_version = 1
    if parent_pack_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.keyword_packs WHERE id = $1::uuid",
            parent_pack_id,
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        if audience_record_id:
            row = await pool.fetchrow(
                "SELECT MAX(version) AS v FROM pipeline.keyword_packs "
                "WHERE sku_id = $1 AND audience_record_id = $2::uuid",
                sku_id, audience_record_id,
            )
        else:
            row = await pool.fetchrow(
                "SELECT MAX(version) AS v FROM pipeline.keyword_packs WHERE sku_id = $1",
                sku_id,
            )
        if row and row["v"]:
            next_version = int(row["v"]) + 1

    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.keyword_packs (
                audience_record_id, audience_pack_id, sku_id,
                seed_keywords, keyword_text, keyword_count, target_count,
                extra_context,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_pack_id
            ) VALUES (
                $1::uuid, $2::uuid, $3,
                $4, $5, $6, $7,
                $8,
                $9, $10, $11, $12,
                'draft', $13, $14::uuid
            ) RETURNING id::text AS id
            """,
            audience_record_id,
            audience_pack_id,
            sku_id,
            seed_keywords.strip(),
            keyword_text.strip(),
            keyword_count,
            target_count,
            extra_context,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_pack_id,
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_keyword_pack failed: %s", exc)
        return None


async def list_keyword_packs(
    sku_id: str | None = None,
    audience_record_id: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    pool = get_pool()
    where = []
    params: list[Any] = []
    if sku_id:
        params.append(sku_id)
        where.append(f"sku_id = ${len(params)}")
    if audience_record_id:
        params.append(audience_record_id)
        where.append(f"audience_record_id = ${len(params)}::uuid")
    params.append(limit)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = await pool.fetch(
        f"""
        SELECT id::text, sku_id, audience_record_id::text, audience_pack_id::text,
               seed_keywords, keyword_count, target_count, version, status,
               model, created_at
        FROM pipeline.keyword_packs
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def get_keyword_pack(pack_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, sku_id, audience_record_id::text, audience_pack_id::text,
               seed_keywords, keyword_text, keyword_count, target_count,
               extra_context, model_provider, model, version, status,
               parent_pack_id::text, created_at, updated_at
        FROM pipeline.keyword_packs
        WHERE id = $1::uuid
        """,
        pack_id,
    )
    return dict(row) if row else None


async def list_audience_packs(
    audience_record_id: str | None = None,
    sku_id: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    pool = get_pool()
    where = []
    params: list[Any] = []
    if audience_record_id:
        params.append(audience_record_id)
        where.append(f"audience_record_id = ${len(params)}::uuid")
    if sku_id:
        params.append(sku_id)
        where.append(f"sku_id = ${len(params)}")
    params.append(limit)
    where_sql = "WHERE " + " AND ".join(where) if where else ""

    rows = await pool.fetch(
        f"""
        SELECT id::text, audience_record_id::text, sku_id, version, status,
               model_provider, model, created_at, parent_pack_id::text
        FROM pipeline.audience_packs
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def get_audience_pack(pack_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, audience_record_id::text, audience_run_id::text,
               matrix_run_id::text, sku_id, pack_md, dmp_tags, budget_suggestion,
               extra_context, model_provider, model, version, status,
               parent_pack_id::text, created_at, updated_at
        FROM pipeline.audience_packs
        WHERE id = $1::uuid
        """,
        pack_id,
    )
    if not row:
        return None
    d = dict(row)
    d["dmp_tags"] = _coerce_jsonb_list(d.get("dmp_tags"))
    d["budget_suggestion"] = _coerce_jsonb_dict(d.get("budget_suggestion"))
    return d


async def list_matrix_runs(sku_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    pool = get_pool()
    if sku_id:
        rows = await pool.fetch(
            """
            SELECT id::text, sku_id, version, status, model_provider, model,
                   created_at, parent_run_id::text
            FROM pipeline.matrix_runs
            WHERE sku_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            sku_id, limit,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id::text, sku_id, version, status, model_provider, model,
                   created_at, parent_run_id::text
            FROM pipeline.matrix_runs
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def get_matrix_run(matrix_run_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, sku_id, matrix_md, version, status, model_provider, model,
               user_initial_points, user_reviews, kb_context, extra_context,
               cost_estimate, parent_run_id::text, created_at, updated_at
        FROM pipeline.matrix_runs
        WHERE id = $1::uuid
        """,
        matrix_run_id,
    )
    return dict(row) if row else None


async def list_audience_records(
    audience_run_id: str | None = None,
    sku_id: str | None = None,
    selected_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    pool = get_pool()
    where = []
    params: list[Any] = []
    if audience_run_id:
        params.append(audience_run_id)
        where.append(f"audience_run_id = ${len(params)}::uuid")
    if sku_id:
        params.append(sku_id)
        where.append(f"sku_id = ${len(params)}")
    if selected_only:
        where.append("selected_for_pack = TRUE")
    params.append(limit)
    where_sql = "WHERE " + " AND ".join(where) if where else ""

    rows = await pool.fetch(
        f"""
        SELECT id::text, audience_run_id::text, matrix_run_id::text, sku_id,
               ordinal, name, kb_doc, kb_section, layer_tags, match_reasons,
               status, selected_for_pack, created_at
        FROM pipeline.audience_records
        {where_sql}
        ORDER BY audience_run_id, ordinal
        LIMIT ${len(params)}
        """,
        *params,
    )
    out = []
    for r in rows:
        d = dict(r)
        d["layer_tags"] = _coerce_jsonb_list(d.get("layer_tags"))
        d["match_reasons"] = _coerce_jsonb_list(d.get("match_reasons"))
        out.append(d)
    return out


async def get_audience_record(record_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, audience_run_id::text, matrix_run_id::text, sku_id,
               ordinal, name, kb_doc, kb_section, kb_chunk_text,
               match_reasons, layer_tags, raw_md_segment,
               status, selected_for_pack, created_at, updated_at
        FROM pipeline.audience_records
        WHERE id = $1::uuid
        """,
        record_id,
    )
    if not row:
        return None
    d = dict(row)
    d["layer_tags"] = _coerce_jsonb_list(d.get("layer_tags"))
    d["match_reasons"] = _coerce_jsonb_list(d.get("match_reasons"))
    return d


# ════════════════════════════════════════════════════════════════
# step 3.5 人群画像落库（migration 047，audience_portraits）
# ════════════════════════════════════════════════════════════════

async def save_audience_portrait(
    *,
    audience_record_id: str,
    sku_id: str,
    portrait_md: str,
    audience_run_id: str | None = None,
    matrix_run_id: str | None = None,
    recall_meta: dict | None = None,
    validation_warnings: list | None = None,
    extra_context: str | None = None,
    kb_recall_override: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    parent_portrait_id: str | None = None,
) -> str | None:
    """落 1 行 pipeline.audience_portraits（step 3.5），返回 id。失败返 None 不抛。"""
    if not portrait_md or not portrait_md.strip():
        logger.warning("save_audience_portrait: portrait_md 空，跳过落库")
        return None

    pool = get_pool()

    # 版本号：同 record 下自增；显式 parent 时取其 version+1
    next_version = 1
    if parent_portrait_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.audience_portraits WHERE id = $1::uuid",
            parent_portrait_id,
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        row = await pool.fetchrow(
            "SELECT MAX(version) AS v FROM pipeline.audience_portraits WHERE audience_record_id = $1::uuid",
            audience_record_id,
        )
        if row and row["v"]:
            next_version = int(row["v"]) + 1

    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.audience_portraits (
                audience_record_id, audience_run_id, matrix_run_id, sku_id,
                portrait_md, recall_meta, validation_warnings,
                extra_context, kb_recall_override,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_portrait_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4,
                $5, $6::jsonb, $7::jsonb,
                $8, $9,
                $10, $11, $12, $13,
                'draft', $14, $15::uuid
            ) RETURNING id::text AS id
            """,
            audience_record_id,
            audience_run_id,
            matrix_run_id,
            sku_id,
            portrait_md.strip(),
            json.dumps(recall_meta or {}, ensure_ascii=False),
            json.dumps(validation_warnings or [], ensure_ascii=False),
            extra_context,
            kb_recall_override,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_portrait_id,
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_audience_portrait failed: %s", exc)
        return None


async def get_audience_portrait(portrait_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, audience_record_id::text, audience_run_id::text,
               matrix_run_id::text, sku_id,
               portrait_md, recall_meta, validation_warnings,
               extra_context, status, version, parent_portrait_id::text,
               model_provider, model, cost_estimate, created_at, updated_at
        FROM pipeline.audience_portraits
        WHERE id = $1::uuid
        """,
        portrait_id,
    )
    if not row:
        return None
    d = dict(row)
    d["recall_meta"] = _coerce_jsonb_dict(d.get("recall_meta"))
    d["validation_warnings"] = _coerce_jsonb_list(d.get("validation_warnings"))
    return d


async def list_audience_portraits(
    sku_id: str | None = None,
    audience_record_id: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """列画像（step 3.5），按时间倒序。portrait_md 截前 200 字做预览。"""
    pool = get_pool()
    conds, args = [], []
    if sku_id:
        args.append(sku_id)
        conds.append(f"sku_id = ${len(args)}")
    if audience_record_id:
        args.append(audience_record_id)
        conds.append(f"audience_record_id = ${len(args)}::uuid")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    args.append(max(1, min(100, limit)))
    rows = await pool.fetch(
        f"""
        SELECT id::text, audience_record_id::text, audience_run_id::text,
               matrix_run_id::text, sku_id,
               left(portrait_md, 200) AS portrait_preview,
               status, version, validation_warnings,
               model_provider, model, created_at
        FROM pipeline.audience_portraits
        {where}
        ORDER BY created_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    out = []
    for row in rows:
        d = dict(row)
        d["validation_warnings"] = _coerce_jsonb_list(d.get("validation_warnings"))
        out.append(d)
    return out


# ════════════════════════════════════════════════════════════════
# step 5 创意素材落库（W4-B 切片 14.4 phase C，6 类素材入 pipeline.scripts）
# ════════════════════════════════════════════════════════════════

CREATIVE_KINDS = (
    "video_soft_ad",
    "video_planting",
    "video_harvest",
    "graphic_harvest",
    "product_main_image",
    "product_detail_page",
    "director_brief",
)

# kind → 旧 target_purpose 字段映射（向后兼容）
_KIND_TO_TARGET_PURPOSE = {
    "video_soft_ad": "awareness",
    "video_planting": "planting",
    "video_harvest": "conversion",
    # 图文/主图/详情页不写 target_purpose
}


# ════════════════════════════════════════════════════════════════
# scenes 解析（W4-B 切片 14.4 phase D：从 script_md 拆分镜清单）
# ════════════════════════════════════════════════════════════════

# 视频类 kind 通用：#### 节点 N · 名称（X-Xs）
_VIDEO_SCENE_HEADER_RE = re.compile(
    r"^#{3,4}\s*(?:节点|分镜|镜头|场景|节)\s*(?P<no>\d+)\s*[·\.\-]?\s*"
    r"(?P<name>[^（(\n]*?)\s*"
    r"(?:[（(](?P<time>[\d\-~至到]+\s*[s秒]?)[）)])?\s*$",
    re.M,
)
# 字段抽取：- **画面**：xxx / - **台词/字幕**：xxx 等
_VIDEO_FIELD_RES = {
    "visual":       re.compile(r"\*\*\s*画面\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\s*$|$)", re.S),
    "dialog":       re.compile(r"\*\*\s*台词[/／]?\s*字幕?\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\s*$|$)", re.S),
    "shot":         re.compile(r"\*\*\s*镜头\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\s*$|$)", re.S),
    "sound":        re.compile(r"\*\*\s*声音\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\s*$|$)", re.S),
    "core":         re.compile(r"\*\*\s*(?:节点)?内核\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\s*$|$)", re.S),
    "change_point": re.compile(r"\*\*\s*变化点\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\s*$|$)", re.S),
}

# phase D 新加 5 字段：本段角色 / 产品出场 / image_prompt（首帧）/ last_frame_prompt（尾帧）/ motion_prompt（运动）
_VIDEO_FIELD_RES_PHASE_D = {
    # **本段角色**：[daughter, mother] — 抓 [...] 内的 role_id 列表
    "characters_in_scene": re.compile(r"\*\*\s*本段角色\s*\*\*\s*[:：]\s*\[([^\]]*)\]"),
    # **产品出场**：true / false（理由）— 抓 true/false bool
    "product_appearance": re.compile(r"\*\*\s*产品出场\s*\*\*\s*[:：]\s*(true|false|是|否)", re.I),
    # **image_prompt**(...): 自然语言长描述 — 抓 : 后到下一个 - **xxx** 之前 / 或段落末尾
    "image_prompt": re.compile(
        r"\*\*\s*image_prompt\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\n```|\Z)",
        re.S,
    ),
    # **last_frame_prompt**(尾帧 ...): 动作完成态出帧 — 喂 step 6 生 image_last
    "last_frame_prompt": re.compile(
        r"\*\*\s*last_frame_prompt\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\n```|\Z)",
        re.S,
    ),
    # **motion_prompt**(运动描述 · 英文 ...): 首帧→尾帧间的可见运动 — 喂 step 7 Veo i2v
    "motion_prompt": re.compile(
        r"\*\*\s*motion_prompt\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\n```|\Z)",
        re.S,
    ),
}

# character_sheet 段（第 3.5 部分）：#### 角色 {role_id} · {简称}
_CHARACTER_HEADER_RE = re.compile(
    r"^#{3,4}\s*角色\s+(?P<role_id>[a-z][a-z0-9_]*)\s*[·\.\-]?\s*(?P<name>[^\n]*?)\s*$",
    re.M,
)
_CHARACTER_FIELD_RES = {
    # v12+ structured fields (Layer 1 of 5-layer character anchor framework)
    "age":              re.compile(r"\*\*\s*年龄\s*\*\*\s*[:：]\s*([^\n]+)"),
    "gender":           re.compile(r"\*\*\s*性别\s*\*\*\s*[:：]\s*([^\n]+)"),
    "body_type":        re.compile(r"\*\*\s*体型\s*\*\*\s*[:：]\s*([^\n]+)"),
    "ethnicity":        re.compile(r"\*\*\s*族裔\s*\*\*\s*[:：]\s*([^\n]+)"),
    "role":             re.compile(r"\*\*\s*社会角色\s*\*\*\s*[:：]\s*([^\n]+)"),
    "life_context":     re.compile(r"\*\*\s*生活语境\s*\*\*\s*[:：]\s*([^\n]+)"),
    "personality":      re.compile(r"\*\*\s*性格关键词\s*\*\*\s*[:：]\s*([^\n]+)"),
    "scene_type":       re.compile(r"\*\*\s*场景类型\s*\*\*\s*[:：]\s*([^\n]+)"),
    "realism_level":    re.compile(r"\*\*\s*写实程度\s*\*\*\s*[:：]\s*([^\n]+)"),
    # v11 legacy fields (kept for backward compat with old scripts)
    "appearance_keywords": re.compile(
        r"\*\*\s*外貌关键词\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\Z)",
        re.S,
    ),
    "aura": re.compile(
        r"\*\*\s*气质\s*[/／]?\s*神韵?\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\Z)",
        re.S,
    ),
    "audience_anchor":  re.compile(
        r"\*\*\s*人群锚点\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\n#|\Z)",
        re.S,
    ),
}

# 专属瑕疵列表 — 抓 ** 专属瑕疵 ** 下的 bullet 行（负向前瞻排除 - ** 字段行）
_CUSTOM_IMPERFECTIONS_SECTION_RE = re.compile(
    r"\*\*\s*专属瑕疵\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*\n"
    r"((?:[ \t]+-(?!\s*\*\*)[^\n]+\n?)+)",
    re.S,
)

# 图文类 kind：每段图片 brief 简单格式（按 #### 图 N / #### 主图 N / #### 段 N）
_GRAPHIC_SCENE_HEADER_RE = re.compile(
    r"^#{3,4}\s*(?:图|主图|分镜图|段|配图)\s*(?P<no>\d+)\s*[·\.\-：:]?\s*"
    r"(?P<name>[^\n]*?)\s*$",
    re.M,
)

# ── 新形态（2026-06-12 一大段提示词）：### 提示词块 X（0-15s / 0:00-0:15）──
_WHOLE_PROMPT_BLOCK_RE = re.compile(
    r"^#{2,4}\s*提示词块\s*(?P<no>\d+)\s*"
    r"(?:[（(]\s*(?P<time>[^）)\n]*?)\s*[）)])?\s*$",
    re.M,
)
_TIME_POINT_RE = re.compile(r"(?:(\d+)[:：])?(\d+(?:\.\d+)?)")


def _time_range_to_seconds(raw: str) -> tuple[int | None, int | None]:
    """'0-22s'/'0:00-0:22'/'5-18秒'/'0~22' → (start, end)；失败 (None, None)。"""
    if not raw:
        return (None, None)
    txt = raw.strip()
    for ch in ("～", "~", "—", "–", "至", "到"):
        txt = txt.replace(ch, "-")
    halves = [h.strip().rstrip("s秒S") for h in txt.split("-") if h.strip()]
    if len(halves) != 2:
        return (None, None)

    def _pt(p: str) -> int | None:
        m = _TIME_POINT_RE.fullmatch(p)
        if not m:
            return None
        return int((int(m.group(1)) if m.group(1) else 0) * 60 + float(m.group(2)))

    a, b = _pt(halves[0]), _pt(halves[1])
    return (a, b) if a is not None and b is not None and b > a else (None, None)


def _parse_whole_prompt_blocks(text: str) -> list[dict[str, Any]]:
    """新形态：每块 = 连续叙事全文（脚本=单一创意源，原样存，不抽字段）。"""
    headers = list(_WHOLE_PROMPT_BLOCK_RE.finditer(text))
    if not headers:
        return []
    scenes: list[dict[str, Any]] = []
    seen: set[int] = set()
    for i, h in enumerate(headers):
        no = int(h.group("no"))
        if no in seen:
            continue
        seen.add(no)
        body = text[h.end(): headers[i + 1].start() if i + 1 < len(headers) else len(text)].strip()
        # 截掉块后误入的下一节标题（## 自检 / # 第 X 部分）与 metrics_json 代码栅栏
        nxt = re.search(r"^#{1,3}\s", body, re.M)
        if nxt:
            body = body[:nxt.start()].strip()
        fence = body.find("\n```")
        if fence != -1:
            body = body[:fence].strip()
        if not body:
            continue
        t_raw = (h.group("time") or "").strip() or None
        t0, t1 = _time_range_to_seconds(t_raw or "")
        scene: dict[str, Any] = {
            "scene_no": no,
            "name": None,
            # 归一化成 "A-Bs" 喂旧 duration 解析器；解析失败保留原文
            "time_range": f"{t0}-{t1}s" if t0 is not None else t_raw,
            "video_prompt": body,
            "whole_prompt": True,
        }
        if t0 is not None and t1 is not None:
            scene["duration_s"] = t1 - t0
        scenes.append(scene)
    scenes.sort(key=lambda s: s["scene_no"])
    return scenes


def _video_scene_block_kinds() -> set[str]:
    return {"video_soft_ad", "video_planting", "video_harvest"}


def _graphic_scene_block_kinds() -> set[str]:
    return {"graphic_harvest", "product_main_image", "product_detail_page"}


def parse_scenes_from_script_md(script_md: str, kind: str) -> list[dict[str, Any]]:
    """从 script_md 拆出分镜清单。

    视频类（video_soft_ad/video_planting/video_harvest）：拆 #### 节点 N · XXX（X-Xs）
      段，提取 6 字段（画面/台词字幕/镜头/声音/内核/变化点）。
    图文类（graphic_harvest/product_main_image/product_detail_page）：拆 #### 图 N
      / 主图 N / 段 N 段，整段作 visual。

    返回 list of dict。失败返 []，主流程继续（save_creative_pack 不阻塞）。
    """
    if not script_md or not script_md.strip():
        return []

    # 截到"### 第 X 部分：分镜" 段（若有），避免把"钩子变体"等其他段当 scene
    # 不强制截 — 先全文匹配，scenes 自带 scene_no 唯一即可
    text = script_md

    if kind in _video_scene_block_kinds():
        # 新形态优先：「### 提示词块 X」= 单一创意源，压过任何残留"节点 N"段
        whole = _parse_whole_prompt_blocks(text)
        if whole:
            return whole
        return _parse_video_scenes(text)
    if kind in _graphic_scene_block_kinds():
        return _parse_graphic_scenes(text, kind)
    return []


def _parse_video_scenes(text: str) -> list[dict[str, Any]]:
    headers = list(_VIDEO_SCENE_HEADER_RE.finditer(text))
    if not headers:
        return []
    scenes: list[dict[str, Any]] = []
    seen_no: set[int] = set()
    for i, h in enumerate(headers):
        try:
            scene_no = int(h.group("no"))
        except (TypeError, ValueError):
            continue
        # 同 scene_no 多次出现（钩子变体也可能用"节点"），去重保第 1 次
        if scene_no in seen_no:
            continue
        seen_no.add(scene_no)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end]
        scene: dict[str, Any] = {
            "scene_no": scene_no,
            "name": (h.group("name") or "").strip() or None,
            "time_range": (h.group("time") or "").strip() or None,
        }
        # 老 6 字段（v10 / v11 都有）
        for field_key, regex in _VIDEO_FIELD_RES.items():
            m = regex.search(body)
            if m:
                value = m.group(1).strip().rstrip("- ").strip()
                # 去掉行尾的 markdown 表格分隔符等噪声
                value = re.sub(r"\s+", " ", value)
                if value:
                    scene[field_key] = value
        # phase D 新 3 字段（v11+ 才有；v10 解析不到，留空不阻塞）
        # characters_in_scene：[daughter, mother] → ['daughter', 'mother']
        m_chars = _VIDEO_FIELD_RES_PHASE_D["characters_in_scene"].search(body)
        if m_chars:
            raw = m_chars.group(1).strip()
            if raw:
                roles = [r.strip().strip("'\"") for r in re.split(r"[,，、/\s]+", raw) if r.strip()]
                scene["characters_in_scene"] = roles
            else:
                scene["characters_in_scene"] = []
        # product_appearance：true/false → bool
        m_prod = _VIDEO_FIELD_RES_PHASE_D["product_appearance"].search(body)
        if m_prod:
            v = m_prod.group(1).strip().lower()
            scene["product_appearance"] = v in ("true", "是")
        # image_prompt / last_frame_prompt / motion_prompt：自然语言长描述
        # 三套 prompt 同格式（**field**（描述）：内容多行可缩进），同流水线 strip + 压空白
        for _field in ("image_prompt", "last_frame_prompt", "motion_prompt"):
            m = _VIDEO_FIELD_RES_PHASE_D[_field].search(body)
            if not m:
                continue
            v = m.group(1).strip()
            # 去多余空白，但保留段落
            v = re.sub(r"\n\s+", " ", v)
            v = re.sub(r"\s+", " ", v).strip()
            if v:
                scene[_field] = v

        scenes.append(scene)
    # 按 scene_no 升序
    scenes.sort(key=lambda s: s["scene_no"])
    return scenes


# ════════════════════════════════════════════════════════════════
# character_sheet 段解析（W4-B 切片 14.4 phase D：脚本顶部锁脸清单）
# ════════════════════════════════════════════════════════════════

def parse_character_sheets_from_script_md(script_md: str) -> list[dict[str, Any]]:
    """从 script_md 第 3.5 部分提取角色清单。

    v12+ 新格式返回 [{role_id, name, age, gender, body_type, ethnicity, role, life_context,
                       personality, scene_type, realism_level, custom_imperfections,
                       audience_anchor}]。
    v11 旧格式兼容返回 [{role_id, name, age, gender, appearance_keywords, aura, audience_anchor}]。
    解析失败返 []，主流程不阻塞。
    """
    if not script_md or not script_md.strip():
        return []
    section_re = re.compile(r"^#{2,4}\s*第\s*3\.5\s*部分", re.M)
    end_re = re.compile(r"^#{2,4}\s*第\s*4\s*部分", re.M)
    sm = section_re.search(script_md)
    if not sm:
        return []
    em = end_re.search(script_md, pos=sm.end())
    text = script_md[sm.end():em.start() if em else len(script_md)]

    headers = list(_CHARACTER_HEADER_RE.finditer(text))
    if not headers:
        return []
    sheets: list[dict[str, Any]] = []
    seen_role: set[str] = set()
    for i, h in enumerate(headers):
        role_id = (h.group("role_id") or "").strip()
        if not role_id or role_id in seen_role:
            continue
        seen_role.add(role_id)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end]
        sheet: dict[str, Any] = {
            "role_id": role_id,
            "name": (h.group("name") or "").strip().lstrip("·").strip() or None,
        }
        for field_key, regex in _CHARACTER_FIELD_RES.items():
            m = regex.search(body)
            if m:
                value = m.group(1).strip().rstrip("- ").strip()
                value = re.sub(r"\s+", " ", value)
                # Strip parenthetical enum hints like （slim / average / sturdy / heavy）
                value = re.sub(r"[（(][^)）]{3,80}[)）]", "", value).strip()
                if value:
                    sheet[field_key] = value
        # custom_imperfections: extract bullet list under ** 专属瑕疵 **
        imp_m = _CUSTOM_IMPERFECTIONS_SECTION_RE.search(body)
        if imp_m:
            bullets_raw = imp_m.group(1)
            imperfections = [
                re.sub(r"^\s*-\s*", "", line).strip()
                for line in bullets_raw.splitlines()
                if line.strip().startswith("-")
            ]
            sheet["custom_imperfections"] = [x for x in imperfections if x]
        sheets.append(sheet)
    return sheets


def _parse_graphic_scenes(text: str, kind: str) -> list[dict[str, Any]]:
    headers = list(_GRAPHIC_SCENE_HEADER_RE.finditer(text))
    if not headers:
        return []
    scenes: list[dict[str, Any]] = []
    seen_no: set[int] = set()
    for i, h in enumerate(headers):
        try:
            scene_no = int(h.group("no"))
        except (TypeError, ValueError):
            continue
        if scene_no in seen_no:
            continue
        seen_no.add(scene_no)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end].strip()
        scenes.append({
            "scene_no": scene_no,
            "name": (h.group("name") or "").strip() or None,
            "visual": body[:1500],  # 整段做 visual prompt
        })
    scenes.sort(key=lambda s: s["scene_no"])
    return scenes


async def save_creative_pack(
    *,
    sku_id: str,
    kind: str,
    script_md: str,
    audience_record_id: str | None = None,
    audience_pack_id: str | None = None,
    audience_run_id: str | None = None,
    matrix_run_id: str | None = None,
    hooks: list | None = None,
    scenes: list | None = None,
    character_sheets: list | None = None,
    extra_context: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    portrait_id: str | None = None,
    intent: str | None = None,
    parent_script_id: str | None = None,
    notes: str | None = None,
    content_contract: dict | None = None,
) -> str | None:
    """落 1 行 pipeline.scripts，返回 id。失败返 None 不抛。

    弹性挂：record/pack/audience_run/matrix_run 都可空，但 sku_id 必填。
    kind 必须在 CREATIVE_KINDS 里。
    """
    if not script_md or not script_md.strip():
        logger.warning("save_creative_pack: script_md 空，跳过落库")
        return None
    if kind not in CREATIVE_KINDS:
        logger.warning("save_creative_pack: kind=%s 非法，跳过落库", kind)
        return None
    if content_contract is not None and not isinstance(content_contract, Mapping):
        logger.warning("save_creative_pack: content_contract 非映射，跳过落库")
        return None

    pool = get_pool()

    # 同 sku + kind 的 version 自增
    next_version = 1
    if parent_script_id:
        row = await pool.fetchrow(
            "SELECT version FROM pipeline.scripts WHERE id = $1::uuid",
            parent_script_id,
        )
        if row and row["version"]:
            next_version = int(row["version"]) + 1
    else:
        row = await pool.fetchrow(
            "SELECT MAX(version) AS v FROM pipeline.scripts WHERE sku_id = $1 AND kind = $2",
            sku_id, kind,
        )
        if row and row["v"]:
            next_version = int(row["v"]) + 1

    target_purpose = _KIND_TO_TARGET_PURPOSE.get(kind)

    # scenes 没显式传 → 自动从 script_md 解析（视频类拆"节点 N"，图文类拆"图/段 N"）
    if not scenes:
        try:
            scenes = parse_scenes_from_script_md(script_md, kind)
        except Exception as exc:
            logger.warning("parse_scenes_from_script_md failed (kind=%s): %s", kind, exc)
            scenes = []

    # character_sheets 没显式传 → 自动从 script_md 第 3.5 部分解析
    if not character_sheets:
        try:
            character_sheets = parse_character_sheets_from_script_md(script_md)
        except Exception as exc:
            logger.warning("parse_character_sheets_from_script_md failed: %s", exc)
            character_sheets = []

    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.scripts (
                audience_pack_id, audience_record_id, matrix_run_id, sku_id,
                script_md, hooks, scenes, character_sheets, target_purpose, kind,
                extra_context,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_script_id, portrait_id, intent, notes,
                content_contract
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4,
                $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10,
                $11,
                $12, $13, $14, $15,
                'draft', $16, $17::uuid, $18::uuid, $19, $20, $21::jsonb
            ) RETURNING id::text AS id
            """,
            audience_pack_id,
            audience_record_id,
            matrix_run_id,
            sku_id,
            script_md.strip(),
            json.dumps(hooks or [], ensure_ascii=False),
            json.dumps(scenes or [], ensure_ascii=False),
            json.dumps(character_sheets or [], ensure_ascii=False),
            target_purpose,
            kind,
            extra_context,
            model_provider,
            model,
            _prompt_hash(final_prompt) if final_prompt else None,
            cost_estimate,
            next_version,
            parent_script_id,
            portrait_id,
            intent,
            notes,
            json.dumps(dict(content_contract or {}), ensure_ascii=False),
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_creative_pack failed: %s", exc)
        return None


# ════════════════════════════════════════════════════════════════
# step 6 资产落库（W4-B 切片 14.4 phase D：分镜图/视频生成挂血缘）
# ════════════════════════════════════════════════════════════════

async def get_product_reference_by_file(file_ref: str) -> dict[str, Any] | None:
    """Return the active registered product reference for a canonical file."""

    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, sku_id, asset_type, file_url, status,
               script_id::text, experiment_arm_id::text,
               generation_set_id::text, created_at
        FROM pipeline.assets
        WHERE asset_type = 'product_reference'
          AND status <> 'discarded'
          AND file_url = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        file_ref,
    )
    return dict(row) if row else None


async def save_product_reference_asset(*, sku_id: str, file_ref: str) -> str | None:
    """Register one SKU-owned, adopted product image with no downstream owner."""

    pool = get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO pipeline.assets (
                sku_id, asset_type, file_url, status,
                script_id, experiment_arm_id, generation_set_id
            ) VALUES (
                $1, 'product_reference', $2, 'adopted',
                NULL, NULL, NULL
            )
            RETURNING id::text AS id
            """,
            sku_id,
            file_ref,
        )
        return row["id"] if row else None
    except Exception as exc:
        logger.exception("save_product_reference_asset failed: %s", exc)
        return None


async def get_product_reference_assets(asset_ids: list[str]) -> list[dict[str, Any]]:
    """Load registered references in the exact caller-supplied ID order."""

    if not asset_ids:
        return []
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id::text, sku_id, asset_type, file_url, status,
               script_id::text, experiment_arm_id::text,
               generation_set_id::text, created_at
        FROM pipeline.assets
        WHERE id = ANY($1::uuid[])
          AND asset_type = 'product_reference'
          AND status <> 'discarded'
        """,
        asset_ids,
    )
    by_id = {str(row["id"]): dict(row) for row in rows}
    return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]


async def save_storyboard_asset(
    *,
    sku_id: str,
    asset_type: str,                   # 'image' / 'video' / 'character_sheet'
    script_id: str | None = None,
    audience_pack_id: str | None = None,
    audience_record_id: str | None = None,
    matrix_run_id: str | None = None,
    scene_no: int | None = None,
    character_role: str | None = None,  # asset_type='character_sheet' 时填 daughter/mother 等
    file_url: str | None = None,
    thumbnail_url: str | None = None,
    prompt: str | None = None,
    duration_seconds: float | None = None,
    external_video_id: str | None = None,
    notes: str | None = None,
    persist_to_disk: bool = True,
    experiment_arm_id: str | None = None,
    experiment_id: str | None = None,
) -> str | None:
    """落 1 行 pipeline.assets（status='draft'），返 id。失败返 None 不抛。

    persist_to_disk=True（默认）：先把 file_url 转存到本地磁盘（解决 cdn 24h 过期）。
    落盘失败 fallback 用原 url（不挡链路）；notes 自动追加错误描述供复盘。
    """
    if asset_type not in ("image", "image_first", "image_last", "video", "character_sheet"):
        logger.warning("save_storyboard_asset: invalid asset_type=%s", asset_type)
        return None

    # W4-B 14.4 phase D 候选 D：cdn url 24h 过期 → 落本地磁盘
    if persist_to_disk and file_url:
        from app.services.asset_storage import persist_or_fallback
        new_url, persist_err = await persist_or_fallback(
            file_url, sku_id=sku_id, asset_type=asset_type,
        )
        file_url = new_url
        if persist_err:
            notes = (notes + " | " if notes else "") + f"persist_err={persist_err}"
    # thumbnail 同样转存（步骤数据量小，串行 OK）
    if persist_to_disk and thumbnail_url:
        from app.services.asset_storage import persist_or_fallback
        new_thumb, thumb_err = await persist_or_fallback(
            thumbnail_url, sku_id=sku_id, asset_type=asset_type,
        )
        thumbnail_url = new_thumb
        if thumb_err:
            notes = (notes + " | " if notes else "") + f"thumb_persist_err={thumb_err}"

    pool = get_pool()
    # 实验臂归属：只给了 arm 就反查 experiment_id denorm（AI 视频在 step7 自动挂臂，供视觉快环/北极星聚合）
    if experiment_arm_id and not experiment_id:
        _armrow = await pool.fetchrow(
            "SELECT experiment_id::text AS eid FROM pipeline.experiment_arms WHERE id = $1::uuid",
            experiment_arm_id,
        )
        if _armrow:
            experiment_id = _armrow["eid"]
    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.assets (
                script_id, audience_pack_id, audience_record_id, matrix_run_id, sku_id,
                asset_type, character_role,
                file_url, thumbnail_url, prompt,
                duration_seconds, scene_no, external_video_id,
                status, notes, experiment_id, experiment_arm_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5,
                $6, $7,
                $8, $9, $10,
                $11, $12, $13,
                'draft', $14, $15::uuid, $16::uuid
            ) RETURNING id::text AS id
            """,
            script_id,
            audience_pack_id,
            audience_record_id,
            matrix_run_id,
            sku_id,
            asset_type,
            character_role,
            file_url,
            thumbnail_url,
            prompt,
            duration_seconds,
            scene_no,
            external_video_id,
            notes,
            experiment_id,
            experiment_arm_id,
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_storyboard_asset failed: %s", exc)
        return None


async def list_character_sheets_for_script(
    script_id: str,
    experiment_arm_id: str | None = None,
) -> list[dict[str, Any]]:
    """拉同 script_id 的所有 character_sheet asset（按 character_role 字典序）。

    给 step 6 用：scene.characters_in_scene=['daughter','mother'] → 找对应 url 当 face_refs。
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id::text, sku_id, asset_type, script_id::text,
               character_role, file_url, status,
               experiment_arm_id::text, generation_set_id::text, created_at
        FROM pipeline.assets
        WHERE script_id = $1::uuid
          AND asset_type = 'character_sheet'
          AND ($2::uuid IS NULL OR experiment_arm_id = $2::uuid)
        ORDER BY character_role, created_at DESC
        """,
        script_id,
        experiment_arm_id,
    )
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


async def list_assets(
    *,
    sku_id: str | None = None,
    script_id: str | None = None,
    asset_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    pool = get_pool()
    where: list[str] = []
    params: list[Any] = []
    if sku_id:
        params.append(sku_id)
        where.append(f"sku_id = ${len(params)}")
    if script_id:
        params.append(script_id)
        where.append(f"script_id = ${len(params)}::uuid")
    if asset_type:
        params.append(asset_type)
        where.append(f"asset_type = ${len(params)}")
    params.append(limit)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = await pool.fetch(
        f"""
        SELECT id::text, script_id::text, audience_pack_id::text,
               audience_record_id::text, matrix_run_id::text, sku_id,
               asset_type, scene_no, file_url, thumbnail_url, prompt,
               duration_seconds, external_video_id, external_creative_id,
               status, notes, created_at
        FROM pipeline.assets
        {where_sql}
        ORDER BY scene_no NULLS LAST, created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


# ═══════════════════════════════════════════════════════
# 投后数据回传（phase D 闭环：测试投放后把 ad_metrics 写回血缘）
# ═══════════════════════════════════════════════════════

async def record_ad_metrics(
    *,
    asset_id: str | None = None,
    external_video_id: str | None = None,
    external_creative_id: str | None = None,
    metrics: dict[str, Any] | None = None,
    mark_published: bool = True,
    experiment_arm_id: str | None = None,
) -> dict[str, Any] | None:
    """投后回传：把广告数据合并进 pipeline.assets.ad_metrics。

    定位资产三选一（优先级 asset_id > external_video_id > external_creative_id）。
    可多次回传累积（如先回传 plays/ctr，几天后补 roi/gmv）。
    mark_published=True 时把非 discarded 资产状态推到 'published'。
    返回更新后 {asset_id, sku_id, status, ad_metrics, last_metrics_at}；定位不到返 None。

    入库校验（蓝图 §1.4 / §5 白名单 / R-4 拒手填 roi）：在**一个事务 + SELECT ... FOR UPDATE
    行锁**内读当前 ad_metrics → Python 累积合并 → **对合并后的全量做校验**（否则多次回传时上次
    标过 suspect 的 key 这次没带，_validation 会覆盖丢历史标记）→ 全量写回。FOR UPDATE 锁住该
    行，杜绝 SELECT-UPDATE 之间被并发回传覆盖（lost update）；恢复原 `||` 单步写的原子性。
    fail-open：不拒收任何 key，只把存疑/未知/手填roi 标进 _validation，分析层据此排除聚合。
    """
    metrics = metrics or {}
    pool = get_pool()

    where, val = None, None
    if asset_id:
        where, val = "id = $1::uuid", asset_id
    elif external_video_id:
        where, val = "external_video_id = $1", external_video_id
    elif external_creative_id:
        where, val = "external_creative_id = $1", external_creative_id
    elif not experiment_arm_id:
        logger.warning(
            "record_ad_metrics: 缺定位锚（asset_id / external_video_id / external_creative_id / experiment_arm_id 之一）"
        )
        return None

    from app.services.ad_metrics_validation import validate_ad_metrics
    _val_report: dict[str, Any] = {}
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = None
                if where:
                    existing = await conn.fetchrow(
                        f"SELECT id, ad_metrics FROM pipeline.assets WHERE {where} FOR UPDATE",
                        val,
                    )
                # 真人编导拍的视频没有 asset 行：给了 experiment_arm_id 又没定位到 →
                # 在该臂下自动建一条 video 资产（asset_type CHECK 只允许 image/video），
                # 让人工链的投后数据也能挂进实验臂、进 v_experiment_round_results 聚合。
                if not existing and experiment_arm_id:
                    arm = await conn.fetchrow(
                        "SELECT sku_id, script_id::text AS script_id, experiment_id::text AS eid "
                        "FROM pipeline.experiment_arms WHERE id = $1::uuid",
                        experiment_arm_id,
                    )
                    if arm:
                        existing = await conn.fetchrow(
                            "INSERT INTO pipeline.assets "
                            "(sku_id, asset_type, status, external_video_id, script_id, "
                            " experiment_id, experiment_arm_id, ad_metrics) "
                            "VALUES ($1,'video','published',$2,$3::uuid,$4::uuid,$5::uuid,'{}'::jsonb) "
                            "RETURNING id, ad_metrics",
                            arm["sku_id"], external_video_id, arm["script_id"], arm["eid"], experiment_arm_id,
                        )
                if not existing:
                    return None
                current = _coerce_jsonb_dict(existing["ad_metrics"]) or {}
                current.pop("_validation", None)        # 剔旧校验元数据，不当指标参与重校验
                merged = {**current, **metrics}          # 累积合并（保留可多次回传语义）
                _val_report = validate_ad_metrics(merged)  # 校验全量 → _validation 反映所有累积 key
                merged["_validation"] = _val_report
                rec = await conn.fetchrow(
                    """
                    UPDATE pipeline.assets
                       SET ad_metrics = $2::jsonb,
                           last_metrics_at = NOW(),
                           status = CASE
                               WHEN $3::bool AND status <> 'discarded' THEN 'published'
                               ELSE status
                           END
                     WHERE id = $1
                    RETURNING id::text AS asset_id, sku_id, status,
                              ad_metrics, last_metrics_at
                    """,
                    existing["id"], json.dumps(merged), mark_published,
                )
                # 编导 brief A/B 闭环：把这条 asset 挂到实验臂（denorm experiment_id）
                if experiment_arm_id and rec:
                    armrow = await conn.fetchrow(
                        "SELECT experiment_id::text AS eid FROM pipeline.experiment_arms WHERE id = $1::uuid",
                        experiment_arm_id,
                    )
                    if armrow:
                        await conn.execute(
                            "UPDATE pipeline.assets SET experiment_arm_id = $2::uuid, "
                            "experiment_id = $3::uuid WHERE id = $1",
                            existing["id"], experiment_arm_id, armrow["eid"],
                        )
    except Exception as exc:
        logger.exception("record_ad_metrics failed: %s", exc)
        return None
    if not rec:
        return None
    d = dict(rec)
    d["ad_metrics"] = _coerce_jsonb_dict(d.get("ad_metrics"))
    if d.get("last_metrics_at"):
        d["last_metrics_at"] = d["last_metrics_at"].isoformat()
    # 把校验结论也回给调用方（agent/老板能立刻看到哪些 key 被标存疑、为什么）
    d["validation"] = _val_report
    return d


# ── 巨量素材报表 CSV 整轮回灌（内容版本迭代闭环·块0a）─────────────────────────────
# 常见表头 → ad_metrics key（默认映射，column_map 可覆盖/补充）。
_BATCH_DEFAULT_METRIC_MAP: dict[str, str] = {
    "完播率": "completion_rate", "5s完播率": "play_5s_rate", "3s完播率": "play_3s_rate",
    "转化率": "cvr", "点击率": "ctr",
    "展示数": "impressions", "展示量": "impressions", "曝光数": "impressions",
    "曝光量": "impressions", "封面曝光数": "impressions", "封面展示数": "impressions", "封面展现量": "impressions",
    "播放数": "plays", "播放量": "plays", "视频播放数": "plays",
    "点击数": "clicks",
    "转化数": "conversions", "成交订单数": "orders", "直接成交订单数": "direct_orders",
    "消耗": "spend", "花费": "spend", "总花费": "spend",
    "成交金额": "gmv", "直接成交金额": "direct_pay_amount", "支付金额": "gmv_paid",
    "点赞数": "likes", "评论数": "comments", "分享数": "shares",
    "新增粉丝数": "new_followers", "涨粉数": "new_followers",
}
_BATCH_NAME_COLS = ("素材名称", "视频名称", "素材名", "视频名", "creative_name", "素材", "视频")
_BATCH_ID_COLS = ("视频ID", "素材ID", "视频id", "素材id", "video_id", "creative_id", "广告ID", "计划ID")


async def record_ad_metrics_batch(
    *,
    experiment_id: str,
    csv_text: str | None = None,
    csv_path: str | None = None,
    name_column: str | None = None,
    id_column: str | None = None,
    column_map: dict[str, str] | None = None,
    round_no: int | None = None,
    mark_published: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """整轮 CSV 回灌：巨量素材报表（一行一条视频）按臂码匹配到实验臂，逐行写投后数据。

    匹配：每臂派生臂码 R{round}{label}（如 R2B），跟 name_column 列做大小写无关子串匹配；
    匹配不到再退而用 variable_value 子串。命中后调 record_ad_metrics(experiment_arm_id=臂)
    逐行落库（有 id_column 则带 external_video_id，重复导入按它去重不产生重复 asset）。
    dry_run=True 只返匹配预览不写库（先看匹配对不对再真写）。
    """
    import csv as _csv
    import io as _io

    pool = get_pool()
    exp = await pool.fetchrow(
        "SELECT id::text AS id, sku_id FROM pipeline.experiments WHERE id=$1::uuid", experiment_id)
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}

    if round_no is not None:
        arm_rows = await pool.fetch(
            "SELECT id::text AS arm_id, round_no, arm_label, variable_value, swept_variable "
            "FROM pipeline.experiment_arms WHERE experiment_id=$1::uuid AND round_no=$2 "
            "ORDER BY round_no, arm_label", experiment_id, round_no)
    else:
        arm_rows = await pool.fetch(
            "SELECT id::text AS arm_id, round_no, arm_label, variable_value, swept_variable "
            "FROM pipeline.experiment_arms WHERE experiment_id=$1::uuid "
            "ORDER BY round_no, arm_label", experiment_id)
    if not arm_rows:
        return {"ok": False, "error": "no_arms",
                "hint": "该实验（或该轮）还没挂臂——先 experiment_attach_arm / experiment_register_round"}
    arms = [dict(r) for r in arm_rows]
    for a in arms:
        a["arm_code"] = f"R{a['round_no']}{a['arm_label']}"

    # 读 CSV 文本（path 优先 utf-8-sig，再 gb18030；巨量导出常见这两种）
    text = csv_text
    if text is None:
        if not csv_path:
            return {"ok": False, "error": "missing_csv", "hint": "传 csv_text 或 csv_path"}
        try:
            with open(csv_path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return {"ok": False, "error": "csv_path_not_found", "csv_path": csv_path}
        for enc in ("utf-8-sig", "gb18030", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return {"ok": False, "error": "csv_decode_failed", "hint": "试试另存为 UTF-8 CSV"}

    try:
        reader = _csv.DictReader(_io.StringIO(text))
        headers = [h.strip() for h in (reader.fieldnames or [])]
    except Exception as exc:
        return {"ok": False, "error": "csv_parse_failed", "detail": str(exc)}
    if not headers:
        return {"ok": False, "error": "csv_empty"}

    def _pick(cands: tuple[str, ...]) -> str | None:
        return next((h for h in headers if h in cands), None)

    name_col = name_column or _pick(_BATCH_NAME_COLS)
    id_col = id_column or _pick(_BATCH_ID_COLS)
    if not name_col:
        return {"ok": False, "error": "name_column_not_found",
                "hint": f"找不到素材名列，显式传 name_column；现有表头={headers}"}

    metric_map = {**_BATCH_DEFAULT_METRIC_MAP, **(column_map or {})}
    active_metric_cols = {h: metric_map[h] for h in headers if h in metric_map}
    if not active_metric_cols:
        return {"ok": False, "error": "no_metric_columns",
                "hint": f"表头里没认出任何指标列，用 column_map 显式映射；现有表头={headers}"}

    matched, unmatched, ambiguous = [], [], []
    applied = 0
    rows = list(reader)
    for idx, r in enumerate(rows):
        row = {(k.strip() if k else k): v for k, v in r.items()}
        name_val = (row.get(name_col) or "").strip()
        if not name_val:
            continue
        low = name_val.lower()
        hits = [a for a in arms if a["arm_code"].lower() in low]
        if not hits:
            hits = [a for a in arms if a["variable_value"] and a["variable_value"] in name_val]
        if not hits:
            unmatched.append({"row": idx + 1, "name": name_val})
            continue
        if len(hits) > 1:
            ambiguous.append({"row": idx + 1, "name": name_val,
                              "candidates": [a["arm_code"] for a in hits]})
            continue
        arm = hits[0]
        metrics = {key: row[h].strip() for h, key in active_metric_cols.items()
                   if (row.get(h) or "").strip() != ""}
        ext_vid = (row.get(id_col) or "").strip() if id_col else None
        rec = {"row": idx + 1, "name": name_val, "arm_code": arm["arm_code"],
               "arm_id": arm["arm_id"], "metrics": metrics,
               "has_impressions": "impressions" in metrics,
               "external_video_id": ext_vid or None}
        if not metrics:
            rec["skipped"] = "row_has_no_metric_values"
            matched.append(rec)
            continue
        if not dry_run:
            asset = await record_ad_metrics(
                metrics=metrics, experiment_arm_id=arm["arm_id"],
                external_video_id=ext_vid or None, mark_published=mark_published)
            rec["written"] = bool(asset)
            if asset:
                rec["asset_id"] = asset.get("asset_id")
                applied += 1
        matched.append(rec)

    n_missing_imp = sum(1 for m in matched if not m["has_impressions"] and not m.get("skipped"))
    warnings: list[str] = []
    if n_missing_imp:
        warnings.append(f"⚠ {n_missing_imp} 条匹配上但没带曝光量(impressions)——补上才能判 winner 可不可信。")
    if unmatched:
        warnings.append(f"⚠ {len(unmatched)} 行没匹配到臂（臂码没写进素材名？）——见 unmatched，改名/补 column 后重导。")
    if ambiguous:
        warnings.append(f"⚠ {len(ambiguous)} 行匹配到多个臂——见 ambiguous，手动消歧。")
    if not id_col and not dry_run:
        warnings.append("⚠ 没找到视频ID列——本次每行新建 asset，重复导入同一份会产生重复行（建议加 id_column 或别重导）。")

    return {
        "ok": True,
        "dry_run": dry_run,
        "experiment_id": experiment_id,
        "columns": {"name_column": name_col, "id_column": id_col,
                    "metric_columns": active_metric_cols},
        "summary": {"rows": len(rows), "matched": len(matched), "applied": applied,
                    "unmatched": len(unmatched), "ambiguous": len(ambiguous),
                    "missing_impressions": n_missing_imp},
        "matched": matched, "unmatched": unmatched, "ambiguous": ambiguous,
        "warnings": warnings,
        "next_step_hint": (
            "dry_run=True 是预览——确认匹配无误后 record_ad_metrics_batch(..., dry_run=False) 真写库。"
            if dry_run else
            f"已写 {applied} 条投后数据进各臂。experiment_status(experiment_id) 看排名 + 曝光量是否均衡。"
        ),
    }


async def get_asset_lineage(asset_id: str) -> dict[str, Any] | None:
    """按 asset_id 一句 SELECT 反查全链路（SKU/卖点矩阵/人群/圈包/脚本 + 投后 ad_metrics）。"""
    pool = get_pool()
    try:
        rec = await pool.fetchrow(
            "SELECT * FROM pipeline.v_asset_full_lineage WHERE asset_id = $1::uuid",
            asset_id,
        )
    except Exception as exc:
        logger.exception("get_asset_lineage failed: %s", exc)
        return None
    if not rec:
        return None
    d = dict(rec)
    d["ad_metrics"] = _coerce_jsonb_dict(d.get("ad_metrics"))
    if d.get("asset_created_at"):
        d["asset_created_at"] = d["asset_created_at"].isoformat()
    for k in ("asset_id", "script_id", "audience_pack_id", "audience_record_id",
              "audience_run_id", "matrix_run_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d


async def list_asset_performance(
    *, sku_id: str | None = None, limit: int = 50,
) -> list[dict[str, Any]]:
    """列已回传投后数据的资产（ad_metrics 非空），按 last_metrics_at 倒序。

    给"哪套卖点+人群+脚本真带货"复盘用——配合 get_asset_lineage 反查具体链路。
    """
    pool = get_pool()
    where = ["a.ad_metrics <> '{}'::jsonb"]
    params: list[Any] = []
    if sku_id:
        params.append(sku_id)
        where.append(f"a.sku_id = ${len(params)}")
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT a.id::text AS asset_id, a.sku_id, a.asset_type, a.file_url,
               a.ad_metrics, a.status, a.last_metrics_at,
               a.script_id::text AS script_id,
               a.audience_record_id::text AS audience_record_id,
               a.matrix_run_id::text AS matrix_run_id
        FROM pipeline.assets a
        WHERE {" AND ".join(where)}
        ORDER BY a.last_metrics_at DESC NULLS LAST
        LIMIT ${len(params)}
        """,
        *params,
    )
    out = []
    for r in rows:
        d = dict(r)
        d["ad_metrics"] = _coerce_jsonb_dict(d.get("ad_metrics"))
        if d.get("last_metrics_at"):
            d["last_metrics_at"] = d["last_metrics_at"].isoformat()
        out.append(d)
    return out


# ═══════════════════════════════════════════════════════
# Lineage context enrichment (step 6 / 6.5 / 7 injection)
# ═══════════════════════════════════════════════════════

def _parse_audience_content_prefs(raw_md: str) -> list[str]:
    m = re.search(r"爱看短剧类型[：:]\s*([^\n]+)", raw_md)
    if not m:
        return []
    return [x.strip() for x in re.split(r"[、，,/]", m.group(1)) if x.strip()]


def _parse_audience_persona_line(raw_md: str) -> str:
    m = re.search(r"###\s*【[^】]+】\s*\n([^\n]+)", raw_md)
    return m.group(1).strip() if m else ""


def _parse_matrix_top_points(matrix_md: str) -> list[dict]:
    """Extract top selling points from matrix_md '第1部分 显性卖点' section."""
    points: list[dict] = []
    for m in re.finditer(
        r"####\s*(1\.\d+)\s+\*\*([^*\n]+)\*\*", matrix_md
    ):
        sid = m.group(1).strip()
        name = m.group(2).strip()
        # Try to grab 核心关键词 within next 800 chars
        snippet = matrix_md[m.start():m.start() + 800]
        kw_m = re.search(r"核心关键词[：:]\s*([^\n]+)", snippet)
        keywords: list[str] = []
        if kw_m:
            keywords = [k.strip() for k in kw_m.group(1).split("、") if k.strip()][:4]
        scene_m = re.search(r"匹配场景[：:]\s*([^\n]+)", snippet)
        scenes_str = scene_m.group(1).strip() if scene_m else ""
        points.append({"id": sid, "name": name, "keywords": keywords, "scenes": scenes_str})
        if len(points) >= 5:
            break
    return points


def _parse_matrix_product_profile(matrix_md: str) -> str:
    m = re.search(r"第\s*0\s*部分[·・\s]+产品档案速写\s*\n+([\s\S]+?)(?=\n---|\n###|\Z)", matrix_md)
    return m.group(1).strip()[:500] if m else ""


async def gather_lineage_context(script: dict) -> dict:
    """Pull SKU + audience_record + matrix_run for a script.

    Returns structured dict injected into step 6/6.5/7 prompt builders.
    Non-blocking: missing IDs → empty sections, never raises.
    """
    pool = get_pool()
    ctx: dict[str, Any] = {}
    try:
        sku_id = script.get("sku_id")
        if sku_id:
            row = await pool.fetchrow(
                "SELECT name, price_min, specifications, owner_selling_points "
                "FROM mvp_sku WHERE id = $1",
                sku_id,
            )
            if row:
                raw_sps = row["owner_selling_points"]
                sps_list = json.loads(raw_sps) if isinstance(raw_sps, str) else (raw_sps or [])
                ctx["sku_name"] = row["name"] or ""
                ctx["sku_price"] = str(row["price_min"]) if row["price_min"] else ""
                ctx["sku_specs"] = row["specifications"] or ""
                ctx["sku_selling_points"] = [s["text"] for s in sps_list if isinstance(s, dict) and s.get("text")]
    except Exception as e:
        logger.warning("gather_lineage_context: sku fetch failed: %s", e)

    try:
        ar_id = script.get("audience_record_id")
        if ar_id:
            row = await pool.fetchrow(
                "SELECT name, raw_md_segment, layer_tags, match_reasons "
                "FROM pipeline.audience_records WHERE id = $1::uuid",
                ar_id,
            )
            if row:
                raw = row["raw_md_segment"] or ""
                ctx["audience_name"] = row["name"] or ""
                raw_tags = row["layer_tags"]
                ctx["audience_layer_tags"] = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
                ctx["audience_content_prefs"] = _parse_audience_content_prefs(raw)
                ctx["audience_persona"] = _parse_audience_persona_line(raw)
                ctx["audience_raw_snippet"] = raw[:1000]
    except Exception as e:
        logger.warning("gather_lineage_context: audience_record fetch failed: %s", e)

    try:
        mr_id = script.get("matrix_run_id")
        if mr_id:
            row = await pool.fetchrow(
                "SELECT matrix_md FROM pipeline.matrix_runs WHERE id = $1::uuid",
                mr_id,
            )
            if row:
                mmd = row["matrix_md"] or ""
                ctx["matrix_top_points"] = _parse_matrix_top_points(mmd)
                ctx["matrix_product_profile"] = _parse_matrix_product_profile(mmd)
    except Exception as e:
        logger.warning("gather_lineage_context: matrix_run fetch failed: %s", e)

    return ctx


def build_product_visual_anchor(ctx: dict) -> str:
    """Translate lineage context → concise visual description for image/video prompts.

    Uses sku_selling_points to derive material/texture/label cues only.
    Strips non-visual business language (工厂年份/认证机构 names etc).
    """
    sps = ctx.get("sku_selling_points", [])
    specs = ctx.get("sku_specs", "")
    parts: list[str] = []

    # Material cues
    if any("玻璃" in s for s in sps):
        parts.append("dark glass bottle")
    if any("瓶" in s for s in sps) and not parts:
        parts.append("sauce bottle")

    # Liquid visual
    sku_name = ctx.get("sku_name", "").lower()
    if "酱油" in sku_name or "soy" in sku_name:
        parts.append("deep amber-brown viscous soy sauce")
    elif "醋" in sku_name or "vinegar" in sku_name:
        parts.append("dark rice vinegar, translucent amber liquid")
    elif "辣" in sku_name:
        parts.append("deep red chili sauce")

    # Label aesthetic cues
    if any("日式" in s or "日本" in s for s in sps):
        parts.append("Japanese-style label with clean calligraphy typography")
    if any("有机" in s for s in sps):
        parts.append("organic certification seal visible on label")
    if any("零添加" in s or "无添加" in s for s in sps):
        parts.append("minimal clean ingredient label design")

    # Size
    if specs:
        parts.append(f"packaging: {specs}")

    return ", ".join(parts) if parts else ""


def build_audience_visual_hint(ctx: dict) -> str:
    """Translate audience_record data → visual atmosphere hint for image/video."""
    parts: list[str] = []
    prefs = ctx.get("audience_content_prefs", [])
    tags = ctx.get("audience_layer_tags", [])
    persona = ctx.get("audience_persona", "")

    if any(p in ("家庭伦理", "年代", "婆媳", "代际") for p in prefs):
        parts.append("warm domestic atmosphere, multi-generational family context")
    elif any(p in ("都市情感", "爱情") for p in prefs):
        parts.append("urban modern lifestyle setting, couple or friendship context")
    elif any(p in ("悬疑", "都市奇遇") for p in prefs):
        parts.append("slightly dramatic lighting, modern urban environment")

    if any("银发" in str(t) for t in tags):
        parts.append("elderly-friendly warm color palette, unhurried pace")
    if any("短剧" in str(t) for t in tags):
        parts.append("short-video aesthetic, direct visual impact")

    return ", ".join(parts) if parts else ""


def build_selling_point_motion_hint(ctx: dict, scene_no: int = 1) -> str:
    """For step 7 video: translate top selling points → motion/demonstration cues."""
    points = ctx.get("matrix_top_points", [])
    if not points:
        return ""
    # Rotate through top 2 points by scene number
    pt = points[(scene_no - 1) % min(len(points), 2)]
    name = pt["name"]
    keywords = pt.get("keywords", [])
    visual_kws = [k for k in keywords if any(c in k for c in ["色", "香", "感", "质", "纹", "光"])]
    if visual_kws:
        return f"visual emphasis: {name} — {', '.join(visual_kws[:2])}"
    return f"visual emphasis: {name}"


async def backfill_scenes_for_existing_scripts(force_reparse: bool = False) -> dict[str, Any]:
    """一次性回填：按 kind 重解析 pipeline.scripts.script_md 写 scenes/character_sheets。

    默认只补 scenes=[] 或 character_sheets=[] 的（首跑 phase D 用）；
    force_reparse=True 时扫所有非空 script_md，把历史 v11+ 脚本里
    新加的 last_frame_prompt / motion_prompt 等字段重新解析进 scenes JSONB。

    返 {scanned, scripts_updated, scenes_parsed_total, character_sheets_parsed_total, by_kind}。
    """
    pool = get_pool()
    where_clause = (
        "WHERE script_md IS NOT NULL AND script_md != ''"
        if force_reparse
        else """WHERE (scenes::text = '[]' OR character_sheets::text = '[]')
          AND script_md IS NOT NULL AND script_md != ''"""
    )
    rows = await pool.fetch(f"SELECT id::text AS id, kind, script_md FROM pipeline.scripts {where_clause}")
    scanned = len(rows)
    scenes_total = 0
    sheets_total = 0
    updated_total = 0
    per_kind: dict[str, int] = {}
    for r in rows:
        try:
            scenes = parse_scenes_from_script_md(r["script_md"], r["kind"])
        except Exception as exc:
            logger.warning("backfill: parse_scenes failed id=%s kind=%s: %s", r["id"], r["kind"], exc)
            scenes = []
        try:
            sheets = parse_character_sheets_from_script_md(r["script_md"])
        except Exception as exc:
            logger.warning("backfill: parse_character_sheets failed id=%s: %s", r["id"], exc)
            sheets = []
        if not scenes and not sheets:
            continue
        scenes_total += len(scenes)
        sheets_total += len(sheets)
        await pool.execute(
            "UPDATE pipeline.scripts SET scenes = $1::jsonb, character_sheets = $2::jsonb WHERE id = $3::uuid",
            json.dumps(scenes, ensure_ascii=False),
            json.dumps(sheets, ensure_ascii=False),
            r["id"],
        )
        updated_total += 1
        per_kind[r["kind"]] = per_kind.get(r["kind"], 0) + 1
    return {
        "ok": True,
        "scanned": scanned,
        "scripts_updated": updated_total,
        "scenes_parsed_total": scenes_total,
        "character_sheets_parsed_total": sheets_total,
        "by_kind": per_kind,
    }


async def list_creative_packs(
    sku_id: str | None = None,
    kind: str | None = None,
    audience_record_id: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    pool = get_pool()
    where = []
    params: list[Any] = []
    if sku_id:
        params.append(sku_id)
        where.append(f"sku_id = ${len(params)}")
    if kind:
        params.append(kind)
        where.append(f"kind = ${len(params)}")
    if audience_record_id:
        params.append(audience_record_id)
        where.append(f"audience_record_id = ${len(params)}::uuid")
    params.append(limit)
    where_sql = "WHERE " + " AND ".join(where) if where else ""

    rows = await pool.fetch(
        f"""
        SELECT id::text, sku_id, kind, audience_record_id::text, audience_pack_id::text,
               matrix_run_id::text, version, status, target_purpose,
               model_provider, model, content_contract, created_at, parent_script_id::text
        FROM pipeline.scripts
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    result = []
    for row in rows:
        item = dict(row)
        item["content_contract"] = _coerce_jsonb_dict(item.get("content_contract"))
        result.append(item)
    return result


async def get_creative_pack(script_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, sku_id, kind, audience_record_id::text, audience_pack_id::text,
               matrix_run_id::text, script_md, hooks, scenes, character_sheets,
               target_purpose,
               extra_context, model_provider, model, version, status,
               parent_script_id::text, portrait_id::text, intent, notes, content_contract,
               created_at, updated_at
        FROM pipeline.scripts
        WHERE id = $1::uuid
        """,
        script_id,
    )
    if not row:
        return None
    d = dict(row)
    d["hooks"] = _coerce_jsonb_list(d.get("hooks"))
    d["scenes"] = _coerce_jsonb_list(d.get("scenes"))
    d["character_sheets"] = _coerce_jsonb_list(d.get("character_sheets"))
    d["content_contract"] = _coerce_jsonb_dict(d.get("content_contract"))
    return d


# ════════════════════════════════════════════════════════════════
# 全血缘聚合（W4-B 切片 14.4 phase C v3：血缘图前端用）
# ════════════════════════════════════════════════════════════════

async def get_sku_lineage(sku_id: str, *, limit_per_table: int = 100, include_archived: bool = False, hide_draft_videos: bool = True) -> dict[str, Any]:
    """串某 SKU 的全血缘嵌套树，给前端血缘图用。

    返回 6 张表的嵌套：matrix_runs → audience_runs → audience_records
      → audience_packs → scripts；assets 单独列（phase D 起填，当前可能空）。

    默认行为：
    - 隐藏 status='archived'；include_archived=True 时全返
    - 隐藏 asset_type='video' AND status='draft'（step 7 跑过没采纳的视频段不挤血缘图）；
      hide_draft_videos=False 时也返

    实现：6 个 query 按 sku_id 一次拉全，Python 内存按 FK 嵌套（避免 N+1）。
    """
    pool = get_pool()
    # 默认隐藏 archived；老板想看已归档时传 include_archived=True
    arch_filter = "" if include_archived else " AND status != 'archived'"
    # 默认隐藏 draft video asset（草稿视频段不挤血缘）；只对 asset 查询生效
    draft_video_filter = "" if not hide_draft_videos else " AND NOT (asset_type = 'video' AND status = 'draft')"

    matrix_rows = await pool.fetch(
        f"""
        SELECT id::text, sku_id, version, status, model_provider, model,
               created_at, parent_run_id::text
        FROM pipeline.matrix_runs
        WHERE sku_id = $1{arch_filter}
        ORDER BY created_at DESC
        LIMIT $2
        """,
        sku_id, limit_per_table,
    )
    arun_rows = await pool.fetch(
        f"""
        SELECT id::text, matrix_run_id::text, sku_id, version, status,
               record_count, model_provider, model, created_at, parent_run_id::text
        FROM pipeline.audience_runs
        WHERE sku_id = $1{arch_filter}
        ORDER BY created_at DESC
        LIMIT $2
        """,
        sku_id, limit_per_table,
    )
    arec_rows = await pool.fetch(
        f"""
        SELECT id::text, audience_run_id::text, matrix_run_id::text, sku_id,
               ordinal, name, kb_doc, layer_tags, status, selected_for_pack,
               created_at
        FROM pipeline.audience_records
        WHERE sku_id = $1{arch_filter}
        ORDER BY audience_run_id, ordinal
        LIMIT $2
        """,
        sku_id, limit_per_table * 5,  # records 拆 N 倍多
    )
    pack_rows = await pool.fetch(
        f"""
        SELECT id::text, audience_record_id::text, audience_run_id::text,
               matrix_run_id::text, sku_id, version, status,
               model_provider, model, created_at, parent_pack_id::text
        FROM pipeline.audience_packs
        WHERE sku_id = $1{arch_filter}
        ORDER BY created_at DESC
        LIMIT $2
        """,
        sku_id, limit_per_table,
    )
    script_rows = await pool.fetch(
        f"""
        SELECT id::text, audience_pack_id::text, audience_record_id::text,
               matrix_run_id::text, sku_id, kind, version, status, target_purpose,
               model_provider, model, created_at, parent_script_id::text
        FROM pipeline.scripts
        WHERE sku_id = $1{arch_filter}
        ORDER BY created_at DESC
        LIMIT $2
        """,
        sku_id, limit_per_table,
    )
    asset_rows = await pool.fetch(
        f"""
        SELECT id::text, script_id::text, audience_pack_id::text,
               audience_record_id::text, matrix_run_id::text, sku_id,
               asset_type, scene_no, file_url, thumbnail_url,
               external_video_id, external_creative_id, status, created_at
        FROM pipeline.assets
        WHERE sku_id = $1{arch_filter}{draft_video_filter}
        ORDER BY created_at DESC
        LIMIT $2
        """,
        sku_id, limit_per_table,
    )

    # ── 转 dict + 处理 JSONB ───────────────────────────────────
    def _row(r) -> dict:
        d = dict(r)
        if "layer_tags" in d:
            d["layer_tags"] = _coerce_jsonb_list(d.get("layer_tags"))
        if "created_at" in d and d["created_at"]:
            d["created_at"] = d["created_at"].isoformat()
        return d

    matrix_list = [_row(r) for r in matrix_rows]
    arun_list = [_row(r) for r in arun_rows]
    arec_list = [_row(r) for r in arec_rows]
    pack_list = [_row(r) for r in pack_rows]
    script_list = [_row(r) for r in script_rows]
    asset_list = [_row(r) for r in asset_rows]

    # ── 按 FK 嵌套（自下而上） ────────────────────────────────
    # assets 挂 script
    assets_by_script: dict[str, list[dict]] = {}
    orphan_assets: list[dict] = []
    for a in asset_list:
        if a.get("script_id"):
            assets_by_script.setdefault(a["script_id"], []).append(a)
        else:
            orphan_assets.append(a)

    # scripts 挂 pack 或 record（pack 优先，record 次之，sku 兜底）
    scripts_by_pack: dict[str, list[dict]] = {}
    scripts_by_record: dict[str, list[dict]] = {}
    orphan_scripts: list[dict] = []  # 没挂 pack 也没挂 record（sku 模式直跑）
    for s in script_list:
        s["assets"] = assets_by_script.get(s["id"], [])
        if s.get("audience_pack_id"):
            scripts_by_pack.setdefault(s["audience_pack_id"], []).append(s)
        elif s.get("audience_record_id"):
            scripts_by_record.setdefault(s["audience_record_id"], []).append(s)
        else:
            orphan_scripts.append(s)

    # packs 挂 record
    packs_by_record: dict[str, list[dict]] = {}
    orphan_packs: list[dict] = []
    for p in pack_list:
        p["scripts"] = scripts_by_pack.get(p["id"], [])
        if p.get("audience_record_id"):
            packs_by_record.setdefault(p["audience_record_id"], []).append(p)
        else:
            orphan_packs.append(p)

    # records 挂 audience_run
    records_by_arun: dict[str, list[dict]] = {}
    for r in arec_list:
        # record 节点下挂 packs；scripts 走 pack（如果没经 pack 直接挂 record，走 scripts_by_record）
        r["audience_packs"] = packs_by_record.get(r["id"], [])
        r["scripts_direct"] = scripts_by_record.get(r["id"], [])  # 绕过 pack 直接挂 record 的脚本
        if r.get("audience_run_id"):
            records_by_arun.setdefault(r["audience_run_id"], []).append(r)

    # audience_runs 挂 matrix_run
    aruns_by_matrix: dict[str, list[dict]] = {}
    for ar in arun_list:
        ar["audience_records"] = records_by_arun.get(ar["id"], [])
        if ar.get("matrix_run_id"):
            aruns_by_matrix.setdefault(ar["matrix_run_id"], []).append(ar)

    # matrix_runs 顶层
    for m in matrix_list:
        m["audience_runs"] = aruns_by_matrix.get(m["id"], [])

    return {
        "ok": True,
        "sku_id": sku_id,
        "matrix_runs": matrix_list,
        "orphan_packs": orphan_packs,
        "orphan_scripts": orphan_scripts,
        "orphan_assets": orphan_assets,
        "counts": {
            "matrix_runs": len(matrix_list),
            "audience_runs": len(arun_list),
            "audience_records": len(arec_list),
            "audience_packs": len(pack_list),
            "scripts": len(script_list),
            "assets": len(asset_list),
        },
    }


async def archive_node(table: str, run_id: str) -> dict[str, Any]:
    """归档节点：status='archived'，从血缘图默认视图隐藏（include_archived=True 才显示）。

    软删除（可恢复）：data 保留，外键引用不破坏；后续可手动 UPDATE status='draft' 恢复。

    table 在 {matrix_runs, audience_runs, audience_records, audience_packs, scripts, assets, keyword_packs}.
    """
    if table not in {"matrix_runs", "audience_runs", "audience_records", "audience_packs", "scripts", "assets", "keyword_packs", "audience_portraits"}:
        return {"ok": False, "error": f"未知 table: {table}"}
    pool = get_pool()
    sql = (
        f"UPDATE pipeline.{table} SET status='archived' "
        "WHERE id = $1::uuid AND status != 'archived' "
        "RETURNING id::text, status"
    )
    row = await pool.fetchrow(sql, run_id)
    if not row:
        return {"ok": False, "error": "not_found_or_already_archived", "run_id": run_id}
    return {"ok": True, **dict(row)}


async def adopt_run(table: str, run_id: str, *, set_selected: bool = False) -> dict[str, Any]:
    """把 status 从 draft 改 adopted。table 在 {matrix_runs, audience_runs, audience_records, audience_packs, scripts, assets, audience_portraits}。

    audience_records 额外可选 set_selected_for_pack=TRUE。
    """
    if table not in {"matrix_runs", "audience_runs", "audience_records", "audience_packs", "scripts", "assets", "audience_portraits"}:
        return {"ok": False, "error": f"未知 table: {table}"}

    pool = get_pool()

    if table == "audience_records" and set_selected:
        sql = (
            f"UPDATE pipeline.{table} "
            "SET status='adopted', selected_for_pack=TRUE "
            "WHERE id = $1::uuid AND status != 'archived' "
            "RETURNING id::text, status, selected_for_pack"
        )
    else:
        sql = (
            f"UPDATE pipeline.{table} "
            "SET status='adopted' "
            "WHERE id = $1::uuid AND status != 'archived' "
            f"RETURNING id::text, status"
            + (", selected_for_pack" if table == "audience_records" else "")
        )
    row = await pool.fetchrow(sql, run_id)
    if not row:
        return {"ok": False, "error": "not_found_or_archived", "run_id": run_id}
    return {"ok": True, **dict(row)}
