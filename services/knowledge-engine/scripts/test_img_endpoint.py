"""Test the image serving endpoint."""
import httpx, asyncio

async def t():
    async with httpx.AsyncClient() as c:
        r = await c.get("http://localhost:8002/api/v1/knowledge/harvester/images/test-final/HAw3b4UfGooE5UxQyG6cAPMunCe.jpg")
        ct = r.headers.get("content-type", "?")
        print(f"Status: {r.status_code}, Content-Type: {ct}, Size: {len(r.content)} bytes")

asyncio.run(t())
