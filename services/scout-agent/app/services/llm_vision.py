"""
LLM vision: send a screenshot to ai-provider-hub /analyze endpoint for
structured extraction. Falls back to empty dict on any error so it never
blocks the main pipeline.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.runtime_trace import outbound_trace_headers

log = logging.getLogger(__name__)


def _try_parse_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from LLM free-form text."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip ```json fences if present
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Find first balanced {...} block
    m2 = re.search(r"\{[\s\S]*\}", text)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass
    return {}


async def vision_extract(image_path: str, prompt: str) -> dict[str, Any]:
    path = Path(image_path)
    if not path.exists():
        log.warning("vision_extract: image not found %s", image_path)
        return {}

    try:
        b64 = base64.b64encode(path.read_bytes()).decode()

        # ai-provider-hub /api/v1/ai/analyze: {type, content (base64), prompt, provider, model}
        # returns {analysis: <text>, structured_data: {...}, ...}
        payload = {
            "type": "image",
            "content": b64,
            "prompt": prompt,
            "provider": "gemini",
            # Don't pin a model — let ai-provider-hub pick its configured default
            # (provider-config.json: gemini-3-flash-preview).
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.ai_hub_url}/api/v1/ai/analyze",
                json=payload,
                headers=outbound_trace_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data.get("structured_data"), dict) and data["structured_data"]:
            return data["structured_data"]
        analysis = data.get("analysis") or data.get("text") or ""
        parsed = _try_parse_json(analysis)
        if parsed:
            return parsed
        return {"_raw_text": analysis[:2000]} if analysis else {}

    except Exception as exc:
        log.warning("vision_extract failed (%s): %s", image_path, str(exc)[:200])
        return {}
