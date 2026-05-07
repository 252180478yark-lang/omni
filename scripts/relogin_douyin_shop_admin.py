#!/usr/bin/env python3
"""
抖店后台 (fxg.jinritemai.com) 重新登录脚本——直接在 host 跑。

用途：scout-agent 容器跑 sku_bootstrapper 时报 "session expired" → 用这个脚本
弹浏览器让老板手动登录 → cookie 持久化到 services/scout-agent/sessions/
douyin_shop_admin/user_data/，下次容器启动 sku_bootstrapper 自动用新 cookie。

前提：docker-compose.yml 已把 scout-agent 的 sessions volume 改 bind mount
（W4-B 切片 12，2026-05-07）。这样 host 写的 cookie 容器立刻可见。

用法：
    python scripts/relogin_douyin_shop_admin.py

流程：
1. 浏览器窗口自动打开 → fxg.jinritemai.com
2. 老板扫码 / 输账号密码登录
3. 看到抖店后台首页（不是 login/passport 页）→ 关闭浏览器
4. 脚本自动检测到登录成功 → 退出
5. 重启 scout-agent 容器：docker compose restart scout-agent
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION_DIR = REPO_ROOT / "services" / "scout-agent" / "sessions" / "douyin_shop_admin"
USER_DATA_DIR = SESSION_DIR / "user_data"
STORAGE_STATE_FILE = SESSION_DIR / "storage_state.json"
TARGET_URL = "https://fxg.jinritemai.com/ffa/g/list"
DEADLINE_SECONDS = 300  # 老板有 5 分钟登录


async def main() -> int:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[ERROR] host 没装 playwright。先装：pip install playwright && playwright install chromium")
        return 1

    print(f"[INFO] user_data_dir = {USER_DATA_DIR}")
    print(f"[INFO] 浏览器即将打开 → {TARGET_URL}")
    print(f"[INFO] 你有 {DEADLINE_SECONDS}s 时间登录；登录到看见 g-list 页面就 OK")
    print("[INFO] 关闭浏览器或脚本检测到登录成功 → 自动退出")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print(f"[WARN] 初始 nav 失败/慢: {exc}（继续等登录）")

        success = False
        for i in range(DEADLINE_SECONDS):
            await asyncio.sleep(1)
            if not ctx.pages:
                print(f"[INFO] 你关闭了浏览器（{i}s）")
                break
            try:
                cur_url = ctx.pages[-1].url
            except Exception:
                continue

            # 登录成功 = URL 跳到 g/list 工作区且没有 login/passport 关键词
            url_lower = cur_url.lower()
            if (
                "fxg.jinritemai.com" in url_lower
                and "login" not in url_lower
                and "passport" not in url_lower
                and "store-select" not in url_lower
            ):
                # 先确认有 cookie（避免误判）
                cookies = await ctx.cookies()
                if any(
                    c.get("name") in {"sessionid", "sid_tt", "uid_tt", "passport_csrf_token"}
                    for c in cookies
                ):
                    if i >= 10:  # 给 10 秒冷启动 buffer，避免立刻误判
                        success = True
                        print(f"[OK] 登录态检测到（{i}s 后）；cur_url={cur_url}")
                        print(f"[OK] cookie 数：{len(cookies)}")
                        break

            if (i + 1) % 30 == 0:
                print(f"[INFO] 已等 {i+1}s，cur_url={cur_url}")

        # 关键：保存 storage_state.json（明文 JSON，跨 OS 通用）
        # user_data_dir 里的 cookie 在 Windows 用 DPAPI 加密，容器 Linux 解不出
        try:
            await ctx.storage_state(path=str(STORAGE_STATE_FILE))
            print(f"[OK] storage_state 已保存 → {STORAGE_STATE_FILE}")
            print(f"[OK] 文件大小：{STORAGE_STATE_FILE.stat().st_size} bytes")
        except Exception as exc:
            print(f"[ERROR] storage_state 保存失败：{exc}")

        try:
            await ctx.close()
        except Exception:
            pass

    if not success:
        print("[WARN] 没检测到明确登录态。如果你确认登好了，storage_state 仍可能保存成功——")
        print("       检查上面 [OK] storage_state 行；有就直接重启 scout-agent 试")

    print("[DONE] 下一步：")
    print("  docker compose restart scout-agent")
    print("  docker logs -f omni-scout-agent | grep g-list")
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
