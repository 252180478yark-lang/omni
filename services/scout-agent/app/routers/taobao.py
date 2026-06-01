"""
淘宝/天猫竞品调研抓取端点（W1 竞品调研切片 · 2026-06-01）。

两个 endpoint，纯浏览器层（不碰 LLM —— 拆解在 knowledge-engine 做）：

  POST /api/v1/scout/taobao/search   —— 搜词 → 前 N 个商品卡片（标题/显示价/月销/店铺/链接/主图）
  POST /api/v1/scout/taobao/detail   —— 单链接 → 主图组 + 详情页长图（都是 alicdn CDN url）

复用 scout-agent 既有的 persistent-context 登录态（sessions/taobao/user_data，
老板先跑一次 relogin 扫码登录）。淘宝反爬狠，本模块：
  - headless 可按请求覆盖（容器默认 headless=true；老板要稳就 host 跑 headless=false）
  - 同一 user_data_dir 不能并发开 context → 全局 asyncio.Lock 串行化
  - 抓不到也不抛：返回 login_required / 空结果 + 落 snapshots（全页截图 + HTML）供调选择器

到手价现实：只取**搜索页/详情页显示价**（可能是券前标价或预估），不加购算真到手价。
月销：淘宝部分商品已隐藏，拿不到就 null（如实标）。选择器是启发式，可能要按 snapshots 调几轮。
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import urllib.parse
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter()
log = logging.getLogger(__name__)

# 同一 user_data_dir 同时只能开一个 Chromium context（Playwright 文件锁）。
# KE 会连着调 search→detail、或多次 detail，必须串行。
_TAOBAO_LOCK = asyncio.Lock()

_SESSION_SUBDIR = "taobao"

# ─────────────────────────── 浏览器内提取脚本 ───────────────────────────
# 淘宝 class 名是 hash 化且会变，所以靠"商品详情链接锚点 + 结构爬升 + 文本正则"
# 这种抗变更的启发式，而不是固定 class 选择器。

_SEARCH_EXTRACT_JS = r"""
() => {
  const norm = (u) => {
    if (!u) return null;
    u = String(u).trim();
    if (u.startsWith('//')) u = 'https:' + u;
    else if (u.startsWith('http://')) u = 'https://' + u.slice(7);
    return u;
  };
  const anchors = Array.from(document.querySelectorAll(
    'a[href*="item.htm"], a[href*="//item.taobao.com"], a[href*="detail.tmall.com"], ' +
    'a[href*="//item.tmall.com"], a[href*="//detail.tmall.com"], a[href*="?id="], a[href*="&id="]'
  ));
  const seen = new Set();
  const out = [];
  for (const a of anchors) {
    let href = a.href || a.getAttribute('href') || '';
    const m = href.match(/[?&]id=(\d+)/);
    const itemId = m ? m[1] : null;
    if (!itemId || seen.has(itemId)) continue;
    // climb to a plausible card container（有图 + 有价/销量文本）
    let card = a;
    for (let i = 0; i < 7; i++) {
      if (!card.parentElement) break;
      card = card.parentElement;
      const t = card.innerText || '';
      if (card.querySelector('img') && /¥|\d+\.\d|人付款|人收货|销量|月销|笔/.test(t)) break;
    }
    const cardText = (card.innerText || '').replace(/\s+/g, ' ').trim();
    // title
    let title = a.getAttribute('title') || '';
    if (!title) {
      const img = a.querySelector('img') || card.querySelector('img');
      if (img) title = img.getAttribute('alt') || '';
    }
    if (!title) title = (a.innerText || '').trim();
    title = title.replace(/\s+/g, ' ').trim().slice(0, 200);
    if (!title) continue;        // 没标题的多半是图标/广告位锚点，跳过
    seen.add(itemId);
    // price（先找 price-ish 元素，再退回卡片文本正则）
    let price = null;
    const priceEl = card.querySelector('[class*="price" i], [class*="Price"], strong, em');
    let pm = priceEl ? (priceEl.innerText || '').match(/(\d+(?:\.\d+)?)/) : null;
    if (!pm) pm = cardText.match(/¥\s*(\d+(?:\.\d+)?)/) || cardText.match(/(\d+(?:\.\d+)?)\s*元/);
    if (pm) price = pm[1];
    // sales（月销/人付款；淘宝常隐藏 → 可能 null）
    let sales = null;
    const sm = cardText.match(/([\d.]+\s*万?\+?)\s*(?:人付款|人收货|人加购|笔成交|笔)/)
            || cardText.match(/(?:月销|销量)\s*([\d.]+\s*万?\+?)/);
    // 用捕获组 sm[1]（纯数字+万+），不是 sm[0]（含"人付款/月销"前后缀）→ 月销列只放值
    if (sm && sm[1]) sales = sm[1].replace(/\s+/g, '');
    // shop
    let shop = null;
    const shopEl = card.querySelector('[class*="shop" i], [class*="Shop"], [class*="seller" i]');
    if (shopEl) shop = (shopEl.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60) || null;
    // main image
    let img = null;
    for (const im of Array.from(card.querySelectorAll('img'))) {
      const s = im.getAttribute('src') || im.getAttribute('data-src') || im.getAttribute('data-ks-lazyload') || '';
      if (s && /alicdn|aliimg/.test(s) && !/(\.svg|icon|logo|sprite)/i.test(s)) { img = s; break; }
    }
    out.push({
      item_id: itemId, title, price, sales_text: sales, shop,
      // 用规范详情页 url（很多是直通车 simba 跳转链，但都带 id=），避免 ad 跟踪链
      item_url: 'https://item.taobao.com/item.htm?id=' + itemId,
      raw_href: norm(href), main_image_url: norm(img),
    });
  }
  return out;
}
"""

_DETAIL_EXTRACT_JS = r"""
() => {
  const norm = (u) => {
    if (!u) return null;
    u = String(u).trim();
    if (u.startsWith('//')) u = 'https:' + u;
    else if (u.startsWith('http://')) u = 'https://' + u.slice(7);
    return u;
  };
  const collect = (sel) => {
    const set = [];
    document.querySelectorAll(sel).forEach(im => {
      const s = im.getAttribute('data-ks-lazyload') || im.getAttribute('data-src') ||
                im.getAttribute('data-lazy-src') || im.getAttribute('src') || '';
      if (s && /alicdn|aliimg/.test(s) && !/(\.svg|icon|logo|sprite|spaceball|blank\.gif)/i.test(s)) {
        const n = norm(s);
        if (n && !set.includes(n)) set.push(n);
      }
    });
    return set;
  };
  let title = '';
  const tEl = document.querySelector('#J_Title, .tb-detail-hd h1, [class*="ItemTitle" i], [class*="mainTitle" i], h1');
  if (tEl) title = (tEl.innerText || '').trim();
  if (!title) title = document.title || '';
  let price = null;
  const pEl = document.querySelector('[class*="price" i] [class*="text" i], [class*="price" i] em, [class*="price" i] strong, [class*="Price"] em, [class*="rmb" i], .tb-rmb-num, [class*="priceText" i]');
  if (pEl) { const pm = (pEl.innerText || '').match(/(\d+(?:\.\d+)?)/); if (pm) price = pm[1]; }
  const main = collect(
    '#J_UlThumb img, [class*="thumbnail" i] img, [class*="PicGallery" i] img, ' +
    '[class*="MainPic" i] img, [class*="mainPic" i] img, [class*="gallery" i] img, ' +
    '[class*="ThumbItem" i] img, [class*="preview" i] img'
  );
  const detail = collect(
    '#description img, #J_DivItemDesc img, [class*="desc" i] img, [class*="Detail" i] img, ' +
    '#content img, [class*="content" i] img, [id*="desc" i] img'
  );
  return { title: (title || '').slice(0, 200), price, main_images: main, detail_images: detail };
}
"""


# ─────────────────────────── 公共浏览器助手 ───────────────────────────

def _session_dir() -> Path:
    d = Path(settings.sessions_dir) / _SESSION_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snap_dir() -> Path:
    d = Path(settings.snapshots_dir) / "taobao"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_headless(override: bool | None) -> bool:
    # 淘宝 headless 必被 rgv587 反爬 deny（实测即使带登录 cookie 也拦）→ 默认走 headed，
    # 容器内靠 xvfb 提供虚拟显示（Dockerfile 装了 xvfb + CMD 用 xvfb-run 起）。
    # 老板可显式传 headless=True 强制（基本会被拦，仅调试用）。
    return False if override is None else bool(override)


async def _scroll_to_load(page, steps: int = 8, pause: float = 0.9) -> None:
    """逐段下滚触发淘宝懒加载（搜索结果/详情页长图都是滚到才加载）。"""
    for _ in range(steps):
        try:
            await page.mouse.wheel(0, 2400)
        except Exception:
            await page.evaluate("window.scrollBy(0, 2400)")
        await page.wait_for_timeout(int(pause * 1000) + random.randint(80, 260))


async def _human_scroll_to_bottom(page, max_rounds: int = 50, settle_rounds: int = 3) -> int:
    """像人一样逐段滚到底，把懒加载内容全部 load 出来。

    每轮：可变滚速 + 随机停顿 + 偶尔小回滚（更像真人，降反爬触发）。
    页面高度 scrollHeight + 图片数 images.length 连续 settle_rounds 轮都不再增长才停
    （详情页边滚边长，长完为止）。返回最终图片数。
    """
    stable = 0
    last_h, last_n = 0, 0
    for _ in range(max_rounds):
        try:
            await page.mouse.wheel(0, random.randint(500, 950))
        except Exception:
            await page.evaluate("window.scrollBy(0, 700)")
        await page.wait_for_timeout(random.randint(380, 820))
        if random.random() < 0.15:                       # 偶尔小回滚，更像人手
            try:
                await page.mouse.wheel(0, -random.randint(80, 220))
                await page.wait_for_timeout(220)
            except Exception:
                pass
        try:
            h = await page.evaluate("document.body.scrollHeight")
            n = await page.evaluate("document.images.length")
        except Exception:
            continue
        if h <= last_h and n <= last_n:
            stable += 1
            if stable >= settle_rounds:
                break
        else:
            stable = 0
        last_h, last_n = h, n
    return last_n


async def _login_ok(ctx) -> bool:
    try:
        cookies = await ctx.cookies()
    except Exception:
        return False
    names = {c.get("name", "") for c in cookies}
    # unb = 登录后的用户数字 id（最强标记）；tracknick = 登录昵称
    return ("unb" in names) or ("tracknick" in names)


# 登录态走 storage_state.json（明文 cookie，跨 OS 可移植）。
# 关键：不能用 launch_persistent_context 读 user_data —— 那是 host(Windows) 写的
# Chromium profile，cookie 被 Windows DPAPI 加密，Linux 容器解不开 → 0 cookie → 被反爬拦。
# _login_taobao.py 已把 storage_state.json（明文）落到 sessions/taobao/，这里加载它。
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 反 headless 指纹检测（淘宝会查 navigator.webdriver 等）
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def _storage_state_file() -> Path:
    return _session_dir() / "storage_state.json"


async def _new_context(p, headless: bool):
    """常规 browser + new_context(storage_state) + 反检测。返回 (browser, context)。"""
    ss = _storage_state_file()
    browser = await p.chromium.launch(
        headless=headless,
        # 去掉 Playwright 默认的 --enable-automation（淘宝 AWSC 会查这个自动化标记）
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await browser.new_context(
        storage_state=str(ss) if ss.exists() else None,
        viewport={"width": 1366, "height": 900},
        user_agent=_UA,
        locale="zh-CN",
    )
    await ctx.add_init_script(_STEALTH_JS)
    return browser, ctx


# 详情页走移动 H5 + 截图路线（PC item 页一律"验证码拦截"，DOM 也抓不到）。
# 登录 cookie 是 .taobao.com 域，PC 登录的 storage_state 在移动 h5 子域照样有效。
_MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")


async def _new_mobile_context(p, headless: bool):
    """手机 UA context（详情页截图用）。返回 (browser, context)。"""
    ss = _storage_state_file()
    browser = await p.chromium.launch(
        headless=headless,
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await browser.new_context(
        storage_state=str(ss) if ss.exists() else None,
        viewport={"width": 390, "height": 844},
        user_agent=_MOBILE_UA, is_mobile=True, has_touch=True, locale="zh-CN",
    )
    await ctx.add_init_script(_STEALTH_JS)
    return browser, ctx


# ─────────────────────────── 请求体 ───────────────────────────

class TaobaoSearchRequest(BaseModel):
    query: str
    top_n: int = 50
    headless: bool | None = None     # None=用 settings；老板要稳传 False（host 非 headless）
    max_pages: int = 3               # 淘宝一页约 44-48 条，凑够 top_n 翻几页
    scroll_steps: int = 8


class TaobaoDetailRequest(BaseModel):
    item_url: str
    headless: bool | None = None
    scroll_steps: int = 12           # 详情页长图要多滚几下才全懒加载出来
    search_query: str | None = None  # 给了就"先搜再进"（拟人路径绕详情页验证码拦截）


class TaobaoDetailShotsRequest(BaseModel):
    item_url: str
    search_query: str | None = None  # 拟人热身搜索词
    headless: bool | None = None
    max_shots: int = 9               # 从上往下滚动截多少张


# ─────────────────────────── 端点 ───────────────────────────

@router.post("/taobao/search")
async def taobao_search(req: TaobaoSearchRequest) -> dict:
    """搜词抓前 N 个商品卡片。返回 items + debug（截图/HTML 路径 + 登录态）。"""
    from playwright.async_api import async_playwright

    query = (req.query or "").strip()
    if not query:
        return {"ok": False, "error": "empty_query", "hint": "query 不能为空"}

    headless = _resolve_headless(req.headless)
    if not _storage_state_file().exists():
        return {
            "ok": False, "error": "login_required",
            "hint": "淘宝还没登录态。先在 host 跑 `python services/scout-agent/_login_taobao.py` 扫码登录"
                    "（生成 sessions/taobao/storage_state.json，明文 cookie 可移植进容器）。",
        }

    ts = time.strftime("%Y%m%d_%H%M%S")
    snap = _snap_dir()
    items: list[dict] = []
    debug: dict = {"login_ok": False, "pages_scraped": 0, "headless": headless}

    async with _TAOBAO_LOCK:
        try:
            async with async_playwright() as p:
                browser, ctx = await _new_context(p, headless)
                try:
                    page = await ctx.new_page()
                    # 反爬热身：先进登录态首页让 AWSC 落 token，再直链搜索页。
                    # 实测这样能进真实结果页；不热身直接深链搜索页会被 rgv587 deny。
                    try:
                        await page.goto("https://www.taobao.com/", wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(2500)
                    except Exception as warm_exc:
                        log.warning("taobao homepage warmup failed: %s", warm_exc)

                    seen: set[str] = set()
                    for pg in range(max(1, req.max_pages)):
                        # 用 page 翻页参数（实测能进结果页）；老的 &s=offset 起始位会触发 rgv587 deny
                        url = (
                            "https://s.taobao.com/search?q="
                            + urllib.parse.quote(query)
                            + f"&page={pg + 1}&tab=all"
                        )
                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        except Exception as nav_exc:
                            log.warning("taobao search nav slow/failed p%d: %s", pg, nav_exc)
                        await page.wait_for_timeout(2500)
                        # 反爬壳页（title=s.taobao.com、无结果）会自我跳转/需重载到真结果页。
                        # 等结果锚点出现（最多 12s）；等不到重载一次再等。wait_for_selector 能扛页面跳转。
                        try:
                            await page.wait_for_selector('a[href*="id="]', timeout=12000)
                        except Exception:
                            try:
                                await page.reload(wait_until="domcontentloaded", timeout=45000)
                                await page.wait_for_selector('a[href*="id="]', timeout=12000)
                            except Exception:
                                log.info("taobao search: 等不到结果锚点（壳页/被校验？）p%d", pg)

                        cur = (page.url or "").lower()
                        if "login.taobao.com" in cur or "login.tmall" in cur or "passport" in cur:
                            debug["redirected_to_login"] = page.url
                            break

                        await _scroll_to_load(page, steps=req.scroll_steps)
                        try:
                            batch = await page.evaluate(_SEARCH_EXTRACT_JS)
                        except Exception as ext_exc:
                            log.warning("taobao search extract failed p%d: %s", pg, ext_exc)
                            batch = []

                        # 第一页落 HTML 快照供调选择器
                        if pg == 0:
                            try:
                                html = await page.content()
                                hp = snap / f"search_{ts}.html"
                                hp.write_text(html, encoding="utf-8")
                                debug["html_snapshot"] = str(hp)
                                debug["html_chars"] = len(html)
                            except Exception:
                                pass
                            try:
                                sp = snap / f"search_{ts}.png"
                                await page.screenshot(path=str(sp), full_page=False)
                                debug["screenshot"] = str(sp)
                            except Exception:
                                pass

                        new_in_batch = 0
                        for it in batch:
                            iid = it.get("item_id")
                            if not iid or iid in seen:
                                continue
                            seen.add(iid)
                            items.append(it)
                            new_in_batch += 1
                        debug["pages_scraped"] = pg + 1
                        log.info("taobao search '%s' p%d: +%d (total %d)", query, pg, new_in_batch, len(items))

                        if len(items) >= req.top_n or new_in_batch == 0:
                            break

                    debug["login_ok"] = await _login_ok(ctx)
                finally:
                    try:
                        await ctx.close()
                        await browser.close()
                    except Exception:
                        pass
        except Exception as exc:
            log.exception("taobao_search failed")
            return {
                "ok": False, "error": "browser_failed",
                "hint": (
                    f"{type(exc).__name__}: {exc}. "
                    "若是 headless=false 在容器内（无显示）报错 → 传 headless=true，"
                    "或在 host 上跑 scout-agent。"
                ),
                "debug": debug,
            }

    # 截断 + 排名
    items = items[: req.top_n]
    for i, it in enumerate(items, 1):
        it["rank"] = i

    if not items and not debug.get("login_ok"):
        return {
            "ok": False, "error": "login_required",
            "hint": "没抓到商品且未检测到登录态。先 relogin 淘宝（看 debug.redirected_to_login）。",
            "debug": debug,
        }
    if not items:
        return {
            "ok": False, "error": "no_items",
            "hint": "登录态在但没解析到商品卡片——淘宝 DOM 可能变了，看 debug.html_snapshot 调 _SEARCH_EXTRACT_JS 选择器。",
            "debug": debug,
        }

    return {"ok": True, "query": query, "count": len(items), "items": items, "debug": debug}


@router.post("/taobao/detail")
async def taobao_detail(req: TaobaoDetailRequest) -> dict:
    """抓单个商品的主图组 + 详情页长图（alicdn CDN url）。"""
    from playwright.async_api import async_playwright

    item_url = (req.item_url or "").strip()
    if not item_url.startswith("http"):
        return {"ok": False, "error": "bad_url", "hint": "item_url 要是完整 http(s) 链接"}

    headless = _resolve_headless(req.headless)
    if not _storage_state_file().exists():
        return {"ok": False, "error": "login_required",
                "hint": "淘宝没登录态，先在 host 跑 `python services/scout-agent/_login_taobao.py`。"}

    ts = time.strftime("%Y%m%d_%H%M%S")
    snap = _snap_dir()
    out = {"title": "", "price": None, "main_images": [], "detail_images": []}
    debug: dict = {"headless": headless}

    async with _TAOBAO_LOCK:
        try:
            async with async_playwright() as p:
                browser, ctx = await _new_context(p, headless)
                try:
                    page = await ctx.new_page()
                    # 拟人导航：首页 → 真搜一次 → 在结果里**真点**该商品链接进详情页。
                    # 直接 goto item.htm 会"验证码拦截"（程序化导航被识别）；真点锚点是站内
                    # 真实导航，能过。点击常开新标签 → 捕获后切过去。
                    item_id_m = re.search(r"[?&]id=(\d+)", item_url)
                    item_id = item_id_m.group(1) if item_id_m else None
                    landed = False
                    referer = "https://www.taobao.com/"
                    try:
                        await page.goto("https://www.taobao.com/", wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(2000)
                        if req.search_query and item_id:
                            search_url = ("https://s.taobao.com/search?q="
                                          + urllib.parse.quote(req.search_query) + "&page=1&tab=all")
                            try:
                                await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                                await page.wait_for_selector('a[href*="id="]', timeout=12000)
                                referer = search_url
                                anchor = await page.query_selector(f'a[href*="id={item_id}"]')
                                if anchor:
                                    await anchor.scroll_into_view_if_needed(timeout=5000)
                                    await page.wait_for_timeout(600)
                                    try:                              # 点击常开新标签
                                        async with ctx.expect_page(timeout=8000) as newp:
                                            await anchor.click()
                                        page = await newp.value
                                        await page.wait_for_load_state("domcontentloaded", timeout=30000)
                                    except Exception:                 # 没开新标签=同页导航
                                        await page.wait_for_timeout(2500)
                                    landed = True
                                else:
                                    log.info("taobao detail: 搜索页没找到 id=%s 的锚点", item_id)
                            except Exception as sx:
                                log.info("taobao detail search-click warmup 失败: %s", sx)
                    except Exception:
                        pass
                    if not landed:                                    # 兜底：带 referer 直链
                        try:
                            await page.goto(item_url, wait_until="domcontentloaded", timeout=45000, referer=referer)
                        except Exception as nav_exc:
                            log.warning("taobao detail nav slow/failed: %s", nav_exc)
                    await page.wait_for_timeout(2500)

                    cur = (page.url or "").lower()
                    if "login.taobao.com" in cur or "login.tmall" in cur or "passport" in cur:
                        debug["redirected_to_login"] = page.url
                        return {"ok": False, "error": "login_required",
                                "hint": "详情页要登录态，跳登录了。先 relogin 淘宝。", "debug": debug}

                    # 像人一样滚到底，把详情区长图全部懒加载出来（页高+图数不再增长才停）
                    await _human_scroll_to_bottom(page)
                    await page.wait_for_timeout(1200)

                    try:
                        res = await page.evaluate(_DETAIL_EXTRACT_JS)
                        out.update(res or {})
                    except Exception as ext_exc:
                        log.warning("taobao detail extract failed: %s", ext_exc)

                    # 详情区有时在 iframe（老版 #desc-iframe）→ 额外从 frame 收图
                    for fr in page.frames:
                        furl = (fr.url or "").lower()
                        if "desc" in furl or "describe" in furl:
                            try:
                                # iframe 内部也懒加载 → 先在 frame 里逐段滚再收图
                                for _ in range(20):
                                    await fr.evaluate("window.scrollBy(0, 800)")
                                    await page.wait_for_timeout(280)
                                more = await fr.evaluate(_DETAIL_EXTRACT_JS)
                                for u in (more or {}).get("detail_images", []):
                                    if u not in out["detail_images"]:
                                        out["detail_images"].append(u)
                            except Exception:
                                pass

                    try:
                        sp = snap / f"detail_{ts}.png"
                        await page.screenshot(path=str(sp), full_page=False)
                        debug["screenshot"] = str(sp)
                    except Exception:
                        pass
                    debug["login_ok"] = await _login_ok(ctx)
                finally:
                    try:
                        await ctx.close()
                        await browser.close()
                    except Exception:
                        pass
        except Exception as exc:
            log.exception("taobao_detail failed")
            return {"ok": False, "error": "browser_failed",
                    "hint": f"{type(exc).__name__}: {exc}", "debug": debug}

    if not out["main_images"] and not out["detail_images"]:
        return {
            "ok": False, "error": "no_images",
            "hint": "没抓到主图/详情图——DOM 可能变了或详情在跨域 iframe，看 debug.screenshot 调 _DETAIL_EXTRACT_JS。",
            "item_url": item_url, "title": out.get("title"), "debug": debug,
        }

    return {
        "ok": True,
        "item_url": item_url,
        "title": out.get("title"),
        "price": out.get("price"),
        "main_images": out.get("main_images", []),
        "detail_images": out.get("detail_images", []),
        "counts": {"main": len(out.get("main_images", [])), "detail": len(out.get("detail_images", []))},
        "debug": debug,
    }


@router.post("/taobao/detail_shots")
async def taobao_detail_shots(req: TaobaoDetailShotsRequest) -> dict:
    """移动 H5 详情页 滚动+截图（PC item 页/DOM 抓不到时的视觉路线）。

    拟人链路：移动首页热身 →（有 query 则）移动搜索 → H5 详情页 → 逐屏滚动截图。
    返回 base64 JPEG 截图列表给 KE 喂多模态视觉模型（截图=渲染出的主图区+详情长图）。
    """
    import base64 as _b64
    from playwright.async_api import async_playwright

    item_url = (req.item_url or "").strip()
    item_id_m = re.search(r"[?&]id=(\d+)", item_url)
    item_id = item_id_m.group(1) if item_id_m else None
    if not item_id:
        return {"ok": False, "error": "bad_url", "hint": "item_url 要含 id="}
    if not _storage_state_file().exists():
        return {"ok": False, "error": "login_required",
                "hint": "淘宝没登录态，先在 host 跑 `python services/scout-agent/_login_taobao.py`。"}

    headless = _resolve_headless(req.headless)
    ts = time.strftime("%Y%m%d_%H%M%S")
    snap = _snap_dir()
    shots: list[str] = []
    debug: dict = {"headless": headless}
    blocked = False

    async with _TAOBAO_LOCK:
        try:
            async with async_playwright() as p:
                browser, ctx = await _new_mobile_context(p, headless)
                try:
                    page = await ctx.new_page()
                    referer = "https://h5.m.taobao.com/"
                    try:
                        await page.goto("https://h5.m.taobao.com/", wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(2500)
                        if req.search_query:
                            msearch = "https://s.m.taobao.com/h5?q=" + urllib.parse.quote(req.search_query)
                            try:
                                await page.goto(msearch, wait_until="domcontentloaded", timeout=40000)
                                await page.wait_for_timeout(2500)
                                referer = msearch
                            except Exception:
                                pass
                    except Exception:
                        pass

                    detail_url = f"https://h5.m.taobao.com/awp/core/detail.htm?id={item_id}"
                    try:
                        await page.goto(detail_url, wait_until="domcontentloaded", timeout=45000, referer=referer)
                    except Exception as nav_exc:
                        log.warning("taobao detail_shots nav: %s", nav_exc)
                    await page.wait_for_timeout(5000)

                    try:
                        html = await page.content()
                        title = await page.title()
                        if (any(k in html for k in ("访问被拒绝", "rgv587", "/punish", "deny_h5"))
                                or "验证" in (title or "")):
                            blocked = True
                        debug["title"] = (title or "")[:40]
                    except Exception:
                        pass
                    debug["blocked"] = blocked

                    # 逐屏滚动 + 截图（mouse.wheel + window.scrollBy 双保险）
                    for _ in range(max(3, req.max_shots)):
                        try:
                            shots.append(_b64.b64encode(
                                await page.screenshot(type="jpeg", quality=72)).decode())
                        except Exception:
                            break
                        try:
                            await page.mouse.move(195, 430)
                            await page.mouse.wheel(0, 780)
                        except Exception:
                            pass
                        try:
                            await page.evaluate("window.scrollBy(0, 780)")
                        except Exception:
                            pass
                        await page.wait_for_timeout(1100)

                    try:
                        if shots:
                            sp = snap / f"detshots_{ts}.jpg"
                            sp.write_bytes(_b64.b64decode(shots[0]))
                            debug["sample"] = str(sp)
                    except Exception:
                        pass
                finally:
                    try:
                        await ctx.close()
                        await browser.close()
                    except Exception:
                        pass
        except Exception as exc:
            log.exception("taobao_detail_shots failed")
            return {"ok": False, "error": "browser_failed",
                    "hint": f"{type(exc).__name__}: {exc}", "debug": debug}

    # 截图大小全相同 → 多半没滚动/拦截页（debug 提示）
    if len(shots) > 2 and len({len(s) for s in shots}) <= 1:
        debug["all_identical"] = True

    return {"ok": True, "blocked": blocked, "item_id": item_id,
            "shot_count": len(shots), "shots": shots, "debug": debug}
