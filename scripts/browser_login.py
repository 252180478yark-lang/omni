#!/usr/bin/env python3
"""
浏览器登录助手 — 在本机打开浏览器，登录后自动捕获 Cookie 并发送到后端。

Usage:
    python scripts/browser_login.py oceanengine
    python scripts/browser_login.py feishu
    python scripts/browser_login.py feishu https://custom-lark-url.com
"""

import asyncio
import json
import subprocess
import sys
import time
import urllib.request

PROFILES = {
    "oceanengine": {
        "url": "https://yuntu.oceanengine.com",
        "label": "帮助中心 (Ocean Engine)",
        "session_keys": ("session", "sid_tt", "sid_guard", "uid_tt"),
        "cookie_domains": ("oceanengine", "bytedance", "toutiao"),
    },
    "feishu": {
        "url": "https://bytedance.larkoffice.com",
        "label": "飞书 (Lark Office)",
        "session_keys": ("session", "sid", "session_list", "lark_oapi"),
        "cookie_domains": ("feishu", "larkoffice", "larksuite", "bytedance"),
    },
}

API_BASE = "http://localhost:8002/api/v1/knowledge/harvester"


def _ensure_playwright():
    try:
        import playwright  # noqa: F401
        return
    except ImportError:
        pass
    print("  Playwright 未安装，正在安装...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "playwright"],
        stdout=subprocess.DEVNULL,
    )
    print("  安装 Chromium 浏览器...")
    subprocess.check_call(
        [sys.executable, "-m", "playwright", "install", "chromium"],
    )
    print()


async def run_login(login_type: str, custom_url: str | None = None):
    profile = PROFILES[login_type]
    url = custom_url or profile["url"]

    _ensure_playwright()
    from playwright.async_api import async_playwright

    print(f"\n  正在打开浏览器 → {url}")
    print(f"  请在浏览器中完成 [{profile['label']}] 登录")
    print("  登录成功后将自动捕获 Cookie 并发送到后端\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  ! 页面加载异常: {e}")
            print("    浏览器已打开，请手动导航到目标页面并登录\n")

        print("  等待登录...")

        deadline = time.time() + 300
        found = False

        while time.time() < deadline:
            await asyncio.sleep(3)
            try:
                current_url = page.url
            except Exception:
                break

            cookies = await ctx.cookies()
            session_cookies = [
                c
                for c in cookies
                if any(k in c["name"].lower() for k in profile["session_keys"])
            ]

            if session_cookies and "login" not in current_url.lower():
                target_cookies = [
                    c
                    for c in cookies
                    if any(
                        d in c.get("domain", "") for d in profile["cookie_domains"]
                    )
                ]
                if not target_cookies:
                    target_cookies = cookies

                pw_cookies = [
                    {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c["domain"],
                        "path": c.get("path", "/"),
                        "httpOnly": c.get("httpOnly", False),
                        "secure": c.get("secure", True),
                        "sameSite": c.get("sameSite", "None"),
                    }
                    for c in target_cookies
                ]

                payload = json.dumps(
                    {"login_type": login_type, "cookies": pw_cookies}
                ).encode()

                endpoint = f"{API_BASE}/upload-login-cookies"
                req = urllib.request.Request(
                    endpoint,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                try:
                    resp = urllib.request.urlopen(req, timeout=10)
                    result = json.loads(resp.read())
                    if result.get("success"):
                        print(f"\n  >>> 登录成功！已保存 {len(pw_cookies)} 个 Cookie <<<\n")
                        found = True
                    else:
                        print(f"\n  X 保存失败: {result.get('error', 'unknown')}")
                except Exception as e:
                    print(f"\n  X 发送 Cookie 到后端失败: {e}")
                    print("    请确认 knowledge-engine 服务正在运行 (docker ps)")

                await asyncio.sleep(2)
                break

        if not found:
            print("\n  登录超时（5 分钟）或未检测到会话 Cookie")

        await browser.close()
        print("  浏览器已关闭\n")


def main():
    print("\n" + "=" * 50)
    print("  Omni-Vibe 浏览器登录助手")
    print("=" * 50)

    if len(sys.argv) < 2 or sys.argv[1] not in PROFILES:
        print("\nUsage: python scripts/browser_login.py <type> [url]")
        print("\n  type:")
        for k, v in PROFILES.items():
            print(f"    {k:15s} — {v['label']}")
        print(f"\nExamples:")
        print(f"  python scripts/browser_login.py oceanengine")
        print(f"  python scripts/browser_login.py feishu")
        print(f"  python scripts/browser_login.py feishu https://my-company.larkoffice.com")
        sys.exit(1)

    login_type = sys.argv[1]
    custom_url = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(run_login(login_type, custom_url))


if __name__ == "__main__":
    main()
