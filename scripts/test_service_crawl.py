"""Test service-side crawl with 1 page."""
import asyncio
import httpx

KE = "http://localhost:8002/api/v1/knowledge"
URL = "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221"


async def main():
    async with httpx.AsyncClient(timeout=300.0) as c:
        print("Starting crawl (1 page)...")
        r = await c.post(f"{KE}/harvester/crawl", json={"url": URL, "max_pages": 1})
        data = r.json()["data"]
        job_id = data["job_id"]
        print(f"Job: {job_id}, Auth: {data['has_auth']}")

        while True:
            await asyncio.sleep(5)
            r = await c.get(f"{KE}/harvester/jobs/{job_id}")
            job = r.json()["data"]
            status = job["status"]
            current = job.get("current_article")
            name = current.get("title", "")[:40] if current else ""
            print(f"  [{status}] {job['progress']}/{job['total']} {name}")
            if status in ("done", "failed"):
                break

        print(f"\nStatus: {status}")
        print(f"Error: {job.get('error', '(none)')}")
        for ch in job.get("chapters", []):
            err = ch.get("error", "")
            wc = ch.get("word_count", 0)
            flag = "OK" if wc > 50 else f"ERR:{err}"
            print(f"  [{flag}] {ch['title'][:50]} — {wc} chars")


if __name__ == "__main__":
    asyncio.run(main())
