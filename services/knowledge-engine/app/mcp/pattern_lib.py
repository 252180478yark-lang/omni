"""W4-A T1：Pattern Library 文件读写 helper。

design doc §7.4 反馈循环：
- successful_patterns.md 累积 rating='good' 调用
- failed_patterns.md 累积 rating='bad' / 'redo' 调用

文件写在 /app/agent_state（host bind mount = data/agent_state/），
host 上 Claude Code 进 omni 项目时可直接读做 ICL 输入。

用 sync IO（patterns 文件小，不阻塞 event loop）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

AGENT_STATE_DIR = Path("/app/agent_state")


def _ensure_file(path: Path, header: str) -> None:
    """文件不存在时建空文件。"""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header, encoding="utf-8")


def append_successful_pattern(
    *,
    tool_call_id: str,
    tool_name: str,
    note: str = "",
) -> None:
    """追加一条 successful pattern。

    Args:
        tool_call_id: mcp.tool_calls.id（uuid str）
        tool_name: tool 名（如 generate_brief）
        note: 老板打分时附带的备注
    """
    path = AGENT_STATE_DIR / "successful_patterns.md"
    _ensure_file(path, "# Successful Patterns\n\n")
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    entry = f"\n## {ts} · {tool_name}\n\n- tool_call_id: `{tool_call_id}`\n- note: {note or '_无_'}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def append_failed_pattern(
    *,
    tool_call_id: str,
    tool_name: str,
    note: str = "",
) -> None:
    """追加一条 failed pattern。"""
    path = AGENT_STATE_DIR / "failed_patterns.md"
    _ensure_file(path, "# Failed Patterns\n\n")
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    entry = f"\n## {ts} · {tool_name}\n\n- tool_call_id: `{tool_call_id}`\n- note: {note or '_无_'}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def read_recent_patterns(
    *,
    kind: Literal["successful", "failed"],
    limit: int = 10,
) -> list[dict]:
    """读最近 N 条 pattern（按写入时间倒序）。

    Returns:
        [{"timestamp": str, "tool_name": str, "tool_call_id": str, "note": str}, ...]
    """
    path = AGENT_STATE_DIR / f"{kind}_patterns.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    blocks = text.split("\n## ")[1:]  # 第 0 块是 header
    blocks.reverse()  # 最近的在前
    out: list[dict] = []
    for block in blocks[:limit]:
        lines = block.splitlines()
        if not lines:
            continue
        # 第 0 行：YYYY-MM-DD HH:MM:SSZ · tool_name
        head = lines[0]
        if " · " not in head:
            continue
        ts, tool_name = head.split(" · ", 1)
        call_id = ""
        note = ""
        for ln in lines[1:]:
            ln = ln.strip()
            if ln.startswith("- tool_call_id: `"):
                call_id = ln.split("`")[1] if "`" in ln else ""
            elif ln.startswith("- note: "):
                note = ln[len("- note: "):]
        out.append({
            "timestamp": ts.strip(),
            "tool_name": tool_name.strip(),
            "tool_call_id": call_id,
            "note": note,
        })
    return out
