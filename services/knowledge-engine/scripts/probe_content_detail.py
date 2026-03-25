"""Check what contentData.content actually contains."""
import asyncio
import json
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}


async def main():
    url = (
        "https://yuntu.oceanengine.com/support/content/143250"
        "?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
        "&__ssrDirect=true&graphId=610&mappingType=2"
        "&pageId=445&spaceId=221"
    )

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
        resp = await client.get(url)
        data = json.loads(resp.text)

    cd = data.get("contentData", {})
    print("=== contentData fields ===")
    for k, v in cd.items():
        if k == "content":
            print(f"  content type: {type(v).__name__}")
            if isinstance(v, str):
                print(f"  content length: {len(v)}")
                print(f"  content[:500]: {v[:500]}")
                print(f"  content[-500:]: {v[-500:]}")
                # Try parse as JSON
                try:
                    parsed = json.loads(v)
                    print(f"  content parsed as JSON, type: {type(parsed).__name__}")
                    if isinstance(parsed, dict):
                        print(f"  content JSON keys: {list(parsed.keys())[:15]}")
                        for ck in list(parsed.keys())[:3]:
                            cv = parsed[ck]
                            cv_str = json.dumps(cv, ensure_ascii=False)[:300]
                            print(f"    [{ck}]: {cv_str}")
                    elif isinstance(parsed, list):
                        print(f"  content is list, len={len(parsed)}")
                        if parsed:
                            print(f"  first item: {json.dumps(parsed[0], ensure_ascii=False)[:500]}")
                except json.JSONDecodeError:
                    # Maybe HTML?
                    if "<" in v[:50]:
                        print("  Looks like HTML content")
                    else:
                        print("  Not JSON, not HTML")
            elif isinstance(v, dict):
                print(f"  content dict keys: {list(v.keys())[:15]}")
                for ck in list(v.keys())[:3]:
                    cv_str = json.dumps(v[ck], ensure_ascii=False)[:300]
                    print(f"    [{ck}]: {cv_str}")
            elif isinstance(v, list):
                print(f"  content list len={len(v)}")
                if v:
                    print(f"  first: {json.dumps(v[0], ensure_ascii=False)[:500]}")
        else:
            val_str = json.dumps(v, ensure_ascii=False)[:200] if v else "null"
            print(f"  {k}: {val_str}")

    # Also check attachmentMap
    am = data.get("attachmentMap")
    if am:
        print(f"\n=== attachmentMap keys (first 5): {list(am.keys())[:5]} ===")
        for k in list(am.keys())[:2]:
            print(f"  [{k}]: {json.dumps(am[k], ensure_ascii=False)[:300]}")


asyncio.run(main())
