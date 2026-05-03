"""ai-hub HTTP 客户端 thin wrapper（design doc §2.6）。

调用 `services/ai-provider-hub`（http://ai-provider-hub:8001）的统一端点：
- POST /api/v1/ai/chat                  → chat()
- POST /api/v1/ai/images/generate       → generate_image()
- POST /api/v1/ai/videos/generate       → generate_video()
- GET  /api/v1/ai/videos/status/{id}    → wait_for_video()

W1 仅留接口；W2 起在 generate_brief / generate_image / generate_video tool 中
作为唯一入口使用，避免各 tool 重复写 httpx 调用模式。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class AIHubClient:
    def __init__(self, base_url: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = (base_url or settings.ai_provider_hub_url).rstrip("/")
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict],
        *,
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-6",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        enforce_human_voice: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        """统一 chat 入口。enforce_human_voice=True 时在 system 头拼 ANTI_AI_HUMAN_VOICE。"""
        if enforce_human_voice:
            from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE
            sys_idx = next((i for i, m in enumerate(messages) if m.get("role") == "system"), None)
            if sys_idx is None:
                messages = [{"role": "system", "content": ANTI_AI_HUMAN_VOICE}, *messages]
            else:
                messages = list(messages)
                messages[sys_idx] = {
                    **messages[sys_idx],
                    "content": ANTI_AI_HUMAN_VOICE + "\n\n" + (messages[sys_idx].get("content") or ""),
                }
        body = {
            "provider": provider,
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **(extra or {}),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/chat", json=body)
            r.raise_for_status()
            return r.json()

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "gpt-image-2",
        refs: list[str] | None = None,
        aspect: str | None = None,
        n: int = 1,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"prompt": prompt, "model": model, "n": n}
        if refs:
            body["reference_images"] = refs
        if aspect:
            body["aspect_ratio"] = aspect
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/images/generate", json=body)
            r.raise_for_status()
            return r.json()

    async def generate_video(
        self,
        prompt: str,
        *,
        model: str | None = None,
        refs: list[str] | None = None,
        duration_sec: int = 5,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"prompt": prompt, "duration": duration_sec}
        if model:
            body["model"] = model
        if refs:
            body["reference_images"] = refs
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/videos/generate", json=body)
            r.raise_for_status()
            return r.json()

    async def wait_for_video(self, task_id: str, *, max_seconds: int = 600, poll: float = 5.0) -> dict:
        import asyncio
        deadline = max_seconds
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            while deadline > 0:
                r = await cli.get(f"{self.base_url}/api/v1/ai/videos/status/{task_id}")
                r.raise_for_status()
                data = r.json()
                status = (data.get("data") or {}).get("status") or data.get("status")
                if status in {"succeeded", "failed", "completed", "error"}:
                    return data
                await asyncio.sleep(poll)
                deadline -= poll
            return {"status": "timeout", "task_id": task_id}
