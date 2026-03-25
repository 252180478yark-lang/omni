"""巨量云图帮助中心 — 一键采集入库脚本

用法:
  # 首次使用：交互式登录获取 Cookie，然后爬取入库
  python scripts/harvest_yuntu.py --login

  # Cookie 已保存：直接爬取入库
  python scripts/harvest_yuntu.py

  # 只爬前 5 页测试
  python scripts/harvest_yuntu.py --max-pages 5

  # 指定目标知识库
  python scripts/harvest_yuntu.py --kb-id 47d201b3-7a1e-4a52-bb46-e99c01f4be9f
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

KE_BASE = "http://localhost:8002/api/v1/knowledge"
TARGET_URL = (
    "https://yuntu.oceanengine.com/support/content/root"
    "?graphId=610&pageId=445&spaceId=221"
)
DEFAULT_KB_NAME = "巨量云图"


async def check_services():
    """Verify knowledge-engine and ai-provider-hub are running."""
    async with httpx.AsyncClient(timeout=5.0) as c:
        try:
            r = await c.get("http://localhost:8002/health")
            assert r.status_code == 200
        except Exception:
            print("[ERROR] Knowledge Engine (localhost:8002) is not running")
            return False
        try:
            r = await c.get("http://localhost:8001/health")
            assert r.status_code == 200
        except Exception:
            print("[ERROR] AI Provider Hub (localhost:8001) is not running")
            return False
    return True


async def check_auth() -> bool:
    """Check if harvester has valid auth cookies."""
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{KE_BASE}/harvester/auth-status")
        data = r.json().get("data", {})
        return data.get("has_auth", False)


async def interactive_login():
    """Open a Playwright browser for manual login, then capture and save cookies."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[ERROR] Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

    print("\n=== Interactive Login ===")
    print("A browser window will open. Please:")
    print("  1. Log in to yuntu.oceanengine.com")
    print("  2. Wait for the help center page to fully load")
    print("  3. Close the browser window when done")
    print()

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    ctx = await browser.new_context()
    page = await ctx.new_page()

    await page.goto(TARGET_URL, wait_until="domcontentloaded")
    print("[INFO] Browser opened. Waiting for you to log in...")

    try:
        # Wait for the user to close the browser or for the page to navigate past login
        while True:
            try:
                await page.wait_for_timeout(2000)
                url = page.url
                if "yuntu.oceanengine.com/support" in url and "login" not in url.lower():
                    # Check if cookies look valid (has session)
                    cookies = await ctx.cookies()
                    session_cookies = [c for c in cookies if "session" in c["name"].lower() or "sid_tt" in c["name"]]
                    if session_cookies:
                        print(f"[INFO] Detected {len(session_cookies)} session cookies. Saving...")
                        break
            except Exception:
                break

        # Get all cookies and save via harvester API
        all_cookies = await ctx.cookies()
        ocean_cookies = [c for c in all_cookies if "oceanengine" in c.get("domain", "")]
        if not ocean_cookies:
            ocean_cookies = all_cookies

        print(f"[INFO] Captured {len(ocean_cookies)} cookies")

        # Save via API
        cookie_payload = [
            {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")}
            for c in ocean_cookies
        ]
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{KE_BASE}/harvester/save-auth", json={"cookies": cookie_payload})
            if r.status_code == 200:
                print(f"[OK] Saved {len(cookie_payload)} cookies to harvester auth state")
            else:
                print(f"[ERROR] Failed to save cookies: {r.text}")
                return False

    finally:
        await browser.close()
        await pw.stop()

    return True


async def save_cookies_from_string(cookie_str: str):
    """Parse a raw cookie string and save via API."""
    cookies = []
    for pair in cookie_str.strip().split("; "):
        eq = pair.find("=")
        if eq < 0:
            continue
        name = pair[:eq].strip()
        value = pair[eq + 1:].strip()
        cookies.append({"name": name, "value": value, "domain": ".oceanengine.com", "path": "/"})

    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(f"{KE_BASE}/harvester/save-auth", json={"cookies": cookies})
        if r.status_code == 200:
            print(f"[OK] Saved {len(cookies)} cookies")
            return True
        print(f"[ERROR] {r.text}")
        return False


async def find_or_create_kb(kb_id: str | None) -> str:
    """Find or create the target knowledge base."""
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{KE_BASE}/bases")
        kbs = r.json()["data"]

        if kb_id:
            for kb in kbs:
                if kb["id"] == kb_id:
                    print(f"[KB] Using: {kb['name']} ({kb['id'][:8]})")
                    return kb["id"]
            print(f"[ERROR] KB {kb_id} not found")
            sys.exit(1)

        for kb in kbs:
            if DEFAULT_KB_NAME in kb["name"]:
                print(f"[KB] Using existing: {kb['name']} ({kb['id'][:8]})")
                return kb["id"]

        r = await c.post(f"{KE_BASE}/bases", json={
            "name": DEFAULT_KB_NAME,
            "description": "巨量云图帮助中心文档 — 自动采集",
        })
        new_kb = r.json()["data"]
        print(f"[KB] Created: {new_kb['name']} ({new_kb['id'][:8]})")
        return new_kb["id"]


async def crawl_and_ingest(kb_id: str, max_pages: int | None = None):
    """Main pipeline: crawl → save to KB."""
    async with httpx.AsyncClient(timeout=600.0) as c:
        # Step 1: Start crawl
        print(f"\n=== Step 1: Starting crawl ===")
        print(f"  URL: {TARGET_URL}")
        payload = {"url": TARGET_URL}
        if max_pages:
            payload["max_pages"] = max_pages
            print(f"  Max pages: {max_pages}")

        r = await c.post(f"{KE_BASE}/harvester/crawl", json=payload)
        if r.status_code != 200:
            print(f"[ERROR] Crawl start failed: {r.text}")
            return
        job_id = r.json()["data"]["job_id"]
        has_auth = r.json()["data"]["has_auth"]
        print(f"  Job ID: {job_id}")
        print(f"  Auth: {'Yes' if has_auth else 'No (public only)'}")

        # Step 2: Monitor crawl
        print(f"\n=== Step 2: Monitoring crawl ===")
        while True:
            await asyncio.sleep(3)
            r = await c.get(f"{KE_BASE}/harvester/jobs/{job_id}")
            job = r.json()["data"]
            status = job["status"]
            progress = job["progress"]
            total = job["total"]
            current = job.get("current_article")

            if current:
                title = current.get("title", "")[:40]
                print(f"  [{status}] {progress}/{total} — {title}")
            else:
                print(f"  [{status}] {progress}/{total}")

            if status in ("done", "failed"):
                break

        if status == "failed":
            print(f"[ERROR] Crawl failed: {job.get('error')}")
            return

        # Step 3: Analyze results
        chapters = job.get("chapters", [])
        success = [ch for ch in chapters if ch.get("word_count", 0) > 50]
        failed = [ch for ch in chapters if ch.get("error")]
        needs_auth = [ch for ch in chapters if ch.get("error") == "needs_auth"]

        print(f"\n=== Step 3: Crawl Results ===")
        print(f"  Total articles: {len(chapters)}")
        print(f"  Successfully extracted: {len(success)}")
        print(f"  Failed/empty: {len(failed)}")
        if needs_auth:
            print(f"  Needs auth (try --login): {len(needs_auth)}")

        if not success:
            print("[WARNING] No content extracted. Try --login to authenticate first.")
            return

        # Step 4: Save to KB
        print(f"\n=== Step 4: Saving {len(success)} chapters to KB ===")
        save_payload = {
            "kb_id": kb_id,
            "chapters": [
                {
                    "title": ch["title"],
                    "markdown": ch["markdown"],
                    "source_url": ch.get("source_url"),
                }
                for ch in success
            ],
        }
        r = await c.post(f"{KE_BASE}/harvester/save", json=save_payload)
        result = r.json()["data"]
        task_ids = result.get("task_ids", [])
        print(f"  Submitted {len(task_ids)} ingestion tasks")

        # Step 5: Monitor ingestion
        print(f"\n=== Step 5: Monitoring ingestion ===")
        completed = set()
        succeeded = 0
        fail_count = 0
        for _ in range(240):
            await asyncio.sleep(5)
            all_done = True
            for tid in task_ids:
                if tid in completed:
                    continue
                r = await c.get(f"{KE_BASE}/tasks/{tid}")
                t = r.json()["data"]
                if t["status"] == "succeeded":
                    completed.add(tid)
                    succeeded += 1
                elif t["status"] == "failed":
                    completed.add(tid)
                    fail_count += 1
                    print(f"  [FAIL] {tid[:8]}: {t.get('error', '')[:80]}")
                else:
                    all_done = False
            if all_done:
                break
            if len(completed) % 5 == 0 and len(completed) > 0:
                print(f"  Progress: {len(completed)}/{len(task_ids)} ({succeeded} ok, {fail_count} fail)")

        # Step 6: Final stats
        print(f"\n=== Final Results ===")
        print(f"  Ingested: {succeeded}/{len(task_ids)}")
        print(f"  Failed: {fail_count}")

        r = await c.get(f"{KE_BASE}/stats")
        stats = r.json()["data"]
        print(f"  Total documents: {stats['documents']}")
        print(f"  Total chunks: {stats['chunks']}")

        r = await c.get(f"{KE_BASE}/graph/{kb_id}")
        graph = r.json()["data"]
        print(f"  Graph entities: {len(graph['nodes'])}")
        print(f"  Graph relations: {len(graph['edges'])}")

        print("\n[DONE] Harvesting complete!")


async def main():
    parser = argparse.ArgumentParser(description="Harvest yuntu.oceanengine.com help center")
    parser.add_argument("--login", action="store_true", help="Open browser for interactive login")
    parser.add_argument("--cookie", type=str, help="Raw cookie string to save")
    parser.add_argument("--max-pages", type=int, help="Max pages to crawl")
    parser.add_argument("--kb-id", type=str, help="Target knowledge base ID")
    parser.add_argument("--crawl-only", action="store_true", help="Only crawl, don't ingest")
    args = parser.parse_args()

    print("=" * 50)
    print("  Yuntu Help Center Harvester")
    print("=" * 50)

    if not await check_services():
        sys.exit(1)
    print("[OK] Services are running")

    # Handle auth
    if args.cookie:
        if not await save_cookies_from_string(args.cookie):
            sys.exit(1)
    elif args.login:
        if not await interactive_login():
            sys.exit(1)
    else:
        has_auth = await check_auth()
        if not has_auth:
            print("[WARNING] No auth cookies found. Public content only.")
            print("  Use --login for interactive login, or --cookie 'cookie_string' to set cookies.")
            print()

    kb_id = await find_or_create_kb(args.kb_id)
    await crawl_and_ingest(kb_id, max_pages=args.max_pages)


if __name__ == "__main__":
    asyncio.run(main())
