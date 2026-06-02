"""抖音分享链接解析 + 视频下载 service。

输入老板发的 v.douyin.com 短链(或 iesdouyin.com 长链) → 输出 KE 容器内
能直接喂 reverse_storyboard_video 的本地 mp4 路径。

走 SSR HTML 抠 play_addr.url_list 的路径,不依赖 cookies/签名,小视频(<60MB) 几秒拉完。

设计:
- 缓存目录默认 /host/Desktop/omni_video_cache(host bind-mount,KE 重启不丢)
- aweme_id 当缓存 key(同一视频不重复下载,老板反复反推一条视频零费用)
- playwm → play 替换试无水印(老抖音 web 端套路,这版 CDN 实测两版返同样视频)
- 多档失败码(短链失败/无 aweme_id/SSR 失败/无 play_addr/下载失败) 给前端友好 hint
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# KE 容器内 host bind-mount 的 Desktop(docker-compose volume 已配)
DEFAULT_CACHE_DIR = "/host/Desktop/omni_video_cache"

# 抖音 web SSR 走 mobile UA 拿到的 HTML 含完整 play_addr;桌面 UA 拿到的是 PC 版骨架
_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

_SHORT_HOST = "v.douyin.com"
_LONG_HOSTS = {"www.iesdouyin.com", "iesdouyin.com"}

_AWEME_ID_RE = re.compile(r"/share/video/(\d+)/")
_PLAYWM_URL_RE = re.compile(r'https?:[^"\']*?playwm[^"\']*')

# 抠混合文本里的抖音 URL。老板从 app 复制粘贴典型长这样:
#   "0.74 :1pm lCU:/ 07/07 婚后最可怕的... # 婚姻现实 https://v.douyin.com/oJAmOHtMYmw/ 复制此链接,打开Dou音搜索..."
# 用 \S+ 抓非空白,$ 不强求(末尾可能有标点)
_EXTRACT_DOUYIN_URL_RE = re.compile(
    r'https?://(?:v\.douyin\.com|(?:www\.)?iesdouyin\.com)/\S+',
    re.IGNORECASE,
)


def _extract_share_url_from_text(text: str) -> str | None:
    """从老板可能粘的整段分享文案里抠出抖音 URL。

    抠到的 URL 可能带尾巴标点(如 .../xxx/, ),用 rstrip 清掉。
    没抠到返 None,让上层 fallback 到原 is_douyin_share_url 判断。
    """
    if not text or not isinstance(text, str):
        return None
    m = _EXTRACT_DOUYIN_URL_RE.search(text)
    if not m:
        return None
    url = m.group(0).rstrip(',.;)、。，；） \t')  # 中英文常见末尾标点
    return url


def is_douyin_share_url(url: str) -> bool:
    """判断 url 是不是抖音分享链接(短链或长链)。"""
    if not url or not isinstance(url, str):
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == _SHORT_HOST or host in _LONG_HOSTS


def _decode_unicode_json_str(s: str) -> str:
    """把 JSON 里 \\u4f60\\u597d 这种序列解成中文。失败返原值。"""
    try:
        return s.encode("latin1", errors="ignore").decode("unicode_escape").encode("latin1").decode("utf-8")
    except Exception:
        return s


async def _resolve_short_link(client: httpx.AsyncClient, share_url: str) -> str | None:
    try:
        r = await client.get(
            share_url,
            headers={"User-Agent": _MOBILE_UA},
            follow_redirects=False,
            timeout=10.0,
        )
    except Exception as exc:
        logger.warning("douyin short link http error: %s", exc)
        return None
    if r.status_code not in (301, 302, 303, 307, 308):
        return None
    return r.headers.get("location")


def _extract_aweme_id(long_url: str) -> str | None:
    m = _AWEME_ID_RE.search(long_url)
    return m.group(1) if m else None


async def _fetch_ssr_html(client: httpx.AsyncClient, aweme_id: str) -> str | None:
    url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    try:
        r = await client.get(
            url,
            headers={"User-Agent": _MOBILE_UA},
            timeout=15.0,
            follow_redirects=True,
        )
    except Exception as exc:
        logger.warning("douyin SSR fetch error: %s", exc)
        return None
    if r.status_code != 200:
        return None
    return r.text


def _extract_playwm_url(html: str) -> str | None:
    m = _PLAYWM_URL_RE.search(html)
    if not m:
        return None
    return m.group(0).replace("\\u002F", "/")


def _extract_metadata(html: str) -> dict:
    out: dict = {}
    m_desc = re.search(r'"desc":"([^"]+)"', html)
    if m_desc:
        out["desc"] = _decode_unicode_json_str(m_desc.group(1))
    m_nick = re.search(r'"nickname":"([^"]+)"', html)
    if m_nick:
        out["author_nickname"] = _decode_unicode_json_str(m_nick.group(1))
    return out


async def _download(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    referer: str,
    max_bytes: int = 60 * 1024 * 1024,
) -> tuple[bool, str | None]:
    """下载 mp4 到 dest。返 (ok, error_msg)。"""
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        async with client.stream(
            "GET",
            url,
            headers={"User-Agent": _MOBILE_UA, "Referer": referer},
            timeout=60.0,
            follow_redirects=True,
        ) as r:
            if r.status_code != 200:
                return False, f"http_{r.status_code}"
            ctype = r.headers.get("content-type", "").lower()
            if "video" not in ctype and "octet-stream" not in ctype:
                return False, f"non_video_content_type:{ctype}"
            total = 0
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes(64 * 1024):
                    f.write(chunk)
                    total += len(chunk)
                    if total > max_bytes:
                        return False, f"too_large:>{max_bytes // 1024 // 1024}MB"
            if total < 100 * 1024:
                return False, f"too_small:{total}bytes"
        tmp.replace(dest)
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


async def resolve_douyin_share_url(
    share_url: str,
    cache_dir: str = DEFAULT_CACHE_DIR,
) -> dict:
    """抖音分享链接 → 本地 mp4 路径。

    Args:
        share_url: v.douyin.com 短链 / iesdouyin.com 长链
        cache_dir: KE 容器内能写的缓存目录(默认 /host/Desktop/omni_video_cache)

    Returns:
        成功: {ok: True, video_path, aweme_id, source_url, watermark, from_cache,
              size_bytes, desc?, author_nickname?}
        失败: {ok: False, error, hint, share_url, aweme_id?}
    """
    # 容忍老板粘整段分享文案:先抠 URL,抠到就用它,抠不到再走严格判断
    raw_input = share_url
    extracted = _extract_share_url_from_text(share_url)
    if extracted:
        share_url = extracted
    elif not is_douyin_share_url(share_url):
        return {
            "ok": False,
            "error": "not_douyin_url",
            "hint": (
                "目前只支持 v.douyin.com 短链或 iesdouyin.com 长链;其他平台先用本地路径模式。"
                "贴整段分享文案也行(我会自动抠 URL),但你这段里没找到抖音 URL。"
            ),
            "share_url": raw_input,
        }

    cache_path = Path(cache_dir)
    try:
        cache_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "ok": False,
            "error": "cache_dir_unwritable",
            "hint": f"无法创建/访问缓存目录 {cache_dir}: {exc}",
            "share_url": share_url,
        }

    async with httpx.AsyncClient(verify=True) as client:
        long_url = share_url
        host = (urlparse(share_url).hostname or "").lower()
        if host == _SHORT_HOST:
            loc = await _resolve_short_link(client, share_url)
            if not loc:
                return {
                    "ok": False,
                    "error": "short_link_resolve_failed",
                    "hint": "短链没拿到 302 重定向(链接已失效或被风控)",
                    "share_url": share_url,
                }
            long_url = loc

        aweme_id = _extract_aweme_id(long_url)
        if not aweme_id:
            return {
                "ok": False,
                "error": "no_aweme_id",
                "hint": f"长链没找到 /share/video/<id>/ 结构: {long_url[:200]}",
                "share_url": share_url,
            }

        dest = cache_path / f"dyrev_{aweme_id}.mp4"
        if dest.exists() and dest.stat().st_size > 100 * 1024:
            return {
                "ok": True,
                "video_path": str(dest),
                "aweme_id": aweme_id,
                "source_url": share_url,
                "watermark": "unknown",  # 缓存命中,不知道当时下的是哪版
                "from_cache": True,
                "size_bytes": dest.stat().st_size,
            }

        html = await _fetch_ssr_html(client, aweme_id)
        if not html:
            return {
                "ok": False,
                "error": "ssr_fetch_failed",
                "hint": "拉 iesdouyin SSR HTML 失败(网络/被风控)",
                "share_url": share_url,
                "aweme_id": aweme_id,
            }

        playwm_url = _extract_playwm_url(html)
        if not playwm_url:
            return {
                "ok": False,
                "error": "no_play_url",
                "hint": "SSR HTML 里没找到 play_addr.url_list(视频已删/作者隐藏/抖音改版)",
                "share_url": share_url,
                "aweme_id": aweme_id,
            }

        meta = _extract_metadata(html)
        long_ref = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
        play_url = playwm_url.replace("/playwm/", "/play/")

        # 先试无水印 (老 web 端套路 playwm→play),失败回退带水印
        ok, err = await _download(client, play_url, dest, referer=long_ref)
        watermark: str | None = "none" if ok else None
        if not ok:
            logger.info("douyin play (no-wm) failed: %s; fallback to playwm", err)
            ok, err = await _download(client, playwm_url, dest, referer=long_ref)
            watermark = "embedded" if ok else None

        if not ok:
            return {
                "ok": False,
                "error": "download_failed",
                "hint": f"两次下载都失败: {err}。CDN URL 可能过期或被风控,重试一次试试。",
                "share_url": share_url,
                "aweme_id": aweme_id,
            }

        return {
            "ok": True,
            "video_path": str(dest),
            "aweme_id": aweme_id,
            "source_url": share_url,
            "watermark": watermark,
            "from_cache": False,
            "size_bytes": dest.stat().st_size,
            **meta,
        }
