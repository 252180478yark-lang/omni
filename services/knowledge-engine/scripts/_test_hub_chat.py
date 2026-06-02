import asyncio

from app.services.ai_hub_client import AIHubClient


async def main():
    for m in ["gemini-3-flash-preview", "gemini-2.5-flash"]:
        try:
            r = await AIHubClient().chat(
                messages=[{"role": "user", "content": "只回复两个字：你好"}],
                provider="gemini", model=m, max_tokens=50,
            )
            print(f"{m} -> content={repr((r.get('content') or ''))[:120]} | provider={r.get('provider')} model={r.get('model')}")
        except Exception as e:
            print(f"{m} ERR {type(e).__name__}: {e}")


asyncio.run(main())
