"""Quick test crawl — 3 articles only."""
import asyncio
import logging

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from app.services.harvester import crawl_articles


async def test():
    result = await crawl_articles(
        "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221",
        auth_state_path="/app/data/harvester_auth.json",
        max_pages=3,
        job_id="test-quick",
    )
    print("=" * 60)
    print("STATUS:", result["status"])
    print("CHAPTERS:", len(result["chapters"]))
    for ch in result["chapters"]:
        err = ch.get("error", "")
        wc = ch["word_count"]
        print(f"  [{ch['index']}] {ch['title']} -- {wc} chars {err}")
        if wc > 0:
            print(f"      preview: {ch['text'][:200]}")


asyncio.run(test())
