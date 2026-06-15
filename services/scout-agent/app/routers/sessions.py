"""
Session management endpoints.

GET  /sessions/{platform}         — health check
POST /sessions/{platform}/relogin — trigger Playwright relogin flow (headless=False)
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.database import get_pool

router = APIRouter()
log = logging.getLogger(__name__)

PLATFORMS = {"douyin_compass", "douyin_shop_admin", "yuntu", "taobao", "jd"}


@router.get("/sessions/{platform}")
async def get_session(platform: str):
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mvp_session WHERE platform=$1", platform
        )
    if not row:
        raise HTTPException(status_code=404, detail="Session not configured")
    return dict(row)


@router.post("/sessions/{platform}/relogin")
async def relogin(platform: str):
    """
    Opens a visible Chromium window for the user to scan the QR code.
    Returns immediately; the user scans and the session is saved automatically.
    """
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}")

    urls = {
        "douyin_compass": "https://compass.jinritemai.com/",
        "douyin_shop_admin": "https://fxg.jinritemai.com/",
        "yuntu": "https://yuntu.oceanengine.com/",
        # 竞品调研：淘宝/天猫。落 www.taobao.com 首页；未登录会出登录浮层，
        # 老板扫码/账密登录后回首页，_run_relogin 监测到 unb/tracknick 即落库。
        "taobao": "https://www.taobao.com/",
        # 京东商智（切片2）：sz.jd.com 商智后台；登录后 _run_relogin 监测 pt_pin/thor 即落库。
        "jd": "https://sz.jd.com/",
    }

    asyncio.create_task(_run_relogin(platform, urls[platform]))
    return {"status": "relogin_started", "platform": platform,
            "message": "请在弹出的浏览器窗口中扫码登录，完成后窗口会自动关闭。"}


async def _run_relogin(platform: str, url: str) -> None:
    """Open visible Chromium, wait for real login cookies, then persist storage state.

    Detection rule: a session is considered "logged in" only when the browser
    holds at least one auth cookie for the platform domain — typically
    `sessionid` / `sessionid_ss` / `passport_csrf_token`. Just landing on the
    home URL is NOT enough (page may render but ask user to log in).
    """
    from pathlib import Path
    from app.config import settings
    from playwright.async_api import async_playwright

    session_dir = Path(settings.sessions_dir) / platform
    session_dir.mkdir(parents=True, exist_ok=True)
    storage_file = session_dir / "storage_state.json"

    # STRICT auth-cookie names — only set after a real login completes.
    # Excludes ttwid / s_v_web_id / passport_csrf_token: those are visitor /
    # CSRF tokens that get planted on plain page.goto without any login.
    # Platform-keyed: 淘宝/天猫的登录 cookie 名跟抖音系完全不同。
    AUTH_COOKIE_NAMES_BY_PLATFORM = {
        "_default": {
            "sessionid",       # douyin/jinritemai/yuntu — primary login cookie
            "sessionid_ss",    # secure variant
            "sid_tt",          # alt session id
            "sid_guard",       # session guard
            "uid_tt",          # logged-in user id
            "uid_tt_ss",       # secure variant
            "LOGIN_STATUS",    # yuntu specific
        },
        # 淘宝/天猫登录后才会写的强标记：unb=登录用户数字 id，tracknick=登录昵称，
        # lgc=login account，_nk_=昵称。
        # （cookie2/_tb_token_/sgcookie/cna/isg/tfstk/t 是游客态 cookie，page.goto 即落，
        #   不能当登录标记——否则刚打开 taobao.com 就被误判成已登录。）
        "taobao": {"unb", "tracknick", "lgc", "_nk_"},
        # 京东登录后才写的强标记：pt_pin=登录 pin、pt_key=登录态 token、thor=登录态。
        # （pt_pin/pt_key/thor 是 JD 标准登录 cookie；切片0 实测确认为准。）
        "jd": {"pt_pin", "pt_key", "thor"},
    }
    auth_cookie_names = AUTH_COOKIE_NAMES_BY_PLATFORM.get(
        platform, AUTH_COOKIE_NAMES_BY_PLATFORM["_default"]
    )
    MIN_COOKIES = 8  # post-login pages set 10-30+ cookies; 8 is a safe floor

    # URL fragments that mean user is NOT yet on the real workspace:
    #   - login / passport / sso        → still scanning QR
    #   - select-shop / store-select / dispatch / select / shop-list
    #     → 抖店"请选择店铺"页（扫码完成后会先跳到这里，必须点选具体店铺
    #       才进入真正的罗盘 /shop/{id}/home）
    URL_NOT_SETTLED_KEYWORDS = (
        "login", "passport", "sso",
        "select-shop", "store-select", "shop-list", "/select", "dispatch",
    )

    def has_auth_cookies(cookies: list) -> tuple[bool, int, list[str]]:
        names = [c.get("name", "") for c in cookies]
        hit = [n for n in names if n in auth_cookie_names]
        ok = (len(cookies) >= MIN_COOKIES) and (len(hit) > 0)
        return ok, len(cookies), hit

    def url_is_workspace(url: str) -> bool:
        """True only when URL is past login AND past store-select."""
        u = (url or "").lower()
        if not u or u == "about:blank":
            return False
        for kw in URL_NOT_SETTLED_KEYWORDS:
            if kw in u:
                return False
        return True

    final_status = "expired"
    error_msg: str | None = None

    try:
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(session_dir / "user_data"),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as nav_exc:
                log.warning("relogin: initial nav slow/failed (%s), continuing anyway", nav_exc)

            log.info("relogin: window opened for %s, waiting up to 5 min for QR scan", platform)
            deadline_iters = 300  # 300 * 1s = 5 minutes
            cold_start_skip = 8   # ignore cookies for the first 8s — visitor cookies
                                  # land within 2-3s and would false-positive otherwise
            logged_in = False
            for i in range(deadline_iters):
                await asyncio.sleep(1)
                # Stop early if user closed the window
                if not ctx.pages:
                    log.info("relogin: user closed window for %s after %ds", platform, i)
                    break
                if i < cold_start_skip:
                    continue
                try:
                    cookies = await ctx.cookies()
                    # Look at the LAST opened page — user may switch tabs / land
                    # on store-select tab while initial tab is the dispatch URL.
                    current_url = ctx.pages[-1].url if ctx.pages else ""
                except Exception:
                    continue
                ok, n, hit = has_auth_cookies(cookies)
                settled = url_is_workspace(current_url)
                if ok and settled:
                    logged_in = True
                    log.info("relogin: %s logged in after %ds — %d cookies, auth=[%s], url=%s",
                             platform, i, n, ",".join(hit), current_url[:80])
                    # Brief settle delay so all cookies finish writing
                    await asyncio.sleep(2)
                    break
                if i and i % 15 == 0:
                    if ok and not settled:
                        log.info("relogin: %s 已扫码 ✓ — 请在浏览器选店铺/进入工作台 (当前 url=%s)",
                                 platform, current_url[:80])
                    else:
                        log.info("relogin: still waiting on %s (cookies=%d auth=%s url=%s)",
                                 platform, n, hit or "none", current_url[:60])

            if logged_in:
                await ctx.storage_state(path=str(storage_file))
                final_status = "ok"
            else:
                error_msg = "no auth cookies detected within 5 min"
                log.warning("relogin: %s — %s", platform, error_msg)

            try:
                await ctx.close()
            except Exception:
                pass

    except Exception as exc:
        error_msg = str(exc) or repr(exc)
        log.error("relogin failed for %s: %s", platform, error_msg)
        final_status = "error"

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 新平台（如 taobao）首次 relogin 时 mvp_session 还没行 → 先补一行
        # （migration 009 只 seed 了抖音三平台）。storage_path NOT NULL，给持久化路径。
        await conn.execute(
            "INSERT INTO mvp_session (platform, storage_path) VALUES ($1, $2) "
            "ON CONFLICT (platform) DO NOTHING",
            platform, str(storage_file),
        )
        if final_status == "ok":
            await conn.execute(
                """
                UPDATE mvp_session
                SET health='ok', last_login_at=NOW(), notes=NULL, updated_at=NOW()
                WHERE platform=$1
                """,
                platform,
            )
            log.info("relogin: saved valid session for %s", platform)
        else:
            await conn.execute(
                """
                UPDATE mvp_session
                SET health=$2, notes=$3, updated_at=NOW()
                WHERE platform=$1
                """,
                platform, final_status, error_msg or "login not completed",
            )
