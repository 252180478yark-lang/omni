# -*- coding: utf-8 -*-
"""把 Claude Code 终端 memory 全量打包成 1 份 markdown，老板上传到 Claude.ai 项目知识库。

为什么需要：
  Claude Code 终端 memory 在本地（C:\\Users\\Administrator\\.claude\\projects\\E--agent-omni\\memory）；
  Claude.ai 客户端（网页/桌面/手机）memory 在 Anthropic 服务器，不互通。
  这个脚本把终端 memory 合成 1 份 markdown，老板上传到 Claude.ai 项目知识库，
  客户端 Claude 就能"看到"终端积累的所有上下文。

用法：
  python scripts/dump_memory_for_claude_ai.py
  → 输出 data/agent_state/omni_memory_export.md
  → 老板手动上传到 Claude.ai 项目知识库（更新时重新跑+重新上传）

按类型分组：user / feedback / project / reference / index。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

MEMORY_DIR = Path(r"C:\Users\Administrator\.claude\projects\E--agent-omni\memory")
OUTPUT = Path(__file__).parent.parent / "data" / "agent_state" / "omni_memory_export.md"

TYPE_ORDER = ["user", "feedback", "project", "reference"]
TYPE_LABELS = {
    "user": "👤 用户身份与协作风格",
    "feedback": "🎯 老板反馈与硬约束（最重要）",
    "project": "📋 项目状态与进度",
    "reference": "🔗 外部资源与位置参考",
}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_memory_file(path: Path) -> dict | None:
    """读取一份 memory .md，解析 frontmatter + body。失败返 None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[skip] {path.name}: {exc}")
        return None

    m = FRONTMATTER_RE.match(text)
    if not m:
        return None

    fm_text = m.group(1)
    body = text[m.end():].strip()

    fm = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()

    return {
        "path": path,
        "filename": path.name,
        "name": fm.get("name", path.stem),
        "description": fm.get("description", ""),
        "type": fm.get("type", "unknown"),
        "body": body,
    }


def build_export() -> str:
    files = sorted(MEMORY_DIR.glob("*.md"))
    memories = []
    index_md_text = None

    for p in files:
        if p.name == "MEMORY.md":
            index_md_text = p.read_text(encoding="utf-8").strip()
            continue
        parsed = parse_memory_file(p)
        if parsed:
            memories.append(parsed)

    # 按 type 分组
    grouped: dict[str, list[dict]] = {t: [] for t in TYPE_ORDER}
    for m in memories:
        t = m["type"] if m["type"] in grouped else "reference"
        grouped[t].append(m)
    for t in grouped:
        grouped[t].sort(key=lambda x: x["filename"])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = [
        "# 终端 Claude Code Memory 全量导出",
        "",
        f"> 生成于 **{now}** · 来源 `{MEMORY_DIR}` · 由 `scripts/dump_memory_for_claude_ai.py` 自动生成",
        "",
        "## 这份文档是什么",
        "",
        "Claude Code（终端 / CLI）会从本地文件 `~/.claude/projects/.../memory/` 加载我跟老板的"
        "跨会话记忆 — 包括用户身份、反馈硬约束、项目状态、外部资源位置。",
        "",
        "Claude.ai 客户端（网页/桌面/手机）的 memory 是 Anthropic 服务器托管的，跟本地不互通。"
        "为了让客户端 Claude 也能看到这些上下文，把整份 memory 合并成本文档，老板**上传到 "
        "Claude.ai 项目知识库当附件**，客户端 Claude 就能 看到 终端积累的全部信息。",
        "",
        "**更新机制**：终端 memory 改动后跑 `python scripts/dump_memory_for_claude_ai.py` "
        "重新生成此文件，再到 Claude.ai 项目知识库重新上传（覆盖旧版）。",
        "",
        "---",
        "",
        "## 索引（MEMORY.md）",
        "",
    ]

    if index_md_text:
        # 去掉 MEMORY.md 顶部的 H1 标题（避免跟我们的章节标题冲突）
        idx = index_md_text
        idx = re.sub(r"^#\s+Memory Index\s*\n", "", idx)
        lines.append(idx)
    else:
        lines.append("（MEMORY.md 不存在）")

    lines.extend(["", "---", ""])

    for t in TYPE_ORDER:
        items = grouped.get(t, [])
        if not items:
            continue
        lines.append(f"## {TYPE_LABELS[t]}")
        lines.append("")
        for m in items:
            lines.append(f"### {m['name']}")
            lines.append("")
            if m["description"]:
                lines.append(f"> {m['description']}")
                lines.append("")
            lines.append(m["body"])
            lines.append("")
            lines.append("---")
            lines.append("")

    # 文件大小估算
    total_chars = sum(len(m["body"]) for m in memories)
    lines.append(
        f"_本文档共 {len(memories)} 条 memory，约 {total_chars:,} 字符。Claude.ai 项目知识库附件"
        f"上限通常很宽松，本文档大小不会超限。_"
    )

    return "\n".join(lines)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    content = build_export()
    OUTPUT.write_text(content, encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"✓ 导出完毕：{OUTPUT}")
    print(f"  大小：{size_kb:.1f} KB")
    print(f"  条数：{len(list(MEMORY_DIR.glob('*.md'))) - 1} 条 memory + 1 份 MEMORY.md 索引")
    print()
    print(f"下一步：把 {OUTPUT.name} 上传到 Claude.ai 项目知识库 (覆盖旧版)。")


if __name__ == "__main__":
    main()
