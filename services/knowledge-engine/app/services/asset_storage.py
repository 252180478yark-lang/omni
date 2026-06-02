"""资产磁盘存储（W4-B 切片 14.4 phase D 候选 D）。

目的：把生成端拿到的 cdn url / base64 资产**异步落到本地磁盘**，永久保留。

背景痛点（§三十九 教训 3）：
- 火山方舟 seedance / seedream cdn url 24h 过期（X-Tos-Expires=86400）
- OpenAI gpt-image 返 url 也短期过期（~1h）
- 之前 pipeline.assets.file_url 直接存 cdn url → 24h 后老板回头打开是 404

方案：
- 资产生成完后落 disk → file_url 存本地 path（`/api/v1/knowledge/static/<sku>/<uuid>.ext`）
- 浏览器请求 → nginx `/api/v1/knowledge/` 路由 → KE FastAPI StaticFiles → 直接发文件
- 落盘失败兜底回原 url（不挡链路）

磁盘根：`/app/data/assets/{sku_id}/{uuid}.{ext}`（容器内）
volume 映射：docker-compose `knowledge_data:/app/data` → 宿主机持久化
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# 磁盘根（容器内绝对路径）
ASSETS_ROOT: Final[Path] = Path("/app/data/assets")

# 对外访问 url 前缀（nginx + FastAPI StaticFiles mount 路径）
PUBLIC_URL_PREFIX: Final[str] = "/api/v1/knowledge/static"

# mime → ext 映射（data: url 解析用）
_MIME_TO_EXT: Final[dict[str, str]] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "audio/mpeg": "mp3",
}

# url path 后缀提取
_URL_EXT_RE: Final[re.Pattern[str]] = re.compile(r"\.([a-zA-Z0-9]{2,5})(?:$|\?|#)")


def _safe_sku_dir(sku_id: str) -> str:
    """把 sku_id 转成磁盘安全的目录名（防穿越攻击/特殊字符）。"""
    safe = re.sub(r"[^A-Za-z0-9_\-.]", "_", sku_id or "unknown")
    return safe[:128] or "unknown"


def _ext_from_data_url(data_url: str) -> str:
    """data:image/png;base64,... → 'png'。"""
    m = re.match(r"data:([^;,]+)[;,]", data_url)
    if not m:
        return "bin"
    return _MIME_TO_EXT.get(m.group(1).lower(), "bin")


def _ext_from_http_url(url: str, asset_type: str | None) -> str:
    """从 http url path 推 ext，找不到时按 asset_type 兜底（image→png, video→mp4）。"""
    try:
        path = urlparse(url).path or ""
        m = _URL_EXT_RE.search(path)
        if m:
            ext = m.group(1).lower()
            # 一些常见保留
            if ext in {"png", "jpg", "jpeg", "webp", "gif", "mp4", "mov", "webm"}:
                return "jpg" if ext == "jpeg" else ext
    except Exception:
        pass
    if asset_type == "video":
        return "mp4"
    if asset_type in {"image", "character_sheet"}:
        return "png"
    return "bin"


def _is_already_local(url: str) -> bool:
    """已经是本地 url（idempotent 跳过下载）。"""
    return url.startswith(PUBLIC_URL_PREFIX + "/")


async def _download_http(url: str, *, timeout_s: float = 120.0) -> bytes:
    """异步下载远端 url。失败抛异常。"""
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        return r.content


def _decode_data_url(data_url: str) -> bytes:
    """data:image/png;base64,xxxxxx → bytes。"""
    head, _, body = data_url.partition(",")
    if not body:
        raise ValueError("data url has empty body")
    if ";base64" in head.lower():
        return base64.b64decode(body)
    # 非 base64 的 data url（urlencoded text）— 当前 omni 链路不会走到这
    from urllib.parse import unquote
    return unquote(body).encode("utf-8")


def _decode_raw_base64(s: str) -> bytes:
    """裸 base64 字符串（无 data: 前缀）→ bytes。"""
    return base64.b64decode(s)


def _looks_like_base64(s: str) -> bool:
    """启发：是否裸 base64（无 http / 无 data: 前缀，长度 > 200，全是 base64 字符）。"""
    if not s or len(s) < 200:
        return False
    if s.startswith(("http://", "https://", "data:", "/")):
        return False
    # base64 字符集：A-Z a-z 0-9 + / =
    return bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", s[:512]))


async def persist_asset_to_disk(
    source: str,
    *,
    sku_id: str,
    asset_type: str,
    timeout_s: float = 120.0,
) -> str:
    """把 source（cdn url / data url / 裸 base64）转存到本地磁盘，返本地访问 url。

    Args:
        source: 资产源（http(s)://... / data:... / 裸 base64）
        sku_id: SKU id（落到 `/app/data/assets/<sku_id>/...` 子目录）
        asset_type: 'image' / 'video' / 'character_sheet' / 'audio'（推 ext 时兜底）
        timeout_s: 下载超时

    Returns:
        本地访问 url：`/api/v1/knowledge/static/<sku_safe>/<uuid>.<ext>`

    Raises:
        失败时抛异常，**调用方负责 fallback 原 url**（保命，链路不挂）。
    """
    if not source:
        raise ValueError("empty source")

    # idempotent：已经是本地 url 直接返
    if _is_already_local(source):
        return source

    # 1. 解出 bytes + ext
    if source.startswith("data:"):
        ext = _ext_from_data_url(source)
        data = _decode_data_url(source)
    elif source.startswith(("http://", "https://")):
        ext = _ext_from_http_url(source, asset_type)
        data = await _download_http(source, timeout_s=timeout_s)
    elif _looks_like_base64(source):
        # 火山方舟有时会返裸 base64（极少见，但 hub 层 _build_content 兜底过）
        ext = "png" if asset_type in {"image", "character_sheet"} else "mp4"
        data = _decode_raw_base64(source)
    else:
        raise ValueError(f"unrecognized asset source format (head={source[:40]!r})")

    # 2. 落盘
    sku_safe = _safe_sku_dir(sku_id)
    sku_dir = ASSETS_ROOT / sku_safe
    sku_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = sku_dir / filename

    # 异步写盘（asyncio.to_thread 避免阻塞 event loop）
    await asyncio.to_thread(dest.write_bytes, data)

    local_url = f"{PUBLIC_URL_PREFIX}/{sku_safe}/{filename}"
    logger.info(
        "persist_asset_to_disk ok: sku=%s type=%s bytes=%d → %s",
        sku_id, asset_type, len(data), local_url,
    )
    return local_url


async def persist_or_fallback(
    source: str | None,
    *,
    sku_id: str,
    asset_type: str,
    timeout_s: float = 120.0,
) -> tuple[str | None, str | None]:
    """对 source 试落盘；失败回原 url。返 (final_url, error_or_None)。

    供 save_storyboard_asset 兜底用：永远不让落盘失败挡链路。
    """
    if not source:
        return None, None
    try:
        local = await persist_asset_to_disk(
            source, sku_id=sku_id, asset_type=asset_type, timeout_s=timeout_s,
        )
        return local, None
    except Exception as exc:
        logger.warning(
            "persist_asset_to_disk failed (fallback to original): sku=%s type=%s "
            "head=%r err=%s",
            sku_id, asset_type, (source or "")[:60], exc,
        )
        return source, f"{type(exc).__name__}: {exc}"


def get_disk_path_for_public_url(public_url: str) -> Path | None:
    """反查：`/api/v1/knowledge/static/<sku>/<file>` → `/app/data/assets/<sku>/<file>`。
    用于回填脚本/管理工具检查文件是否存在。"""
    if not _is_already_local(public_url):
        return None
    rel = public_url[len(PUBLIC_URL_PREFIX) + 1:]  # 去掉前缀 + '/'
    if ".." in rel or rel.startswith("/"):
        return None
    return ASSETS_ROOT / rel


def asset_disk_exists(public_url: str) -> bool:
    """本地 url 对应的磁盘文件是否真的存在。"""
    p = get_disk_path_for_public_url(public_url)
    return bool(p and p.exists())
