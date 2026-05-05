"""W3c: 3 个通用专家 tool。

- summarize_text(text, instruction?) — 文本摘要
- parse_long_doc_with_gemini(file_path, instruction?) — 长文档解析（T2 加）
- query_template_chunks(query, kb_id?, source_type?, top_k?) — 模板素材检索（T3 加）
"""
from __future__ import annotations

import logging

from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import build_trace
from app.services.ai_hub_client import AIHubClient

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def summarize_text(
    text: str,
    instruction: str | None = None,
    max_input_chars: int = 30000,
) -> dict:
    """对一段文本出摘要。

    Args:
        text: 待摘要文本
        instruction: 可选方向指引
        max_input_chars: 输入字符上限，超过截断

    Returns:
        {ok, result: {summary, length_in, length_out, truncated}, trace}
    """
    text = text or ""
    if not text.strip():
        return {
            "ok": False,
            "error": "empty_text",
            "hint": "text 不能为空或纯空白",
        }

    length_in = len(text)
    truncated = length_in > max_input_chars
    text_for_llm = text[:max_input_chars] if truncated else text

    instruction_block = (
        f"额外要求：{instruction}\n\n" if (instruction and instruction.strip()) else ""
    )

    system_prompt = prompts.load("summarize_text.system")
    user_prompt = prompts.render(
        "summarize_text.user",
        instruction_block=instruction_block,
        text=text_for_llm,
    )

    cfg = get_model_for_tool("summarize_text")
    client = AIHubClient()
    try:
        resp = await client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider=cfg["provider"],
            model=cfg["model"],
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 2048),
            enforce_human_voice=True,
        )
    except Exception as exc:
        logger.exception("summarize_text chat failed")
        return {
            "ok": False,
            "error": "llm_call_failed",
            "hint": f"ai-hub /chat 调用失败: {exc}",
        }

    summary = (resp.get("content") or "").strip()
    effective_provider = resp.get("provider") or cfg["provider"]
    effective_model = resp.get("model") or cfg["model"]

    trace = build_trace(
        provider=effective_provider,
        model=effective_model,
        prompt=f"[system]\n{system_prompt}\n\n[user]\n{user_prompt[:500]}...",
        params={
            "temperature": cfg.get("temperature", 0.3),
            "max_tokens": cfg.get("max_tokens", 2048),
            "input_chars": len(text_for_llm),
        },
        cost_estimate=f"~{len(text_for_llm) // 1000 + 1}k chars input",
    )
    # 测试 + 调用方按 trace["provider"] / trace["model"] 读值；
    # build_trace 返 model_provider，加 provider 别名保持一致
    trace["provider"] = effective_provider

    return {
        "ok": True,
        "result": {
            "summary": summary,
            "length_in": length_in,
            "length_out": len(summary),
            "truncated": truncated,
        },
        "trace": trace,
    }
