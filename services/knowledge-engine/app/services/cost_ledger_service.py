"""月度成本总账 service(2026-06-01 · 蓝图 §4 L0-2【R-28】).

把每次 Claude Code 会话跑完报的 total_cost_usd 按月归集进 mcp.monthly_spend,
配套"某月累计 / 月度软上限 / 超额检测"。本切片**只记账 + 算账**:
- 不接 cron(后续切片定时跑)
- 不发企微告警(check_over_cap 只返回"是否超 + 差额",供未来接告警)
- 月度上限从 env 读 OMNI_MONTHLY_SPEND_CAP_USD,默认保守值 500 美元

设计跟 bug_memory_service / agent_log_service 一致:async + get_pool + 返 dict,
单条挂不阻断、防御式校验。session_id 兼容 uuid / claude_session_id 文本
(复用 bug_memory_service._resolve_session_uuid,不复制逻辑避免漂移)。
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from app.database import get_pool
# 复用已有的 session_id → uuid 解析(同 mcp 域,稳定 helper),不复制逻辑(蓝图禁漂移)
from app.services.bug_memory_service import _resolve_session_uuid

logger = logging.getLogger(__name__)


# 月度软上限默认值(美元)。保守起见给 500;老板可在 KE .env 配
# OMNI_MONTHLY_SPEND_CAP_USD 覆盖。读 env 而非 config.Settings 是因为本切片
# 只允许加新文件,不改 config.py;env 缺失/非法时回退到这个默认。
# needs_boss:这个 500 是占位默认,老板 apply migration 033 后定真实月度上限。
_DEFAULT_MONTHLY_CAP_USD = Decimal("500")
_CAP_ENV_KEY = "OMNI_MONTHLY_SPEND_CAP_USD"

_VALID_SOURCES = {"claude_session", "manual", "other"}


# 账月按老板**本地时区**算（默认 +0800），不用 UTC——否则月初凌晨/月末深夜跑的会话
# 会被错归到相邻月（审查 finding）。env OMNI_TZ_OFFSET_HOURS 可覆盖（小时偏移）。
def _local_tz() -> _dt.timezone:
    raw = os.getenv("OMNI_TZ_OFFSET_HOURS", "8")
    try:
        h = float(raw)
    except (TypeError, ValueError):
        h = 8.0
    if not (-24 < h < 24):
        h = 8.0
    return _dt.timezone(_dt.timedelta(hours=h))


# ─────────────────────────── 内部工具 ───────────────────────────


def _coerce_cost(value: Any) -> Decimal | None:
    """把传进来的金额转成非负 Decimal;非法 / 负数 → None(调用方拒收)。"""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d.is_nan() or d.is_infinite() or d < 0:
        return None
    return d


def _month_floor(d: _dt.date) -> _dt.date:
    """某日期归到所在自然月的月初(用月初零点 DATE 当账月键)。"""
    return d.replace(day=1)


def get_monthly_cap_usd() -> Decimal:
    """读月度软上限(美元)。

    OMNI_MONTHLY_SPEND_CAP_USD 非法 / 缺失 / 负数 → 回退到 _DEFAULT_MONTHLY_CAP_USD。
    """
    raw = os.getenv(_CAP_ENV_KEY)
    if raw is None or not str(raw).strip():
        return _DEFAULT_MONTHLY_CAP_USD
    cap = _coerce_cost(raw)
    # cap<=0 视为非法（0 会让 check_over_cap 永远判超 + usage_ratio=None 误导前端），回退默认
    if cap is None or cap <= 0:
        logger.warning(
            "%s 值非法(%r,需 >0),回退默认 %s 美元", _CAP_ENV_KEY, raw, _DEFAULT_MONTHLY_CAP_USD
        )
        return _DEFAULT_MONTHLY_CAP_USD
    return cap


# ─────────────────────────── 记一笔花费 ───────────────────────────


async def record_spend(
    cost_usd: Any,
    session_id: str | None = None,
    claude_session_id: str | None = None,
    source: str = "claude_session",
    client: str | None = None,
    actor_id: str = "yark",
    note: str | None = None,
    spent_at: _dt.datetime | None = None,
) -> dict:
    """记一笔会话成本进 mcp.monthly_spend。

    - cost_usd:必填,非负;非法 / 负数 → 拒收(返 ok=False),不写脏数据进总账。
    - session_id:uuid 或 claude_session_id 文本均可(解析得到就挂 session_id,
      解析不到仍把原文留进 claude_session_id 备查,账目照记 fail-open)。
    - spent_at:不传用 now();账月 spend_month 按 spent_at 落在哪个自然月算好写入。

    返 {ok, ?id, ?spend_month, ?cost_usd, ?error, ?hint}。
    """
    cost = _coerce_cost(cost_usd)
    if cost is None:
        return {
            "ok": False,
            "error": "invalid_cost",
            "hint": "cost_usd 必须是非负数(防负值/NaN 进总账)",
        }

    if source not in _VALID_SOURCES:
        # 不卡死(老板加新来源不挂),但记日志便于发现 typo
        logger.info("monthly_spend unfamiliar source=%s", source)

    # 解析 session:优先用显式 claude_session_id,其次拿 session_id 试解析
    # 空串归一成 None（防前端漏改把 "" 当有效 claude_session_id 写库污染账目）
    session_id = session_id.strip() if isinstance(session_id, str) and session_id.strip() else None
    raw_claude_sid = (claude_session_id.strip()
                      if isinstance(claude_session_id, str) and claude_session_id.strip() else None)
    resolved_uuid: uuid.UUID | None = None
    if session_id:
        resolved_uuid = await _resolve_session_uuid(session_id)
        if resolved_uuid is None and raw_claude_sid is None:
            # session_id 没解析成 agent_sessions.id,把原文当 claude_session_id 留底
            raw_claude_sid = session_id
    if resolved_uuid is None and raw_claude_sid:
        # 再试一次:claude_session_id 也可能恰好是个能解析的 uuid
        resolved_uuid = await _resolve_session_uuid(raw_claude_sid)
    if resolved_uuid is None and raw_claude_sid is None:
        # 孤立账目（没挂上任何 session）——fail-open 照记，但留日志便于运维排查
        logger.info("record_spend: 未解析到 session，cost=%s 记为孤立账目", cost)

    # 账月按老板本地时区算（避免月界 UTC 错归）。约定：spent_at 带 tz → 转本地后取月；
    # naive spent_at（无 tzinfo）**按"已是本地时区"处理**（不转换，调用方需保证；当前唯一
    # 调用方[前端 task_done]不传 spent_at → 走 now(local) 分支，naive 分支仅手动补录时可能命中）。
    when = spent_at or _dt.datetime.now(_local_tz())
    local_when = when.astimezone(_local_tz()) if when.tzinfo else when
    spend_month = _month_floor(local_when.date())

    pool = get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO mcp.monthly_spend (
                session_id, claude_session_id, cost_usd, source,
                client, actor_id, note, spend_month, spent_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id, spend_month, cost_usd
            """,
            resolved_uuid,
            raw_claude_sid,
            cost,
            source,
            client,
            actor_id,
            note,
            spend_month,
            when,
        )
    except Exception as exc:  # pragma: no cover - 记账失败不该炸调用方
        logger.exception("record_spend insert failed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "ok": True,
        "id": str(row["id"]),
        "spend_month": row["spend_month"].isoformat(),
        "cost_usd": float(row["cost_usd"]),
    }


