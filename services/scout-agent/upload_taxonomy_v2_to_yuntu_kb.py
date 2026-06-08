"""把 yuntu_taxonomy_full_v2.md 也加进**现有巨量云图 KB**（608807ec，authoritative）。

为什么要双入：generate_audience_pack（step 4 圈包 tool）的 platform_kb_context 是从
**硬编码 _PLATFORM_KB_IDS = (巨量云图, 巨量千川)** 召回的（media.py，不按 kb_role 动态选）。
所以新建的 methodology KB 它够不着——必须把同一份补全文档也作为**新 doc 加进巨量云图 KB**
（纯加法，不覆盖/不删任何现有 doc），step 4 才能召回到电商品类树/标签工厂字段/提纯三刀法。

可逆：删这一个 doc 即回退（按 title 唯一）。

跑法（host，PowerShell 做 docker cp 避免路径被改写）：
    docker cp E:/agent/omni/docs/yuntu-taxonomy/yuntu_taxonomy_full_v2.md omni-knowledge-engine:/tmp/yuntu_taxonomy_full_v2.md
    docker cp services/scout-agent/upload_taxonomy_v2_to_yuntu_kb.py omni-knowledge-engine:/tmp/upload_taxonomy_v2_to_yuntu_kb.py
    docker exec omni-knowledge-engine python /tmp/upload_taxonomy_v2_to_yuntu_kb.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")

YUNTU_KB_ID = "608807ec-29ff-4fc0-b15b-73d0609c93a8"  # 巨量云图 (authoritative)
MD_PATH = "/tmp/yuntu_taxonomy_full_v2.md"
TITLE = "巨量云图标签体系 完整结构化字典 v2（数据工厂标签树补全 2026-06-08）"
CHUNK_SIZE = 2400
CHUNK_OVERLAP = 200


async def main():
    from app.database import init_pool, close_pool, get_pool
    from app.services import ingestion

    md_text = Path(MD_PATH).read_text(encoding="utf-8")
    print(f"[i] markdown: {len(md_text)} 字 / {md_text.count(chr(10))} 行")

    await init_pool()
    try:
        pool = get_pool()
        # 重跑覆盖：先删同 title 旧 doc（只动这一个 doc，纯加法可逆）
        old = await pool.fetch(
            "SELECT id FROM knowledge.documents WHERE kb_id=$1::uuid AND title=$2",
            YUNTU_KB_ID, TITLE,
        )
        for r in old:
            await pool.execute(
                "DELETE FROM knowledge.documents WHERE id=$1::uuid", r["id"]
            )
            print(f"[i] 删旧 doc {r['id']}（重跑覆盖）")

        task_id = await ingestion.submit_ingestion_task(
            kb_id=YUNTU_KB_ID,
            title=TITLE,
            text=md_text,
            source_url="https://yuntu.oceanengine.com/ (数据工厂标签工厂 + 自定义人群)",
            source_type="manual",
            filename="yuntu_taxonomy_full_v2.md",
            metadata={
                "version": "v2",
                "built_at": "2026-06-08",
                "builder": "build_yuntu_taxonomy_full.py",
                "category": "yuntu_label_taxonomy_full",
                "note": "数据工厂标签树补全（dump v1 抓不到的电商品类/品牌成交偏好全量）",
            },
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        print(f"[OK] 提交 task_id={task_id} → 巨量云图 KB (chunk_size={CHUNK_SIZE})")

        for i in range(72):
            await asyncio.sleep(5)
            t = await ingestion.get_task(task_id)
            if not t:
                print("  [!!] task 不见了"); break
            status = t.get("status")
            print(f"  [{i*5}s] status={status}")
            if status in {"done", "failed"}:
                if status == "done":
                    doc_id = t.get("document_id")
                    n = await pool.fetchval(
                        "SELECT count(*) FROM knowledge.knowledge_chunks WHERE document_id=$1::uuid",
                        doc_id,
                    )
                    print(f"[OK] 完成！巨量云图 KB document_id={doc_id} chunks={n}")
                else:
                    print(f"[!!] 失败：{t.get('error')}")
                break
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
