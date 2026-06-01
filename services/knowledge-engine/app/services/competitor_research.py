"""竞品调研 service（W1 竞品调研切片 · 2026-06-01）。

职责（浏览器层在 scout-agent，LLM 层在 competitor.py tool；本 service 是中间胶水）：
- scout_search / scout_detail：HTTP 调 scout-agent 的淘宝抓取端点
- fetch_image_data_uri：把 alicdn CDN 图（公开可取，无需登录）下载 → 归一成
  `data:image/jpeg;base64,...`。必须转 data URI：ai-provider-hub 的 gemini chat
  只把 `data:` 块转 inline_data，普通 http url 会被当成 `[Image: url]` 文本（不真看图）。
  顺带 webp→jpeg + 最长边压到 max_dim，控制多模态请求体大小。
- render_listing_markdown：把搜索榜单渲成 markdown 表

老板选了"只出 md 报告"——本 service 不落任何 DB。
"""
from __future__ import annotations

import base64
import io
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 取 alicdn 图时带上浏览器 UA + 淘宝 referer，规避个别防盗链
_IMG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://www.taobao.com/",
}


# ─────────────────────────── scout-agent HTTP ───────────────────────────

async def scout_search(
    query: str, top_n: int = 50, headless: bool | None = None,
    max_pages: int = 3, timeout: float = 180.0,
) -> dict:
    """POST scout-agent /taobao/search。返回 scout 原始 dict（含 ok/items/debug 或 error）。"""
    body: dict[str, Any] = {"query": query, "top_n": top_n, "max_pages": max_pages}
    if headless is not None:
        body["headless"] = headless
    url = f"{settings.scout_agent_url.rstrip('/')}/api/v1/scout/taobao/search"
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.post(url, json=body)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": "scout_http_error",
                "hint": f"scout-agent 返 {exc.response.status_code}: {exc.response.text[:300]}"}
    except Exception as exc:
        return {"ok": False, "error": "scout_unreachable",
                "hint": f"连不上 scout-agent ({url}): {type(exc).__name__}: {exc}. "
                        "确认 scout-agent 容器在跑（docker ps）。"}


async def scout_detail(
    item_url: str, headless: bool | None = None, scroll_steps: int = 12,
    search_query: str | None = None, timeout: float = 200.0,
) -> dict:
    """POST scout-agent /taobao/detail。search_query 给了就"先搜再进"绕详情页验证码。返回 scout 原始 dict。"""
    body: dict[str, Any] = {"item_url": item_url, "scroll_steps": scroll_steps}
    if headless is not None:
        body["headless"] = headless
    if search_query:
        body["search_query"] = search_query
    url = f"{settings.scout_agent_url.rstrip('/')}/api/v1/scout/taobao/detail"
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.post(url, json=body)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": "scout_http_error",
                "hint": f"scout-agent 返 {exc.response.status_code}: {exc.response.text[:300]}"}
    except Exception as exc:
        return {"ok": False, "error": "scout_unreachable",
                "hint": f"连不上 scout-agent ({url}): {type(exc).__name__}: {exc}"}


async def scout_detail_shots(
    item_url: str, headless: bool | None = None, search_query: str | None = None,
    max_shots: int = 9, timeout: float = 240.0,
) -> dict:
    """POST scout-agent /taobao/detail_shots（移动 H5 滚动截图）。返回 {ok, blocked, shots:[base64], ...}。"""
    body: dict[str, Any] = {"item_url": item_url, "max_shots": max_shots}
    if headless is not None:
        body["headless"] = headless
    if search_query:
        body["search_query"] = search_query
    url = f"{settings.scout_agent_url.rstrip('/')}/api/v1/scout/taobao/detail_shots"
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.post(url, json=body)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": "scout_http_error",
                "hint": f"scout-agent 返 {exc.response.status_code}: {exc.response.text[:300]}"}
    except Exception as exc:
        return {"ok": False, "error": "scout_unreachable",
                "hint": f"连不上 scout-agent: {type(exc).__name__}: {exc}"}


# ─────────────────────────── 图片处理 ───────────────────────────

# alicdn 缩略图常见尾缀：name.jpg_400x400q90.jpg / name.jpg_60x60.jpg /
# name.jpg_.webp / name.jpg_q50.jpg / name_400x400.jpg
_SIZE_SUFFIX_RE = re.compile(
    r"(\.(?:jpg|jpeg|png|webp))_(?:\d+x\d+)?(?:xz)?(?:q\d+)?(?:\.(?:jpg|jpeg|png|webp)|_\.webp)?$",
    re.IGNORECASE,
)


def upscale_alicdn(url: str) -> str:
    """保守去掉 alicdn 缩略尾缀拿更大原图；任何拿不准就返原 url。"""
    if not url or "alicdn" not in url and "aliimg" not in url:
        return url
    m = _SIZE_SUFFIX_RE.search(url)
    if m:
        # 把 'name.jpg_400x400q90.jpg' → 'name.jpg'（保留 group(1) 的真扩展名）
        return url[: m.start()] + m.group(1)
    return url


