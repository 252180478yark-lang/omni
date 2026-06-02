"""W2 T2：tool trace 工具函数（design doc §6 review-after iterate 必带字段）。

每个 LLM tool 的 result 必须含 trace（让老板诊断 + Claude 大脑判断重跑参数）。
建工具函数避免每个 tool 自己拼。
"""
from __future__ import annotations

from typing import Any

_PROMPT_MAX_LEN = 16_384
_TRUNC_SUFFIX = "...[truncated]"


def build_trace(
    *,
    provider: str,
    model: str,
    prompt: str,
    params: dict[str, Any],
    cost_estimate: str,
) -> dict[str, Any]:
    """构造 trace 字段。

    Args:
        provider: e.g. "anthropic" / "openai" / "seedance"
        model: 实际调的 model（来自 tool_models.yaml 解析后）
        prompt: 完整 final prompt（system + user 拼好；过长截断）
        params: 关键参数（temperature / top_p / max_tokens 等）
        cost_estimate: 人话费用描述，如 "1 quota call" / "¥0.5" / "¥15"

    Returns:
        {model_provider, model, final_prompt, params, cost_estimate}
    """
    p = prompt or ""
    if len(p) > _PROMPT_MAX_LEN:
        # 截断后总长度（含 suffix）不超过 _PROMPT_MAX_LEN，防止 audit 表 jsonb 行爆
        p = p[: _PROMPT_MAX_LEN - len(_TRUNC_SUFFIX)] + _TRUNC_SUFFIX
    return {
        "model_provider": provider,
        "model": model,
        "final_prompt": p,
        "params": dict(params),
        "cost_estimate": cost_estimate,
    }


def attach_next_step(
    result: dict[str, Any],
    *,
    suggested_tool: str | None,
    suggested_args: dict[str, Any] | None = None,
    human_text: str = "",
) -> dict[str, Any]:
    """给 tool result 加 next_step_hint 字段。

    Args:
        result: 已含 ok/result/trace 的 dict
        suggested_tool: 建议下一步调哪个 tool；None 表示链路到此结束
        suggested_args: 给老板看的建议入参（参考用，老板可改）
        human_text: 给老板的 1 句话说明（"出 3 张分镜图，~¥1.5"）
    """
    result["next_step_hint"] = {
        "suggested_tool": suggested_tool,
        "suggested_args": suggested_args or {},
        "human_text": human_text,
    }
    return result
