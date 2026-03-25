"""Check image extraction from a single article."""
import asyncio, logging, json
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from app.services.harvester import crawl_articles

async def test():
    result = await crawl_articles(
        "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221",
        auth_state_path="/app/data/harvester_auth.json",
        max_pages=2,
        job_id="test-img",
    )
    for ch in result["chapters"]:
        md = ch.get("markdown", "")
        img_lines = [l.strip() for l in md.split("\n") if "![" in l]
        board_lines = [l.strip() for l in md.split("\n") if "画板" in l]
        print(f"\n=== {ch['title']} ===")
        print(f"  Text: {ch['word_count']} chars")
        print(f"  Image refs: {len(img_lines)}")
        for l in img_lines[:3]:
            print(f"    {l[:180]}")
        if board_lines:
            print(f"  Whiteboards: {len(board_lines)}")
            for l in board_lines[:2]:
                print(f"    {l[:180]}")

        # Try to fetch first image URL to see if accessible
        if img_lines:
            import re
            m = re.search(r'\(([^)]+)\)', img_lines[0])
            if m:
                url = m.group(1)
                print(f"  Testing image URL accessibility...")
                import httpx
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    try:
                        resp = await client.head(url)
                        print(f"    Status: {resp.status_code}, Content-Type: {resp.headers.get('content-type','?')}, Size: {resp.headers.get('content-length','?')}")
                    except Exception as e:
                        print(f"    Error: {e}")

asyncio.run(test())
