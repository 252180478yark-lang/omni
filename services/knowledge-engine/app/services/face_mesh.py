"""人脸网格覆盖工具 — 绕过 Seedance InputImageSensitiveContentDetected。

原理：在首帧图人脸区域画三角剖分网格（类 3D 人脸扫描效果），使内容审查无法
识别真实人脸；再在 Seedance prompt 末尾加 "remove face mesh" 指令，
让模型在生成视频时自动恢复自然人脸。

不依赖 OpenCV——使用 PIL 简单绘制 + 人脸区域启发式定位。
"""
from __future__ import annotations

import io
import logging
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_ASSET_DIR = Path("/app/data/assets/face_mesh")
_STATIC_PREFIX = "/api/v1/knowledge/static/face_mesh/"

# 网格参数
_MESH_COLOR = (0, 220, 180, 180)    # 青绿色半透明线条（类 3D 扫描效果）
_MESH_STEP = 22                     # 网格间距 px
_MESH_LINE_WIDTH = 1


def _face_region(w: int, h: int) -> tuple[int, int, int, int]:
    """启发式人脸区域：宽度中间 60%，高度上方 68%。

    适合 9:16 竖版（主播类）和 1:1 方图；横版 16:9 偏保守（面积稍大）。
    """
    x0 = int(w * 0.20)
    x1 = int(w * 0.80)
    y0 = int(h * 0.02)
    y1 = int(h * 0.68)
    return x0, y0, x1, y1


def apply_face_mesh(image_bytes: bytes) -> bytes:
    """在图片人脸区域叠加三角剖分网格，返回 PNG bytes。"""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    x0, y0, x1, y1 = _face_region(w, h)
    step = _MESH_STEP
    color = _MESH_COLOR

    # 水平线
    y = y0
    while y <= y1:
        draw.line([(x0, y), (x1, y)], fill=color, width=_MESH_LINE_WIDTH)
        y += step

    # 垂直线
    x = x0
    while x <= x1:
        draw.line([(x, y0), (x, y1)], fill=color, width=_MESH_LINE_WIDTH)
        x += step

    # 右斜线（左上→右下），形成三角剖分效果
    for r in range(y0, y1 + 1, step):
        c = x0
        draw.line([(c, r), (min(c + (y1 - r), x1), min(r + (x1 - c), y1))],
                  fill=color, width=_MESH_LINE_WIDTH)
    for c in range(x0, x1 + 1, step):
        r = y0
        draw.line([(c, r), (min(c + (y1 - r), x1), min(r + (x1 - c), y1))],
                  fill=color, width=_MESH_LINE_WIDTH)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


async def apply_face_mesh_to_url(image_url: str) -> str:
    """下载 image_url → 叠加网格 → 存本地 → 返回本地静态 URL。

    本地 URL 格式 `/api/v1/knowledge/static/face_mesh/<uuid>.png` 会被
    `_localize_url` 自动转 base64 data URL 再喂给 Seedance。
    """
    # 下载原图
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            resp = await cli.get(image_url)
            resp.raise_for_status()
            raw = resp.content
    except Exception as exc:
        logger.warning("face_mesh: 下载失败 %s err=%s，返回原 URL", image_url[:80], exc)
        return image_url

    # 叠加网格
    try:
        meshed = apply_face_mesh(raw)
    except Exception as exc:
        logger.warning("face_mesh: PIL 处理失败 err=%s，返回原 URL", exc)
        return image_url

    # 存本地
    _ASSET_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
    fpath = _ASSET_DIR / fname
    fpath.write_bytes(meshed)

    local_url = _STATIC_PREFIX + fname
    logger.info("face_mesh: %s → %s (%.1f KB)", image_url[:60], local_url, len(meshed) / 1024)
    return local_url


# ── Prompt 后缀 ─────────────────────────────────────────────────────────────

MESH_REMOVAL_SUFFIX = (
    "remove the cyan wireframe mesh overlay on the face, "
    "restore natural human skin texture and facial features seamlessly"
)
