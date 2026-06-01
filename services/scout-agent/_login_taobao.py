"""Host-run 淘宝登录助手（竞品调研用）。

容器是 headless 无显示，登录得在 host 上弹可见浏览器。本脚本把 cookie 持久化到
sessions/taobao/user_data —— 这目录 bind-mount 进 omni-scout-agent 容器，
登完容器里的 /taobao/search、/taobao/detail 直接就有登录态。

用法（在有显示器的 host 上跑）：
    cd E:\\agent\\omni\\services\\scout-agent
    python _login_taobao.py
弹出的 Chromium 里扫码/账密登录淘宝，检测到登录态后自动存盘关窗（最多等 5 分钟）。
"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SESSION = Path(__file__).parent / "sessions" / "taobao"
USER_DATA = SESSION / "user_data"
SESSION.mkdir(parents=True, exist_ok=True)

# 淘宝登录后才写的强标记（跟 app/routers/sessions.py 一致）。
# 只用 unb/tracknick/lgc/_nk_ —— cookie2/_tb_token_/sgcookie 游客访问 taobao.com 就有，
# 当登录标记会在打开页面 8s 内误判成"已登录"提前关窗。
AUTH = {"unb", "tracknick", "lgc", "_nk_"}
NOT_SETTLED = ("login", "passport", "sso")


def settled(url: str) -> bool:
    u = (url or "").lower()
    if not u or u == "about:blank":
        return False
    return not any(k in u for k in NOT_SETTLED)


def main() -> int:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.taobao.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print("nav warn:", exc, flush=True)

        print("=== 请在弹出的 Chromium 里登录淘宝（扫码或账密），最多等 5 分钟 ===", flush=True)
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
                print(f"...等登录 (cookies={len(cookies)} auth={sorted(hit) or 'none'} url={url[:50]})", flush=True)

        if ok:
            try:
                ctx.storage_state(path=str(SESSION / "storage_state.json"))
            except Exception:
                pass
            print(f"SAVED -> {USER_DATA}", flush=True)
        else:
            print("LOGIN_TIMEOUT_OR_CLOSED", flush=True)
        ctx.close()
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
