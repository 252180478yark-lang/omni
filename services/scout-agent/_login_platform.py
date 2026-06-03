"""Host-run 三平台（云图/罗盘/抖店）登录助手 —— 给 live_fetch 底座刷新 cookie。

容器是 headless 无显示，登录得在 host 上弹可见浏览器。本脚本在宿主弹 Chromium，
你扫码（抖店还要选店铺）后，把登录态持久化到 sessions/<platform>/storage_state.json
—— 这目录 bind-mount 进 omni-scout-agent 容器，登完容器里的 platform_fetch 直接有登录态。

用法（在有显示器的 host 上跑；cookie 1-4 天过期，过期就重跑）：
    cd E:\\agent\\omni\\services\\scout-agent
    python _login_platform.py douyin_compass     # 罗盘
    python _login_platform.py douyin_shop_admin   # 抖店后台
    python _login_platform.py yuntu               # 云图（一般还没过期，可不重登）

弹出的 Chromium 里登录（抖店/罗盘扫码后需点选具体店铺进入工作台），
检测到真实登录态后自动存盘关窗（最多等 5 分钟）。
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# 平台 → 登录起始 URL（跟 app/routers/sessions.py 一致）
URLS = {
    "douyin_compass": "https://compass.jinritemai.com/",
    "douyin_shop_admin": "https://fxg.jinritemai.com/",
    "yuntu": "https://yuntu.oceanengine.com/",
}

# 抖音系登录后才写的强标记（跟 sessions.py _default 一致）；游客/CSRF token 不算
AUTH = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "uid_tt_ss", "LOGIN_STATUS"}
# 还没进真正工作台的 URL 片段：登录中 / 抖店"请选择店铺"页
NOT_SETTLED = ("login", "passport", "sso", "select-shop", "store-select", "shop-list", "/select", "dispatch")


def settled(url: str) -> bool:
    u = (url or "").lower()
    if not u or u == "about:blank":
        return False
    return not any(k in u for k in NOT_SETTLED)


def main(platform: str) -> int:
    if platform not in URLS:
        print(f"未知平台: {platform}，可选: {', '.join(URLS)}", flush=True)
        return 2
    session = Path(__file__).parent / "sessions" / platform
    session.mkdir(parents=True, exist_ok=True)
    user_data = session / "user_data"

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URLS[platform], wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print("nav warn:", exc, flush=True)

        print(f"=== 请在弹出的 Chromium 里登录 {platform}（扫码；抖店/罗盘登录后需点选店铺进工作台），最多等 5 分钟 ===", flush=True)
        ok = False
        for i in range(300):
            time.sleep(1)
            if not ctx.pages:
                print("窗口被关了（未完成登录）", flush=True)
                break
            if i < 8:                      # 头 8s 是游客 cookie，跳过免误判
                continue
            try:
                cookies = ctx.cookies()
                url = ctx.pages[-1].url
            except Exception:
                continue
            names = {c.get("name", "") for c in cookies}
            hit = names & AUTH
            if len(cookies) >= 8 and hit and settled(url):
                ok = True
                print(f"LOGIN_OK after {i}s cookies={len(cookies)} auth={sorted(hit)} url={url[:60]}", flush=True)
                time.sleep(2)              # 等 cookie 全落盘
                break
            if i % 15 == 0:
                if hit and not settled(url):
                    print(f"...已扫码 ✓ 请在浏览器里【选店铺/进工作台】(url={url[:55]})", flush=True)
                else:
                    print(f"...等登录 (cookies={len(cookies)} auth={sorted(hit) or 'none'} url={url[:50]})", flush=True)

        if ok:
            try:
                ctx.storage_state(path=str(session / "storage_state.json"))
                print(f"SAVED -> {session / 'storage_state.json'}", flush=True)
            except Exception as exc:
                print("save warn:", exc, flush=True)
                ok = False
        else:
            print("LOGIN_TIMEOUT_OR_CLOSED（没检测到登录态；重跑再试）", flush=True)
        ctx.close()
        return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _login_platform.py <douyin_compass|douyin_shop_admin|yuntu>", flush=True)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
