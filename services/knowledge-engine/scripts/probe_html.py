"""Analyze the HTML content from support.oceanengine.com article page."""
import asyncio
import json
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def main():
    article_url = (
        "https://support.oceanengine.com/support/content/143250"
        "?graphId=610&pageId=445&spaceId=221"
    )
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
        r = await client.get(article_url)
        html = r.text
        print(f"HTML length: {len(html)}")

        # Look for script tags with data
        import re
        scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)
        print(f"\nFound {len(scripts)} script tags")
        for i, s in enumerate(scripts):
            if len(s.strip()) > 50:
                # Check for interesting data
                for marker in ["window.__", "window.DATA", "clientVars", "contentData",
                               "feishu", "block_map", "__SSR", "initialState", "INITIAL"]:
                    if marker.lower() in s.lower():
                        print(f"\nScript {i} contains '{marker}' (len={len(s)}):")
                        # Find the marker and print context
                        idx = s.lower().find(marker.lower())
                        print(s[max(0,idx-50):idx+500])
                        break

        # Look for feishu docx iframe
        iframes = re.findall(r"<iframe[^>]*>", html)
        print(f"\nFound {len(iframes)} iframes")
        for iframe in iframes:
            print(f"  {iframe[:300]}")

        # Look for feishu-related URLs
        feishu_refs = re.findall(r'https?://[^"\'>\s]*(?:larkoffice|feishu|larksuite)[^"\'>\s]*', html)
        print(f"\nFeishu URLs found: {len(feishu_refs)}")
        for u in feishu_refs[:10]:
            print(f"  {u[:200]}")

        # Check if there's rendered text content
        # Strip all HTML tags and see what's left
        text_only = re.sub(r"<[^>]+>", " ", html)
        text_only = re.sub(r"\s+", " ", text_only).strip()
        print(f"\nText content length after stripping tags: {len(text_only)}")
        if len(text_only) > 100:
            print(f"Text preview: {text_only[:500]}")

        # Dump last portion of HTML (often has data/scripts)
        print(f"\n=== HTML tail (last 3000 chars) ===")
        print(html[-3000:])

asyncio.run(main())
