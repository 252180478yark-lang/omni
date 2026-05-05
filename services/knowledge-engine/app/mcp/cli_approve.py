"""W3a T7：human_gates CLI 批/驳/列/tail。

用法（容器内）：
    docker exec -it omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.cli_approve <cmd> [args]"

命令：
    list                            列所有 pending gate
    approve <id> [--note "..."]    批一条
    reject  <id> [--note "..."]    驳一条
    tail [--interval 5]             持续显示 pending（Ctrl-C 退出）

<id> 接受完整 uuid 或前 8 位 short_id（如多条 short_id 撞同一前缀，CLI 会列冲突让你补全）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid as _uuid
from datetime import datetime, timezone

from app.database import init_pool, close_pool, get_pool
from app.mcp import human_gate


def _short(gate_id) -> str:
    return str(gate_id)[:8]


def _fmt_age(created_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    delta = now - created_at
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60}s"
    return f"{s // 3600}h{(s % 3600) // 60}m"


async def _resolve_id(short_or_full: str) -> str | None:
    """short_id (8 chars) 或全 uuid → 全 uuid。返回 None 表 not found / ambiguous。"""
    pool = get_pool()
    if len(short_or_full) >= 32:
        # 全 uuid（去掉横杠后 32 位）
        try:
            full = str(_uuid.UUID(short_or_full))
            row = await pool.fetchrow(
                "SELECT id FROM mcp.human_gates WHERE id=$1 AND decision IS NULL",
                _uuid.UUID(full),
            )
            return str(row["id"]) if row else None
        except ValueError:
            return None

    # short_id：扫 pending 找前缀匹配
    rows = await pool.fetch(
        "SELECT id::text AS id_str FROM mcp.human_gates WHERE decision IS NULL"
    )
    matches = [r["id_str"] for r in rows if r["id_str"].startswith(short_or_full)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"[ambiguous] short_id '{short_or_full}' 匹配多条：")
        for m in matches:
            print(f"  {m}")
        return None
    return None


async def cmd_list() -> int:
    pending = await human_gate.list_pending()
    if not pending:
        print("（无待批）")
        return 0
    print(f"{'short':9} {'tool':28} {'age':>8}  summary")
    print("-" * 80)
    for g in pending:
        sid = _short(g["id"])
        tool = (g["tool_name"] or "?")[:28]
        age = _fmt_age(g["created_at"])
        summary = (g["summary"] or "")[:60]
        print(f"{sid:9} {tool:28} {age:>8}  {summary}")
    return 0


async def cmd_approve(short_or_full: str, note: str) -> int:
    full = await _resolve_id(short_or_full)
    if not full:
        print(f"[not found] {short_or_full}", file=sys.stderr)
        return 1
    ok = await human_gate.approve(full, note)
    print(f"approved {full[:8]}" if ok else f"[failed] gate already decided?", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


async def cmd_reject(short_or_full: str, note: str) -> int:
    full = await _resolve_id(short_or_full)
    if not full:
        print(f"[not found] {short_or_full}", file=sys.stderr)
        return 1
    ok = await human_gate.reject(full, note)
    print(f"rejected {full[:8]}" if ok else f"[failed] gate already decided?", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


async def cmd_tail(interval: float) -> int:
    """持续显示 pending（每 interval 秒刷新一次）。"""
    try:
        while True:
            print("\033[2J\033[H", end="")  # clear + home
            print(f"[{datetime.now().strftime('%H:%M:%S')}] omni human gate tail")
            await cmd_list()
            await asyncio.sleep(interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 0


async def _main() -> int:
    ap = argparse.ArgumentParser(prog="cli_approve")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列 pending gates")
    pa = sub.add_parser("approve", help="批一条 gate")
    pa.add_argument("id")
    pa.add_argument("--note", default="")
    pr = sub.add_parser("reject", help="驳一条 gate")
    pr.add_argument("id")
    pr.add_argument("--note", default="")
    pt = sub.add_parser("tail", help="持续显示 pending")
    pt.add_argument("--interval", type=float, default=5.0)

    args = ap.parse_args()
    await init_pool()
    try:
        if args.cmd == "list":
            return await cmd_list()
        if args.cmd == "approve":
            return await cmd_approve(args.id, args.note)
        if args.cmd == "reject":
            return await cmd_reject(args.id, args.note)
        if args.cmd == "tail":
            return await cmd_tail(args.interval)
        return 2
    finally:
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
