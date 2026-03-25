"""Recreate knowledge bases and trigger crawl + ingestion."""
import asyncio
import httpx

BASE = "http://localhost:8002/api/v1/knowledge"

KBS = [
    {
        "name": "\u5de8\u91cf\u4e91\u56fe",
        "description": "\u5de8\u91cf\u4e91\u56fe\u5e2e\u52a9\u4e2d\u5fc3\u6587\u6863",
        "embedding_provider": "gemini",
        "embedding_model": "gemini-embedding-2-preview",
        "dimension": 1536,
    },
    {
        "name": "\u76f4\u64ad\u5207\u7247\u77e5\u8bc6\u5e93-\u5356\u8d27",
        "description": "\u76f4\u64ad\u5207\u7247\u5206\u6790-\u5356\u8d27\u7c7b",
        "embedding_provider": "gemini",
        "embedding_model": "gemini-embedding-2-preview",
        "dimension": 1536,
    },
    {
        "name": "\u76f4\u64ad\u5207\u7247\u77e5\u8bc6\u5e93-\u505a\u83dc",
        "description": "\u76f4\u64ad\u5207\u7247\u5206\u6790-\u505a\u83dc\u7c7b",
        "embedding_provider": "gemini",
        "embedding_model": "gemini-embedding-2-preview",
        "dimension": 1536,
    },
]

YUNTU_URL = "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221"


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        kb_ids = {}
        for kb in KBS:
            r = await c.post(f"{BASE}/bases", json=kb)
            r.raise_for_status()
            data = r.json()["data"]
            kb_ids[data["name"]] = data["id"]
            print(f"  Created: {data['name']} -> {data['id']}")

        yuntu_id = kb_ids.get("\u5de8\u91cf\u4e91\u56fe")
        print(f"\nYuntu KB ID: {yuntu_id}")

        print("\nStarting crawl...")
        r = await c.post(
            f"{BASE}/harvester/crawl",
            json={"url": YUNTU_URL},
        )
        r.raise_for_status()
        job = r.json()["data"]
        job_id = job["job_id"]
        print(f"  Crawl job: {job_id}, auth={job['has_auth']}")

        while True:
            await asyncio.sleep(10)
            r = await c.get(f"{BASE}/harvester/jobs/{job_id}")
            d = r.json()["data"]
            status = d["status"]
            progress = d["progress"]
            total = d["total"]
            chapters = len(d.get("chapters", []))
            print(f"  [{status}] {progress}/{total} chapters={chapters}")
            if status in ("done", "failed"):
                break

        if status == "failed":
            print(f"  ERROR: {d.get('error')}")
            return

        chapters = d.get("chapters", [])
        valid = [
            {"title": ch["title"], "markdown": ch["markdown"], "source_url": ch.get("url", "")}
            for ch in chapters
            if ch.get("markdown", "").strip() and ch.get("word_count", 0) > 20
        ]
        print(f"\n  Valid chapters: {len(valid)}/{len(chapters)}")

        if not valid:
            print("  WARNING: No valid chapters extracted (auth required for feishu content)")
            print("  Please provide cookies and re-run crawl with auth")
            return

        print(f"\n  Saving to KB {yuntu_id}...")
        r = await c.post(
            f"{BASE}/harvester/save",
            json={"kb_id": yuntu_id, "chapters": valid},
        )
        r.raise_for_status()
        save = r.json()["data"]
        print(f"  Saved: {save['saved_count']} chapters submitted")

        print("\nAll KB IDs:")
        for name, kid in kb_ids.items():
            print(f"  {name}: {kid}")


if __name__ == "__main__":
    asyncio.run(main())
