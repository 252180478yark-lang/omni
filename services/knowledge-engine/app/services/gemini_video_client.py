"""Gemini Files API 视频分析客户端。

绕过 ai-provider-hub 直调 google-generativeai SDK,目的是支持大视频
（hub 当前只支持 inline_data ≤20MB,reverse_storyboard_video 测试视频 25MB+）。

用法见 app.mcp.tools.media.reverse_storyboard_video
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from app.services.gemini_proxy_patch import patch_httplib2_for_proxy

# 模块加载期一次性 patch httplib2,Files API 上传走代理
patch_httplib2_for_proxy()

logger = logging.getLogger(__name__)


class GeminiVideoClient:
    """单实例对应一个 model_id,可复用调多次 analyze_video。"""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY 未配置 (检查 docker-compose KE service env_file 是否读 ai-provider-hub/.env)"
            )

        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                f"google-generativeai 未安装,需要 pip install 'google-generativeai>=0.8.0' (Dockerfile rebuild?): {exc}"
            )

        # transport='rest' 关键:gRPC 在国内代理下经常 hang,REST 稳很多 (参考 video-analysis/analysis.py)
        genai.configure(api_key=key, transport="rest")
        self._genai = genai
        self.model_id = model
        self.model = genai.GenerativeModel(model)

    async def analyze_video(
        self,
        video_path: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 16000,
        poll_timeout_sec: int = 180,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """上传视频 + LLM 分析,返回 (parsed_json, usage_meta)。

        - 上传期 3 次重试 (SSL/EOF/connection 错误)
        - 等 ACTIVE 期 poll_interval=3s,total 上限 poll_timeout_sec
        - LLM 输出强制 JSON (response_mime_type=application/json)
        - 解析失败时 fallback 用 regex 抽 {...} 块
        - finally 删 uploaded file (TTL 48h 反正会自动删,显式删省额度)
        """
        genai = self._genai
        upload_path = os.path.abspath(video_path)
        if not os.path.exists(upload_path):
            raise FileNotFoundError(f"video_path 不存在: {upload_path}")

        # ── 1. upload (重试 3 次) ──
        last_err: Exception | None = None
        video_file = None
        for attempt in range(3):
            try:
                logger.info(f"[gemini-video] upload attempt {attempt+1}/3: {upload_path}")
                video_file = await asyncio.to_thread(genai.upload_file, upload_path)
                break
            except Exception as exc:
                last_err = exc
                msg = str(exc).lower()
                retryable = any(k in msg for k in ("ssl", "eof", "connection", "retries exceeded"))
                if not retryable or attempt == 2:
                    raise
                logger.warning(f"[gemini-video] upload retryable: {exc}, retry in 2s")
                await asyncio.sleep(2)
        if video_file is None:
            raise last_err or RuntimeError("upload_file failed without exception")

        upload_start_to_active = time.time()
        try:
            # ── 2. poll ACTIVE ──
            logger.info(f"[gemini-video] uploaded as {video_file.name}, polling for ACTIVE")
            poll_interval = 3
            waited = 0
            while waited < poll_timeout_sec:
                try:
                    file_status = await asyncio.to_thread(genai.get_file, video_file.name)
                except Exception as exc:
                    msg = str(exc).lower()
                    if any(k in msg for k in ("ssl", "eof", "connection")) and waited < poll_timeout_sec - 6:
                        await asyncio.sleep(2)
                        waited += 2
                        continue
                    raise
                state = getattr(file_status, "state", None)
                state_name = getattr(state, "name", str(state)) if state else ""
                if state_name == "ACTIVE":
                    break
                if state_name == "FAILED":
                    raise RuntimeError(f"Gemini file processing FAILED: {video_file.name}")
                await asyncio.sleep(poll_interval)
                waited += poll_interval
            else:
                raise TimeoutError(
                    f"等待 file ACTIVE 超过 {poll_timeout_sec}s,最后状态: {state_name}"
                )

            upload_elapsed = time.time() - upload_start_to_active
            logger.info(f"[gemini-video] file ACTIVE in {upload_elapsed:.1f}s,开始 generate_content (streaming)")

            # ── 3. generate_content (STREAMING + JSON 强制输出) ──
            # 为啥 streaming: 国内代理(FlClash 等)会切断长 connection;非流式 generate
            # 16k token 输出要 60s+,代理超时切断 ProxyError;
            # streaming 每 chunk 短,TCP 连接持续活跃,FlClash 不切断。
            # streaming 也兼容代理通 (rest transport 默认).
            gen_start = time.time()

            def _stream_to_text():
                """同步流式收集所有 chunks 到一段 text + 收集 usage."""
                full_text_parts = []
                last_resp = None
                stream = self.model.generate_content(
                    [system_prompt, user_prompt, video_file],
                    generation_config={
                        "response_mime_type": "application/json",
                        "temperature": temperature,
                        "max_output_tokens": max_tokens,
                    },
                    stream=True,
                )
                for chunk in stream:
                    # chunk.text 是 property, 没 Part 时会 raise ValueError(不是返回 None)
                    # 用 candidates[0].content.parts 直接取,避免触发 quick accessor 校验
                    try:
                        cand = chunk.candidates[0] if chunk.candidates else None
                        if cand and cand.content and cand.content.parts:
                            for part in cand.content.parts:
                                pt = getattr(part, "text", None)
                                if pt:
                                    full_text_parts.append(pt)
                    except (ValueError, AttributeError, IndexError) as e:
                        # 空 chunk / safety filter / 结构异常 — skip 这个 chunk 继续下一个
                        logger.debug(f"[gemini-video] skip chunk: {type(e).__name__}: {e}")
                    last_resp = chunk
                return "".join(full_text_parts), last_resp

            text, last_chunk = await asyncio.to_thread(_stream_to_text)
            gen_elapsed = time.time() - gen_start
            logger.info(f"[gemini-video] generate done in {gen_elapsed:.1f}s (streaming), output_chars={len(text)}")

            # ── 4. parse JSON (regex fallback) ──
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                m = re.search(r"\{[\s\S]*\}", text)
                if not m:
                    raise RuntimeError(
                        f"LLM 未返回合法 JSON (前 500 字符): {text[:500]}"
                    )
                result = json.loads(m.group(0))

            # ── 5. usage meta (从最后一个 chunk 拿 usage_metadata) ──
            usage_meta_obj = getattr(last_chunk, "usage_metadata", None) if last_chunk else None
            usage = {
                "input_tokens": getattr(usage_meta_obj, "prompt_token_count", 0) if usage_meta_obj else 0,
                "output_tokens": getattr(usage_meta_obj, "candidates_token_count", 0) if usage_meta_obj else 0,
                "total_tokens": getattr(usage_meta_obj, "total_token_count", 0) if usage_meta_obj else 0,
                "upload_seconds": round(upload_elapsed, 1),
                "generate_seconds": round(gen_elapsed, 1),
            }
            return result, usage
        finally:
            # ── 6. delete uploaded file (TTL 48h,显式删省额度) ──
            try:
                await asyncio.to_thread(genai.delete_file, video_file.name)
                logger.info(f"[gemini-video] deleted {video_file.name}")
            except Exception as exc:
                logger.warning(f"[gemini-video] delete {video_file.name} failed (TTL 48h auto): {exc}")
