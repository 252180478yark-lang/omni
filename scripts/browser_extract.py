#!/usr/bin/env python3
"""
本机内容提取助手 — 在本机浏览器中打开帮助中心页面，
等待 JSSDK 渲染完成后自动提取全部内容+图片，发送到后端。

Usage:
    python scripts/browser_extract.py <url>

Examples:
    python scripts/browser_extract.py "https://yuntu.oceanengine.com/support/content/143250?graphId=610&mappingType=2&pageId=445&spaceId=221"
"""

import asyncio
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

API_BASE = "http://localhost:8002/api/v1/knowledge/harvester"


def _ensure_playwright():
    try:
        import playwright  # noqa: F401
        return
    except ImportError:
        pass
    print("  Playwright 未安装，正在安装...")
    import subprocess
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "playwright"],
        stdout=subprocess.DEVNULL,
    )
    print("  安装 Chromium 浏览器...")
    subprocess.check_call(
        [sys.executable, "-m", "playwright", "install", "chromium"],
    )
    print()


EXTRACT_CONTENT_JS = """() => {
    const result = { title: '', markdown: '', images: [], debug: {} };

    // Get page title from breadcrumb / h1
    const h1 = document.querySelector('h1');
    result.title = h1 ? h1.innerText.trim() : document.title || '';

    // --- Detect Feishu JSSDK rendered content ---
    // The yuntu help center loads content via Feishu JSSDK which renders
    // into the main content area. We need to find the RIGHT container
    // (not the sidebar/nav).

    // Step 1: Try to find Feishu JSSDK rendered content specifically
    const jssdkSelectors = [
        '.render-doc-container',
        '[class*="render-doc"]',
        '.lark-editor-core',
        '[class*="docx-editor"]',
        '[class*="lark-doc"]',
        '.feishu-doc-render',
        '#feishu-doc-render',
        '[class*="suite-render"]',
        '.doc-content-container',
        '[data-page-id]',
        '[class*="page-content"] [class*="render"]',
    ];

    let contentEl = null;
    for (const sel of jssdkSelectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText.trim().length > 100) {
            contentEl = el;
            result.debug.foundBy = 'jssdk: ' + sel;
            break;
        }
    }

    // Step 2: Check inside iframes (JSSDK sometimes uses them)
    if (!contentEl) {
        const iframes = document.querySelectorAll('iframe');
        for (const iframe of iframes) {
            try {
                const iDoc = iframe.contentDocument || iframe.contentWindow.document;
                if (iDoc && iDoc.body && iDoc.body.innerText.trim().length > 200) {
                    contentEl = iDoc.body;
                    result.debug.foundBy = 'iframe: ' + (iframe.src || iframe.id || 'unknown');
                    break;
                }
            } catch(e) { /* cross-origin */ }
        }
    }

    // Step 3: Try the main content area (skip sidebar)
    if (!contentEl) {
        const mainSelectors = [
            '.article-detail',
            '.article-content',
            '[class*="article-detail"]',
            '[class*="content-detail"]',
            '.content-main',
            '[class*="content-main"]',
            '[class*="page-content"]:not([class*="nav"])',
            'main',
            '[role="main"]',
            '.main-content',
        ];
        for (const sel of mainSelectors) {
            const el = document.querySelector(sel);
            if (el && el.innerText.trim().length > 200) {
                contentEl = el;
                result.debug.foundBy = 'main: ' + sel;
                break;
            }
        }
    }

    // Step 4: Heuristic — find the largest non-nav content block
    if (!contentEl) {
        const candidates = document.querySelectorAll('div, section, article');
        let best = null;
        let bestScore = 0;
        for (const el of candidates) {
            // Skip nav/sidebar elements
            const cls = (el.className || '').toLowerCase();
            const id = (el.id || '').toLowerCase();
            if (/(nav|sidebar|menu|header|footer|toc|breadcrumb)/.test(cls + id)) continue;
            // Skip elements that are likely just wrappers for the whole page
            if (el === document.body || el.parentElement === document.body) continue;

            const text = el.innerText.trim();
            const len = text.length;
            const childBlocks = el.querySelectorAll('p, h1, h2, h3, li, img, table').length;
            const score = len * (1 + childBlocks * 0.1);
            if (score > bestScore && len > 300) {
                bestScore = score;
                best = el;
            }
        }
        if (best) {
            contentEl = best;
            result.debug.foundBy = 'heuristic';
        }
    }

    if (!contentEl) {
        result.markdown = '';
        result.debug.error = 'no content container found';
        result.debug.bodyLen = document.body ? document.body.innerText.length : 0;
        return JSON.stringify(result);
    }

    result.debug.containerTag = contentEl.tagName;
    result.debug.containerClass = (contentEl.className || '').toString().slice(0, 200);
    result.debug.textLen = contentEl.innerText.trim().length;

    // Convert DOM to markdown-like text
    function domToMarkdown(node, depth) {
        if (depth > 50) return '';
        if (node.nodeType === Node.TEXT_NODE) {
            return node.textContent;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return '';

        const style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return '';

        const tag = node.tagName.toLowerCase();
        if (tag === 'script' || tag === 'style' || tag === 'noscript') return '';

        const children = Array.from(node.childNodes).map(c => domToMarkdown(c, depth + 1)).join('');

        if (tag === 'h1') return '# ' + children.trim() + '\\n\\n';
        if (tag === 'h2') return '## ' + children.trim() + '\\n\\n';
        if (tag === 'h3') return '### ' + children.trim() + '\\n\\n';
        if (tag === 'h4') return '#### ' + children.trim() + '\\n\\n';
        if (tag === 'h5' || tag === 'h6') return '##### ' + children.trim() + '\\n\\n';
        if (tag === 'p') {
            const text = children.trim();
            return text ? text + '\\n\\n' : '';
        }
        if (tag === 'li') return '- ' + children.trim() + '\\n';
        if (tag === 'ul' || tag === 'ol') return '\\n' + children + '\\n';
        if (tag === 'br') return '\\n';
        if (tag === 'hr') return '\\n---\\n\\n';
        if (tag === 'strong' || tag === 'b') return '**' + children.trim() + '**';
        if (tag === 'em' || tag === 'i') return '*' + children.trim() + '*';
        if (tag === 'code') return '`' + children + '`';
        if (tag === 'pre') return '```\\n' + children + '\\n```\\n\\n';
        if (tag === 'blockquote') return '> ' + children.trim().replace(/\\n/g, '\\n> ') + '\\n\\n';
        if (tag === 'a') {
            const href = node.getAttribute('href') || '';
            const text = children.trim();
            if (!text) return '';
            return href ? '[' + text + '](' + href + ')' : text;
        }
        if (tag === 'img') {
            const src = node.getAttribute('src') || node.dataset.src || '';
            const alt = node.getAttribute('alt') || '';
            if (src && !src.startsWith('data:image/svg')) {
                result.images.push({ src, alt, width: node.naturalWidth || 0, height: node.naturalHeight || 0 });
                return '![' + alt + '](' + src + ')\\n\\n';
            }
            return '';
        }
        if (tag === 'table') {
            const rows = node.querySelectorAll('tr');
            let md = '';
            rows.forEach((row, ri) => {
                const cells = row.querySelectorAll('td, th');
                const line = Array.from(cells).map(c => c.innerText.trim()).join(' | ');
                md += '| ' + line + ' |\\n';
                if (ri === 0) {
                    md += '| ' + Array.from(cells).map(() => '---').join(' | ') + ' |\\n';
                }
            });
            return md + '\\n';
        }
        if (tag === 'div') {
            const text = children.trim();
            if (!text) return '';
            const hasBlock = node.querySelector('p, h1, h2, h3, h4, h5, ul, ol, table, blockquote, pre, img');
            return hasBlock ? children : text + '\\n\\n';
        }
        return children;
    }

    result.markdown = domToMarkdown(contentEl, 0).replace(/\\n{3,}/g, '\\n\\n').trim();

    // Collect all images from the content area
    contentEl.querySelectorAll('img').forEach(img => {
        const src = img.getAttribute('src') || img.dataset.src || '';
        if (src && !src.startsWith('data:image/svg') && !result.images.find(i => i.src === src)) {
            result.images.push({
                src, alt: img.getAttribute('alt') || '',
                width: img.naturalWidth || 0, height: img.naturalHeight || 0,
            });
        }
    });

    return JSON.stringify(result);
}"""

