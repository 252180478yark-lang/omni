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

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# W4-B 14.4 phase D 候选 D：本地资产 url 喂 hub 前自动转 base64 data url
# 背景：cdn url 24h 过期 → asset_storage 把 file_url 落本地（/api/v1/knowledge/static/...）
#       但 hub → OpenAI / Seedance 拿到相对 url 没法 fetch → 锁脸/i2v 链路断
# 解决：发请求前把本地 url 透明转 data:image/png;base64,... 喂下游
_LOCAL_STATIC_PREFIX = "/api/v1/knowledge/static/"
_LOCAL_DISK_ROOT = Path("/app/data/assets")


def _localize_url(url: Any) -> Any:
    """本地资产 url → base64 data url；其他原样返。

    不抛异常：磁盘缺文件 / 路径越界都返原 url，让 hub 自己报错（不挡链路）。
    """
    if not isinstance(url, str) or not url.startswith(_LOCAL_STATIC_PREFIX):
        return url
    rel = url[len(_LOCAL_STATIC_PREFIX):]
    if not rel or ".." in rel or rel.startswith("/"):
        return url
    try:
        path = _LOCAL_DISK_ROOT / rel
        if not path.exists():
            logger.warning("_localize_url: disk file missing %s", path)
            return url
        mime, _ = mimetypes.guess_type(str(path))
        if not mime:
            mime = "image/png" if path.suffix.lower() in {".png", ".webp", ".gif"} else \
                   "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else \
                   "video/mp4" if path.suffix.lower() == ".mp4" else \
                   "application/octet-stream"
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as exc:
        logger.warning("_localize_url failed (fallback to original): %s err=%s", url, exc)
        return url


def _localize_list(urls: Any) -> Any:
    if not isinstance(urls, list):
        return urls
    return [_localize_url(u) for u in urls]


class HubError(Exception):
    """Hub 调用失败 — 保留 status_code + detail（含火山方舟/OpenAI 原始 error code）。

    classify() 把 detail 文本里的 provider 错误码识别成上层能消费的 category：
      - 'account_overdue'（火山方舟欠费/余额不足）
      - 'content_sensitive'（火山方舟内容审查命中：真实人物/隐私/敏感词）
      - 'model_not_open'（模型未在 console 激活）
      - 'rate_limited' / 'quota_exhausted'
      - 'unknown'（兜底）
    """

    _CATEGORY_PATTERNS: list[tuple[str, str]] = [
        ("account_overdue", "AccountOverdueError"),
        ("account_overdue", "overdue balance"),
        ("content_sensitive", "InputImageSensitiveContentDetected"),
        ("content_sensitive", "ContentSensitive"),
        ("content_sensitive", "real person"),
        ("content_sensitive", "敏感内容"),
        ("model_not_open", "ModelNotOpen"),
        ("rate_limited", "RateLimit"),
        ("rate_limited", "429"),
        ("quota_exhausted", "QuotaExhausted"),
        ("quota_exhausted", "quota_exceeded"),
    ]

    def __init__(self, *, status_code: int, detail: str, response_text: str = "") -> None:
        self.status_code = status_code
        self.detail = detail or ""
        self.response_text = response_text or ""
        super().__init__(f"hub_error status={status_code}: {self.detail[:200]}")

    def classify(self) -> str:
        haystack = (self.detail + " " + self.response_text).lower()
        for cat, key in self._CATEGORY_PATTERNS:
            if key.lower() in haystack:
                return cat
        return "unknown"

    def actionable_hint(self) -> str:
        cat = self.classify()
        if cat == "account_overdue":
            return "火山方舟账号余额不足 — 去 console.volcengine.com/finance/account 充值后重跑"
        if cat == "content_sensitive":
            return (
                "首帧图含真实人脸被 Seedance 内容审查拦截（平台硬规则，AI 生成图也会触发）。"
                "✅ 要保留人物：重跑 step 7 时加 skip_first_frame_scene_nums=[<失败的 scene_no>]，"
                "改 t2v 模式让 Seedance 自己从 prompt 生成角色（不传首帧）。"
                "⚠️ 要固定特定真人脸：需走火山方舟数字人 API（不同流程，需单独申请）。"
            )
        if cat == "model_not_open":
            return "火山方舟模型未激活 — 去 console.volcengine.com/ark 开通 inference 服务"
        if cat == "rate_limited":
            return "频率限制 — 等 1-2min 重跑，或降低并发段数"
        if cat == "quota_exhausted":
            return "配额耗尽 — 检查火山方舟控制台月度配额"
        return f"未知错误（HTTP {self.status_code}）— 详情见 detail"


