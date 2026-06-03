"""把 kpi-extractors workflow 的三平台 extractions 合成一份配置 JSON，供组装抽取器。"""
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path("E:/agent/omni/services/scout-agent/catalog/_kpi_extractions.json")

d = json.loads(SRC.read_text(encoding="utf-8"))
r = d["result"]
allx = []
for plat in ("compass", "doudian", "yuntu"):
    xs = (r.get(plat, {}) or {}).get("extractions") or []
    for x in xs:
        x["_platform"] = plat
        allx.append(x)
OUT.write_text(json.dumps(allx, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"合并 {len(allx)} 个抽取标量 -> {OUT}\n")
for plat in ("compass", "doudian", "yuntu"):
    xs = [x for x in allx if x["_platform"] == plat]
    print(f"== {plat} ({len(xs)}) ==")
    for x in xs:
        print(f"  [{x.get('endpoint')}] {x.get('metric_name')} = {x.get('sample_value')} ({x.get('unit')}) <- {x.get('json_path')}")
