import asyncio
import json
import httpx


async def main():
    resp = await httpx.AsyncClient(timeout=180).post(
        "http://localhost:8002/api/v1/knowledge/rag",
        json={
            "kb_id": "53a2a083-c662-487e-b914-10a56ee73672",
            "query": "直播中主播用了哪些互动技巧",
            "top_k": 5,
            "stream": False,
        },
    )
    data = resp.json().get("data", {})
    print("=== GraphRAG Status ===")
    print("graph_rag_used:", data.get("graph_rag_used"))
    print()
    print("=== Graph Context Preview ===")
    ctx = data.get("graph_context_preview", "")
    print(ctx[:500] if ctx else "(empty)")
    print()
    print("=== Answer (first 400 chars) ===")
    print(data.get("answer", "")[:400])
    print()
    print("=== Sources count ===")
    print(len(data.get("sources", [])))


asyncio.run(main())
