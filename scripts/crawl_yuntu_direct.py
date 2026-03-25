"""巨量云图帮助中心 — 直接爬取 + 图片下载 + LLM 图片分析 + 入库

用法:
  python scripts/crawl_yuntu_direct.py            # 全量爬取
  python scripts/crawl_yuntu_direct.py 5           # 只爬前 5 页
  python scripts/crawl_yuntu_direct.py --no-images # 跳过图片处理
"""
import argparse
import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "knowledge-engine"))

import httpx
from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

KE = "http://localhost:8002/api/v1/knowledge"
AI_HUB = "http://localhost:8001/api/v1/ai/chat"
BASE_URL = "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221"
AUTH_FILE = Path(r"E:\agent\omni\services\knowledge-engine\data\harvester_auth.json")
if not AUTH_FILE.exists():
    AUTH_FILE = Path(r"E:\app\data\harvester_auth.json")

IMAGE_DIR = Path(r"E:\agent\omni\services\knowledge-engine\data\images")
_IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

IMAGE_ANALYSIS_PROMPT = (
    "请用中文详细描述这张图片的内容。"
    "如果是产品界面截图，请描述界面上的关键元素、按钮、数据和操作流程。"
    "如果包含图表或数据，请提取关键数字和趋势。"
    "如果是流程图或架构图，请描述节点和连线关系。"
    "输出纯文本描述，不超过300字。"
)


def _detect_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"RIFF":
        return "webp"
    return "png"


