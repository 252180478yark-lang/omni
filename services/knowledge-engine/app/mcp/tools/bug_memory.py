"""Bug 记忆库 + 客户端日志 MCP tools(2026-05-28 Phase A+/A++).

解决"bug 第一次修第二次还要修":
- log_client_event: 批量记录客户端 IPC/fetch/spawn/error/etc(被动抓不依赖反馈)
- report_bug: 一键报 bug 入记忆库,30 天内同 title 相似自动合并 occurrences++
- list_bugs: 查 bug 列表(默认按 last_seen DESC,unfixed_only=true 启动期自动拉)
- update_bug: 老板修了改 fix_applied=true 让其退出启动期 inject 池

均不走 Human Gate(高频被动抓 + 老板手动报).
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import bug_memory_service as svc

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def log_client_event(events: list[dict]) -> dict:
    """批量记录客户端运行时事件(IPC/fetch/spawn/error/etc).

    events 每条至少含 client + event_type + severity;可选
    channel/payload/result/duration_ms/stack_trace/session_id/user_marked_bug.

    session_id 接受两种:mcp.agent_sessions.id (uuid str) 或
    claude_session_id (text);找不到返 None 但日志照存(允许不挂 session).

    event_type 推荐集合:ipc_call / ke_fetch / claude_spawn / claude_stderr /
    electron_error / electron_crash / startup / manual_bug_report;新类型不卡死.

    Returns:
        {ok, inserted_count, errors: [{index, error}]}
        失败行不阻断其他.
    """
    result = await svc.insert_client_logs_batch(events)
    if result.get("ok"):
        inserted = result.get("inserted_count", 0)
        errs = len(result.get("errors") or [])
        if errs > 0:
            logger.warning("log_client_event inserted=%d errors=%d", inserted, errs)
        else:
            logger.info("log_client_event inserted=%d", inserted)
    return result


@tool_with_audit(mcp, require_approval=False)
async def report_bug(
    title: str,
    symptom: str,
    trigger_conditions: str | None = None,
    root_cause: str | None = None,
    fix_recipe: str | None = None,
    client_log_ids: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """报告一个 bug 入记忆库.

    同 title 相似的 30 天内自动合并(occurrences++ + last_seen=now + tags 合并).
    其他字段(symptom/trigger/cause/fix)仅在原行为空时补,不覆盖.

    老板话术触发:'这又出 bug 了' / '记录这个问题' / '加进 bug 库'.

    Returns:
        {ok, bug_id, deduped, occurrences, ?merged_tags, ?warning}
    """
    result = await svc.insert_bug(
        title=title,
        symptom=symptom,
        trigger_conditions=trigger_conditions,
        root_cause=root_cause,
        fix_recipe=fix_recipe,
        client_log_ids=client_log_ids,
        tags=tags,
        auto_dedupe=True,
    )
    if result.get("ok"):
        logger.info(
            "report_bug bug_id=%s deduped=%s occ=%d title=%s",
            result.get("bug_id", "")[:8],
            result.get("deduped"),
            result.get("occurrences", 0),
            title[:30],
        )
    return result


@tool_with_audit(mcp, require_approval=False)
async def list_bugs(
    unfixed_only: bool = False,
    tags: list[str] | None = None,
    limit: int = 50,
) -> dict:
    """查 bug 列表.fix_applied=false 优先看,按 last_seen 倒序.

    老板话术触发:'看看 bug 库' / '还有哪些 bug 没修' / 启动期自动拉.

    Returns:
        {ok, bugs: list, count}
    """
    bugs = await svc.list_bugs(
        unfixed_only=unfixed_only, tags=tags, limit=limit,
    )
    return {"ok": True, "bugs": bugs, "count": len(bugs)}


@tool_with_audit(mcp, require_approval=False)
async def update_bug(
    bug_id: str,
    fix_applied: bool | None = None,
    root_cause: str | None = None,
    fix_recipe: str | None = None,
    add_tags: list[str] | None = None,
    note_append: str | None = None,
) -> dict:
    """更新一个 bug.老板修了改 fix_applied=true 让它退出启动期 inject 池.

    - fix_applied/root_cause/fix_recipe 非 None 就更新(覆盖)
    - add_tags 追加去重
    - note_append 追加到 fix_recipe 末尾(加分隔)

    老板话术触发:'bug-X 修了' / '这个标记为已修' / '加个原因到 bug-X'.

    Returns:
        {ok, updated_fields}
    """
    result = await svc.update_bug(
        bug_id=bug_id,
        fix_applied=fix_applied,
        root_cause=root_cause,
        fix_recipe=fix_recipe,
        add_tags=add_tags,
        note_append=note_append,
    )
    if result.get("ok"):
        logger.info(
            "update_bug bug_id=%s fields=%s",
            bug_id[:8],
            result.get("updated_fields"),
        )
    return result
