"""生意参谋（sycm.taobao.com）登录 + 探针 —— 天猫店自有经营数据接入 切片 0。

一个脚本干两件事：
  A. 登录：先拿现有淘宝竞品登录态试进生意参谋；进不去（跳登录页）就让你在
     这个窗口里**当场登录**（扫码 / 密码 / 短信都行），登录成功后把登录态存到
     sessions/tmall/storage_state.json —— 这份才是 scout 抓天猫数据要用的。
  B. 勘测：登录后你正常点平时看的数据页（实时/流量/交易/商品），脚本在背后
     把这些页用的真实数据接口（mtop / sycm api）全记下来 + 存响应样本，作为
     catalog/tmall.json 端点勘测的一手素材（你真看什么，就接什么）。

复用 app/routers/taobao.py 已攻克的淘宝 AWSC 反爬配方（headed + storage_state +
stealth + 去自动化标记）。**host 上跑**（要弹可见窗口；sycm headless 必被拦）。

用法（在有显示器的 host 上跑）：
    cd E:\\agent\\omni\\services\\scout-agent
    python scripts/_probe_sycm.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent           # services/scout-agent/
# 自己店登录态（本脚本产出/复用）；不掺淘宝竞品态，避免账号混淆
TMALL_SESSION = HERE / "sessions" / "tmall"
TMALL_SESSION.mkdir(parents=True, exist_ok=True)
TMALL_STORAGE = TMALL_SESSION / "storage_state.json"
OUT_DIR = HERE / "snapshots" / "sycm"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 淘宝卖家中心登录入口（sub=true 支持子账号）；登录态同账号体系，对生意参谋(sycm)也有效
START_URL = ("https://loginmyseller.taobao.com/?from=taobaoindex&f=top&style=&sub=true"
             "&redirect_url=https%3A%2F%2Fmyseller.taobao.com%2F")
SYCM_URL = "https://sycm.taobao.com/"
LOGIN_WAIT_SECONDS = 300      # 现场登录最多等 5 分钟
CAPTURE_SECONDS = 120         # 登录后记接口的时长

# 反爬配方（照抄 taobao.py _new_context）
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""

# 淘宝登录后才写的强标记（跟 _login_taobao.py 一致）
_AUTH = {"unb", "tracknick", "lgc", "_nk_"}

_SKIP_EXT = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
             ".woff", ".woff2", ".ttf", ".ico", ".mp4", ".map")
_SKIP_FRAG = ("gm.mmstat.com", "log.mmstat.com", "/log/", "ynuf.aliapp",
              "acjs.aliyun", "wl.alibaba", ".gif?", "/_____tmd_____",
              "errorjson", "/v.gif", "ali-usersync")


def _interesting(url: str, ctype: str) -> bool:
    u = url.lower()
    if any(f in u for f in _SKIP_FRAG):
        return False
    path = urlsplit(u).path
    if any(path.endswith(e) for e in _SKIP_EXT):
        return False
    if "mtop." in u or "/sycm" in u or ("sycm.taobao.com" in u and "/api" in u):
        return True
    if "json" in ctype:
        return True
    return False


def _logged_in(ctx, page=None) -> bool:
    # 只认 context 级 cookie 的强登录标记（unb/tracknick 登录后才有，游客没有）。
    # 不依赖 page.url —— 淘宝登录/选店常在新 tab 完成，盯着旧 page 的网址会一直误判没登录。
    try:
        names = {c.get("name", "") for c in ctx.cookies()}
    except Exception:
        return False
    return bool(names & _AUTH)


def main() -> int:
    captured: dict[str, dict] = {}
    sample_idx = [0]

    def on_response(resp):
        try:
            url = resp.url
            req = resp.request
            ctype = (resp.headers or {}).get("content-type", "")
        except Exception:
            return
        if not _interesting(url, ctype):
            return
        key = urlsplit(url)._replace(query="").geturl()
        if key in captured:
            return
        rec = {"method": req.method, "status": resp.status,
               "full_url": url[:300], "sample_file": None}
        try:
            body = resp.text()
            if body and ("json" in ctype or body.lstrip()[:1] in "{["):
                sample_idx[0] += 1
                fn = OUT_DIR / f"sample_{sample_idx[0]:02d}.json"
                fn.write_text(body[:200_000], encoding="utf-8")
                rec["sample_file"] = fn.name
        except Exception:
            pass
        captured[key] = rec
        print(f"  · [{rec['status']}] {req.method} {key[:90]}"
              + (f"  → {rec['sample_file']}" if rec["sample_file"] else ""), flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        # 已有自己店登录态就带上（免重登）；首次没有 → 空态从卖家登录页开始
        ctx = browser.new_context(
            storage_state=str(TMALL_STORAGE) if TMALL_STORAGE.exists() else None,
            viewport={"width": 1440, "height": 900},
            user_agent=_UA,
            locale="zh-CN",
        )
        ctx.add_init_script(_STEALTH_JS)
        page = ctx.new_page()
        page.on("response", on_response)

        try:
            page.goto(START_URL, wait_until="domcontentloaded", timeout=40000)
        except Exception as exc:
            print("nav warn:", exc, flush=True)
        time.sleep(4)

        # ── A. 登录 ──────────────────────────────────────────────────
        if _logged_in(ctx, page):
            print("✓ 现有淘宝登录态直接进了卖家中心（省去重新登录）。", flush=True)
            print("  请看窗口确认是不是你自己天猫店；不是的话在窗口里切换成你天猫店卖家账号。", flush=True)
        else:
            print("\n=== 需要登录 ===", flush=True)
            print(f"当前在卖家中心登录页（{page.url[:70]}）。请在这个窗口里登录：", flush=True)
            print("  扫码（手机淘宝/千牛 App 扫）/ 密码登录 / 短信验证码 —— 哪种都行。", flush=True)
            print("  二维码刷不出来就点登录框切「密码登录」。最多等 5 分钟。", flush=True)
            for i in range(LOGIN_WAIT_SECONDS):
                time.sleep(1)
                if not ctx.pages:
                    print("窗口被关了（未完成登录）。", flush=True)
                    break
                if i >= 5 and _logged_in(ctx, page):
                    print(f"✓ 登录成功（{i}s）url={page.url[:60]}", flush=True)
                    time.sleep(2)
                    break
                if i and i % 20 == 0:
                    print(f"  ...等登录中 (url={page.url[:55]})", flush=True)

        if not _logged_in(ctx, page):
            print("✗ 没检测到登录态，结束。重跑再试，或确认账号有生意参谋数据权限。", flush=True)
            try:
                browser.close()
            except Exception:
                pass
            return 1

        # ── 存登录态（这份给 scout 抓天猫数据用）──────────────────────
        try:
            ctx.storage_state(path=str(TMALL_STORAGE))
            print(f"SAVED 登录态 -> {TMALL_STORAGE}", flush=True)
        except Exception as exc:
            print("save warn:", exc, flush=True)

        # 登录可能在新 tab 完成，把 page 指向最新窗口再操作
        if ctx.pages:
            page = ctx.pages[-1]

        # 卖家中心登录态同账号体系，导航到生意参谋验证 + 抓首页接口
        try:
            page.goto(SYCM_URL, wait_until="domcontentloaded", timeout=40000)
            time.sleep(4)
            if _logged_in(ctx, page):
                print("✓ 生意参谋(sycm)也是登录态，数据接口可勘测。", flush=True)
            else:
                print("· 生意参谋跳了登录 —— 可在卖家中心里点数据页（订单/交易/商品），"
                      "或在窗口里把 sycm 也登一下。", flush=True)
        except Exception as exc:
            print("sycm nav warn:", exc, flush=True)

        try:
            page.screenshot(path=str(OUT_DIR / "sycm_home.png"), full_page=False)
            print(f"截图: {OUT_DIR / 'sycm_home.png'}（看这张确认是不是你自己店）", flush=True)
        except Exception:
            pass

        # ── B. 勘测：老板点数据页，背后记接口 ─────────────────────────
        print(f"\n=== 现在请在窗口里点你平时常看的数据页 ===", flush=True)
        print("  生意参谋(sycm)：实时概况 / 流量看板 / 交易分析 / 商品效果", flush=True)
        print("  卖家中心(myseller)：订单 / 交易 / 商品 也行", flush=True)
        print(f"  每页停 2-3 秒等出数。{CAPTURE_SECONDS}s 后自动汇总，或点完直接关窗。", flush=True)
        for _ in range(CAPTURE_SECONDS):
            time.sleep(1)
            if not ctx.pages:
                print("  （窗口已关，提前汇总）", flush=True)
                break

        try:
            ctx.close()
            browser.close()
        except Exception:
            pass

    # ── 汇总 ─────────────────────────────────────────────────────────
    endpoints_file = OUT_DIR / "_endpoints.txt"
    lines = [f"[{r['status']}] {r['method']}\t{key}\t{r.get('sample_file') or '-'}"
             for key, r in captured.items()]
    endpoints_file.write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "_endpoints.json").write_text(
        json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== 汇总：抓到 {len(captured)} 个数据接口 ===", flush=True)
    print(f"  接口清单: {endpoints_file}", flush=True)
    print(f"  响应样本: {OUT_DIR}\\sample_*.json", flush=True)
    print("  → 把上面的接口清单贴给 Claude，我据此挑接口建 catalog/tmall.json + 写抽取器。", flush=True)
    return 0 if captured else 1


if __name__ == "__main__":
    raise SystemExit(main())
