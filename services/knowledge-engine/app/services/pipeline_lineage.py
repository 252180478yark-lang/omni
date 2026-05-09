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

    try:
        rec = await pool.fetchrow(
            """
            INSERT INTO pipeline.scripts (
                audience_pack_id, audience_record_id, matrix_run_id, sku_id,
                script_md, hooks, scenes, target_purpose, kind,
                extra_context,
                model_provider, model, prompt_hash, cost_estimate,
                status, version, parent_script_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid, $4,
                $5, $6::jsonb, $7::jsonb, $8, $9,
                $10,
                $11, $12, $13, $14,
                'draft', $15, $16::uuid
            ) RETURNING id::text AS id
            """,
            audience_pack_id,
            audience_record_id,
            matrix_run_id,
            sku_id,
            script_md.strip(),
            json.dumps(hooks or [], ensure_ascii=False),
            json.dumps(scenes or [], ensure_ascii=False),
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
               matrix_run_id::text, script_md, hooks, scenes, target_purpose,
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
    return d


async def adopt_run(table: str, run_id: str, *, set_selected: bool = False) -> dict[str, Any]:
    """把 status 从 draft 改 adopted。table 在 {matrix_runs, audience_runs, audience_records, audience_packs, scripts}。

    audience_records 额外可选 set_selected_for_pack=TRUE。
    """
    if table not in {"matrix_runs", "audience_runs", "audience_records", "audience_packs", "scripts"}:
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
