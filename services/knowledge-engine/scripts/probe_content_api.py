"""Probe various API patterns to find article content without browser."""
import asyncio
import json
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}

GID = "610"
PID = "445"
SID = "221"


async def try_url(client: httpx.AsyncClient, label: str, url: str):
    try:
        resp = await client.get(url)
        text = resp.text[:2000]
        print(f"\n=== {label} ===")
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', '?')}")
        if resp.status_code == 200:
            # Try parse as JSON
            try:
                data = json.loads(resp.text.strip() if resp.text.strip().startswith("{") else "{}")
                print(f"JSON keys: {list(data.keys())[:15]}")
                if "contentData" in data:
                    cd = data["contentData"]
                    print(f"contentData type: {type(cd).__name__}, keys: {list(cd.keys())[:10] if isinstance(cd, dict) else 'N/A'}")
                    if isinstance(cd, dict):
                        for k, v in list(cd.items())[:3]:
                            val_str = json.dumps(v, ensure_ascii=False)[:300] if v else "null"
                            print(f"  contentData[{k}]: {val_str}")
                if "data" in data:
                    d = data["data"]
                    if isinstance(d, dict):
                        print(f"data keys: {list(d.keys())[:10]}")
            except Exception:
                pass
            print(f"Body snippet: {text[:800]}")
        else:
            print(f"Body: {text[:500]}")
    except Exception as e:
        print(f"\n=== {label} === ERROR: {e}")


async def main():
    # First get the article list
    tree_url = (
        f"https://yuntu.oceanengine.com/support/content/root"
        f"?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
        f"&__ssrDirect=true&graphId={GID}&mappingType=1"
        f"&pageId={PID}&spaceId={SID}"
    )

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
        resp = await client.get(tree_url)
        tree_data = json.loads(resp.text)

        articles = []
        def walk(nodes):
            for n in nodes:
                if n.get("mappingType") == 2 and n.get("mappingId"):
                    articles.append(n)
                for child in n.get("subTreeNodes", []):
                    walk([child])
        walk(tree_data.get("nodes", []))

        print(f"Found {len(articles)} articles")
        if not articles:
            return

        first = articles[0]
        mid = first["mappingId"]
        name = first["mappingName"]
        print(f"Testing with: {name} (mappingId={mid})")

        # Check if contentData is already in tree response
        cd = tree_data.get("contentData")
        if cd:
            print(f"\ncontentData in tree response! type={type(cd).__name__}")
            if isinstance(cd, dict):
                print(f"  keys: {list(cd.keys())[:10]}")
                for k, v in list(cd.items())[:2]:
                    print(f"  [{k}]: {json.dumps(v, ensure_ascii=False)[:500]}")

        # Try different URL patterns
        patterns = [
            (
                "SSR content with mappingId",
                f"https://yuntu.oceanengine.com/support/content/{mid}"
                f"?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
                f"&__ssrDirect=true&graphId={GID}&mappingType=1"
                f"&pageId={PID}&spaceId={SID}"
            ),
            (
                "support.oceanengine SSR direct",
                f"https://support.oceanengine.com/support/content/{mid}"
                f"?__ssrDirect=true&graphId={GID}&pageId={PID}&spaceId={SID}"
            ),
            (
                "support.oceanengine SSR with loader",
                f"https://support.oceanengine.com/support/content/{mid}"
                f"?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
                f"&__ssrDirect=true&graphId={GID}&mappingType=2"
                f"&pageId={PID}&spaceId={SID}"
            ),
            (
                "yuntu SSR mappingType=2",
                f"https://yuntu.oceanengine.com/support/content/{mid}"
                f"?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
                f"&__ssrDirect=true&graphId={GID}&mappingType=2"
                f"&pageId={PID}&spaceId={SID}"
            ),
        ]

        for label, url in patterns:
            await try_url(client, label, url)


asyncio.run(main())