async def _post_hub(cli: httpx.AsyncClient, url: str, body: dict) -> dict:
    """统一 hub POST：失败时把详情 dump 到 HubError，调用方负责 classify。"""
    r = await cli.post(url, json=body)
    if r.status_code >= 400:
        detail = ""
        try:
            payload = r.json() or {}
            detail = payload.get("detail") or payload.get("error") or payload.get("message", "")
        except Exception:
            detail = r.text[:500]
        raise HubError(
            status_code=r.status_code,
            detail=str(detail),
            response_text=r.text[:1000],
        )
    return r.json()


class AIHubClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
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
            body["reference_images"] = _localize_list(refs)
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
            body["reference_images"] = _localize_list(refs)
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            return await _post_hub(cli, f"{self.base_url}/api/v1/ai/videos/generate", body)

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

    # ── W2 v2 接口（多类 refs + 首尾帧）───────────────────────────────────────
    # hub openapi 实测（2026-05-04）：
    #   ImageGenerateRequest 磁盘源已支持 reference_images: list[dict]
    #     形如 {url, type(character|product), weight}；运行容器 image 较旧、
    #     额外字段静默丢弃（Pydantic 默认 ignore）；W3 重启 hub 后自动启用。
    #   VideoGenerateRequest 已实装：first_frame / last_frame / reference_images
    #     （list[str | dict]，dict 含 url/type/weight）/ content（VideoContentItem
    #     带 role 字段）—— 即时可用。
    # 设计：v2 用 reference_images 数组，每个元素是 {url, type, weight} dict，
    #   type 取 face|product|style；image 同样发，旧容器降级（refs 被丢，至少 prompt 落地）。
    async def generate_image_v2(
        self,
        prompt: str,
        *,
        face_refs: list[str] | None = None,
        product_refs: list[str] | None = None,
        style_refs: list[str] | None = None,
        aspect: str = "9:16",
        n: int = 1,
        model: str = "gpt-image-2",
        provider: str = "openai",
        quality: str | None = None,
        size: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        """W2: image gen with multi-class refs (face / product / style)。

        body shape：
          - reference_images: [{url, type, weight}, ...]  type ∈ {face, product, style}
          - aspect_ratio: 字符串（hub ImageGenerateRequest 当前用 size，但视频侧已统一用
            aspect_ratio；这里两个字段都带，hub 不识别的会被静默丢）
          - quality: 'low' / 'medium' / 'high' / 'auto'（gpt-image-2 推荐 'high' 锁脸）
        """
        refs: list[dict[str, Any]] = []
        for r in _localize_list(face_refs) or []:
            refs.append({"url": r, "type": "face", "weight": 1.0})
        for r in _localize_list(product_refs) or []:
            refs.append({"url": r, "type": "product", "weight": 1.0})
        for r in _localize_list(style_refs) or []:
            refs.append({"url": r, "type": "style", "weight": 0.5})

        body: dict[str, Any] = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "n": n,
            "aspect_ratio": aspect,
        }
        if quality:
            body["quality"] = quality
        if size:
            body["size"] = size
        if refs:
            body["reference_images"] = refs
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.base_url}/api/v1/ai/images/generate", json=body)
            r.raise_for_status()
            return r.json()

    async def generate_video_v2(
        self,
        prompt: str,
        *,
        first_frame: str | None = None,
        last_frame: str | None = None,
        duration_sec: int = 8,
        face_refs: list[str] | None = None,
        product_refs: list[str] | None = None,
        aspect: str = "9:16",
        model: str = "seedance-2-0",
        provider: str = "seedance",
        extra: dict[str, Any] | None = None,
    ) -> dict:
        """W2: video gen with first / last frame + multi-class refs.

        hub VideoGenerateRequest 原生支持 first_frame / last_frame / reference_images
        （list[str | dict]，dict 含 url/type/weight），直接对接。
        """
        body: dict[str, Any] = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "duration": duration_sec,
            "aspect_ratio": aspect,
        }
        if first_frame:
            body["first_frame"] = _localize_url(first_frame)
        if last_frame:
            body["last_frame"] = _localize_url(last_frame)
        refs: list[dict[str, Any]] = []
        for r in _localize_list(face_refs) or []:
            refs.append({"url": r, "type": "face", "weight": 1.0})
        for r in _localize_list(product_refs) or []:
            refs.append({"url": r, "type": "product", "weight": 1.0})
        if refs:
            body["reference_images"] = refs
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            return await _post_hub(cli, f"{self.base_url}/api/v1/ai/videos/generate", body)