SCROLL_AND_WAIT_JS = """() => {
    return new Promise(resolve => {
        const containers = [
            document.scrollingElement,
            document.documentElement,
            ...document.querySelectorAll('[class*="render"], [class*="layout"], [class*="editor"], [class*="doc"], [class*="content"]')
        ].filter(Boolean);
        const el = containers.find(e => e.scrollHeight > e.clientHeight + 100) || containers[0];
        if (!el) { resolve(); return; }
        let pos = 0;
        const step = Math.max(400, Math.floor(el.scrollHeight / 20));
        const timer = setInterval(() => {
            pos += step;
            el.scrollTo(0, pos);
            if (pos >= el.scrollHeight) {
                clearInterval(timer);
                el.scrollTo(0, 0);
                setTimeout(resolve, 2000);
            }
        }, 300);
    });
}"""


async def download_image(page, src: str) -> bytes | None:
    """Download image via the authenticated browser session."""
    try:
        b64 = await page.evaluate("""(url) => {
            return new Promise(async (resolve) => {
                try {
                    const resp = await fetch(url, {credentials: 'include'});
                    if (!resp.ok) { resolve(null); return; }
                    const blob = await resp.blob();
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result.split(',')[1]);
                    reader.readAsDataURL(blob);
                } catch(e) { resolve(null); }
            });
        }""", src)
        if b64:
            return base64.b64decode(b64)
    except Exception:
        pass
    return None