# ─────────────────────────── 查某月累计 ───────────────────────────


async def get_month_total(
    month: _dt.date | str | None = None,
    actor_id: str | None = None,
) -> dict:
    """查某月累计成本(美元)。

    - month:DATE / 'YYYY-MM-DD' / 'YYYY-MM' 都接;None → 当前月。
    - actor_id:None → 不分操作者,合计全月;给值 → 只这个操作者。

    返 {ok, spend_month, total_cost_usd, entry_count, ?actor_id}。
    """
    target_month = _parse_month_arg(month)
    if target_month is None:
        return {
            "ok": False,
            "error": "invalid_month",
            "hint": "month 需 DATE / 'YYYY-MM-DD' / 'YYYY-MM'",
        }

    pool = get_pool()
    if actor_id is None:
        row = await pool.fetchrow(
            """
            SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS cnt
            FROM mcp.monthly_spend
            WHERE spend_month = $1
            """,
            target_month,
        )
    else:
        row = await pool.fetchrow(
            """
            SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS cnt
            FROM mcp.monthly_spend
            WHERE spend_month = $1 AND actor_id = $2
            """,
            target_month,
            actor_id,
        )

    result = {
        "ok": True,
        "spend_month": target_month.isoformat(),
        "total_cost_usd": float(row["total"]),
        "entry_count": int(row["cnt"]),
    }
    if actor_id is not None:
        result["actor_id"] = actor_id
    return result


