# generate_director_brief 黄金集（占位）

截至 seed 时 `pipeline.scripts kind='director_brief'` **0 条 adopted**（只有 draft）——
黄金集只收老板真实采纳过的产物，不拿 draft 凑数。

**等老板在 /sku-pipeline step 3.6 采纳一版 brief 后**（`pipeline_adopt(table='scripts', run_id=...)`），
重跑 `python /app/scripts/eval/seed_golden.py --tool generate_director_brief` 自动出 case。
