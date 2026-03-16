"""Intent classification for RAG query routing.

Classifies user queries into two categories:
- browse: meta-questions about KB contents (list docs, count, stats)
- generate: questions that require vector retrieval + LLM generation

Uses keyword + rule-based matching — no extra LLM call needed.
Priority: generate signals checked FIRST to avoid false browse classification.
"""

from __future__ import annotations

import re

# ── Generate signals: if any match, always return 'generate' ──
_GENERATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(平均|总结|分析|对比|比较|区别|生成|写|帮我|根据|基于|结合|提取|归纳|概括)", re.I),
    re.compile(r"(多少字|多少钱|什么价|怎么说|怎么做|如何|为什么|什么区别|什么不同)", re.I),
    re.compile(r"(脚本|话术|文案|推广|策略|方案|建议|优化|改进)", re.I),
    re.compile(r"(每分钟|每秒|每段|每个人|各自|分别)", re.I),
    re.compile(r"(风格|特点|特征|亮点|优势|不足)", re.I),
]

# ── Browse patterns: only match if no generate signal ──
_BROWSE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(有多少|有几个|多少个|数量|总共|一共).*(文档|文件|报告|资料|切片|视频)", re.I),
    re.compile(r"(文档|文件|报告|切片|视频).*(有多少|有几个|多少个|数量|列表|清单|目录)", re.I),
    re.compile(r"(列出|列举|罗列).*(所有|全部|文档|文件|报告|资料|切片|标题|列表|目录|名称)", re.I),
    re.compile(r"(知识库).*(里有|包含|存了|保存了|有什么|有哪些|概况|概览)", re.I),
    re.compile(r"(都有|有哪些).*(文档|文件|报告|切片|视频|内容|资料)", re.I),
    re.compile(r"^(浏览|概览|概况|目录|统计)$", re.I),
]

_BROWSE_KEYWORDS: set[str] = {
    "有多少", "有几个", "列出", "列举", "展示所有", "有哪些文档",
    "知识库概览", "知识库统计", "文档列表", "文档目录",
    "都有什么", "包含什么", "存了什么", "保存了什么",
}

_BROWSE_ONLY_QUERIES: set[str] = {
    "查看内容", "查看知识库", "知识库概览", "知识库统计", "文档列表",
}


def classify_intent(query: str) -> str:
    """Return 'browse' or 'generate'."""
    q = query.strip()
    if not q:
        return "generate"

    # Short exact-match browse phrases
    if q in _BROWSE_ONLY_QUERIES:
        return "browse"

    # Generate signals take priority — any analytical / creative intent → generate
    for pat in _GENERATE_PATTERNS:
        if pat.search(q):
            return "generate"

    # Only fall through to browse if query is short & meta-level
    if len(q) > 50:
        return "generate"

    for kw in _BROWSE_KEYWORDS:
        if kw in q:
            return "browse"

    for pat in _BROWSE_PATTERNS:
        if pat.search(q):
            return "browse"

    return "generate"