async def run_extract(url: str):
    _ensure_playwright()
    from playwright.async_api import async_playwright

    # Load cookies if available
    auth_paths = [
        Path("services/knowledge-engine/data/harvester_auth.json"),
        Path("data/harvester_auth.json"),
    ]
    feishu_auth_paths = [
        Path("services/knowledge-engine/data/feishu_auth.json"),
        Path("data/feishu_auth.json"),
    ]

    print(f"\n  正在打开浏览器 → {url}")
    print("  请等待页面完全加载...\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})

        # Try to load cookies
        total_loaded = 0
        for ap in auth_paths:
            if ap.exists():
                try:
                    state = json.loads(ap.read_text(encoding="utf-8"))
                    cookies = state.get("cookies", [])
                    if cookies:
                        await ctx.add_cookies(cookies)
                        total_loaded += len(cookies)
                except Exception:
                    pass
                break
        for ap in feishu_auth_paths:
            if ap.exists():
                try:
                    state = json.loads(ap.read_text(encoding="utf-8"))
                    cookies = state.get("cookies", [])
                    if cookies:
                        await ctx.add_cookies(cookies)
                        total_loaded += len(cookies)
                except Exception:
                    pass
                break
        if total_loaded:
            print(f"  已加载 {total_loaded} 个认证 Cookie")

        page = await ctx.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  ! 页面加载异常: {e}")

        # Wait for JSSDK to initialize and render
        print("  等待 JSSDK 渲染内容...")
        await page.wait_for_timeout(12000)

        # Check if content has rendered, wait more if needed
        for wait_round in range(3):
            body_len = await page.evaluate("() => document.body.innerText.length")
            iframes = await page.evaluate("() => document.querySelectorAll('iframe').length")
            jssdk_el = await page.evaluate("""() => {
                const sels = ['.render-doc-container', '[class*="render-doc"]',
                    '.lark-editor-core', '[class*="docx-editor"]', '[class*="lark-doc"]',
                    '[class*="suite-render"]', '.doc-content-container'];
                for (const s of sels) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim().length > 100) return s + ':' + el.innerText.length;
                }
                return null;
            }""")
            print(f"  [检查 {wait_round+1}/3] 页面文字={body_len}, iframes={iframes}, JSSDK容器={jssdk_el}")
            if jssdk_el or body_len > 2000:
                break
            print("  继续等待渲染...")
            await page.wait_for_timeout(5000)

        # Scroll to trigger lazy-loaded content and images
        print("  滚动页面加载全部内容...")
        try:
            await page.evaluate(SCROLL_AND_WAIT_JS)
        except Exception:
            await page.wait_for_timeout(3000)

        await page.wait_for_timeout(3000)

        # Try to find Feishu JSSDK iframe via Playwright frames API
        print("  检查 iframe 内容...")
        print(f"  共 {len(page.frames)} 个 frame")
        target_frame = None
        for frame in page.frames:
            frame_url = frame.url or ""
            if frame == page.main_frame:
                continue
            try:
                frame_text_len = await frame.evaluate("() => document.body ? document.body.innerText.length : 0")
                frame_title = await frame.evaluate("() => document.title || ''")
                frame_snippet = await frame.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 200)")
                print(f"  [frame] {frame_url[:100]}")
                print(f"    文字: {frame_text_len}, 标题: {frame_title}")
                print(f"    片段: {frame_snippet[:120]}")
                if any(d in frame_url for d in ("larkoffice", "feishu", "larksuite", "docx")) and frame_text_len > 100:
                    target_frame = frame
            except Exception as fe:
                print(f"  [frame] {frame_url[:80]} — 无法访问: {fe}")

        # Extract content from the best source
        print("  提取文本内容...")
        if target_frame:
            print(f"  >>> 从飞书 iframe 中提取内容")
            raw = await target_frame.evaluate(EXTRACT_CONTENT_JS)
        else:
            raw = await page.evaluate(EXTRACT_CONTENT_JS)
        data = json.loads(raw)

        title = data.get("title", "")
        markdown = data.get("markdown", "")
        images_info = data.get("images", [])
        block_map = data.get("_blockMap")
        debug = data.get("debug", {})

        if block_map:
            print(f"  发现 JSSDK clientVars: {len(block_map)} 个块")

        if debug:
            print(f"  [调试] 内容发现方式: {debug.get('foundBy', 'unknown')}")
            if debug.get('containerClass'):
                print(f"  [调试] 容器: <{debug.get('containerTag')}> class={debug.get('containerClass', '')[:100]}")
            if debug.get('error'):
                print(f"  [调试] 错误: {debug['error']}")
            if debug.get('textLen'):
                print(f"  [调试] 容器文本长度: {debug['textLen']}")

        print(f"  标题: {title}")
        print(f"  文本: {len(markdown)} 字符")
        print(f"  图片: {len(images_info)} 张")

        if len(markdown) < 200 and not block_map:
            print("\n  ! 提取到的内容太少，请确认页面已完全加载")
            print("    如果页面还在加载中，请等待加载完成后按 Enter 重试")
            print("    也可以手动滚动页面让内容完全显示")
            input("    按 Enter 重试提取...")
            await page.wait_for_timeout(3000)

            # Re-check frames after manual wait
            for frame in page.frames:
                frame_url = frame.url or ""
                if any(d in frame_url for d in ("larkoffice", "feishu", "larksuite", "docx")):
                    try:
                        flen = await frame.evaluate("() => document.body ? document.body.innerText.length : 0")
                        if flen > 200:
                            target_frame = frame
                            print(f"  重试: 发现 iframe 内容 ({flen} chars)")
                            break
                    except Exception:
                        pass

            if target_frame:
                raw = await target_frame.evaluate(EXTRACT_CONTENT_JS)
            else:
                raw = await page.evaluate(EXTRACT_CONTENT_JS)
            data = json.loads(raw)
            title = data.get("title", "") or title
            markdown = data.get("markdown", "")
            images_info = data.get("images", [])
            block_map = data.get("_blockMap")
            debug = data.get("debug", {})
            print(f"  重试: {len(markdown)} 字符, {len(images_info)} 张图片")

        # Download images from the correct context
        download_ctx = target_frame or page
        downloaded_images = []
        if images_info:
            print(f"\n  下载 {len(images_info)} 张图片...")
            for i, img in enumerate(images_info):
                src = img.get("src", "")
                if not src or src.startswith("data:"):
                    continue
                # Try download from iframe first, then from page
                img_data = await download_image(download_ctx, src)
                if not img_data or len(img_data) < 500:
                    img_data = await download_image(page, src)
                if img_data and len(img_data) > 500:
                    downloaded_images.append({
                        "data_b64": base64.b64encode(img_data).decode(),
                        "alt": img.get("alt", ""),
                        "src": src,
                        "size": len(img_data),
                    })
                    print(f"    [{i+1}/{len(images_info)}] {len(img_data)} bytes")
                else:
                    print(f"    [{i+1}/{len(images_info)}] 跳过 (太小或下载失败)")

        await browser.close()
        print("\n  浏览器已关闭")

        # Send to backend
        print("\n  发送到后端...")
        payload = json.dumps({
            "url": url,
            "title": title,
            "markdown": markdown,
            "images": downloaded_images,
            "block_map": block_map,
        }).encode()

        req = urllib.request.Request(
            f"{API_BASE}/upload-extracted-page",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=120)
            result = json.loads(resp.read())
            if result.get("success"):
                job_data = result.get("data", {})
                chars = job_data.get("word_count", 0)
                imgs = job_data.get("images_saved", 0)
                job_id = job_data.get("job_id", "")
                print(f"\n  >>> 提取成功！{chars} 字符, {imgs} 张图片 <<<")
                if job_id:
                    print(f"  Job ID: {job_id}")
                print("  刷新前端页面查看结果\n")
            else:
                print(f"\n  X 后端返回错误: {result.get('error', 'unknown')}")
        except Exception as e:
            print(f"\n  X 发送失败: {e}")
            fallback = Path("extracted_page.json")
            fallback.write_text(json.dumps({
                "title": title, "markdown": markdown,
                "images_count": len(downloaded_images),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  已保存到: {fallback}")


def main():
    print("\n" + "=" * 50)
    print("  Omni-Vibe 内容提取助手")
    print("=" * 50)

    if len(sys.argv) < 2:
        print("\nUsage: python scripts/browser_extract.py <url>")
        print("\nExample:")
        print('  python scripts/browser_extract.py "https://yuntu.oceanengine.com/support/content/143250?graphId=610&mappingType=2&pageId=445&spaceId=221"')
        sys.exit(1)

    url = sys.argv[1]
    asyncio.run(run_extract(url))


if __name__ == "__main__":
    main()