async def fetch_image_data_uri(
    cli: httpx.AsyncClient, url: str, *, max_dim: int = 1280, jpeg_q: int = 82,
    max_raw_bytes: int = 12_000_000,
) -> str | None:
    """下载图 → RGB JPEG（最长边 max_dim）→ data:image/jpeg;base64,...。失败返 None。"""
    if not url:
        return None
    try:
        from PIL import Image
    except Exception:
        Image = None  # type: ignore

    for candidate in (upscale_alicdn(url), url):
        try:
            r = await cli.get(candidate, headers=_IMG_HEADERS, follow_redirects=True)
            if r.status_code != 200 or not r.content:
                continue
            raw = r.content
            if len(raw) > max_raw_bytes:
                continue
            if Image is None:
                # PIL 不可用：直接按响应 content-type 包 data URI（webp 可能 gemini 不收，但兜底）
                mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
                return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
            with Image.open(io.BytesIO(raw)) as im:
                if im.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    rgba = im.convert("RGBA")
                    bg.paste(rgba, mask=rgba.split()[-1] if "A" in rgba.getbands() else None)
                    im = bg
                elif im.mode != "RGB":
                    im = im.convert("RGB")
                w, h = im.size
                longest = max(w, h)
                if longest > max_dim:
                    s = max_dim / longest
                    im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=jpeg_q, optimize=True)
                jpeg = buf.getvalue()
            return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        except Exception as exc:
            logger.debug("fetch_image_data_uri failed %s: %s", candidate[:80], exc)
            continue
    return None


async def fetch_images_as_blocks(
    urls: list[str], *, max_count: int, max_dim: int = 1280,
) -> tuple[list[dict], list[str]]:
    """批量取图 → OpenAI 风多模态 image_url 块（data URI）。返回 (blocks, ok_urls)。"""
    picked = [u for u in (urls or []) if u][:max_count]
    blocks: list[dict] = []
    ok_urls: list[str] = []
    if not picked:
        return blocks, ok_urls
    async with httpx.AsyncClient(timeout=30.0) as cli:
        for u in picked:
            data_uri = await fetch_image_data_uri(cli, u, max_dim=max_dim)
            if data_uri:
                blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
                ok_urls.append(u)
    return blocks, ok_urls


def read_local_images_as_blocks(
    paths: list[str], *, max_count: int, max_dim: int = 1400, jpeg_q: int = 82,
) -> tuple[list[dict], list[str]]:
    """本地图片文件（容器内路径，如 /host/Desktop/x.jpg）→ 多模态图块。返回 (blocks, ok_paths)。

    给"手动截图"路线用：老板自己截的详情页图丢到挂载目录，KE 读出来喂视觉模型。
    """
    import os
    try:
        from PIL import Image
    except Exception:
        Image = None  # type: ignore
    blocks: list[dict] = []
    ok: list[str] = []
    for path in (paths or [])[:max_count]:
        try:
            if not path or not os.path.exists(path):
                logger.warning("read_local_images: missing %s", path)
                continue
            if Image is None:
                with open(path, "rb") as f:
                    raw = f.read()
                blocks.append({"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")}})
                ok.append(path)
                continue
            with Image.open(path) as im:
                if im.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    rgba = im.convert("RGBA")
                    bg.paste(rgba, mask=rgba.split()[-1] if "A" in rgba.getbands() else None)
                    im = bg
                elif im.mode != "RGB":
                    im = im.convert("RGB")
                w, h = im.size
                longest = max(w, h)
                if longest > max_dim:
                    s = max_dim / longest
                    im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=jpeg_q, optimize=True)
                jpeg = buf.getvalue()
            blocks.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}})
            ok.append(path)
        except Exception as exc:
            logger.warning("read_local_images failed %s: %s", path, exc)
    return blocks, ok


# ─────────────────────────── markdown 渲染 ───────────────────────────

def render_listing_markdown(
    query: str, items: list[dict], skipped: list[dict] | None = None,
    platform: str = "淘宝",
) -> str:
    """搜索榜单 → markdown 表（rank/标题/显示价/月销/店铺/链接）。"""
    lines = [
        f"# 竞品榜单：{platform}「{query}」",
        "",
        f"共 **{len(items)}** 个相关商品（已过滤掉不相关的{(' ' + str(len(skipped)) + ' 个') if skipped else ''}）。",
        "",
        "> 价格=搜索页**显示价**（可能是券前标价/预估，非加购后真到手价）；月销淘宝部分已隐藏，缺则标 —。",
        "",
        "| # | 标题 | 显示价 | 月销 | 店铺 | 链接 |",
        "|---|---|---|---|---|---|",
    ]
    for it in items:
        title = (it.get("title") or "").replace("|", "／").strip()[:60]
        price = it.get("price") or "—"
        sales = it.get("sales_text") or "—"
        shop = (it.get("shop") or "—").replace("|", "／")[:20]
        url = it.get("item_url") or ""
        link = f"[打开]({url})" if url else "—"
        lines.append(f"| {it.get('rank', '?')} | {title} | {price} | {sales} | {shop} | {link} |")
    if skipped:
        lines += ["", "<details><summary>跳过的不相关商品（" + str(len(skipped)) + "）</summary>", ""]
        for s in skipped[:30]:
            lines.append(f"- ~~{(s.get('title') or '')[:50]}~~ — {s.get('reason') or '不相关'}")
        lines += ["", "</details>"]
    lines += [
        "",
        "**下一步**：挑你想深拆的商品（给我序号或链接），我对每个出"
        "「卖点/构图/配色/设计/内容」拆解。",
    ]
    return "\n".join(lines)
