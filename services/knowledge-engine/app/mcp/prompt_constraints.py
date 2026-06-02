"""全局写作风格强制约束（design doc §2.8 / feedback_writing_style.md）。

W3a 起：内容外置到 `config/prompts/anti_ai_voice.md`，本模块只导出 `ANTI_AI_HUMAN_VOICE`
名做后向兼容（ai_hub_client 等模块还在 import 这个名）。改文案直接编辑 .md，
KE 容器 restart 即生效（prompts.load 自带 mtime 缓存）。
"""
from __future__ import annotations

from app.mcp import prompts as _prompts


# 模块级常量：每次 import 时加载一次。
# 改 anti_ai_voice.md 后需 restart KE 容器或在调用方主动 invalidate。
# 实际上 ai_hub_client.chat 每次都走 import，prompts.load 内部 mtime 缓存
# 自动反映 .md 变更，所以热改文案不需要 restart 容器，但 ANTI_AI_HUMAN_VOICE
# 这个模块级名是首次 import 的快照——为保证热改生效，改成 property-like
# 模式：暴露一个 callable，但保留旧名兼容。
def _get_anti_ai_voice() -> str:
    return _prompts.load("anti_ai_voice")


# 后向兼容：旧代码 import ANTI_AI_HUMAN_VOICE 当字符串用。
# 这里改成 module-level __getattr__ 实现"按需加载，自带热更新"。
def __getattr__(name: str) -> str:
    if name == "ANTI_AI_HUMAN_VOICE":
        return _get_anti_ai_voice()
    raise AttributeError(f"module 'app.mcp.prompt_constraints' has no attribute {name!r}")