async def decrypt_and_save_images(
    cdn_url_data: dict[str, dict],
    tokens_needed: set[str],
    job_id: str,
) -> dict[str, Path]:
    """Download from feishucdn.com, AES-GCM decrypt, save to disk."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("  [WARN] cryptography not installed, skipping image download")
        return {}

    available = tokens_needed & set(cdn_url_data.keys())
    if not available:
        return {}

    img_dir = IMAGE_DIR / job_id
    img_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for token in available:
            info = cdn_url_data[token]
            url = info.get("url", "")
            secret = info.get("secret", "")
            nonce_b64 = info.get("nonce", "")
            if not (url and secret and nonce_b64):
                continue
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                key = base64.b64decode(secret)
                nonce = base64.b64decode(nonce_b64)
                decrypted = AESGCM(key).decrypt(nonce, resp.content, None)
                if len(decrypted) > 100:
                    ext = _detect_ext(decrypted)
                    filepath = img_dir / f"{token}.{ext}"
                    filepath.write_bytes(decrypted)
                    result[token] = filepath
            except Exception as e:
                print(f"    decrypt failed for {token[:12]}: {e}")

    return result


def replace_cdn_urls(markdown: str, saved: dict[str, Path], job_id: str) -> str:
    """Replace Feishu CDN URLs with local file paths in markdown."""
    for match in _IMG_RE.finditer(markdown):
        cdn_url = match.group(2)
        tm = re.search(r"/cover/([^/?]+)", cdn_url)
        if not tm:
            continue
        token = tm.group(1)
        if token in saved:
            local = f"[local:{saved[token].name}]"
            markdown = markdown.replace(cdn_url, local)
    return markdown


async def analyze_single_image(client: httpx.AsyncClient, filepath: Path) -> str:
    """Send one image to AI Hub for multimodal analysis."""
    data = filepath.read_bytes()
    ext = filepath.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
    b64 = base64.b64encode(data).decode()
    data_uri = f"data:{mime};base64,{b64}"

    try:
        resp = await client.post(AI_HUB, json={
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": IMAGE_ANALYSIS_PROMPT},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
            "temperature": 0.3,
            "max_tokens": 1024,
        })
        if resp.status_code == 200:
            body = resp.json()
            return body.get("content", "") or body.get("data", {}).get("content", "")
    except Exception as e:
        print(f"    LLM analysis failed: {e}")
    return ""


async def process_article_images(
    markdown: str,
    cdn_url_data: dict[str, dict],
    job_id: str,
) -> tuple[str, int, int]:
    """Full pipeline: download → decrypt → LLM analyze → merge descriptions into markdown."""
    matches = _IMG_RE.findall(markdown)
    if not matches:
        return markdown, 0, 0

    tokens_in_article: set[str] = set()
    for _, u in matches:
        tm = re.search(r"/cover/([^/?]+)", u)
        if tm:
            tokens_in_article.add(tm.group(1))

    saved = await decrypt_and_save_images(cdn_url_data, tokens_in_article, job_id)
    if not saved:
        return markdown, 0, len(matches)

    # LLM analyze each saved image
    descriptions: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=120.0) as client:
        for token, filepath in saved.items():
            desc = await analyze_single_image(client, filepath)
            if desc:
                descriptions[token] = desc
                print(f"    🖼 {filepath.name}: {desc[:60]}...")

    # Merge descriptions into markdown
    for match in _IMG_RE.finditer(markdown):
        alt, cdn_url = match.group(1), match.group(2)
        tm = re.search(r"/cover/([^/?]+)", cdn_url)
        if not tm:
            continue
        token = tm.group(1)
        if token in descriptions:
            original = match.group(0)
            desc_block = f"\n\n> **[图片内容]** {descriptions[token]}\n"
            markdown = markdown.replace(original, original + desc_block, 1)

    return markdown, len(saved), len(matches)


async def extract_article(ctx, article_url, cdn_url_data: dict):
    """Open a fresh page, intercept CDN responses, extract Feishu content."""
    page = await ctx.new_page()

    async def _on_cdn_response(response):
        if "cdn_url" not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
            for item in body.get("data") or []:
                token = item.get("file_token", "")
                if token and item.get("url"):
                    cdn_url_data[token] = {
                        "url": item["url"],
                        "secret": item.get("secret", ""),
                        "nonce": item.get("nonce", ""),
                    }
        except Exception:
            pass

    page.on("response", _on_cdn_response)

    try:
        try:
            await page.goto(article_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            return None, f"nav_failed: {e}"

        if "login" in page.url.lower() or "passport" in page.url.lower():
            return None, "redirected_to_login"

        target_frame = None
        for _ in range(15):
            for frame in page.frames:
                if any(k in frame.url for k in ["larkoffice", "feishu", "larksuite"]):
                    target_frame = frame
                    break
            if target_frame:
                break
            await page.wait_for_timeout(2000)

        if not target_frame:
            return None, "no_feishu_iframe"

        await page.wait_for_timeout(3000)

        for _ in range(10):
            try:
                raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
                if raw:
                    doc = parse_feishu_document(raw)
                    if doc and len(doc.get("text", "")) > 30:
                        # Batch-fetch CDN keys for all images in this article
                        img_tokens = set()
                        for _, u in _IMG_RE.findall(doc.get("markdown", "")):
                            tm = re.search(r"/cover/([^/?]+)", u)
                            if tm:
                                img_tokens.add(tm.group(1))

                        missing = img_tokens - set(cdn_url_data.keys())
                        if missing:
                            # Step 1: Scroll to trigger lazy image CDN requests
                            try:
                                await target_frame.evaluate("""() => {
                                    return new Promise(resolve => {
                                        const containers = [
                                            document.scrollingElement,
                                            document.documentElement,
                                            ...document.querySelectorAll('[class*="render"], [class*="layout"], [class*="editor"], [class*="doc"]')
                                        ].filter(Boolean);
                                        const el = containers.find(e => e.scrollHeight > e.clientHeight + 100) || containers[0];
                                        if (!el) { resolve(); return; }
                                        const step = Math.max(400, Math.floor(el.scrollHeight / 20));
                                        let pos = 0;
                                        const timer = setInterval(() => {
                                            pos += step;
                                            el.scrollTo(0, pos);
                                            if (pos >= el.scrollHeight) { clearInterval(timer); el.scrollTo(0, 0); resolve(); }
                                        }, 100);
                                        setTimeout(() => { clearInterval(timer); resolve(); }, 15000);
                                    });
                                }""")
                            except Exception:
                                pass
                            await page.wait_for_timeout(3000)

                            # Step 2: Batch-fetch CDN keys for still-missing tokens
                            still_missing = list(img_tokens - set(cdn_url_data.keys()))
                            for i in range(0, len(still_missing), 10):
                                batch = still_missing[i:i+10]
                                try:
                                    batch_result = await target_frame.evaluate(
                                        """(tokens) => {
                                        return new Promise(async (resolve) => {
                                            try {
                                                const resp = await fetch('/space/api/box/file/cdn_url/', {
                                                    method: 'POST',
                                                    headers: {'Content-Type': 'application/json'},
                                                    body: JSON.stringify({file_tokens: tokens, type: 'image'}),
                                                    credentials: 'include'
                                                });
                                                const data = await resp.json();
                                                resolve(JSON.stringify(data));
                                            } catch(e) {
                                                resolve(JSON.stringify({error: e.message}));
                                            }
                                        });
                                    }""",
                                        batch,
                                    )
                                    if batch_result:
                                        batch_data = json.loads(batch_result)
                                        for item in batch_data.get("data") or []:
                                            token = item.get("file_token", "")
                                            if token and item.get("url"):
                                                cdn_url_data[token] = {
                                                    "url": item["url"],
                                                    "secret": item.get("secret", ""),
                                                    "nonce": item.get("nonce", ""),
                                                }
                                except Exception as e:
                                    print(f"  Batch CDN chunk failed: {e}")

                            got = len(img_tokens & set(cdn_url_data.keys()))
                            print(f"  CDN keys: {got}/{len(img_tokens)}")

                        return doc, None
            except Exception:
                pass
            await page.wait_for_timeout(2000)

        return None, "content_extraction_failed"
    finally:
        page.remove_listener("response", _on_cdn_response)
        await page.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("max_pages", nargs="?", type=int, default=None)
    parser.add_argument("--no-images", action="store_true", help="Skip image processing")
    args = parser.parse_args()

    if not AUTH_FILE.exists():
        print(f"[ERROR] Auth file not found: {AUTH_FILE}")
        return

    job_id = str(uuid4())
    do_images = not args.no_images
    print(f"Job ID: {job_id}")
    print(f"Images: {'ON (download + LLM analyze)' if do_images else 'OFF'}")

    # Get nav tree
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(f"{KE}/harvester/tree", json={"url": BASE_URL})
        tree = r.json()["data"]
        articles = tree["articles"]
        if args.max_pages:
            articles = articles[:args.max_pages]
        print(f"Graph: {tree['graph_name']}")
        print(f"Articles: {len(articles)} / {tree['total_articles']}")

    # Launch browser
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state=str(AUTH_FILE))

    cdn_url_data: dict[str, dict] = {}
    results = []
    total_images_saved = 0
    total_images_found = 0

    for idx, art in enumerate(articles):
        title = art["title"]
        mid = art["mapping_id"]
        url = f"https://yuntu.oceanengine.com/support/content/{mid}?graphId=610&pageId=445&spaceId=221"

        print(f"\n[{idx+1}/{len(articles)}] {title}")

        doc, err = None, None
        for retry in range(3):
            doc, err = await extract_article(ctx, url, cdn_url_data)
            if doc:
                break
            if retry < 2:
                wait = 5 * (retry + 1)
                print(f"  Retry {retry+1} in {wait}s... ({err})")
                await asyncio.sleep(wait)

        if not doc:
            print(f"  FAIL: {err}")
            if idx < len(articles) - 1:
                await asyncio.sleep(3)
            continue

        md = doc.get("markdown", doc.get("text", ""))
        img_saved, img_total = 0, 0

        if do_images and _IMG_RE.search(md):
            print(f"  Found {len(_IMG_RE.findall(md))} images, processing...")
            md, img_saved, img_total = await process_article_images(md, cdn_url_data, job_id)
            total_images_saved += img_saved
            total_images_found += img_total

        text_len = len(doc.get("text", ""))
        img_info = f", img {img_saved}/{img_total}" if img_total > 0 else ""
        print(f"  OK: {len(md)} md, {text_len} text, {doc['block_count']} blocks{img_info}")

        results.append({"title": title, "markdown": md, "source_url": url})

        if idx < len(articles) - 1:
            await asyncio.sleep(3)

    await browser.close()
    await pw.stop()

    # Summary
    print(f"\n{'='*60}")
    print(f"Crawled: {len(results)}/{len(articles)} articles")
    print(f"Total markdown: {sum(len(r['markdown']) for r in results):,} chars")
    if do_images:
        print(f"Images: {total_images_saved} downloaded+analyzed / {total_images_found} found")
        print(f"Image dir: {IMAGE_DIR / job_id}")

    if not results:
        print("[WARNING] No content extracted!")
        return

    # Save to KB
    print(f"\n=== Saving to Knowledge Base ===")
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.get(f"{KE}/bases")
        kbs = r.json()["data"]
        kb_id = None
        for kb in kbs:
            if "巨量云图" in kb["name"]:
                kb_id = kb["id"]
                print(f"Using KB: {kb['name']} ({kb_id[:8]})")
                break
        if not kb_id:
            r = await c.post(f"{KE}/bases", json={"name": "巨量云图", "description": "巨量云图帮助中心文档"})
            kb_id = r.json()["data"]["id"]
            print(f"Created KB: {kb_id[:8]}")

        chapters = [{"title": r["title"], "markdown": r["markdown"], "source_url": r["source_url"]} for r in results]
        r = await c.post(f"{KE}/harvester/save", json={"kb_id": kb_id, "chapters": chapters})
        save_data = r.json()["data"]
        print(f"Submitted {save_data['saved_count']} ingestion tasks")

    print("\n[DONE]")


if __name__ == "__main__":
    asyncio.run(main())
