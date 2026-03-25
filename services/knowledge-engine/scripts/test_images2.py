"""Test image downloading with 1 article."""
import asyncio, logging, os
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from app.services.harvester import crawl_articles, IMAGE_DIR

async def test():
    result = await crawl_articles(
        "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221",
        auth_state_path="/app/data/harvester_auth.json",
        max_pages=1,
        job_id="test-img2",
    )
    ch = result["chapters"][0]
    print(f"\n=== {ch['title']} ===")
    print(f"  Text: {ch['word_count']} chars")
    print(f"  Images: {ch.get('images', {})}")

    # Check downloaded files
    img_dir = IMAGE_DIR / "test-img2"
    if img_dir.exists():
        files = list(img_dir.iterdir())
        print(f"  Downloaded files: {len(files)}")
        for f in files[:5]:
            print(f"    {f.name} — {f.stat().st_size} bytes")
    else:
        print("  No image directory created")

    # Check markdown has local URLs
    md = ch.get("markdown", "")
    local_refs = [l.strip() for l in md.split("\n") if "/api/omni/knowledge/harvester/images/" in l]
    cdn_refs = [l.strip() for l in md.split("\n") if "internal-api-drive-stream" in l]
    print(f"  Local image refs: {len(local_refs)}")
    print(f"  Remaining CDN refs: {len(cdn_refs)}")
    if local_refs:
        print(f"    Sample: {local_refs[0][:160]}")

asyncio.run(test())
