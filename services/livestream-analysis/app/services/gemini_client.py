"""Gemini API 客户端 — File API 上传 + generateContent 分析"""

import logging
import time
import functools
from typing import Callable, Any

import requests
from pathlib import Path

from app.config import Settings
from app.models import FileInfo

logger = logging.getLogger("livestream-analysis")


class GeminiAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def retry_with_backoff(
    max_retries: int = 2,
    base_delay: float = 3.0,
    retryable_status_codes: tuple = (429, 500, 503),
) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    sc = getattr(e, "status_code", None)
                    if sc and sc not in retryable_status_codes:
                        raise
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning("attempt %d failed, retry in %.0fs: %s", attempt + 1, delay, e)
                        time.sleep(delay)
                    else:
                        raise
            raise last_exception  # type: ignore
        return wrapper
    return decorator


class GeminiClient:
    BASE_URL = "https://generativelanguage.googleapis.com"

    def __init__(self, settings: Settings):
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.timeout = settings.request_timeout_seconds
        self.max_retries = settings.max_retries
        self.poll_interval = settings.upload_poll_interval_seconds
        self.poll_max_wait = settings.upload_poll_max_wait_seconds
        self.temperature = settings.gemini_temperature
        self.max_output_tokens = settings.gemini_max_output_tokens
        self.proxies: dict[str, str] = {}
        if settings.https_proxy:
            self.proxies["https"] = settings.https_proxy
        if settings.http_proxy:
            self.proxies["http"] = settings.http_proxy

    def _headers(self, **extra: str) -> dict:
        h = {"x-goog-api-key": self.api_key}
        h.update(extra)
        return h

    # ------------------------------------------------------------------
    def upload_video(self, video_path: str, display_name: str | None = None) -> FileInfo:
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        file_size = path.stat().st_size
        if display_name is None:
            display_name = path.stem
        mime_type = "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"

        upload_url = self._initiate_upload(file_size, mime_type, display_name)
        file_info = self._upload_bytes(upload_url, path, file_size)
        file_info = self._poll_state(file_info.name)
        return file_info

    def _initiate_upload(self, size: int, mime: str, name: str) -> str:
        url = f"{self.BASE_URL}/upload/v1beta/files"
        headers = self._headers(**{
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        })
        resp = requests.post(url, headers=headers, json={"file": {"display_name": name}},
                             timeout=60, proxies=self.proxies)
        if resp.status_code != 200:
            raise GeminiAPIError(f"初始化上传失败: {resp.status_code} {resp.text}",
                                 status_code=resp.status_code, response_body=resp.text)
        upload_url = resp.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            raise GeminiAPIError("响应中缺少 X-Goog-Upload-URL header")
        return upload_url

    def _upload_bytes(self, upload_url: str, file_path: Path, file_size: int) -> FileInfo:
        headers = {
            "Content-Length": str(file_size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }
        data = file_path.read_bytes()
        resp = requests.put(upload_url, headers=headers, data=data, timeout=self.timeout)
        if resp.status_code != 200:
            raise GeminiAPIError(f"文件上传失败: {resp.status_code} {resp.text}",
                                 status_code=resp.status_code, response_body=resp.text)
        fd = resp.json().get("file", {})
        return FileInfo(name=fd.get("name", ""), uri=fd.get("uri", ""),
                        state=fd.get("state", "PROCESSING"), mime_type=fd.get("mimeType", "video/mp4"))

    def _poll_state(self, file_name: str) -> FileInfo:
        url = f"{self.BASE_URL}/v1beta/{file_name}"
        headers = self._headers()
        elapsed = 0
        while elapsed < self.poll_max_wait:
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code != 200:
                raise GeminiAPIError(f"查询文件状态失败: {resp.status_code} {resp.text}",
                                     status_code=resp.status_code)
            fd = resp.json()
            state = fd.get("state", "PROCESSING")
            if state == "ACTIVE":
                return FileInfo(name=fd.get("name", ""), uri=fd.get("uri", ""),
                                state=state, mime_type=fd.get("mimeType", "video/mp4"))
            if state == "FAILED":
                raise GeminiAPIError(f"文件处理失败: {fd.get('error', {}).get('message', '未知错误')}")
            time.sleep(self.poll_interval)
            elapsed += self.poll_interval
        raise GeminiAPIError(f"文件处理超时（等待 {self.poll_max_wait}s）")

    # ------------------------------------------------------------------
    @retry_with_backoff(max_retries=2, base_delay=3.0)
    def analyze_video(self, file_uri: str, mime_type: str, prompt: str) -> dict:
        url = f"{self.BASE_URL}/v1beta/models/{self.model}:generateContent"
        headers = self._headers(**{"Content-Type": "application/json"})
        body = {
            "contents": [{
                "parts": [
                    {"file_data": {"mime_type": mime_type, "file_uri": file_uri}},
                    {"text": prompt},
                ]
            }],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        logger.info("调用 Gemini 分析视频...")
        resp = requests.post(url, headers=headers, json=body, timeout=self.timeout, proxies=self.proxies)
        if resp.status_code != 200:
            raise GeminiAPIError(f"generateContent 失败: {resp.status_code} {resp.text}",
                                 status_code=resp.status_code, response_body=resp.text)
        return resp.json()

    def delete_file(self, file_name: str) -> bool:
        url = f"{self.BASE_URL}/v1beta/{file_name}"
        try:
            resp = requests.delete(url, headers=self._headers(), timeout=30)
            return resp.status_code == 200
        except Exception as e:
            logger.warning("删除远程文件失败（非致命）: %s", e)
            return False

    # ------------------------------------------------------------------
    def test_connection(self) -> dict:
        """测试 API Key 有效性，返回模型信息"""
        url = f"{self.BASE_URL}/v1beta/models/{self.model}"
        resp = requests.get(url, headers=self._headers(), timeout=30, proxies=self.proxies)
        if resp.status_code != 200:
            raise GeminiAPIError(f"API Key 验证失败: {resp.status_code}",
                                 status_code=resp.status_code, response_body=resp.text)
        return resp.json()
