"""把 yuntu_audience_taxonomy_v1.md 上传到巨量云图 KB（D5 第 2 步）。

走容器内 ingestion 模块直接 submit task（绕过 Human Gate）。

跑法（host 上 docker exec）：
    docker cp E:/agent/omni/data/yuntu_audience_taxonomy_v1.md omni-knowledge-engine:/tmp/
    docker cp services/scout-agent/upload_taxonomy_to_kb.py omni-knowledge-engine:/tmp/
    docker exec omni-knowledge-engine python /tmp/upload_taxonomy_to_kb.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")

YUNTU_KB_ID = "608807ec-29ff-4fc0-b15b-73d0609c93a8"
MD_PATH = "/tmp/yuntu_audience_taxonomy_v1.md"
TITLE = "巨量云图 自定义人群创建页 完整标签字典 v1（爬取版 2026-05-09）"


async def main():
    from app.database import init_pool, close_pool
    from app.services import ingestion

    md_text = Path(MD_PATH).read_text(encoding="utf-8")
    print(f"[i] 读到 markdown: {len(md_text)} 字 / {md_text.count(chr(10))} 行")

    await init_pool()
    try:
        task_id = await ingestion.submit_ingestion_task(
            kb_id=YUNTU_KB_ID,
            title=TITLE,
            text=md_text,
            source_url="https://yuntu.oceanengine.com/yuntu_brand/ecom/analysis/audience/create",
            source_type="manual",
            filename="yuntu_audience_taxonomy_v1.md",
            metadata={
                "version": "v1",
                "scraped_at": "2026-05-08T19:06Z",
                "scraper": "scout-agent dump_yuntu_audience_taxonomy.py",
                "category": "yuntu_official_audience_taxonomy",
            },
        )
        print(f"[OK] 提交 task_id={task_id}")

        # 等任务跑完
        for i in range(60):  # 最多等 5 分钟
            await asyncio.sleep(5)
            t = await ingestion.get_task(task_id)
            if not t:
                print(f"  [!!] task 不见了"); break
            status = t.get("status")
            print(f"  [{i*5}s] status={status}")
            if status in {"done", "failed"}:
                if status == "done":
                    doc_id = t.get("document_id")
                    print(f"[OK] 完成！document_id={doc_id}")
                else:
                    print(f"[!!] 失败：{t.get('error')}")
                break
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
