"""Find Feishu session/auth tokens in the iframe's JavaScript context."""
import asyncio, logging, re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from playwright.async_api import async_playwright

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()

    # Capture CDN request headers more carefully
    cdn_req_details = []
    async def on_request(request):
        if "internal-api-drive-stream" in request.url:
            all_headers = await request.all_headers()
            cdn_req_details.append({"url": request.url, "headers": all_headers})

    page.on("request", on_request)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(8000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if cdn_req_details:
        print("=== CDN Request ALL Headers ===")
        h = cdn_req_details[0]["headers"]
        for k, v in sorted(h.items()):
            vv = v[:150] if len(v) > 150 else v
            print(f"  {k}: {vv}")

    if target_frame:
        # Check for auth globals
        auth_info = await target_frame.evaluate("""() => {
            const results = {};

            // Check common Feishu auth storage
            try { results.localStorage_keys = Object.keys(localStorage).filter(k => k.includes('token') || k.includes('session') || k.includes('auth') || k.includes('csrf')); } catch(e) {}
            try { results.sessionStorage_keys = Object.keys(sessionStorage).filter(k => k.includes('token') || k.includes('session') || k.includes('auth') || k.includes('csrf')); } catch(e) {}

            // Check window globals
            const globals = ['__FEISHU_SESSION', '__SESSION', '__AUTH', '__TOKEN',
                           '_csrf', 'csrfToken', '__config', '__SDK_CONFIG',
                           'g_csrfToken', 'window.__INITIAL_STATE__'];
            for (const g of globals) {
                try {
                    const val = eval(g);
                    if (val) results['global_' + g] = typeof val === 'string' ? val.substring(0, 100) : JSON.stringify(val).substring(0, 200);
                } catch(e) {}
            }

            // Check meta tags
            const metas = document.querySelectorAll('meta');
            for (const m of metas) {
                const name = m.getAttribute('name') || m.getAttribute('property') || '';
                if (name.includes('csrf') || name.includes('token')) {
                    results['meta_' + name] = m.content?.substring(0, 100);
                }
            }

            // Check cookies
            results.document_cookies = document.cookie.substring(0, 500);

            return results;
        }""")
        print("\n=== Iframe Auth Info ===")
        for k, v in auth_info.items():
            print(f"  {k}: {v}")

        # Try to find the XHR/fetch interceptor or image loader
        loader_info = await target_frame.evaluate("""() => {
            const results = {};
            // Check if there's a custom fetch wrapper
            if (window.__LARK_OPENDOC__) {
                results.lark_opendoc = JSON.stringify(Object.keys(window.__LARK_OPENDOC__)).substring(0, 200);
            }
            if (window.__larkApiClient) {
                results.lark_api = JSON.stringify(Object.keys(window.__larkApiClient)).substring(0, 200);
            }
            // Look for bitable/drive SDK
            const winKeys = Object.keys(window).filter(k =>
                k.includes('lark') || k.includes('feishu') || k.includes('drive') ||
                k.includes('suite') || k.includes('opendoc') || k.includes('SDK')
            );
            results.window_keys = winKeys.join(', ').substring(0, 300);
            return results;
        }""")
        print("\n=== Loader/SDK Info ===")
        for k, v in loader_info.items():
            print(f"  {k}: {v}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
