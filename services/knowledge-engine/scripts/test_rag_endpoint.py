"""Test RAG endpoint to verify graph_rag_used is True."""
import asyncio
import httpx
import json

async def main():
    kb_ids = [
        "5f09b9ff-0f9a-4f5e-b1ce-b2144e4ba89a",
        "53a2a083-c662-487e-b914-10a56ee73672",
    ]
    query = "直播中主播用了哪些互动技巧"

    for kb_id in kb_ids:
        print(f"\n=== Testing KB {kb_id[:8]} ===")
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                "http://localhost:8002/api/v1/knowledge/rag",
                json={
                    "kb_id": kb_id,
                    "query": query,
                    "stream": False,
                },
            )
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
                continue
            data = resp.json()
            if "data" in data:
                data = data["data"]
            print(f"  graph_rag_used: {data.get('graph_rag_used')}")
            print(f"  graph_context_preview: {data.get('graph_context_preview', '')[:200]}")
            print(f"  answer snippet: {data.get('answer', '')[:150]}")
            print(f"  sources: {len(data.get('sources', []))}")

asyncio.run(main())
