"""Test service-side crawl - print raw JSON."""
import asyncio
import httpx

KE = "http://localhost:8002/api/v1/knowledge"
URL = "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221"


async def main():
    async with httpx.AsyncClient(timeout=300.0) as c:
        r = await c.post(f"{KE}/harvester/crawl", json={"url": URL, "max_pages": 1})
        job_id = r.json()["data"]["job_id"]
        print(f"Job: {job_id}")

        while True:
            await asyncio.sleep(3)
            r = await c.get(f"{KE}/harvester/jobs/{job_id}")
            raw = r.json()
            status = raw["data"]["status"]
            error = raw["data"].get("error")
            print(f"  status={status}")
            if error:
                print(f"  ERROR:\n{error}")
            if status in ("done", "failed"):
                import json
                print("\n=== FULL JOB DATA ===")
                print(json.dumps(raw["data"], ensure_ascii=False, indent=2)[:3000])
                break


if __name__ == "__main__":
    asyncio.run(main())
