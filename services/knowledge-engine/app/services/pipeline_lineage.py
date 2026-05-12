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
    if isinstance(v, dict):
        return v
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
# step 5 创意素材落库（W4-B 切片 14.4 phase C，6 类素材入 pipeline.scripts）
# ════════════════════════════════════════════════════════════════

CREATIVE_KINDS = (
    "video_soft_ad",
    "video_planting",
    "video_harvest",
    "graphic_harvest",
    "product_main_image",
    "product_detail_page",
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

# phase D 新加 3 字段：本段角色 / 产品出场 / image_prompt
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
}

# character_sheet 段（第 3.5 部分）：#### 角色 {role_id} · {简称}
_CHARACTER_HEADER_RE = re.compile(
    r"^#{3,4}\s*角色\s+(?P<role_id>[a-z][a-z0-9_]*)\s*[·\.\-]?\s*(?P<name>[^\n]*?)\s*$",
    re.M,
)
_CHARACTER_FIELD_RES = {
    "age":                  re.compile(r"\*\*\s*年龄\s*\*\*\s*[:：]\s*([^\n]+)"),
    "gender":               re.compile(r"\*\*\s*性别\s*\*\*\s*[:：]\s*([^\n]+)"),
    "appearance_keywords":  re.compile(r"\*\*\s*外貌关键词\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\Z)", re.S),
    "aura":                 re.compile(r"\*\*\s*气质\s*[/／]?\s*神韵?\s*\*\*\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\Z)", re.S),
    "audience_anchor":      re.compile(r"\*\*\s*人群锚点\s*\*\*\s*[:：]\s*(.+?)(?=\n\s*-\s*\*\*|\n\n|\n#|\Z)", re.S),
}

# 图文类 kind：每段图片 brief 简单格式（按 #### 图 N / #### 主图 N / #### 段 N）
_GRAPHIC_SCENE_HEADER_RE = re.compile(
    r"^#{3,4}\s*(?:图|主图|分镜图|段|配图)\s*(?P<no>\d+)\s*[·\.\-：:]?\s*"
    r"(?P<name>[^\n]*?)\s*$",
    re.M,
)


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
        # image_prompt：自然语言长描述（保留换行 + 缩进）
        m_ip = _VIDEO_FIELD_RES_PHASE_D["image_prompt"].search(body)
        if m_ip:
            ip = m_ip.group(1).strip()
            # 去多余空白，但保留段落（image_prompt 可能多行）
            ip = re.sub(r"\n\s+", " ", ip)
            ip = re.sub(r"\s+", " ", ip).strip()
            if ip:
                scene["image_prompt"] = ip

        scenes.append(scene)
    # 按 scene_no 升序
    scenes.sort(key=lambda s: s["scene_no"])
    return scenes


# ════════════════════════════════════════════════════════════════
# character_sheet 段解析（W4-B 切片 14.4 phase D：脚本顶部锁脸清单）
# ════════════════════════════════════════════════════════════════

def parse_character_sheets_from_script_md(script_md: str) -> list[dict[str, Any]]:
    """从 script_md 第 3.5 部分提取角色清单。

    返回 [{role_id, name, age, gender, appearance_keywords, aura, audience_anchor}]。
    解析失败返 []，主流程不阻塞。
    """
    if not script_md or not script_md.strip():
        return []
    # 截取第 3.5 部分到第 4 部分之间（防止抓到第 4/5 部分的别的 # 节点）
    # 第 3.5 部分头：### 第 3.5 部分... 或 ### 第 3.5 部分：角色清单
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
                if value:
                    sheet[field_key] = value
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
    parent_script_id: str | None = None,
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
                status, version, parent_script_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4,
                $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10,
                $11,
                $12, $13, $14, $15,
                'draft', $16, $17::uuid
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
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_creative_pack failed: %s", exc)
        return None


# ════════════════════════════════════════════════════════════════
# step 6 资产落库（W4-B 切片 14.4 phase D：分镜图/视频生成挂血缘）
# ════════════════════════════════════════════════════════════════

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
) -> str | None:
    """落 1 行 pipeline.assets（status='draft'），返 id。失败返 None 不抛。

    persist_to_disk=True（默认）：先把 file_url 转存到本地磁盘（解决 cdn 24h 过期）。
    落盘失败 fallback 用原 url（不挡链路）；notes 自动追加错误描述供复盘。
    """
    if asset_type not in ("image", "video", "character_sheet"):
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
    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.assets (
                script_id, audience_pack_id, audience_record_id, matrix_run_id, sku_id,
                asset_type, character_role,
                file_url, thumbnail_url, prompt,
                duration_seconds, scene_no, external_video_id,
                status, notes
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5,
                $6, $7,
                $8, $9, $10,
                $11, $12, $13,
                'draft', $14
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
        )
        return rec["id"] if rec else None
    except Exception as exc:
        logger.exception("save_storyboard_asset failed: %s", exc)
        return None


async def list_character_sheets_for_script(script_id: str) -> list[dict[str, Any]]:
    """拉同 script_id 的所有 character_sheet asset（按 character_role 字典序）。

    给 step 6 用：scene.characters_in_scene=['daughter','mother'] → 找对应 url 当 face_refs。
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id::text, character_role, file_url, status, created_at
        FROM pipeline.assets
        WHERE script_id = $1::uuid AND asset_type = 'character_sheet'
        ORDER BY character_role, created_at DESC
        """,
        script_id,
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


async def backfill_scenes_for_existing_scripts() -> dict[str, Any]:
    """一次性回填：扫所有 pipeline.scripts 中 scenes=[] 或 character_sheets=[] 的，按 kind 重解析 script_md 写回。

    给 phase D 起手用，让历史 adopted scripts 也能拉分镜清单 + 角色清单。
    解析 v11+ 的脚本能拿到 9 字段（含 image_prompt / characters_in_scene / product_appearance）+ character_sheets；
    v10 老脚本只能拿到 6 字段（缺 phase D 那 3 个，character_sheets=[]）。

    返 {scanned, scripts_updated, scenes_parsed_total, character_sheets_parsed_total, by_kind}。
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id::text AS id, kind, script_md
        FROM pipeline.scripts
        WHERE (scenes::text = '[]' OR character_sheets::text = '[]')
          AND script_md IS NOT NULL AND script_md != ''
        """
    )
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
               model_provider, model, created_at, parent_script_id::text
        FROM pipeline.scripts
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def get_creative_pack(script_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text, sku_id, kind, audience_record_id::text, audience_pack_id::text,
               matrix_run_id::text, script_md, hooks, scenes, character_sheets,
               target_purpose,
               extra_context, model_provider, model, version, status,
               parent_script_id::text, created_at, updated_at
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
    if table not in {"matrix_runs", "audience_runs", "audience_records", "audience_packs", "scripts", "assets", "keyword_packs"}:
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
    """把 status 从 draft 改 adopted。table 在 {matrix_runs, audience_runs, audience_records, audience_packs, scripts, assets}。

    audience_records 额外可选 set_selected_for_pack=TRUE。
    """
    if table not in {"matrix_runs", "audience_runs", "audience_records", "audience_packs", "scripts", "assets"}:
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
