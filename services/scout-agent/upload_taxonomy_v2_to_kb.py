"""把 yuntu_taxonomy_full_v2.md 入一个**专门的新 KB**（不污染现有巨量云图 KB）。

新 KB：name=『巨量云图标签体系』, kb_role=『methodology』。
大 chunk_size（2400）让"1 个一级品类子树/1 节"尽量落同一个 chunk，圈包检索更准。

跑法（host）：
    docker cp E:/agent/omni/docs/yuntu-taxonomy/yuntu_taxonomy_full_v2.md omni-knowledge-engine:/tmp/
    docker cp services/scout-agent/upload_taxonomy_v2_to_kb.py omni-knowledge-engine:/tmp/
    docker exec omni-knowledge-engine python /tmp/upload_taxonomy_v2_to_kb.py
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "/app")

KB_NAME = "巨量云图标签体系"
KB_ROLE = "methodology"
KB_DESC = "巨量云图数据工厂标签工厂 + 自定义人群 完整标签树（圈包/提纯 ground truth）"
MD_PATH = "/tmp/yuntu_taxonomy_full_v2.md"
TITLE = "巨量云图标签体系 完整结构化字典 v2（数据工厂标签树补全 2026-06-08）"
CHUNK_SIZE = 2400
CHUNK_OVERLAP = 200


async def get_or_create_kb(pool) -> str:
    row = await pool.fetchrow(
        "SELECT id FROM knowledge.knowledge_bases WHERE name=$1", KB_NAME
    )
    if row:
        print(f"[i] KB 已存在: {row['id']}")
        return str(row["id"])
    kb_id = str(uuid4())
    await pool.execute(
        """INSERT INTO knowledge.knowledge_bases (id, name, description, kb_role)
           VALUES ($1::uuid, $2, $3, $4)""",
        kb_id, KB_NAME, KB_DESC, KB_ROLE,
    )
    print(f"[OK] 新建 KB: {kb_id} (name={KB_NAME}, role={KB_ROLE})")
    return kb_id


async def main():
    from app.database import init_pool, close_pool, get_pool
    from app.services import ingestion

    md_text = Path(MD_PATH).read_text(encoding="utf-8")
    print(f"[i] markdown: {len(md_text)} 字 / {md_text.count(chr(10))} 行")

    await init_pool()
    try:
        pool = get_pool()
        kb_id = await get_or_create_kb(pool)

        # 若同名 doc 已存在（重跑），先删旧 doc（纯加法可逆：只动本 KB 自己的 doc）
        old = await pool.fetch(
            "SELECT id FROM knowledge.documents WHERE kb_id=$1::uuid AND title=$2",
            kb_id, TITLE,
        )
        for r in old:
            await pool.execute(
                "DELETE FROM knowledge.documents WHERE id=$1::uuid", r["id"]
            )
            print(f"[i] 删旧 doc {r['id']}（重跑覆盖）")

        task_id = await ingestion.submit_ingestion_task(
            kb_id=kb_id,
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
            },
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        print(f"[OK] 提交 task_id={task_id} (chunk_size={CHUNK_SIZE})")

        for i in range(72):  # 最多 6 分钟
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
                    print(f"[OK] 完成！kb_id={kb_id} document_id={doc_id} chunks={n}")
                else:
                    print(f"[!!] 失败：{t.get('error')}")
                break
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
