"""把 survey 结果按平台拆成小文件（只留有数据的），供整理成表。"""
import json
from pathlib import Path

CAT = Path("/app/catalog")
data = json.loads((CAT / "_survey_result.json").read_text("utf-8"))

KEEP = ("key", "alias", "category", "path", "verdict", "code", "raw_preview")
for plat in ("yuntu", "compass", "doudian"):
    rows = [r for r in data if r.get("platform") == plat and r.get("has_data")]
    out = [{k: r.get(k) for k in KEEP} for r in rows]
    (CAT / f"_survey_{plat}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{plat}: {len(out)} 有数据端点")

nodata = [{"platform": r.get("platform"), "key": r.get("key"), "alias": r.get("alias")}
          for r in data if r.get("verdict") == "PASS_NODATA"]
(CAT / "_survey_nodata.json").write_text(json.dumps(nodata, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"PASS_NODATA(端点通但今日无数据): {len(nodata)}")
