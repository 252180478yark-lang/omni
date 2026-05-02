"""Seedream image generation provider via Volcengine Ark."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability, is_real_api_key
from app.schemas.ai import ChatResponse, Message, TokenUsage

logger = logging.getLogger(__name__)

_ARK_API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
_IMAGE_GENERATION_ENDPOINTS: tuple[str, ...] = (
    f"{_ARK_API_BASE}/images/generations",
    "https://operator.las.cn-beijing.volces.com/api/v1/online/images/generations",
    "https://operator.las.cn-beijing.volces.com/api/v1/images/generations",
)


def _summarize_http_error(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            code = err.get("code") or err.get("type") or exc.response.status_code
            message = err.get("message") or exc.response.text[:200]
            return f"{exc.response.status_code} {code}: {message}"
    except Exception:
        pass
    return f"{exc.response.status_code}: {exc.response.text[:200]}"


def _normalize_size(model: str, requested: object) -> str:
    size = str(requested or "1024x1024")
    if "seedream-5-0" not in model and "seedream-4-5" not in model:
        return size
    try:
        w_raw, h_raw = size.lower().split("x", 1)
        w = int(w_raw)
        h = int(h_raw)
    except Exception:
        return "2048x2048"
    # Seedream 5.0 / 4.5 require at least 2K-class output pixels.
    if w * h < 3_686_400:
        return "2048x2048"
    return size


_KNOWN_SEEDREAM_MODELS: tuple[str, ...] = (
    "doubao-seedream-5-0-260128",
    "doubao-seedream-5-0-lite-260128",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-4-0-250828",
    "doubao-seedream-3-0-t2i-250415",
)


class SeedreamProvider(BaseProvider):
    name = "seedream"
    # 注意：Seedream 是图像生成 provider，不支持 chat/embedding。
    # 这里复用 default_chat_model 字段承载"默认图像模型"，方便共用 update_provider_config
    # 与前端 UI 的 select 控件——具体走 settings.seedream_model 调用。
    default_chat_model = ""
    default_embedding_model = ""
    capabilities = {ProviderCapability.IMAGE_GENERATION}

    def _api_key(self) -> str:
        key = (settings.ark_api_key or "").strip()
        if is_real_api_key(key):
            return key
        return (settings.seedance_access_key or "").strip()

    def _has_key(self) -> bool:
        return is_real_api_key(self._api_key())

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key()}",
        }

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        raise NotImplementedError("Seedream does not support chat")

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        raise NotImplementedError("Seedream does not support chat")
        yield  # noqa: unreachable

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError("Seedream does not support embedding")

    # ── connection test ──

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        """火山方舟 Seedream 连通性测试 + 拉模型列表。

        因为方舟没有针对 seedream 单独的 list 端点，统一走 GET /api/v3/models 验证可达性，
        然后把 settings 里配置的默认模型 + 已知 doubao-seedream-* 系列一并返回，
        让前端能选择具体 Model ID。
        """
        key = (api_key or self._api_key() or "").strip()
        if not is_real_api_key(key):
            return False, "未提供 Seedream / 火山方舟 API Key", list(_KNOWN_SEEDREAM_MODELS)
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{_ARK_API_BASE}/models", headers=headers)
                resp.raise_for_status()
            return True, "Seedream (火山方舟) 连接成功", await self.list_models(api_key=key)
        except httpx.HTTPStatusError as exc:
            return (
                False,
                f"连接失败 (HTTP {exc.response.status_code}): {exc.response.text[:200]}",
                list(_KNOWN_SEEDREAM_MODELS),
            )
        except Exception as exc:
            return False, f"连接失败: {exc}", list(_KNOWN_SEEDREAM_MODELS)

    async def list_models(self, api_key: str | None = None) -> list[str]:
        """返回当前可用的 Seedream Model ID 列表。

        排序：① 当前 settings 配置的默认模型 ② settings.seedream_model_fallback ③ 已知系列。
        """
        configured = [
            (settings.seedream_model or "").strip(),
            (settings.seedream_model_fallback or "").strip(),
        ]
        ordered: list[str] = []
        seen: set[str] = set()
        for m in [*configured, *_KNOWN_SEEDREAM_MODELS]:
            if m and m not in seen:
                seen.add(m)
                ordered.append(m)
        return ordered

    async def generate_image(self, prompt: str, model: str, **kwargs: object) -> dict:
        if not self._has_key():
            logger.warning("Seedream key not configured, returning mock image")
            return {
                "images": [{"url": "https://placeholder.co/1024x1024?text=seedream-mock"}],
                "usage": {"cost_usd": 0},
            }

        refs = kwargs.get("reference_images") or []
        ref_urls: list[str] = []
        for ref in refs:
            if isinstance(ref, str):
                ref_urls.append(ref)
            elif isinstance(ref, dict) and ref.get("url"):
                ref_urls.append(str(ref["url"]))

        chosen_model = model or settings.seedream_model
        payload: dict = {
            "model": chosen_model,
            "prompt": prompt,
            "size": _normalize_size(chosen_model, kwargs.get("size", "1024x1024")),
            "n": kwargs.get("n", 1),
            "response_format": "url",
        }
        if ref_urls:
            payload["image"] = ref_urls

        async with httpx.AsyncClient(timeout=120.0) as client:
            last_exc: httpx.HTTPStatusError | None = None
            primary_exc: httpx.HTTPStatusError | None = None
            resp: httpx.Response | None = None
            models_to_try = [chosen_model]
            if chosen_model != settings.seedream_model_fallback:
                models_to_try.append(settings.seedream_model_fallback)
            for model_id in [m for m in models_to_try if m]:
                payload["model"] = model_id
                payload["size"] = _normalize_size(model_id, payload.get("size"))
                for endpoint in _IMAGE_GENERATION_ENDPOINTS:
                    try:
                        candidate = await client.post(
                            endpoint,
                            headers=self._headers(),
                            json=payload,
                        )
                        candidate.raise_for_status()
                        resp = candidate
                        break
                    except httpx.HTTPStatusError as exc:
                        last_exc = exc
                        if primary_exc is None:
                            primary_exc = exc
                        try:
                            code = (exc.response.json().get("error") or {}).get("code")
                        except Exception:
                            code = ""
                        if code in {"ModelNotOpen", "InvalidEndpointOrModel.NotFound"}:
                            primary_exc = exc
                        # Try the next endpoint/model before surfacing the most
                        # useful error. This avoids LAS 401 masking Ark's
                        # "model not activated" response.
                        continue
                if resp is not None:
                    break
            if resp is None:
                detail = ""
                chosen_exc = primary_exc or last_exc
                if chosen_exc is not None:
                    detail = f": {_summarize_http_error(chosen_exc)}"
                raise RuntimeError(f"Seedream image generation failed{detail}")

        data = resp.json()
        images = []
        for item in data.get("data", []):
            url = item.get("url", "")
            if url:
                images.append({"url": url})
        return {"images": images, "usage": {"cost_usd": 0}}
