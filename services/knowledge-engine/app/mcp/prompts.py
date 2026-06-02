"""W3a T1：prompt 模板加载 + 渲染（design doc §10 prompt 外置）。

设计：
- 模板放 `config/prompts/<name>.md`（支持子目录如 channel_profiles/douyin）
- `load(name)`：读 .md 原文（带 mtime cache，文件改了自动重读）
- `render(name, **ctx)`：load + str.format 占位替换
- `invalidate()`：清缓存（CLI/测试用）

不用 jinja2（YAGNI，个人用，没有循环/条件需求）；
str.format 的 {placeholder} 不存在 ctx 时抛 KeyError（暴露 caller bug）。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 模板根目录（services/knowledge-engine/config/prompts/）
_PROMPTS_DIR: Path = (
    Path(__file__).resolve().parents[2] / "config" / "prompts"
)

# 缓存：name → (mtime, content)
_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _path_for(name: str) -> Path:
    """name 形如 'generate_brief.system' 或 'channel_profiles/douyin' → 文件路径"""
    return _PROMPTS_DIR / f"{name}.md"


def load(name: str, /) -> str:
    """加载模板原文。带 mtime cache：文件改了自动重读。

    Args:
        name: 模板名，相对 config/prompts/，不含 .md 后缀。
              支持子目录形式如 'channel_profiles/douyin'。

    Returns:
        模板原文（utf-8）。

    Raises:
        FileNotFoundError: 模板文件不存在。
    """
    p = _path_for(name)
    if not p.exists():
        raise FileNotFoundError(f"prompt template not found: {p}")

    mtime = p.stat().st_mtime
    with _lock:
        cached = _cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        text = p.read_text(encoding="utf-8")
        _cache[name] = (mtime, text)
        return text


def render(name: str, /, **ctx: Any) -> str:
    """加载模板 + str.format 替换占位。

    Args:
        name: 模板名（同 load）
        **ctx: 占位变量。模板里 {key} 必须在 ctx 里有，否则 KeyError。

    Returns:
        渲染后字符串。

    Raises:
        FileNotFoundError: 模板不存在。
        KeyError: 模板有占位 ctx 没给。
    """
    template = load(name)
    return template.format(**ctx)


def invalidate(name: str | None = None, /) -> None:
    """清缓存。name=None 清全部；指定名清单条。"""
    with _lock:
        if name is None:
            _cache.clear()
        else:
            _cache.pop(name, None)


def list_templates() -> list[str]:
    """列出 config/prompts/ 下所有 .md 模板（递归）。doctor 用。"""
    if not _PROMPTS_DIR.exists():
        return []
    return sorted(
        str(p.relative_to(_PROMPTS_DIR).with_suffix(""))
            .replace("\\", "/")
        for p in _PROMPTS_DIR.rglob("*.md")
    )
