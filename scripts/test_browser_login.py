"""Test the browser-login API endpoint."""
import asyncio
import httpx

KE = "http://localhost:8082/api/v1/knowledge"


async def main():
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Clear existing auth first
        await c.delete(f"{KE}/harvester/auth")

        print("Starting browser login...")
        r = await c.post(f"{KE}/harvester/browser-login",
                         json={"url": "https://yuntu.oceanengine.com"})
        data = r.json()
        print(f"Response: {data}")

        if not data.get("success"):
            return

        session_id = data["data"]["session_id"]

        print("Browser should be opening on your desktop...")
        print("Please log in when you see the browser window.")
        print("Polling for status...")

        for i in range(100):
            await asyncio.sleep(3)
            r = await c.get(f"{KE}/harvester/browser-login/{session_id}")
            s = r.json()["data"]
            status = s["status"]
            extra = ""
            if s.get("cookies_saved"):
                extra = f" — {s['cookies_saved']} cookies saved!"
            elif s.get("error"):
                extra = f" — ERROR: {s['error']}"
            print(f"  [{i*3}s] {status}{extra}")
            if status in ("done", "failed", "timeout"):
                break

        if status == "done":
            # Verify auth
            r = await c.get(f"{KE}/harvester/auth-status")
            print(f"\nAuth status: {r.json()}")


if __name__ == "__main__":
    asyncio.run(main())
