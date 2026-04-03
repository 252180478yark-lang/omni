"""UAT 样本：仅爬取巨量千川帮助中心单页（验收 TC-M1 等）。

目标 URL（固定）：
https://support.oceanengine.com/help/content/206669?graphId=397&mappingType=2&pageId=221&spaceId=122

用法：先启动 knowledge-engine（默认 8002），再执行：
  python scripts/test_harvester_support_206669.py

飞书/内嵌文档路径需要 Playwright + 有效 auth_state；仅 SSR 成功时无需浏览器。
"""
from __future__ import annotations

import re
import time

import httpx

SAMPLE_URL = (
    "https://support.oceanengine.com/help/content/206669"
    "?graphId=397&mappingType=2&pageId=221&spaceId=122"
)

API_BASE = "http://127.0.0.1:8002"
PREFIX = "/api/v1/knowledge/harvester"


def main() -> None:
    resp = httpx.post(
        f"{API_BASE}{PREFIX}/crawl",
        json={"url": SAMPLE_URL, "max_pages": 1},
        timeout=120.0,
    )
    resp.raise_for_status()
    body = resp.json()
    print("Start:", body)
    job_id = body["data"]["job_id"]

    for i in range(60):
        time.sleep(3)
        r = httpx.get(f"{API_BASE}{PREFIX}/job/{job_id}", timeout=60.0)
        j = r.json()
        status = j.get("status", "?")
        progress = j.get("progress", 0)
        total = j.get("total", 0)
        chapters = len(j.get("chapters", []))
        current = j.get("current_article") or {}
        curr_title = (current.get("title") or "")[:60]
        print(
            f"[{i + 1}] status={status} progress={progress}/{total} "
            f"chapters={chapters} current={curr_title!r}"
        )

        if status in ("done", "failed"):
            if status == "failed":
                print("Error:", (j.get("error") or "")[:800])
            else:
                for ch in j.get("chapters", []):
                    md = ch.get("markdown", "")
                    err = ch.get("error", "")
                    idx = ch["index"]
                    title = (ch.get("title") or "")[:80]
                    wc = ch.get("word_count", 0)
                    print(f"\n  Chapter {idx}: {title} | {wc} chars | error={err!r}")

                    local_imgs = len(
                        re.findall(r"/api/omni/knowledge/harvester/images/", md)
                    )
                    placeholders = len(re.findall(r"\[图片[^\]]*\]", md))
                    print(f"    Local proxy imgs: {local_imgs}, placeholders: {placeholders}")

                    out = "test_harvester_support_206669_output.md"
                    with open(out, "w", encoding="utf-8") as f:
                        f.write(md)
                    print(f"    Markdown saved to {out}")
            break
    else:
        print("Timeout waiting for job completion.")


if __name__ == "__main__":
    main()
