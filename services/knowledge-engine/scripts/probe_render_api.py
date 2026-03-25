"""Try to find a content render API or mobile endpoint."""
import asyncio
import json
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}

MAPPING_ID = 143250
GID, PID, SID = "610", "445", "221"


async def try_url(client, label, url, expect_json=True):
    try:
        r = await client.get(url)
        print(f"\n=== {label} ===")
        print(f"Status: {r.status_code}, Content-Type: {r.headers.get('content-type','?')}")
        text = r.text
        if r.status_code == 200 and expect_json:
            try:
                data = json.loads(text)
                print(f"Keys: {list(data.keys())[:10]}")
                if "contentData" in data:
                    cd = data["contentData"]
                    if isinstance(cd, dict):
                        ct = cd.get("content", "")
                        print(f"contentData.content length: {len(ct) if ct else 0}")
                        if ct:
                            print(f"content[:500]: {ct[:500]}")
                        lc = cd.get("larkContent")
                        if lc:
                            print(f"larkContent type: {type(lc).__name__}")
                            lc_str = json.dumps(lc, ensure_ascii=False)[:500] if lc else ""
                            print(f"larkContent[:500]: {lc_str}")
                        fc = cd.get("feishuDocxToken")
                        if fc:
                            print(f"feishuDocxToken: {fc}")
                        ct_type = cd.get("contentType")
                        print(f"contentType: {ct_type}")
            except Exception:
                print(f"Not JSON. Body[:500]: {text[:500]}")
        else:
            print(f"Body[:500]: {text[:500]}")
    except Exception as e:
        print(f"\n=== {label} === ERROR: {e}")


async def main():
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
        # Already known working pattern
        base = "https://support.oceanengine.com/support/content"
        yuntu = "https://yuntu.oceanengine.com/support/content"

        # Try mobile endpoint
        await try_url(client, "mobile content",
            f"https://support.oceanengine.com/support/mobile/?pageId={PID}&spaceId={SID}&contentId={MAPPING_ID}",
            expect_json=False)

        # Try API v2 patterns
        await try_url(client, "support API content detail",
            f"https://support.oceanengine.com/support/api/v2/helpcenter/content/detail?id={MAPPING_ID}&spaceId={SID}")

        await try_url(client, "support API content render",
            f"https://support.oceanengine.com/support/api/v2/helpcenter/content/render?id={MAPPING_ID}&spaceId={SID}")

        await try_url(client, "support API content info",
            f"https://support.oceanengine.com/support/api/v2/helpcenter/content/info?id={MAPPING_ID}&spaceId={SID}")

        # Try helpcenter API
        await try_url(client, "helpcenter API content",
            f"https://support.oceanengine.com/helpcenter/api/content?id={MAPPING_ID}")

        # Try different loader patterns
        for loader in [
            "%28prefix%29%2Fcontent%2F%28id%24%29%2Frender",
            "%28prefix%29%2Fcontent%2F%28id%24%29%2Fdetail",
            "%28prefix%29%2Fcontent%2F%28id%24%29",
            "%28prefix%29%2Fmobile%2Fcontent%2F%28id%24%29",
        ]:
            await try_url(client, f"loader={loader}",
                f"{yuntu}/content/{MAPPING_ID}?__loader={loader}&__ssrDirect=true"
                f"&graphId={GID}&mappingType=2&pageId={PID}&spaceId={SID}")

        # Try the Feishu docx render endpoint via support
        await try_url(client, "feishu docx preview API",
            f"https://support.oceanengine.com/support/api/feishu/docx/preview?token=LHpKdVho7oxCtlxyIgNc3QSfnZc")

        # Try getting content for a specific contentId (from the SSR response)
        await try_url(client, "contentId 143256",
            f"{yuntu}/content/143256?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
            f"&__ssrDirect=true&graphId={GID}&mappingType=2&pageId={PID}&spaceId={SID}")


asyncio.run(main())
