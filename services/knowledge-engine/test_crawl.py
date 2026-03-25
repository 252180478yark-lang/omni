"""Test crawl of the target page via API."""
import re
import time

import httpx

url = "http://127.0.0.1:8002"
prefix = "/api/v1/knowledge/harvester"

resp = httpx.post(f"{url}{prefix}/crawl", json={
    "url": "https://yuntu.oceanengine.com/support/content/143250?graphId=610&mappingType=2&pageId=445&spaceId=221",
    "max_pages": 1,
})
print("Start:", resp.json())
job_id = resp.json()["data"]["job_id"]

for i in range(30):
    time.sleep(3)
    r = httpx.get(f"{url}{prefix}/job/{job_id}")
    j = r.json()
    status = j.get("status", "?")
    progress = j.get("progress", 0)
    total = j.get("total", 0)
    chapters = len(j.get("chapters", []))
    current = j.get("current_article") or {}
    curr_title = current.get("title", "")[:50]
    print(f"[{i+1}] status={status} progress={progress}/{total} chapters={chapters} current={curr_title}")

    if status in ("done", "failed"):
        if status == "failed":
            print("Error:", j.get("error", "")[:500])
        else:
            for ch in j.get("chapters", []):
                md = ch.get("markdown", "")
                err = ch.get("error", "")
                imgs = ch.get("images", {})
                idx = ch["index"]
                title = ch["title"][:50]
                wc = ch["word_count"]
                print(f"\n  Chapter {idx}: {title} | {wc} chars | error={err} | imgs={imgs}")

                table_lines = [l for l in md.split("\n") if l.strip().startswith("|")]
                print(f"    Table lines: {len(table_lines)}")

                lines = md.split("\n")
                broken = sum(
                    1 for li in range(len(lines) - 2)
                    if lines[li].strip().startswith("|")
                    and lines[li + 1].strip() == ""
                    and lines[li + 2].strip().startswith("|")
                )
                print(f"    Broken table gaps: {broken}")

                cdn_imgs = len(re.findall(r"internal-api-drive-stream", md))
                local_imgs = len(re.findall(r"/api/omni/knowledge/harvester/images/", md))
                placeholders = len(re.findall(r"\[图片[^\]]*\]", md))
                print(f"    CDN imgs: {cdn_imgs}, Local imgs: {local_imgs}, Placeholders: {placeholders}")

                # Save full markdown for inspection
                with open("test_crawl_output.md", "w", encoding="utf-8") as f:
                    f.write(md)
                print(f"    Full markdown saved to test_crawl_output.md")
        break
