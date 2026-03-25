import asyncio
import httpx

MODELS = [
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-pro",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
]

async def main():
    for model in MODELS:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "http://ai-provider-hub:8001/api/v1/ai/chat",
                    json={
                        "messages": [{"role": "user", "content": "Reply OK"}],
                        "temperature": 0.1,
                        "max_tokens": 20,
                        "model": model,
                    },
                )
                data = resp.json()
                content = data.get("content", "").strip()
                status = "OK" if content else "EMPTY"
                print(f"  {model}: {status} -> {content[:60]}")
        except Exception as e:
            print(f"  {model}: ERROR {e}")

asyncio.run(main())
