"""切片0 勘测助手：把老板从京东商智/京麦 DevTools 导出的 HAR 蒸馏成候选端点清单。

为什么要这脚本：一个商智会话的 HAR 动辄几 MB、几百个请求，直接喂给 agent 会撑爆上下文。
这脚本只读 HAR、过滤出京东域的 XHR/fetch JSON 接口，去重后产出**紧凑**候选清单
（host/path/method/参数 key/是否 JSON/是否带签名/响应 top-level keys），agent 读这个小报告就能：
  ① 判 h5st 签名（决定走 XHR 回放 A 轨还是导出按钮 B 轨）
  ② 挑首批 5-10 个核心端点填 catalog/jd.json
  ③ 出口径映射表草稿

用法（HAR 放 host 上任意可达路径，或丢进 catalog/）：
    docker exec -w /app omni-scout-agent python scripts/_jd_har_to_catalog.py /app/catalog/jd_shangzhi.har
    # 或 host 上直接（需 host 有 python）：python services/scout-agent/scripts/_jd_har_to_catalog.py path/to.har
输出：同目录 _jd_survey.json（紧凑候选清单）+ stdout 摘要。**只读不落库、不抓取**。
"""
from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# 京东域：商智 sz.jd.com / 京麦 jmworkstation / VC vc.jd.com / 通用 *.jd.com
JD_HOST_HINTS = ("jd.com", "jd.hk", "jingdong", "jmworkstation")
# 签名/风控参数名——命中即标 signed=True（决定 XHR 回放能不能裸放）
SIGN_KEYS = {"h5st", "_stk", "_ste", "sign", "signature", "x-api-eid-token", "sdkToken", "loginType", "fp", "eid"}
# 噪音资源：静态/打点/监控，过滤掉
NOISE_EXT = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".woff2", ".ico", ".mp4")
NOISE_PATH_HINTS = ("/log", "/monitor", "/report", "/track", "/beacon", "/jdvc", "/jdcollect", "/t.gif",
                    "/switch/vendor", "/behavior_report", "/request_algo", "/checkwhitelist", "/jstk", "/bypass")
# 监控/反爬/SSO 域：非业务数据，整域过滤（实测京麦页混了一堆）
NOISE_HOSTS = ("sgm-w.jd", "sgm-m.jd", "cactus.jd", "blackhole.", "jra.jd", "seq.jd", "sso.jd",
               "stream-outside.jd", "dap.jd", "gia.jd", "mitm.jd")


def _is_jd(host: str) -> bool:
    return any(h in host for h in JD_HOST_HINTS)


def _looks_json(entry: dict) -> bool:
    resp = entry.get("response", {})
    ct = ""
    for h in resp.get("headers", []):
        if h.get("name", "").lower() == "content-type":
            ct = (h.get("value") or "").lower()
            break
    if "json" in ct:
        return True
    # 有些接口 content-type 不规范，试探 body 头部
    text = (resp.get("content", {}) or {}).get("text", "") or ""
    text = text.lstrip()
    return text[:1] in ("{", "[")


def _top_keys(entry: dict) -> list[str]:
    text = (entry.get("response", {}).get("content", {}) or {}).get("text", "") or ""
    try:
        obj = json.loads(text)
    except Exception:
        return []
    if isinstance(obj, dict):
        return list(obj.keys())[:12]
    return ["<array>"] if isinstance(obj, list) else []


def main(har_path: str) -> None:
    # 兜底：Windows host 控制台默认 GBK，Chinese/markers 会 UnicodeEncodeError；容器内是 UTF-8 不受影响。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    p = Path(har_path)
    if not p.exists():
        print(f"找不到 HAR：{har_path}", file=sys.stderr)
        sys.exit(2)
    har = json.loads(p.read_text("utf-8", errors="replace"))
    entries = har.get("log", {}).get("entries", [])
    print(f"HAR 共 {len(entries)} 条请求，开始蒸馏京东 XHR…", flush=True)

    seen: "OrderedDict[tuple, dict]" = OrderedDict()
    for e in entries:
        req = e.get("request", {})
        url = req.get("url", "")
        method = req.get("method", "GET")
        parsed = urlparse(url)
        host, path = parsed.netloc, parsed.path
        if not _is_jd(host):
            continue
        if any(h in host for h in NOISE_HOSTS):
            continue
        low = path.lower()
        if low.endswith(NOISE_EXT) or any(h in low for h in NOISE_PATH_HINTS):
            continue
        if not _looks_json(e):
            continue
        qs = parse_qs(parsed.query)
        # body 参数 key（POST）
        body_keys: list[str] = []
        post = req.get("postData", {})
        if post.get("params"):
            body_keys = [pp.get("name", "") for pp in post["params"]]
        elif post.get("text", "").lstrip()[:1] == "{":
            try:
                body_keys = list(json.loads(post["text"]).keys())[:20]
            except Exception:
                pass
        all_param_keys = sorted(set(list(qs.keys()) + body_keys))
        signed = sorted(SIGN_KEYS.intersection({k.lower() for k in all_param_keys}))
        # 京东统一网关（api.m.jd.com / sff.jd.com/api 等）：真实接口由 functionId 区分，
        # 不拆 functionId 会把几十个业务接口塌成一行。从 query / 表单 / json body 三处找。
        fn = (qs.get("functionId") or qs.get("method") or qs.get("api") or [None])[0]
        if not fn:
            _pt = (post.get("text") or "")
            mfn = re.search(r"(?:functionId|api)=([^&]+)", _pt)
            if mfn:
                fn = mfn.group(1)
            elif _pt.lstrip()[:1] == "{":
                try:
                    _j = json.loads(_pt)
                    fn = _j.get("functionId") or _j.get("method")
                except Exception:
                    pass
        if not fn:
            for pp in (post.get("params") or []):
                if pp.get("name") in ("functionId", "method"):
                    fn = pp.get("value")
                    break
        key = (method, host, path, fn or "")
        if key in seen:
            seen[key]["hits"] += 1
            continue
        seen[key] = {
            "method": method,
            "host": host,
            "path": path,
            "functionId": fn or "",
            "param_keys": all_param_keys,
            "signed": signed,            # 非空=带签名，XHR 回放可能过不去（切片0 一票定 A/B 轨）
            "resp_top_keys": _top_keys(e),
            "hits": 1,
        }

    out = list(seen.values())
    out.sort(key=lambda x: (-x["hits"], x["host"], x["path"]))
    report = {
        "har": str(p),
        "jd_xhr_endpoints": len(out),
        "signed_count": sum(1 for x in out if x["signed"]),
        "endpoints": out,
    }
    out_path = p.parent / "_jd_survey.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    print(f"\n京东 JSON XHR 端点 {len(out)} 个（去重后），带签名 {report['signed_count']} 个")
    print(f"紧凑报告已写：{out_path}\n")
    print("Top 30（hits / signed / method host path [functionId]）：")
    for x in out[:30]:
        sig = "SIGNED:" + ",".join(x["signed"]) if x["signed"] else "plain"
        fn = f"  fn={x['functionId']}" if x.get("functionId") else ""
        print(f"  [{x['hits']:>2}] {sig:<14} {x['method']:<4} {x['host']}{x['path']}{fn}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python scripts/_jd_har_to_catalog.py <path-to.har>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
