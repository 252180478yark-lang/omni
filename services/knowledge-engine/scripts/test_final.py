"""Final test: crawl 3 articles with image capture."""
import asyncio, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from app.services.harvester import crawl_articles, IMAGE_DIR

async def test():
    result = await crawl_articles(
        "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221",
        auth_state_path="/app/data/harvester_auth.json",
        max_pages=3,
        job_id="test-final",
    )
    print("=" * 60)
    print(f"STATUS: {result['status']}")
    for ch in result["chapters"]:
        imgs = ch.get("images", {})
        err = ch.get("error", "")
        print(f"  [{ch['index']}] {ch['title']}")
        print(f"       text: {ch['word_count']} chars, images: {imgs.get('downloaded',0)}/{imgs.get('total',0)} {err}")

    # Check saved files
    img_dir = IMAGE_DIR / "test-final"
    if img_dir.exists():
        files = list(img_dir.iterdir())
        total_size = sum(f.stat().st_size for f in files)
        print(f"\nSaved {len(files)} image files ({total_size // 1024} KB)")
        for f in sorted(files)[:5]:
            print(f"  {f.name} -- {f.stat().st_size // 1024} KB")

asyncio.run(test())