def _parse_month_arg(month: _dt.date | str | None) -> _dt.date | None:
    """把 month 入参归一化成"账月"DATE(月初)。

    None → 当前**本地**月(同 record_spend);DATE → 取月初;'YYYY-MM-DD' / 'YYYY-MM' → 解析后取月初。
    解析不了返 None。
    """
    if month is None:
        return _month_floor(_dt.datetime.now(_local_tz()).date())
    if isinstance(month, _dt.datetime):
        return _month_floor(month.date())
    if isinstance(month, _dt.date):
        return _month_floor(month)
    if isinstance(month, str):
        s = month.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m"):
            try:
                return _month_floor(_dt.datetime.strptime(s, fmt).date())
            except ValueError:
                continue
    return None


# ─────────────────────────── 超额检测 ───────────────────────────


async def check_over_cap(
    month: _dt.date | str | None = None,
    actor_id: str | None = None,
    cap_usd: Any = None,
    precomputed_total: Any = None,
) -> dict:
    """月度软上限超额检测(只检测、不告警、不接 cron)。

    供未来切片接企微告警 / BI 看板用。
    - cap_usd:不传 → 读 env OMNI_MONTHLY_SPEND_CAP_USD(缺/非法回退默认 500)。
    - month / actor_id:同 get_month_total。
    - precomputed_total:调用方已查过当月累计时传进来，**复用同一快照**避免再查库
      （否则两次查库间有并发写入会导致 total 与调用方的 entry_count 不自洽）。

    返 {ok, spend_month, total_cost_usd, cap_usd, over_cap(bool),
        remaining_usd, overage_usd, usage_ratio}。
    over_cap=True 时 overage_usd 为正(超出多少),remaining_usd 为 0;
    未超时 remaining_usd 为正,overage_usd 为 0。
    """
    total_pre = _coerce_cost(precomputed_total) if precomputed_total is not None else None
    if total_pre is not None:
        target = _parse_month_arg(month)
        if target is None:
            return {"ok": False, "error": "invalid_month",
                    "hint": "month 需 DATE / 'YYYY-MM-DD' / 'YYYY-MM'"}
        totals = {"ok": True, "spend_month": target.isoformat(),
                  "total_cost_usd": float(total_pre)}
    else:
        # precomputed_total 缺失/不可解析 → 退回查库（不静默当 0 掩盖调用方传错）
        if precomputed_total is not None:
            logger.warning("check_over_cap: precomputed_total 不可解析(%r)，退回查库", precomputed_total)
        totals = await get_month_total(month=month, actor_id=actor_id)
        if not totals.get("ok"):
            return totals

    cap = _coerce_cost(cap_usd) if cap_usd is not None else get_monthly_cap_usd()
    if cap is None:
        cap = get_monthly_cap_usd()

    total = Decimal(str(totals["total_cost_usd"]))
    over = total > cap
    overage = (total - cap) if over else Decimal("0")
    remaining = (cap - total) if not over else Decimal("0")
    usage_ratio = float(total / cap) if cap > 0 else None

    result = {
        "ok": True,
        "spend_month": totals["spend_month"],
        "total_cost_usd": float(total),
        "cap_usd": float(cap),
        "over_cap": over,
        "remaining_usd": float(remaining),
        "overage_usd": float(overage),
        "usage_ratio": usage_ratio,
    }
    if actor_id is not None:
        result["actor_id"] = actor_id
    return result
