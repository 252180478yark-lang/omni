"""把参数化 survey 的 JSONL 切面按端点聚合：{端点: {可切维度: [取值→是否有数据+预览]}}。
只给有数据的切面留 preview（失败切面只留 verdict/code），大幅压缩供 agent 整理成表。"""
import json
from collections import defaultdict
from pathlib import Path

CAT = Path("/app/catalog")
PREV = 380

for plat in ("yuntu", "compass", "doudian"):
    f = CAT / f"_survey_params_{plat}.jsonl"
    if not f.exists():
        print(f"{plat}: 无 jsonl")
        continue
    rows = [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]
    byk: dict = defaultdict(lambda: {"alias": "", "category": "", "dims": defaultdict(list)})
    for r in rows:
        if "key" not in r:
            continue
        e = byk[r["key"]]
        e["alias"] = r.get("alias", "")
        e["category"] = r.get("category", "")
        rec = {"value": r.get("value"), "has_data": r.get("has_data"),
               "verdict": r.get("verdict"), "code": r.get("code")}
        if r.get("has_data"):
            rec["preview"] = (r.get("preview") or "")[:PREV]
        e["dims"][r.get("dim")].append(rec)

    out = {}
    for k, e in byk.items():
        if any(rec.get("has_data") for recs in e["dims"].values() for rec in recs):
            out[k] = {"alias": e["alias"], "category": e["category"],
                      "dims": {d: recs for d, recs in e["dims"].items()}}
    (CAT / f"_survey_params_{plat}_agg.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{plat}: {len(out)} 端点有数据切面")
